"""7 派生因子（向量化）+ 单一入口 compute_factors。

契约（REFACTOR_BRIEF 4.4a / CLAUDE.md "7 个派生因子"）：
  - 数据不足直接返 None，不做 partial
  - 中午时段 today_amount ×2（由 compute_factors 内部处理）
  - |pct_normalized| > 2 → is_outlier=True
  - factor 函数为纯函数：输入 pandas Series / DataFrame，输出标量或 None

不在本文件做的事：
  - 取数（ingest）
  - 归类（classify）
  - 板面聚合（panel）
"""
from __future__ import annotations

import math
from typing import Literal, Optional
import pandas as pd

from src import thresholds_cfg as tcfg

MaAlignment = Literal["多头", "空头", "震荡"]
Ma150Relation = Literal["站上", "跌破", "震荡"]


def price_pctile(closes: pd.Series, window: int, min_periods: int) -> Optional[int]:
    """收盘价分位：今日在最近 window 日中的位置百分比，0=最低，100=最高，含当日。

    公式：(ordinal_rank - 1) / (n - 1) * 100，并列取平均序。
    closes: 升序日期排列的收盘序列，最后一行=今日。
    """
    if len(closes) < min_periods:
        return None
    recent = closes.iloc[-window:] if len(closes) >= window else closes
    n = len(recent)
    if n < 2:
        return None
    today = recent.iloc[-1]
    below = (recent < today).sum()
    equal = (recent == today).sum()
    # 并列时取平均序：first equal at position (below+1), last at (below+equal)
    # 平均 = (below+1 + below+equal) / 2 = below + (equal+1)/2
    avg_rank = below + (equal + 1) / 2
    pct = (avg_rank - 1) / (n - 1) * 100
    return int(round(pct))


def vol_ratio_20(amounts: pd.Series, today_amount: float) -> Optional[float]:
    """today_amount / mean(amount[-20:不含当日])。

    amounts: 不含当日的历史成交额序列（升序日期）
    """
    if len(amounts) < 5:
        return None
    basis = amounts.iloc[-20:].mean()
    if basis <= 0:
        return None
    return round(today_amount / basis, 4)


def vol_pctile_20(amounts_incl_today: pd.Series) -> Optional[int]:
    """成交量分位：含当日，0=最低，100=最高，公式同 price_pctile。"""
    if len(amounts_incl_today) < 10:
        return None
    recent = amounts_incl_today.iloc[-20:] if len(amounts_incl_today) >= 20 else amounts_incl_today
    n = len(recent)
    if n < 2:
        return None
    today = recent.iloc[-1]
    below = (recent < today).sum()
    equal = (recent == today).sum()
    avg_rank = below + (equal + 1) / 2
    pct = (avg_rank - 1) / (n - 1) * 100
    return int(round(pct))


def close_vs_ma(closes: pd.Series, window: int,
                near_threshold: float = 0.005) -> Optional[str]:
    """收盘价相对 window 日 SMA 的位置：above / below / near。
    ±0.5% 内算 near。数据不足返 None。"""
    if len(closes) < window:
        return None
    ma = closes.iloc[-window:].mean()
    if ma <= 0:
        return None
    today = float(closes.iloc[-1])
    diff = (today - ma) / ma
    if abs(diff) <= near_threshold:
        return "near"
    return "above" if diff > 0 else "below"


def ma_alignment(closes: pd.Series) -> Optional[MaAlignment]:
    """5/20/60 SMA 排列。多头=MA5>MA20>MA60，空头=MA5<MA20<MA60，否则震荡。"""
    if len(closes) < 60:
        return None
    ma5 = closes.iloc[-5:].mean()
    ma20 = closes.iloc[-20:].mean()
    ma60 = closes.iloc[-60:].mean()
    if ma5 > ma20 > ma60:
        return "多头"
    if ma5 < ma20 < ma60:
        return "空头"
    return "震荡"


def _atr_20(highs: pd.Series, lows: pd.Series, closes: pd.Series) -> Optional[float]:
    """20 日 ATR：TR=max(h-l, |h-prev_c|, |l-prev_c|), ATR=mean(TR 最近 20 日)。

    所有序列等长且按日期升序，最后行=今日。需要 ≥21 行（20 个 TR 需要 prev_close）。
    """
    if len(closes) < 21:
        return None
    h = highs.iloc[-21:].to_numpy()
    l = lows.iloc[-21:].to_numpy()
    c = closes.iloc[-21:].to_numpy()
    prev_c = c[:-1]
    h_cur = h[1:]
    l_cur = l[1:]
    tr = pd.Series([max(hi - lo, abs(hi - pc), abs(lo - pc))
                    for hi, lo, pc in zip(h_cur, l_cur, prev_c)])
    return float(tr.mean())


def pct_normalized(today_pct: float, highs: pd.Series, lows: pd.Series,
                   closes: pd.Series) -> Optional[float]:
    """today_pct / (ATR_20 / yesterday_close)。

    today_pct 为小数（0.045=4.5%）；分母也化作小数。返回无量纲倍数。
    """
    atr = _atr_20(highs, lows, closes)
    if atr is None:
        return None
    if len(closes) < 2:
        return None
    yest_close = float(closes.iloc[-2])
    if yest_close <= 0:
        return None
    denom = atr / yest_close
    if denom <= 0:
        return None
    return round(today_pct / denom, 4)


