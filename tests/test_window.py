"""window.py 测试 — append/弹出/remove/A 与 US 互不影响。

用 tmp_path 隔离磁盘 IO（patch 模块级路径常量）。
"""
import json
import os
import pytest

from src import window as win


@pytest.fixture
def tmp_dirs(tmp_path, monkeypatch):
    wd = tmp_path / "window"
    sd = tmp_path / "snapshots"
    wd.mkdir()
    (sd / "a").mkdir(parents=True)
    (sd / "us").mkdir(parents=True)
    monkeypatch.setattr(win, "WINDOW_DIR", str(wd))
    monkeypatch.setattr(win, "SNAPSHOT_DIR", str(sd))
    return tmp_path


def _mk(label, market="A"):
    return {"label": label, "market": market, "session_time": "close",
            "tickers": [], "panel": {}, "narrative": None,
            "tracking": {"rating_history": []}}


def test_load_empty(tmp_dirs):
    d = win.load("A")
    assert d["sessions"] == []
    assert d["max_sessions"] == 40


def test_append_basic(tmp_dirs):
    popped = win.append_session("A", _mk("2026-05-20-收"))
    assert popped is None
    d = win.load("A")
    assert len(d["sessions"]) == 1
    assert d["sessions"][0]["label"] == "2026-05-20-收"


def test_append_pops_when_over_max(tmp_dirs):
    # max=40，塞 41 个 → 弹出最老
    for i in range(41):
        last = win.append_session("A", _mk(f"2026-01-01-收-{i:02d}"))
    assert last == "2026-01-01-收-00"
    d = win.load("A")
    assert len(d["sessions"]) == 40
    assert d["sessions"][0]["label"] == "2026-01-01-收-01"


def test_append_idempotent_same_label(tmp_dirs):
    s1 = _mk("2026-05-20-收")
    s1["tickers"] = [{"code": "SH510050", "today_pct": 0.01}]
    win.append_session("A", s1)
    s2 = _mk("2026-05-20-收")
    s2["tickers"] = [{"code": "SH510050", "today_pct": 0.02}]  # 重新跑
    win.append_session("A", s2)
    d = win.load("A")
    assert len(d["sessions"]) == 1  # 没有重复
    assert d["sessions"][0]["tickers"][0]["today_pct"] == 0.02  # 覆盖


def test_remove(tmp_dirs):
    win.append_session("A", _mk("L1"))
    win.append_session("A", _mk("L2"))
    assert win.remove_session("A", "L1") is True
    d = win.load("A")
    assert [s["label"] for s in d["sessions"]] == ["L2"]


def test_remove_missing_returns_false(tmp_dirs):
    assert win.remove_session("A", "nothing") is False


def test_a_us_independent(tmp_dirs):
    win.append_session("A", _mk("A1", "A"))
    win.append_session("US", _mk("U1", "US"))
    assert [s["label"] for s in win.load("A")["sessions"]] == ["A1"]
    assert [s["label"] for s in win.load("US")["sessions"]] == ["U1"]
    assert win.load("US")["max_sessions"] == 20


def test_us_max_20(tmp_dirs):
    for i in range(21):
        last = win.append_session("US", _mk(f"U{i:02d}", "US"))
    assert last == "U00"
    d = win.load("US")
    assert len(d["sessions"]) == 20


def test_archive_writes_snapshot_file(tmp_dirs):
    s = _mk("2026-05-20-收")
    fp = win.archive_to_snapshot("A", s)
    assert os.path.exists(fp)
    with open(fp, "r", encoding="utf-8") as f:
        assert json.load(f)["label"] == "2026-05-20-收"


def test_find_session(tmp_dirs):
    win.append_session("A", _mk("L1"))
    win.append_session("A", _mk("L2"))
    assert win.find_session("A", "L2")["label"] == "L2"
    assert win.find_session("A", "L3") is None


def test_recent_sessions(tmp_dirs):
    for i in range(5):
        win.append_session("A", _mk(f"L{i}"))
    assert [s["label"] for s in win.recent_sessions("A", 3)] == ["L2", "L3", "L4"]
    assert len(win.recent_sessions("A")) == 5
