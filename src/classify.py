"""
classify.py — 把 ingest 出来的 snapshot 做完所有确定性计算。

这块替代了你原来交给 Gemini 算的所有数字活：
    - 四象限归类
    - 涨跌幅差值
    - 龙1/龙2/空龙1/空龙2/反转空龙/修复龙/最弱反转/最弱修复/最增量/最缩量
    - 符合情况
    - 占比统计
    - 极值共振判定（70% 阈值）

LLM 后面只负责"看着这些算好的数字说人话"。
"""
from __future__ import annotations

import copy
from typing import Literal

Category = Literal["持续强化", "强反转", "反包修复", "连续杀跌"]


def _categorize(today_pct: float, yest_pct: float) -> Category:
    """四象限归类。

    边界规则（状态延续假设 / state-dependent classification）：
      今涨幅 = 0 时不算中性，按"昨日方向"延续判断：
        - 昨日涨 + 今日 0 → 强势横盘 → 持续强化（资金托盘，没人砸盘）
        - 昨日跌 + 今日 0 → 弱势整理 → 连续杀跌（反弹无力，承接乏力）
        - 昨日 0 + 今日 0 → 死水，归入持续强化（罕见）
      昨涨幅 = 0 时同理按今日方向决定。

    业界依据：国信金工动量因子研究、西部证券 ETF 日内动量策略都使用
    类似的"路径依赖"或"噪声区域"思路，避免把强势横盘误判为反转。
    """
    # 严格上涨/下跌的清晰象限
    if today_pct > 0 and yest_pct > 0:
        return "持续强化"
    if today_pct > 0 and yest_pct < 0:
        return "反包修复"
    if today_pct < 0 and yest_pct > 0:
        return "强反转"
    if today_pct < 0 and yest_pct < 0:
        return "连续杀跌"

    # 边界态：含 0 的情况，按状态延续假设处理
    if today_pct == 0:
        # 今日横盘，看昨日来路
        if yest_pct > 0:
            return "持续强化"    # 强势横盘
        if yest_pct < 0:
            return "连续杀跌"    # 弱势整理
        return "持续强化"          # 双零，给个默认归宿

    # 今日有涨跌但昨日 == 0，按今日方向决定
    if today_pct > 0:
        return "持续强化"          # 横盘后启动 → 当作延续
    return "连续杀跌"               # 横盘后破位 → 当作延续


def _volume_ratio(today: float, yest: float) -> float:
    """成交额环比，例如 +0.8031 表示放量 80.31%。"""
    if yest == 0:
        return 0.0
    return (today - yest) / yest


def _compliance(item: dict) -> str:
    """符合情况：差值方向与归类方向一致 → 完全符合，否则勉强符合。"""
    cat = item["category"]
    diff = item["pct_diff"]
    if cat in ("持续强化", "反包修复"):
        return "完全符合" if diff > 0 else "勉强符合"
    return "完全符合" if diff < 0 else "勉强符合"


def _assign_features(group: list[dict], category: Category) -> None:
    """给一个分类内的品种打 |归类特征| 标签。in-place 修改。

    每个品种最多一个"位置特征"。量能特征（最增量/最缩量）由 enrich() 在
    全品种维度上统一打，不在分类内打 —— 用户业务语义是"全品种唯一一对"。
    """
    n = len(group)

    # 位置特征：按分类逻辑
    if n < 3:
        for it in group:
            it["_pos_tag"] = "独特"
        return

    if category == "持续强化":
        # 2日累计涨幅最高/次高 → 龙1/龙2
        by_cum = sorted(group, key=lambda x: x["cum_pct"], reverse=True)
        by_cum[0]["_pos_tag"] = "龙1"
        by_cum[1]["_pos_tag"] = "龙2"

    elif category == "连续杀跌":
        # 2日累计涨幅最低/次低 → 空龙1/空龙2
        by_cum = sorted(group, key=lambda x: x["cum_pct"])
        by_cum[0]["_pos_tag"] = "空龙1"
        by_cum[1]["_pos_tag"] = "空龙2"

    elif category == "强反转":
        # 涨跌幅差值最低/次低 → 反转空龙1/反转空龙2，最高 → 最弱反转
        by_diff = sorted(group, key=lambda x: x["pct_diff"])
        by_diff[0]["_pos_tag"] = "反转空龙1"
        by_diff[1]["_pos_tag"] = "反转空龙2"
        by_diff[-1]["_pos_tag"] = "最弱反转"

    elif category == "反包修复":
        # 涨跌幅差值最高/次高 → 修复龙1/修复龙2，最低 → 最弱修复
        by_diff = sorted(group, key=lambda x: x["pct_diff"], reverse=True)
        by_diff[0]["_pos_tag"] = "修复龙1"
        by_diff[1]["_pos_tag"] = "修复龙2"
        by_diff[-1]["_pos_tag"] = "最弱修复"


