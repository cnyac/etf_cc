"""factors.py 单元测试。

覆盖（CLAUDE.md 第 6 条要求的"factors.py 各因子在数据不足时返 null"）：
  - 各因子数据不足 → None
  - 中午 vol_ratio_20 / vol_pctile_20 是收盘版本的 2 倍逻辑
  - pct_normalized 公式正确
  - |pct_normalized|>2 → is_outlier=True
  - ma150 仅美股触发
"""
import pandas as pd
import pytest

from src.factors import (
    price_pctile, vol_ratio_20, vol_pctile_20, ma_alignment,
    pct_normalized, new_high_20d, new_low_20d, ma150,
    vol_std_20, rs_vs_benchmark, er60, mdd60, slope_seg,
    compute_factors,
)


def _mk_ohlcv(n, market="A", base_close=10.0, close_pattern=None, amount=1e9):
    """构造 n 行 OHLCV。close_pattern 可为 list[float] 覆盖收盘价。"""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    if close_pattern is None:
        closes = [base_close + 0.01 * i for i in range(n)]
    else:
        closes = close_pattern
    df = pd.DataFrame({
        "date": dates,
        "open": [c * 0.99 for c in closes],
        "close": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.98 for c in closes],
        "amount": [amount] * n,
        "volume": [amount / 10 for _ in range(n)],
    })
    return df


# --- 数据不足 → None ---

def test_price_pctile_60_insufficient():
    s = pd.Series([10.0] * 29)
    assert price_pctile(s, 60, 30) is None


def test_vol_ratio_20_insufficient():
    s = pd.Series([1e9] * 4)
    assert vol_ratio_20(s, 1e9) is None


def test_ma_alignment_insufficient():
    s = pd.Series([10.0] * 59)
    assert ma_alignment(s) is None


def test_pct_normalized_insufficient_history():
    s = pd.Series([10.0] * 20)
    h = s * 1.01
    l = s * 0.99
    # ATR 需要 21 行才能算
    assert pct_normalized(0.01, h, l, s) is None


def test_new_high_20d_insufficient():
    s = pd.Series([10.0] * 19)
    assert new_high_20d(s) is None


def test_ma150_insufficient():
    s = pd.Series([10.0] * 149)
    dist, rel = ma150(s)
    assert dist is None and rel is None


# --- 正常路径 ---

def test_price_pctile_new_high():
    closes = pd.Series(list(range(1, 61)))  # 1..60 升序
    assert price_pctile(closes, 60, 30) == 100  # 60 最大


def test_price_pctile_new_low():
    closes = pd.Series(list(range(60, 0, -1)))  # 60..1 降序
    assert price_pctile(closes, 60, 30) == 0  # 1 最小


def test_vol_ratio_20_doubles_at_noon():
    """中午 today_amount ×2 → vol_ratio_20 是收盘的 2 倍。"""
    hist = pd.Series([1e9] * 20)
    close_ratio = vol_ratio_20(hist, 1e9)        # 1.0
    noon_ratio = vol_ratio_20(hist, 1e9 * 2)     # 2.0
    assert close_ratio == 1.0
    assert noon_ratio == 2.0


def test_ma_alignment_bullish():
    # 单调上升 → MA5>MA20>MA60
    closes = pd.Series([float(i) for i in range(1, 61)])
    assert ma_alignment(closes) == "多头"


def test_ma_alignment_bearish():
    closes = pd.Series([float(i) for i in range(60, 0, -1)])
    assert ma_alignment(closes) == "空头"


def test_ma_alignment_choppy():
    # MA5=MA20=MA60 → 不满足严格大于 → 震荡
    closes = pd.Series([10.0] * 60)
    assert ma_alignment(closes) == "震荡"


# --- close vs ma 三球 ---

def test_close_vs_ma_above():
    from src.factors import close_vs_ma
    # MA20 = 10，今日 11 → 偏离 +10% → above
    closes = pd.Series([10.0] * 19 + [11.0])
    assert close_vs_ma(closes, 20) == "above"


def test_close_vs_ma_below():
    from src.factors import close_vs_ma
    closes = pd.Series([10.0] * 19 + [9.0])
    assert close_vs_ma(closes, 20) == "below"


def test_close_vs_ma_near():
    from src.factors import close_vs_ma
    # MA20 = 10，今日 10.003 → 偏离 0.03% → near
    closes = pd.Series([10.0] * 19 + [10.003])
    assert close_vs_ma(closes, 20) == "near"


