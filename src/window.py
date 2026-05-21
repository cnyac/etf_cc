"""滚动窗口状态机。

四类操作（CLAUDE.md "滚动窗口操作"）：
  - append:  build_snapshot 完后追加；超 max 自动弹出最老（弹出仅删，不删 snapshots/）
  - remove:  用户主动剔某 label
  - sync_annotations: 见 sync_annotations.py
  - backfill: 见 backfill.py（也通过 append 入库）

冻结原则（CLAUDE.md "冻结/重算"）：
  snapshot / factors / classify / panel / narrative 写入后不可回头改；annotations 可被覆写。
  本模块**不强制**冻结（不加只读锁）；调用方约定遵守。
"""
from __future__ import annotations

import json
import os
from typing import Literal, Optional

from src.schema import empty_window, MAX_SESSIONS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOW_DIR = os.path.join(ROOT, "data", "window")
SNAPSHOT_DIR = os.path.join(ROOT, "data", "snapshots")


def _window_path(market: str) -> str:
    suffix = market.lower()
    return os.path.join(WINDOW_DIR, f"pool_{suffix}.json")


def _snapshot_path(market: str, label: str) -> str:
    return os.path.join(SNAPSHOT_DIR, market.lower(), f"{label}.json")


def load(market: Literal["A", "US"]) -> dict:
    """读窗口文件；不存在则返回空骨架。"""
    fp = _window_path(market)
    if not os.path.exists(fp):
        return empty_window(market)
    with open(fp, "r", encoding="utf-8") as f:
        return json.load(f)


def save(market: Literal["A", "US"], data: dict) -> None:
    """原子写。"""
    os.makedirs(WINDOW_DIR, exist_ok=True)
    fp = _window_path(market)
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fp)


def archive_to_snapshot(market: Literal["A", "US"], session: dict) -> str:
    """把 session 写入 data/snapshots/{a|us}/<label>.json（永久归档）。
    若已存在则覆盖整个文件（snapshot 字段冻结的约定靠调用方守，不在本函数加锁）。
    """
    fp = _snapshot_path(market, session["label"])
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fp)
    return fp


def find_session(market: Literal["A", "US"], label: str,
                 data: Optional[dict] = None) -> Optional[dict]:
    """查 session，找不到返 None。"""
    if data is None:
        data = load(market)
    for s in data["sessions"]:
        if s.get("label") == label:
            return s
    return None


def append_session(market: Literal["A", "US"], session: dict) -> Optional[str]:
    """追加一个 session 到窗口末端。超过 max_sessions 自动弹出最老的。

    幂等性：若同 label 已在窗口，**不重复添加**，原地用新 session 覆盖（适用于
    同一时段被重新跑的场景；调用方负责守冻结约定）。

    Returns:
        被弹出的最老 session 的 label；如未触发弹出则 None。
    """
    data = load(market)
    max_n = data.get("max_sessions", MAX_SESSIONS[market])

    # 同 label 已存在 → 原地覆盖
    for i, s in enumerate(data["sessions"]):
        if s.get("label") == session["label"]:
            data["sessions"][i] = session
            save(market, data)
            return None

    data["sessions"].append(session)
    popped_label = None
    while len(data["sessions"]) > max_n:
        popped = data["sessions"].pop(0)
        popped_label = popped.get("label")

    save(market, data)
    return popped_label


def remove_session(market: Literal["A", "US"], label: str) -> bool:
    """从窗口剔除某 label（snapshots/ 不动）。"""
    data = load(market)
    before = len(data["sessions"])
    data["sessions"] = [s for s in data["sessions"] if s.get("label") != label]
    if len(data["sessions"]) == before:
        return False
    save(market, data)
    return True


def recent_sessions(market: Literal["A", "US"], n: Optional[int] = None) -> list:
    """取最近 n 个 session；n=None 返全部。"""
    data = load(market)
    sessions = data["sessions"]
    if n is None:
        return sessions
    return sessions[-n:]