def _compose_feature(item: dict) -> str:
    """把 _pos_tag 和 _vol_tag 合成 |归类特征| 字符串。"""
    pos = item.pop("_pos_tag", None)
    vol = item.pop("_vol_tag", None)
    parts = [p for p in (pos, vol) if p]
    return "，".join(parts)


def enrich(snapshot: dict) -> dict:
    """对一个 snapshot 做全部确定性计算，返回 enriched dict。

    enriched 在 snapshot 基础上加了：
        每个 item.category / pct_diff / cum_pct / volume_ratio / feature / compliance
        groups: {分类: [items...]}  内部按 pct_diff 降序
        stats:  {分类: {count, pct}}
        resonance: 'up' | 'down' | None
        up_count, down_count, total
    """
    snap = copy.deepcopy(snapshot)
    items = snap["items"]

    # 基础字段
    for it in items:
        it["pct_diff"] = round(it["today_pct"] - it["yest_pct"], 6)
        it["cum_pct"] = round(it["today_pct"] + it["yest_pct"], 6)  # 简化的 2日累计
        it["volume_ratio"] = round(_volume_ratio(it["today_amount"], it["yest_amount"]), 6)
        it["category"] = _categorize(it["today_pct"], it["yest_pct"])
        it["compliance"] = _compliance(it)

    # 分组
    groups: dict[str, list[dict]] = {
        "持续强化": [],
        "强反转": [],
        "反包修复": [],
        "连续杀跌": [],
    }
    for it in items:
        groups[it["category"]].append(it)

    # 打位置标签（分类内）
    for cat, group in groups.items():
        _assign_features(group, cat)  # type: ignore[arg-type]

    # 全品种唯一一对"最增量/最缩量"（用户业务语义）
    if len(items) >= 3:
        by_vol_desc = sorted(items, key=lambda x: x["volume_ratio"], reverse=True)
        by_vol_desc[0]["_vol_tag"] = "最增量"
        by_vol_desc[-1]["_vol_tag"] = "最缩量"

    for it in items:
        it["feature"] = _compose_feature(it)

    # 组内按差值降序
    for cat in groups:
        groups[cat].sort(key=lambda x: x["pct_diff"], reverse=True)

    # 统计 + 极值共振
    total = len(items)
    up_count = sum(1 for it in items if it["today_pct"] > 0)
    down_count = sum(1 for it in items if it["today_pct"] < 0)
    stats = {
        cat: {
            "count": len(group),
            "pct": round(len(group) / total * 100, 2) if total else 0.0,
        }
        for cat, group in groups.items()
    }

    resonance = None
    if total:
        if up_count / total >= 0.7:
            resonance = "up"
        elif down_count / total >= 0.7:
            resonance = "down"

    snap["groups"] = groups
    snap["stats"] = stats
    snap["resonance"] = resonance
    snap["up_count"] = up_count
    snap["down_count"] = down_count
    return snap


if __name__ == "__main__":
    import json
    import sys
    from ingest import load_snapshot

    snap = load_snapshot(sys.argv[1], session_label=sys.argv[2] if len(sys.argv) > 2 else None)
    enriched = enrich(snap)
    # 简要打印
    for cat, group in enriched["groups"].items():
        print(f"\n=== {cat}（{enriched['stats'][cat]['count']}个，{enriched['stats'][cat]['pct']}%）===")
        for it in group:
            print(f"  {it['name']:18s} 今{it['today_pct']*100:+6.2f}% 昨{it['yest_pct']*100:+6.2f}% "
                  f"差{it['pct_diff']*100:+6.2f}% 量比{it['volume_ratio']*100:+8.2f}% "
                  f"[{it['feature']}] {it['compliance']}")
    print(f"\n极值共振: {enriched['resonance']}, 上涨{enriched['up_count']}/{enriched['total']}")