def test_close_vs_ma_insufficient():
    from src.factors import close_vs_ma
    closes = pd.Series([10.0] * 5)
    assert close_vs_ma(closes, 20) is None


def test_new_high_20d_true():
    closes = pd.Series([10.0] * 19 + [15.0])
    assert new_high_20d(closes) is True


def test_new_high_20d_false():
    closes = pd.Series([15.0] + [10.0] * 18 + [12.0])
    assert new_high_20d(closes) is False


def test_new_low_20d_true():
    closes = pd.Series([10.0] * 19 + [5.0])
    assert new_low_20d(closes) is True


def test_pct_normalized_formula():
    """构造已知数据：close 全是 100，high=101, low=99，prev_close=100。
    TR 每天 = max(2, 1, 1) = 2. ATR_20 = 2. yest_close = 100.
    denom = 2/100 = 0.02. today_pct=0.01 → pct_normalized = 0.5。
    """
    n = 22
    closes = pd.Series([100.0] * n)
    highs = pd.Series([101.0] * n)
    lows = pd.Series([99.0] * n)
    pn = pct_normalized(0.01, highs, lows, closes)
    assert pn == pytest.approx(0.5, abs=0.01)


def test_ma150_relation_above():
    closes = pd.Series([10.0] * 149 + [10.5])  # 当日比 MA 高 5%
    dist, rel = ma150(closes)
    assert rel == "站上"
    assert dist > 0


def test_ma150_relation_below():
    closes = pd.Series([10.0] * 149 + [9.5])
    dist, rel = ma150(closes)
    assert rel == "跌破"


def test_ma150_relation_choppy():
    closes = pd.Series([10.0] * 149 + [10.1])  # 偏离 ~1%
    dist, rel = ma150(closes)
    assert rel == "震荡"


# --- compute_factors 集成 ---

def test_compute_factors_a_share_basic():
    df = _mk_ohlcv(100, market="A")
    r = compute_factors(df, market="A", session_time="close")
    assert r["price_pctile_60"] == 100  # 单调上升，最后一天最大
    assert r["ma_alignment"] == "多头"
    assert r["new_high_20d"] is True
    assert r["new_low_20d"] is False
    assert "ma150_dist" not in r  # A 股不算 MA150
    # 三球：单调上升 → 至少 MA20/MA60 above（MA5 因增量太小可能 near）
    assert r["close_vs_ma20"] == "above"
    assert r["close_vs_ma60"] == "above"
    assert r["close_vs_ma5"] in ("above", "near")


def test_compute_factors_us_includes_ma150():
    df = _mk_ohlcv(160, market="US")
    r = compute_factors(df, market="US", session_time="close")
    assert "ma150_dist" in r
    assert r["ma150_relation"] in ("站上", "跌破", "震荡")


def test_compute_factors_noon_doubles_today_amount():
    df = _mk_ohlcv(50, market="A", amount=1e9)
    r_close = compute_factors(df, market="A", session_time="close")
    r_noon = compute_factors(df, market="A", session_time="noon")
    # 历史 19 天全 1e9，今日 close=1e9 → vr20=1.0；午盘等效今日 2e9 → vr20=2.0
    assert r_close["vol_ratio_20"] == pytest.approx(1.0, abs=0.01)
    assert r_noon["vol_ratio_20"] == pytest.approx(2.0, abs=0.01)
    assert r_noon["today_amount_adjusted"] == 2e9


def test_compute_factors_is_outlier_flag():
    # 构造大涨：close 突然跳 10%，ATR 小 → pct_normalized 很大
    closes = [100.0] * 21 + [110.0]
    df = _mk_ohlcv(22, market="A", close_pattern=closes)
    # ATR ~ 2，denom ~ 0.02，today_pct=0.1 → pn~5 > 2
    r = compute_factors(df, market="A", session_time="close")
    assert r["is_outlier"] is True


def test_compute_factors_insufficient_returns_nulls():
    """只给 5 行 → 多数因子返 None。"""
    df = _mk_ohlcv(5, market="A")
    r = compute_factors(df, market="A", session_time="close")
    assert r["price_pctile_60"] is None
    assert r["ma_alignment"] is None
    assert r["new_high_20d"] is None
    assert r["pct_normalized"] is None
    assert r["vol_std_20"] is None
    assert r["er60"] is None
    assert r["mdd60"] is None
    assert r["slope_seg"] is None


