"""一键数据更新入口（REFACTOR_BRIEF §4.6.5）。

流程：
  1. data_refresh.refresh_data()          底层切片补齐（auto-prtsc/gap_fill）
  2. report_gap.detect_report_gaps()      etf_cc 报告层缺口
  3. 逐 label 跑 build_snapshot.build()   单只 ticker 失败不影响整批
  4. log_util.write_run_summary()         落 data/logs/update_<ts>.log

只到 snapshot 落地为止，HTML 渲染另用 render_html.py。

入口：
  python -m src.update_all                       # A + US 都跑，回看 7 天缺口
  python -m src.update_all --markets A           # 只 A
  python -m src.update_all --lookback 14         # 回看 14 天
  python -m src.update_all --skip-refresh        # 跳过底层补齐（已在别处跑过）
"""
from __future__ import annotations

import argparse
import datetime
import time
from typing import Callable, Literal

from src import data_refresh, log_util, report_gap
from src.build_snapshot import build


def _session_time_for(label: str) -> Literal["noon", "close"]:
    return "noon" if label.endswith("-午") else "close"


def _trade_date_from_label(label: str) -> str:
    """label "2026-05-20-收" / "2026-05-20" → "2026-05-20"。"""
    parts = label.split("-")
    if len(parts) >= 3 and len(parts[0]) == 4:
        return f"{parts[0]}-{parts[1]}-{parts[2]}"
    return label


def _prefetch_ohlcv_cache(market, labels, log_cb):
    """一次性拉 [最早缺口 trade_date - 300 自然日, 最新缺口 trade_date] 区间的整池
    OHLCV。返回 DataFrame，传给 build_snapshot 作 ohlcv_cache 参数共享。

    失败 / 池为空 / labels 为空 → 返 None（build_snapshot 退化为各自 fetch）。
    """
    if not labels:
        return None
    # 只为 close session 优化（noon 内部仍要拉腾讯实时快照）
    trade_dates = sorted(set(_trade_date_from_label(lab) for lab in labels))
    if not trade_dates:
        return None

    import os
    import sys
    import yaml
    import pandas as pd

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if r"D:\git\auto prtsc" not in sys.path:
        sys.path.insert(0, r"D:\git\auto prtsc")
    pool_fp = os.path.join(ROOT, "config", f"pool_{market.lower()}.yaml")
    if not os.path.exists(pool_fp):
        return None
    with open(pool_fp, "r", encoding="utf-8") as f:
        pool = yaml.safe_load(f) or {}
    codes = [e["code"] for e in pool.get("etfs", [])]
    if not codes:
        return None

    earliest = pd.Timestamp(trade_dates[0]) - pd.Timedelta(days=300)
    latest = pd.Timestamp(trade_dates[-1])
    log_cb(f"[{market}] 预拉 {len(codes)} 只品种 {earliest.date()} ~ {latest.date()} "
           f"历史 OHLCV（{len(labels)} 个 label 共享）...")

    try:
        import etf_data_api as api
        fetch = api.get_a_etf_ohlcv if market == "A" else api.get_us_ohlcv
        df = fetch(codes, earliest.strftime("%Y-%m-%d"), latest.strftime("%Y-%m-%d"))
        if df is None or df.empty:
            log_cb(f"[{market}] 预拉返空，回退到每 label 单独拉")
            return None
        df["date"] = pd.to_datetime(df["date"])
        log_cb(f"[{market}] 预拉完成: {len(df)} 行，{df['code'].nunique()} 只品种")
        return df
    except Exception as e:
        log_cb(f"[{market}] 预拉失败 ({type(e).__name__}: {e})，回退到每 label 单独拉")
        return None


def run(markets: list[Literal["A", "US"]],
        lookback_days: int = 7,
        skip_refresh: bool = False,
        log_cb: Callable[[str], None] = print) -> dict:
    """跑 update_all。log_cb 默认 print（CLI 行为不变）；GUI 传自己的 callback 收集日志。"""
    started = datetime.datetime.now()
    run_ts = started.strftime("%Y%m%d-%H%M%S")
    t0 = time.time()

    summary: dict = {
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "data_refresh": None,
        "labels": [],
        "elapsed_sec": 0.0,
    }

    if not skip_refresh:
        results = data_refresh.refresh_all(markets, log_cb=log_cb)
        summary["data_refresh"] = {
            m: {"ok": ok, "note": note} for m, (ok, note) in results.items()
        }

    for market in markets:
        end_date, a_until = report_gap.default_end(market)
        start_date = (datetime.date.fromisoformat(end_date)
                      - datetime.timedelta(days=lookback_days)).isoformat()
        gaps = report_gap.detect_report_gaps(market, start_date, end_date, a_until)
        log_cb(f"\n[{market}] 报告缺口 {len(gaps)} 个（{start_date} ~ {end_date}）")

        # 批量预拉 OHLCV cache：多个 close-session 缺口共享一次大区间拉取。
        # noon 时段需腾讯实时快照，不共享；但 cache 提供 ma150 等历史窗口仍可用。
        ohlcv_cache = _prefetch_ohlcv_cache(market, gaps, log_cb)

        for label in gaps:
            failures: list[dict] = []
            try:
                session = build(market, label, _session_time_for(label),
                                failures_out=failures, run_ts=run_ts,
                                log_cb=log_cb, ohlcv_cache=ohlcv_cache)
                total = len(session["tickers"]) + len(failures)
                ok_n = len(session["tickers"])
                summary["labels"].append({
                    "market": market, "label": label,
                    "total": total, "ok": ok_n, "failed": failures,
                })
                log_cb(f"  {label}  成功 {ok_n}/{total}"
                       + (f"  失败 {len(failures)}" if failures else ""))
            except Exception as e:
                log_path = log_util.write_error("__batch__", label, market, e, ts=run_ts)
                summary["labels"].append({
                    "market": market, "label": label,
                    "total": 0, "ok": 0,
                    "failed": [{"ticker": "__batch__",
                                "error_type": type(e).__name__,
                                "message": str(e), "log_path": log_path}],
                })
                log_cb(f"  {label}  整批失败: {type(e).__name__}: {str(e)[:80]}")

    summary["elapsed_sec"] = time.time() - t0
    log_path = log_util.write_run_summary(summary, ts=run_ts)
    log_cb("\n" + log_util.format_run_summary(summary))
    log_cb(f"\n日志: {log_path}")
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--markets", default="A,US",
                   help="逗号分隔，默认 A,US")
    p.add_argument("--lookback", type=int, default=7,
                   help="从今日往前回看几天找缺口（默认 7）")
    p.add_argument("--skip-refresh", action="store_true",
                   help="跳过 auto-prtsc gap_fill 底层补齐")
    args = p.parse_args()
    markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    run(markets, args.lookback, args.skip_refresh)


if __name__ == "__main__":
    main()
