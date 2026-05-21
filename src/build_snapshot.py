"""单时段 snapshot 生产。

流水线：
  1. ingest: 从 auto-prtsc 拉池子 ~80 个交易日 OHLCV（够 ma_alignment 60 日 + 余量）
     美股额外需要 ≥150 日（ma150）
  2. 每只 ticker → src.factors.compute_factors
  3. 拼成 classify.enrich 的入参（包一层 adapter）→ enrich 出归类 + 特征
  4. src.panel.build_panel 聚合
  5. window.append_session + archive_to_snapshot

stage 3 不调 LLM，narrative 留 None（stage 4 填）。

入口：
  python -m src.build_snapshot --market A --label 2026-05-20-收 --session close
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
from typing import Literal

import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, r"D:\git\auto prtsc")

import etf_data_api as api
from src.factors import compute_factors
from src.panel import build_panel
from src.classify import enrich
from src import window as win
from src import log_util
from src import audit as audit_mod

DEFAULT_POOL_A = os.path.join(ROOT, "config", "pool_a.yaml")
DEFAULT_POOL_US = os.path.join(ROOT, "config", "pool_us.yaml")


def _load_pool(market: str, pool_path: str) -> dict:
    with open(pool_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _trade_date_from_label(label: str) -> str:
    """label 形如 '2026-05-20-收' / '2026-05-20-午' / 美股 '2026-05-20' → '2026-05-20'。"""
    parts = label.split("-")
    if len(parts) >= 3 and len(parts[0]) == 4:
        return f"{parts[0]}-{parts[1]}-{parts[2]}"
    return label


def _adapter_for_enrich(per_ticker: list[dict], market: str, name_map: dict) -> dict:
    """构造 classify.enrich 期望的 snapshot 结构。
    enrich 的旧契约：snapshot["items"] = [{name, today_pct, yest_pct, today_amount, yest_amount, ...}]
    """
    items = []
    for t in per_ticker:
        items.append({
            "code": t["code"],
            "name": name_map.get(t["code"], t["code"]),
            "today_pct": t["today_pct"] if t["today_pct"] is not None else 0.0,
            "yest_pct": t["yest_pct"] if t["yest_pct"] is not None else 0.0,
            "today_amount": t["today_amount"],
            "yest_amount": t["yest_amount"],
        })
    return {"items": items}


def build(market: Literal["A", "US"], label: str,
          session_time: Literal["noon", "close"],
          pool_path: str | None = None,
          failures_out: list | None = None,
          run_ts: str | None = None) -> dict:
    """生产单时段 session dict，append 到窗口，归档到 snapshots/。返回 session dict。

    failures_out: 若传入 list，单只 ticker 失败时会 append 一条 dict
                  {ticker, error_type, message, log_path}。caller 据此汇总。
    run_ts:       共享时间戳（让同一次 update_all 的所有错误 json 落在同一时间戳）。
    """
    if pool_path is None:
        pool_path = DEFAULT_POOL_A if market == "A" else DEFAULT_POOL_US

    pool = _load_pool(market, pool_path)
    codes = [e["code"] for e in pool["etfs"]]
    name_map = {e["code"]: e.get("name", e["code"]) for e in pool["etfs"]}

    trade_date = _trade_date_from_label(label)
    # -午 时段是当日盘中快照，仅当 trade_date == today 时合法（防止历史回填把
    # 全天日线 amount ×2 伪装成中午，数字会全错）
    if session_time == "noon":
        if market != "A":
            raise RuntimeError(f"session=noon 仅 A 股支持 (market={market})")
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        if trade_date != today_str:
            raise RuntimeError(
                f"-午 时段只能当日实时生成，不能回填历史日 "
                f"(label={label}, today={today_str})")

    # 拉 200 天历史（美股 ma150 需要 150；A 股 60 够用），含目标日
    end_ts = pd.Timestamp(trade_date)
    start_ts = end_ts - pd.Timedelta(days=300)  # 自然日 → 约 200 交易日
    start_str = start_ts.strftime("%Y-%m-%d")
    end_str = end_ts.strftime("%Y-%m-%d")

    fetch = api.get_a_etf_ohlcv if market == "A" else api.get_us_ohlcv
    df_all = fetch(codes, start_str, end_str)
    if df_all.empty:
        raise RuntimeError(f"未取到数据：{market} {label}")

    # noon: 拉腾讯当日实时快照，逐只 append 到历史末尾
    realtime_snaps: dict = {}
    if session_time == "noon":
        realtime_snaps = api.get_a_etf_realtime(codes)

    # 每只 ticker 单独算 factors（单只挂了不影响整批）
    per_ticker = []
    for code in codes:
        try:
            sub = df_all[df_all["code"] == code].copy()
            # noon: 把腾讯快照 append 成今日那一行
            if session_time == "noon":
                snap = realtime_snaps.get(code)
                if snap is None:
                    raise RuntimeError("腾讯实时快照 None")
                # 若历史 df 已含今日（极少：盘后回头跑 noon），先剔除
                snap_date = pd.Timestamp(snap["日期"])
                sub = sub[sub["date"] < snap_date]
                row = pd.DataFrame([{
                    "date": snap_date, "code": code,
                    "open": snap["开盘"], "close": snap["收盘"],
                    "high": snap["最高"], "low": snap["最低"],
                    "volume": snap["成交量"], "amount": snap["成交额"],
                }])
                sub = pd.concat([sub, row], ignore_index=True)
            if sub.empty:
                raise RuntimeError("无任何交易日数据")
            sub = sub[sub["date"] <= end_ts].copy()
            if len(sub) < 2:
                raise RuntimeError(f"历史日数 {len(sub)} < 2")
            closes = sub["close"].to_numpy()
            yest_pct = None
            if len(closes) >= 3 and closes[-3] > 0:
                yest_pct = float(closes[-2] / closes[-3] - 1)
            today_amount = float((sub["amount"] if "amount" in sub.columns and market == "A"
                                  else sub["volume"]).iloc[-1])
            yest_amount = float((sub["amount"] if "amount" in sub.columns and market == "A"
                                 else sub["volume"]).iloc[-2])

            f = compute_factors(sub, market=market, session_time=session_time)
            per_ticker.append({
                "code": code,
                "today_pct": f["today_pct"],
                "yest_pct": yest_pct,
                "today_amount": f["today_amount_adjusted"],
                "yest_amount": yest_amount,
                "factors": {k: v for k, v in f.items()
                            if k not in ("today_pct", "today_amount_adjusted")},
            })
        except Exception as e:
            log_path = log_util.write_error(code, label, market, e, ts=run_ts)
            if failures_out is not None:
                failures_out.append({
                    "ticker": code,
                    "error_type": type(e).__name__,
                    "message": str(e),
                    "log_path": log_path,
                })

    # classify.enrich 做归类
    snap_in = _adapter_for_enrich(per_ticker, market, name_map)
    enriched = enrich(snap_in)
    # 把 enriched.items 的 category/feature/compliance/pct_diff/cum_pct/volume_ratio 回填
    enriched_by_code = {it["code"]: it for it in enriched["items"]}
    for t in per_ticker:
        e = enriched_by_code.get(t["code"], {})
        t["name"] = name_map.get(t["code"], t["code"])
        t["category"] = e.get("category")
        t["feature"] = e.get("feature", "")
        t["compliance"] = e.get("compliance")
        t["pct_diff"] = e.get("pct_diff")
        t["cum_pct"] = e.get("cum_pct")
        t["volume_ratio"] = e.get("volume_ratio")
        t["annotation"] = None
        # 把 new_high_20d 等从 factors 拷一份到顶层（供 panel 用）
        t["vol_ratio_20"] = t["factors"].get("vol_ratio_20")
        t["new_high_20d"] = t["factors"].get("new_high_20d")
        t["new_low_20d"] = t["factors"].get("new_low_20d")
        if market == "US":
            t["ma150_relation"] = t["factors"].get("ma150_relation")

    panel = build_panel(per_ticker, pool, market)

    # 量化代审兜底（任务 2.2）：用窗口里"前一时段"对每只 ticker 打 D1+D2 分。
    # 必须在 append 当前 session 前查；fill_narrative 时 LLM 可覆盖部分 ticker。
    prev_data = win.load(market)
    prev_session = prev_data["sessions"][-1] if prev_data.get("sessions") else None
    audits = audit_mod.quant_audit_batch(prev_session, {"tickers": per_ticker})
    for t in per_ticker:
        a = audits.get(t["code"])
        t["audit"] = a  # dict 或 None

    # 周末标记（任务 4）：A 股周五-收 / 美股周五 → 触发 macro_cycle_anchor
    is_weekend_close = _is_weekend_close(trade_date, market, session_time, label)

    session = {
        "label": label,
        "market": market,
        "session_time": session_time,
        "trade_date": trade_date,
        "timestamp": datetime.datetime.now().isoformat(),
        "is_weekend_close": is_weekend_close,
        "tickers": per_ticker,
        "panel": panel,
        "narrative": None,
        "tracking": {"rating_history": []},
    }

    win.archive_to_snapshot(market, session)
    popped = win.append_session(market, session)
    if popped:
        print(f"  弹出最老 session: {popped}")

    return session


def _is_weekend_close(trade_date: str, market: str,
                      session_time: str, label: str) -> bool:
    """周末收盘判定：周五（weekday=4）。A 股需 session_time=close；美股每个 label 即收盘。"""
    try:
        wd = datetime.date.fromisoformat(trade_date).weekday()
    except (ValueError, TypeError):
        return False
    if wd != 4:
        return False
    if market == "A":
        return session_time == "close"
    return True  # US


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["A", "US"], required=True)
    p.add_argument("--label", required=True, help="例 2026-05-20-收")
    p.add_argument("--session", choices=["noon", "close"], default="close")
    p.add_argument("--pool", default=None)
    args = p.parse_args()
    s = build(args.market, args.label, args.session, args.pool)
    print(f"OK label={s['label']} tickers={len(s['tickers'])} panel.up={s['panel']['up_count']}")


if __name__ == "__main__":
    main()