# --- 增量 A：vol_std_20 / rs_vs_benchmark ---

def test_vol_std_20_insufficient():
    assert vol_std_20(pd.Series([10.0] * 20)) is None  # 只能产生 19 returns


def test_vol_std_20_basic():
    # 21 个 close，固定每日 +1% → 20 个相同 returns，std=0
    closes = pd.Series([100.0 * (1.01 ** i) for i in range(21)])
    v = vol_std_20(closes)
    assert v == pytest.approx(0.0, abs=1e-6)


def test_vol_std_20_nonzero():
    # 21 个 close，交替 +5% / -5% → std 显著 > 0
    closes = [100.0]
    for i in range(20):
        closes.append(closes[-1] * (1.05 if i % 2 == 0 else 0.95))
    v = vol_std_20(pd.Series(closes))
    assert v is not None and v > 0.04


def test_rs_vs_benchmark_basic():
    assert rs_vs_benchmark(0.05, 0.02) == pytest.approx(0.03, abs=1e-6)
    assert rs_vs_benchmark(0.02, 0.02) == 0.0  # 基准自身


def test_rs_vs_benchmark_nulls():
    assert rs_vs_benchmark(None, 0.02) is None
    assert rs_vs_benchmark(0.05, None) is None


def test_compute_factors_rs_pass_through():
    df = _mk_ohlcv(30, market="A")
    r = compute_factors(df, market="A", session_time="close", benchmark_today_pct=0.0)
    assert r["rs_vs_benchmark"] == pytest.approx(r["today_pct"], abs=1e-6)
    r2 = compute_factors(df, market="A", session_time="close")  # 未传基准 → None
    assert r2["rs_vs_benchmark"] is None


# --- 增量 B：er60 / mdd60 / slope_seg ---

def test_er60_insufficient():
    assert er60(pd.Series([10.0] * 30)) is None  # 只能产生 29 diffs


def test_er60_smooth_close_to_one():
    # 61 个 close，单调线性增长 → er ≈ 1.0
    closes = pd.Series([100.0 + i for i in range(61)])
    e = er60(closes)
    assert e == pytest.approx(1.0, abs=1e-4)


def test_er60_v_shape_low():
    # V 型：先跌 30 段再涨 30 段，最终回到起点 → numerator=0, er=0
    closes = pd.Series([100.0 - i for i in range(31)] + [70.0 + i for i in range(1, 31)])
    e = er60(closes)
    assert e == pytest.approx(0.0, abs=1e-4)


def test_er60_smooth_higher_than_v_shape():
    smooth = pd.Series([100.0 + i for i in range(61)])
    # V 型回拉到起点之上：从 100 跌到 70 再到 110，终点比起点高 10
    v = pd.Series([100.0 - i for i in range(31)] + [70.0 + (i * 40 / 30) for i in range(1, 31)])
    assert er60(smooth) > er60(v) + 0.5


def test_mdd60_insufficient():
    assert mdd60(pd.Series([10.0] * 29)) is None


def test_mdd60_known():
    # 已知序列：peak=120, trough=90 之后 → mdd=(120-90)/120=0.25
    closes = pd.Series([100.0] * 10 + [120.0] + [90.0] + [95.0] * 18)  # 30 个
    m = mdd60(closes)
    assert m == pytest.approx(0.25, abs=1e-4)


def test_mdd60_monotonic_zero():
    closes = pd.Series([100.0 + i for i in range(60)])
    assert mdd60(closes) == pytest.approx(0.0, abs=1e-6)


def test_slope_seg_insufficient():
    assert slope_seg(pd.Series([10.0] * 59)) is None


def test_slope_seg_orientation_far_to_near():
    # 远段平、中段涨、近段跌 → [≈0, +大, -大]
    seg_far = [100.0] * 20
    seg_mid = [100.0 + i * 1.0 for i in range(20)]   # 100 → 119
    seg_near = [120.0 - i * 1.0 for i in range(20)]  # 120 → 101
    closes = pd.Series(seg_far + seg_mid + seg_near)
    s = slope_seg(closes)
    assert s is not None and len(s) == 3
    assert s[0] == pytest.approx(0.0, abs=1e-4)
    assert s[1] > 0.15
    assert s[2] < -0.10
