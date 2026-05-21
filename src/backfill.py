"""历史回填 + 骨架 narrative。

策略（CLAUDE.md "滚动窗口操作 backfill"）：
  - 对范围内每个 A 股交易日生成一个"收"时段（盘中数据无历史，午时段无法回填）
  - 美股每个交易日一个时段
  - narrative.session_summary 用 Python 模板生成，is_skeleton=true
  - LLM 看到 is_skeleton=true 不会被诱导成"我之前判断过"

入口：
  python -m src.backfill --market A --start 2026-04-15 --end 2026-05-20
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Literal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, r"D:\git\auto prtsc")

from src.build_snapshot import build


def _trading_days(start: str, end: str, market: str) -> list[str]:
    """用 auto-prtsc 的 trade_cal 列出交易日（升序）。"""
    import trade_cal
    import exchange_calendars as xcals
    cal_name = "XSHG" if market == "A" else "XNYS"
    cal = xcals.get_calendar(cal_name)
    sessions = cal.sessions_in_range(start, end)
    return [s.strftime("%Y-%m-%d") for s in sessions]


def _format_cross_asset(panel: dict, market: str) -> str:
    cas = panel.get("cross_asset_state", {})
    if market == "A":
        order = ["treasury_10y", "treasury_30y", "gold", "oil"]
        labels = {"treasury_10y": "10年国债", "treasury_30y": "30年国债",
                  "gold": "黄金", "oil": "原油"}
    else:
        order = ["treasury_10y", "treasury_30y", "dollar", "gold",
                 "oil", "vix", "btc", "eth"]
        labels = {"treasury_10y": "10Y", "treasury_30y": "30Y", "dollar": "美元",
                  "gold": "金", "oil": "油", "vix": "VIX", "btc": "BTC", "eth": "ETH"}
    parts = []
    for k in order:
        v = cas.get(k)
        if v:
            parts.append(f"{labels[k]}{v}")
    return "/".join(parts) if parts else "跨资产无数据"


def skeleton_summary(session: dict) -> str:
    """模板（REFACTOR_BRIEF 4.8）：
    <label> [机器生成]: 上涨 X/N（占比 P%），强势 N 个，量能扩张 M 个；<跨资产>；
    分类分布 持续强化 N / 反包修复 N / 强反转 N / 连续杀跌 N。
    """
    label = session["label"]
    panel = session["panel"]
    n = panel["up_count"] + panel["down_count"] + panel["flat_count"]
    up_pct = round(panel["up_count"] / n * 100, 1) if n else 0
    cross = _format_cross_asset(panel, session["market"])
    cats = panel.get("category_distribution", {})
    cat_str = " / ".join(
        f"{k} {cats.get(k, 0)}"
        for k in ("持续强化", "反包修复", "强反转", "连续杀跌")
    )
    return (
        f"{label} [机器生成]: 上涨 {panel['up_count']}/{n}（占比 {up_pct}%），"
        f"强势 {panel['strong_up_count']} 个，量能扩张 {panel['vol_expansion_count']} 个；"
        f"{cross}；分类分布 {cat_str}。"
    )


def backfill(market: Literal["A", "US"], start: str, end: str,
             pool_path: str | None = None) -> dict:
    days = _trading_days(start, end, market)
    print(f"  交易日数: {len(days)}（{start} ~ {end}）")

    ok = fail = 0
    errors = []
    for d in days:
        # A 股 backfill 用"收"；美股不带后缀
        label = f"{d}-收" if market == "A" else d
        try:
            session = build(market, label, "close", pool_path)
            # 用骨架 summary 替换 narrative
            session["narrative"] = {
                "is_skeleton": True,
                "session_summary": skeleton_summary(session),
            }
            # 重新写归档 + 窗口（覆盖原本 narrative=None 的版本）
            from src import window as win
            win.archive_to_snapshot(market, session)
            win.append_session(market, session)
            ok += 1
            print(f"  [{ok}/{len(days)}] {label} OK  (up={session['panel']['up_count']})")
        except Exception as e:
            fail += 1
            errors.append({"label": label, "error": str(e)[:200]})
            print(f"  [FAIL] {label}: {str(e)[:100]}")

    summary = {"ok": ok, "fail": fail, "errors": errors,
               "total": len(days), "market": market}
    print(f"\n汇总: ok={ok} fail={fail}")
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["A", "US"], required=True)
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--pool", default=None)
    args = p.parse_args()
    backfill(args.market, args.start, args.end, args.pool)


if __name__ == "__main__":
    main()