def new_high_20d(closes_incl_today: pd.Series) -> Optional[bool]:
    """今日收盘是否为最近 20 日（含今日）新高。"""
    if len(closes_incl_today) < 20:
        return None
    recent = closes_incl_today.iloc[-20:]
    return bool(recent.iloc[-1] >= recent.max())


def new_low_20d(closes_incl_today: pd.Series) -> Optional[bool]:
    """今日收盘是否为最近 20 日（含今日）新低。"""
    if len(closes_incl_today) < 20:
        return None
    recent = closes_incl_today.iloc[-20:]
    return bool(recent.iloc[-1] <= recent.min())


def ma150(closes: pd.Series) -> tuple[Optional[float], Optional[Ma150Relation]]:
    """30 周均线（150 日 SMA）。返回 (距 MA150 偏离百分比, 关系)。

    偏离 % = (close - MA150) / MA150 * 100；
    |%| <= MA150_NEAR_PCT（默认 2，可在 GUI 调）→ 震荡，> 站上，< 跌破。仅美股调用。
    """
    if len(closes) < 150:
        return None, None
    ma = closes.iloc[-150:].mean()
    if ma <= 0:
        return None, None
    today = float(closes.iloc[-1])
    dist = (today - ma) / ma * 100
    near_pct = tcfg.get("MA150_NEAR_PCT", 2.0)
    if dist > near_pct:
        rel: Ma150Relation = "站上"
    elif dist < -near_pct:
        rel = "跌破"
    else:
        rel = "震荡"
    return round(float(dist), 2), rel


def compute_factors(ohlcv_df: pd.DataFrame, market: Literal["A", "US"],
                    session_time: Literal["noon", "close"] = "close") -> dict:
    """单一入口：给一只标的的 OHLCV 历史（含今日）算出全部因子。

    Args:
        ohlcv_df: 列须含 ["date","open","close","high","low","amount"]（A 股）
                  或 ["date","open","close","high","low","volume"]（美股，无 amount）
                  日期升序，最后一行=今日。
        market:   "A" 或 "US"
        session_time: "noon" → today_amount/today_volume 在算量能因子前 ×2；"close" 不动。

    Returns:
        dict，键见下方。值为 None 表示数据不足。包含 is_outlier 标记。
    """
    if ohlcv_df is None or len(ohlcv_df) == 0:
        return {}

    df = ohlcv_df.sort_values("date").reset_index(drop=True)
    closes = df["close"].astype(float)
    highs = df["high"].astype(float)
    lows = df["low"].astype(float)

    # 量能基准列：A 股用 amount，美股用 volume
    amount_col = "amount" if market == "A" and "amount" in df.columns else "volume"
    amounts_all = df[amount_col].astype(float)

    # 今日量能：午盘 ×2（amounts_all 的最后一行就是 today，原地替换）
    today_amount_raw = float(amounts_all.iloc[-1])
    today_amount_adj = today_amount_raw * 2 if session_time == "noon" else today_amount_raw
    amounts_incl_today = amounts_all.copy()
    amounts_incl_today.iloc[-1] = today_amount_adj
    amounts_excl_today = amounts_all.iloc[:-1]

    # today_pct：(today_close / yest_close - 1)
    today_pct = None
    if len(closes) >= 2 and float(closes.iloc[-2]) > 0:
        today_pct = float(closes.iloc[-1]) / float(closes.iloc[-2]) - 1

    p60 = price_pctile(closes, window=60, min_periods=30)
    p20 = price_pctile(closes, window=20, min_periods=10)
    vr20 = vol_ratio_20(amounts_excl_today, today_amount_adj)
    vp20 = vol_pctile_20(amounts_incl_today)
    ma_align = ma_alignment(closes)
    near_thr = tcfg.get("NEAR_MA_THRESHOLD", 0.005)
    cvs_ma5 = close_vs_ma(closes, 5, near_threshold=near_thr)
    cvs_ma20 = close_vs_ma(closes, 20, near_threshold=near_thr)
    cvs_ma60 = close_vs_ma(closes, 60, near_threshold=near_thr)
    pn = pct_normalized(today_pct, highs, lows, closes) if today_pct is not None else None
    nh = new_high_20d(closes)
    nl = new_low_20d(closes)

    is_outlier = (pn is not None) and (abs(pn) > 2)

    result = {
        "today_pct": round(today_pct, 6) if today_pct is not None else None,
        "today_amount_adjusted": today_amount_adj,
        "price_pctile_60": p60,
        "price_pctile_20": p20,
        "vol_ratio_20": vr20,
        "vol_pctile_20": vp20,
        "ma_alignment": ma_align,
        "close_vs_ma5": cvs_ma5,
        "close_vs_ma20": cvs_ma20,
        "close_vs_ma60": cvs_ma60,
        "pct_normalized": pn,
        "new_high_20d": nh,
        "new_low_20d": nl,
        "is_outlier": is_outlier,
    }

    if market == "US":
        dist, rel = ma150(closes)
        result["ma150_dist"] = dist
        result["ma150_relation"] = rel

    return result
