"""检测 etf_cc 报告层缺口：哪些 label 还没生成 snapshot。

与底层数据层缺口（auto-prtsc/gap_fill 管的"切片缺哪几天"）正交：
本模块只看 data/snapshots/<market>/*.json 文件名，对照交易日历列出缺的 label。

label 约定：
  A 股：<date>-午 + <date>-收
  美股：<date>

完整行为矩阵（default_end + expected_labels 共同决定 update_all 在每个时点补什么）：

  +-------+-----------------------+--------------------+-----------+----------------------------------------+
  | 市场  | 跑的时刻              | end_date           | a_until   | 当天会补什么                           |
  +-------+-----------------------+--------------------+-----------+----------------------------------------+
  | A     | 开盘前 / 周末 / 节假日| 上一交易日         | "close"   | 只补历史 -收                           |
  | A     | 11:35 ≤ now < 15:05   | 今天               | "noon"    | 历史 -收 + 今日 -午（实时腾讯快照）   |
  | A     | 15:05 后              | 今天               | None      | 历史 -收 + 今日 -午（×2 估算）+ 今日 -收|
  | US    | 北京 ≥ 5:30           | 最近一个美股交易日 | —（忽略）| 该交易日 1 个 label                    |
  | US    | 北京 < 5:30           | 再前一个美股交易日 | —（忽略）| 该交易日 1 个 label                    |
  +-------+-----------------------+--------------------+-----------+----------------------------------------+

A 股 -午 实时数据来源：etf_data_api.get_a_etf_realtime（腾讯快照）。
A 股 -午 历史回填被 build_snapshot 拒绝（防"全天日线 ×2 假装中午"）。
"""
from __future__ import annotations

import datetime
import os
from typing import Literal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOTS_DIR = os.path.join(ROOT, "data", "snapshots")


def _trading_days(start: str, end: str, market: str) -> list[str]:
    import exchange_calendars as xcals
    cal_name = "XSHG" if market == "A" else "XNYS"
    cal = xcals.get_calendar(cal_name)
    sessions = cal.sessions_in_range(start, end)
    return [s.strftime("%Y-%m-%d") for s in sessions]


def expected_labels(market: Literal["A", "US"], start: str, end: str,
                    a_until: Literal["noon", "close"] | None = None) -> list[str]:
    """[start, end] 区间内应当存在的 label 列表（升序）。

    A 股：过去日只期望 -收；end 当天按 a_until 决定。
      - a_until="noon"  → 只 -午（当日 11:35-15:05 之间）
      - a_until="close" → 只 -收（end 是历史日：开盘前 / 非 session）
      - a_until=None    → -午 + -收（当日 15:05 后已完整收盘）

    -午 时段由 build_snapshot 内部调 etf_data_api.get_a_etf_realtime 拉腾讯
    当日快照生成；build_snapshot 已禁止"过去日 + noon"组合，本函数也只在
    end == 今天且 a_until in (None, "noon") 时产 -午。

    美股：每个交易日一个 label。
    """
    days = _trading_days(start, end, market)
    if market == "US":
        return list(days)
    labels: list[str] = []
    for d in days:
        is_end = (d == end)
        if not is_end:
            labels.append(f"{d}-收")
        elif a_until == "noon":
            labels.append(f"{d}-午")
        elif a_until == "close":
            labels.append(f"{d}-收")
        else:
            labels.append(f"{d}-午")
            labels.append(f"{d}-收")
    return labels


def existing_labels(market: Literal["A", "US"]) -> set[str]:
    sub = "a" if market == "A" else "us"
    d = os.path.join(SNAPSHOTS_DIR, sub)
    if not os.path.isdir(d):
        return set()
    out = set()
    for fn in os.listdir(d):
        if fn.endswith(".json"):
            out.add(fn[:-5])
    return out


def detect_report_gaps(market: Literal["A", "US"], start: str, end: str,
                       a_until: Literal["noon", "close"] | None = None) -> list[str]:
    """返回升序的缺口 label 列表。"""
    expected = expected_labels(market, start, end, a_until)
    existing = existing_labels(market)
    return [l for l in expected if l not in existing]


def default_end(market: Literal["A", "US"],
                now: datetime.datetime | None = None) -> tuple[str, Literal["noon", "close"] | None]:
    """返回 (end_date_str, a_until)，给 caller 当作 detect_report_gaps 的实参。"""
    import exchange_calendars as xcals
    now = now or datetime.datetime.now()
    cal_name = "XSHG" if market == "A" else "XNYS"
    cal = xcals.get_calendar(cal_name)
    today = now.date().strftime("%Y-%m-%d")

    if market == "A":
        is_session = bool(cal.sessions_in_range(today, today).size)
        if is_session:
            if now.hour > 15 or (now.hour == 15 and now.minute >= 5):
                return today, None        # 收盘到点：当天 -午 + -收 都期望
            if now.hour > 11 or (now.hour == 11 and now.minute >= 35):
                return today, "noon"      # 仅 -午 期望
            # 开盘前：用上一交易日（历史日，永远不产 -午）
            sess = cal.sessions_in_range("2010-01-01", today)
            prior = sess[-2].strftime("%Y-%m-%d") if len(sess) >= 2 else today
            return prior, "close"
        # 非交易日（周末/节假日）：取 today 之前最近的 session（历史日）
        sess = cal.sessions_in_range("2010-01-01", today)
        if not len(sess):
            return today, "close"
        return sess[-1].strftime("%Y-%m-%d"), "close"

    # 美股：北京 5:30 后可补"前一美股交易日"
    cutoff_passed = (now.hour > 5 or (now.hour == 5 and now.minute >= 30))
    today_bj = now.date().strftime("%Y-%m-%d")
    # 取 today_bj 之前最近的美股交易日（不含 today_bj 本身）
    sess = cal.sessions_in_range("2010-01-01", today_bj)
    if not len(sess):
        return today_bj, None
    last_session = sess[-1].strftime("%Y-%m-%d")
    if last_session == today_bj or not cutoff_passed:
        # 今天若是美股 session，按定义还没到次日 5:30；用更早一个
        prior = sess[-2].strftime("%Y-%m-%d") if len(sess) >= 2 else last_session
        return prior, None
    return last_session, None
