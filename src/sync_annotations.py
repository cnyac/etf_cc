"""HTML 批注同步：扫报告目录 → 解析内嵌 JSON → 写回窗口/归档。

批注闭环（CLAUDE.md "HTML 报告"）：
  <script type="application/json" id="snapshot">{label, market, ...}</script>
  <script type="application/json" id="annotations">{code: {color, note}, ...}</script>

流程：
  1. 列 data/reports/{a|us}/*.html
  2. 比 data/window/last_synced.json[market] 新（mtime）→ 处理
  3. 解析 <script id="snapshot">.label，从中提取 market/label
  4. 解析 <script id="annotations">
  5. label 仍在 window → 更新 session.tickers[i].annotation
  6. label 已弹出 → 合并到 snapshots/<label>.json 的 tickers[i].annotation
  7. 更新 last_synced.json
"""
from __future__ import annotations

import json
import os
import sys
from typing import Literal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import window as win

REPORTS_DIR = os.path.join(ROOT, "data", "reports")
LAST_SYNCED_PATH = os.path.join(ROOT, "data", "window", "last_synced.json")


def _load_last_synced() -> dict:
    if not os.path.exists(LAST_SYNCED_PATH):
        return {}
    with open(LAST_SYNCED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_last_synced(d: dict) -> None:
    os.makedirs(os.path.dirname(LAST_SYNCED_PATH), exist_ok=True)
    tmp = LAST_SYNCED_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LAST_SYNCED_PATH)


def parse_html_annotations(html_path: str) -> tuple[dict | None, dict | None]:
    """从 HTML 解析 (snapshot_meta, annotations)。
    snapshot_meta 至少含 label/market；annotations 形如 {code: {color, note}}。
    解析失败返 (None, None)。
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise ImportError("需要 beautifulsoup4：pip install beautifulsoup4")

    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    snap_tag = soup.find("script", id="snapshot")
    ann_tag = soup.find("script", id="annotations")
    if snap_tag is None or ann_tag is None:
        return None, None

    try:
        meta = json.loads(snap_tag.string or "{}")
        ann = json.loads(ann_tag.string or "{}")
    except json.JSONDecodeError:
        return None, None

    return meta, ann


def _apply_annotations(session: dict, annotations: dict) -> None:
    """把 {code: {color, note}} 写入 session.tickers[i].annotation。"""
    by_code = {t["code"]: t for t in session.get("tickers", [])}
    for code, ann in annotations.items():
        if code in by_code:
            by_code[code]["annotation"] = ann


def _archive_path(market: str, label: str) -> str:
    # 用 window.SNAPSHOT_DIR 作为单一来源，方便测试 monkeypatch
    return os.path.join(win.SNAPSHOT_DIR, market.lower(), f"{label}.json")


def sync(market: Literal["A", "US"]) -> dict:
    """同步指定市场的批注。返回 {synced: [...], archived: [...], skipped: [...], errors: [...]}。"""
    market_dir = os.path.join(REPORTS_DIR, market.lower())
    result = {"synced": [], "archived": [], "skipped": [], "errors": []}
    if not os.path.isdir(market_dir):
        return result

    last_synced = _load_last_synced()
    market_last = last_synced.get(market, {})  # {label: mtime_iso}

    window_data = win.load(market)
    window_labels = {s["label"] for s in window_data["sessions"]}

    new_market_last = dict(market_last)
    touched_window = False

    for fname in sorted(os.listdir(market_dir)):
        if not fname.endswith(".html"):
            continue
        fp = os.path.join(market_dir, fname)
        mtime = os.path.getmtime(fp)

        meta, ann = parse_html_annotations(fp)
        if meta is None:
            result["errors"].append({"file": fname, "reason": "解析失败"})
            continue
        label = meta.get("label")
        if not label:
            result["errors"].append({"file": fname, "reason": "无 label"})
            continue

        prev_mtime = market_last.get(label)
        if prev_mtime is not None and mtime <= prev_mtime:
            result["skipped"].append(label)
            continue

        if label in window_labels:
            # 在窗口里 → 更新窗口
            for s in window_data["sessions"]:
                if s["label"] == label:
                    _apply_annotations(s, ann or {})
                    touched_window = True
                    break
            result["synced"].append(label)
        else:
            # 已弹出 → 归档到 snapshots
            arc_fp = _archive_path(market, label)
            if os.path.exists(arc_fp):
                with open(arc_fp, "r", encoding="utf-8") as f:
                    arc = json.load(f)
                _apply_annotations(arc, ann or {})
                tmp = arc_fp + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(arc, f, ensure_ascii=False, indent=2)
                os.replace(tmp, arc_fp)
                result["archived"].append(label)
            else:
                result["errors"].append({"file": fname, "reason": f"找不到归档 {arc_fp}"})
                continue

        new_market_last[label] = mtime

    if touched_window:
        win.save(market, window_data)
    last_synced[market] = new_market_last
    _save_last_synced(last_synced)
    return result


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["A", "US"], required=True)
    args = p.parse_args()
    r = sync(args.market)
    print(json.dumps(r, ensure_ascii=False, indent=2))
