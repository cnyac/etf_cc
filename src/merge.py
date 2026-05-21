"""
merge.py — 多时段合并分析的确定性部分。

Claude Code 模式下只保留两个工具函数：
  - align_timeline: 按 T0 为基准做 Left Join
  - select_rating_candidates: 跨日追踪表的候选筛选

定性分析（小结、宏观研判、变化评级）由 Claude Code 自己写。
"""
from __future__ import annotations

import copy


def align_timeline(snapshots: list[dict]) -> dict:
    """以 T0（snapshots[0]）为基准做 Left Join，给每个品种附上历史时段数据。

    snapshots 按时间倒序传入：[T0, T-0.5, T-1, ...]
    """
    if not snapshots:
        raise ValueError("snapshots 不能为空")

    t0 = snapshots[0]
    prev_indices = []
    for snap in snapshots[1:]:
        idx = {}
        for group in snap["groups"].values():
            for it in group:
                idx[it["name"]] = it
        prev_indices.append((snap["session_label"], idx))

    aligned = copy.deepcopy(t0)
    for group in aligned["groups"].values():
        for it in group:
            it["timeline"] = []
            for label, idx in prev_indices:
                if it["name"] in idx:
                    h = idx[it["name"]]
                    it["timeline"].append({
                        "label": label,
                        "today_pct": h["today_pct"],
                        "yest_pct": h["yest_pct"],
                        "pct_diff": h["pct_diff"],
                        "volume_ratio": h["volume_ratio"],
                        "feature": h["feature"],
                        "category": h["category"],
                        "compliance": h["compliance"],
                        "analysis": h.get("analysis", ""),
                    })
    return aligned


def select_rating_candidates(aligned: dict, snapshots: list[dict]) -> list[dict]:
    """筛选跨日追踪表的候选品种。

    规则：以"昨日收盘"（snapshots[1:] 中第一个含'收盘'的）为基准，
    提取其归类特征中含位置标签（非纯量能标签）的品种。
    """
    yest_close = None
    for snap in snapshots[1:]:
        if "收盘" in snap["session_label"]:
            yest_close = snap
            break
    if yest_close is None:
        return []

    yest_idx = {}
    for group in yest_close["groups"].values():
        for it in group:
            yest_idx[it["name"]] = it

    POS_TAGS = {"龙1", "龙2", "空龙1", "空龙2", "反转空龙1", "反转空龙2",
                "最弱反转", "修复龙1", "修复龙2", "最弱修复", "独特"}

    candidates = []
    for group in aligned["groups"].values():
        for it in group:
            yest = yest_idx.get(it["name"])
            if not yest:
                continue
            tags = [t.strip() for t in (yest["feature"] or "").split("，") if t.strip()]
            has_pos = any(t in POS_TAGS for t in tags)
            if has_pos:
                candidates.append({
                    "name": it["name"],
                    "yesterday_feature": yest["feature"] or "无特征",
                    "yesterday_category": yest["category"],
                    "current_feature": it["feature"] or "无特征",
                    "current_category": it["category"],
                })
    return candidates
