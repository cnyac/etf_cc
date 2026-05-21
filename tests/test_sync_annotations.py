"""sync_annotations.py 测试。

覆盖：
  - 解析 HTML 提取 snapshot.label + annotations
  - 当前窗口的 label → 写入 session.tickers[i].annotation
  - 已弹出的 label → 写入 snapshots/<label>.json 归档
  - mtime 未变 → 跳过
"""
import json
import os
import pytest

from src import window as win
from src import sync_annotations as sa


@pytest.fixture
def tmp_dirs(tmp_path, monkeypatch):
    wd = tmp_path / "window"
    sd = tmp_path / "snapshots"
    rd = tmp_path / "reports"
    wd.mkdir()
    (sd / "a").mkdir(parents=True)
    (rd / "a").mkdir(parents=True)
    monkeypatch.setattr(win, "WINDOW_DIR", str(wd))
    monkeypatch.setattr(win, "SNAPSHOT_DIR", str(sd))
    monkeypatch.setattr(sa, "REPORTS_DIR", str(rd))
    monkeypatch.setattr(sa, "LAST_SYNCED_PATH", str(wd / "last_synced.json"))
    monkeypatch.setattr(sa, "ROOT", str(tmp_path))
    return tmp_path


def _mk_session(label):
    return {
        "label": label, "market": "A", "session_time": "close",
        "tickers": [
            {"code": "SH510050", "name": "上证50ETF", "annotation": None},
            {"code": "SZ159995", "name": "芯片ETF", "annotation": None},
        ],
        "panel": {}, "narrative": None, "tracking": {"rating_history": []},
    }


def _write_html(reports_dir, label, market, annotations):
    fp = os.path.join(reports_dir, market.lower(), f"{label}.html")
    html = f"""<!DOCTYPE html><html><head><title>{label}</title></head><body>
<script type="application/json" id="snapshot">{json.dumps({"label": label, "market": market})}</script>
<script type="application/json" id="annotations">{json.dumps(annotations)}</script>
</body></html>"""
    with open(fp, "w", encoding="utf-8") as f:
        f.write(html)
    return fp


def test_parse_html_basic(tmp_dirs):
    fp = _write_html(str(tmp_dirs / "reports"), "L1", "A",
                     {"SH510050": {"color": "#FFE4B5", "note": "缩量"}})
    meta, ann = sa.parse_html_annotations(fp)
    assert meta["label"] == "L1"
    assert ann["SH510050"]["color"] == "#FFE4B5"


def test_parse_html_malformed_returns_none(tmp_dirs):
    fp = tmp_dirs / "reports" / "a" / "bad.html"
    fp.write_text("<html><body>no scripts</body></html>", encoding="utf-8")
    meta, ann = sa.parse_html_annotations(str(fp))
    assert meta is None and ann is None


def test_sync_writes_to_current_window(tmp_dirs):
    win.append_session("A", _mk_session("L1"))
    _write_html(str(tmp_dirs / "reports"), "L1", "A",
                {"SH510050": {"color": "#FFE4B5", "note": "缩量"}})
    r = sa.sync("A")
    assert r["synced"] == ["L1"]
    assert r["archived"] == []
    s = win.find_session("A", "L1")
    ann = [t["annotation"] for t in s["tickers"] if t["code"] == "SH510050"][0]
    assert ann["color"] == "#FFE4B5"


def test_sync_archives_when_label_popped(tmp_dirs):
    # 写归档但不进窗口
    session = _mk_session("L_old")
    win.archive_to_snapshot("A", session)
    _write_html(str(tmp_dirs / "reports"), "L_old", "A",
                {"SZ159995": {"color": "#D3D3D3", "note": "震荡"}})
    r = sa.sync("A")
    assert r["archived"] == ["L_old"]
    assert r["synced"] == []
    # 验证归档文件被更新
    arc_fp = tmp_dirs / "snapshots" / "a" / "L_old.json"
    with open(arc_fp, "r", encoding="utf-8") as f:
        arc = json.load(f)
    ann = [t["annotation"] for t in arc["tickers"] if t["code"] == "SZ159995"][0]
    assert ann["color"] == "#D3D3D3"


def test_sync_skips_unchanged_mtime(tmp_dirs):
    win.append_session("A", _mk_session("L1"))
    _write_html(str(tmp_dirs / "reports"), "L1", "A", {"SH510050": {"color": "#FFE4B5"}})
    sa.sync("A")  # 第一次同步
    r2 = sa.sync("A")  # 第二次，文件未改
    assert r2["synced"] == []
    assert r2["skipped"] == ["L1"]


def test_sync_redo_after_mtime_bump(tmp_dirs):
    import time
    win.append_session("A", _mk_session("L1"))
    fp = _write_html(str(tmp_dirs / "reports"), "L1", "A", {"SH510050": {"color": "#FFE4B5"}})
    sa.sync("A")
    # 改批注 + 提升 mtime
    time.sleep(0.1)
    _write_html(str(tmp_dirs / "reports"), "L1", "A", {"SH510050": {"color": "#DDA0DD", "note": "新批注"}})
    # 强制 mtime 更新
    now = os.path.getmtime(fp) + 1
    os.utime(fp, (now, now))
    r = sa.sync("A")
    assert r["synced"] == ["L1"]
    s = win.find_session("A", "L1")
    ann = [t["annotation"] for t in s["tickers"] if t["code"] == "SH510050"][0]
    assert ann["color"] == "#DDA0DD"
