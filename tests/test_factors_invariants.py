"""业务合理性不变量自检：A+B 五个新因子。

设计原则：验「业务规律」，不验「具体数值」——数据变了依然有效。
  - 合成数据：构造极端场景，验方向正确 + 边界返 None
  - 真实数据：从网络拉真实 ETF，验取值范围 + 基准逻辑

真实数据 fetch 若网络不通则自动跳过（pytest.skip），不阻断 CI。

真实池配置（已在 pool_a.yaml 确认）：
  - SZ159845: 中证1000ETF（A 股基准）
  - SH518880: 黄金 ETF（与基准关联度低，rs_vs_benchmark 应非零）
"""
from __future__ import annotations

import math
import sys

import pandas as pd
import pytest

sys.path.insert(0, r"D:\git\auto prtsc")

from src.factors import (
    compute_factors,
    er60,
    mdd60,
    rs_vs_benchmark,
    slope_seg,
    vol_std_20,
)

BENCHMARK_CODE_A = "SZ159845"
GOLD_CODE = "SH518880"

# ---------------------------------------------------------------------------
# 辅助：合成 OHLCV
# ---------------------------------------------------------------------------

def _synth(closes: list[float], market: str = "A") -> pd.DataFrame:
    n = len(closes)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "date": dates,
        "open":   [c * 0.99 for c in closes],
        "close":  closes,
        "high":   [c * 1.01 for c in closes],
        "low":    [c * 0.98 for c in closes],
        "amount": [1e9] * n,
        "volume": [1e8] * n,
    })


def _linear(n: int, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start + i * step for i in range(n)]


# ---------------------------------------------------------------------------
# 合成数据：rs_vs_benchmark 方向恒等式
# ---------------------------------------------------------------------------

class TestRsVsBenchmarkInvariants:
    def test_same_pct_gives_zero(self):
        """任何品种 today_pct == 基准 pct → rs == 0.0（基准自身满足此条件）。"""
        for pct in (-0.05, 0.0, 0.03, 0.10):
            assert rs_vs_benchmark(pct, pct) == pytest.approx(0.0, abs=1e-9)

    def test_stronger_than_benchmark_gives_positive(self):
        """个股涨幅 > 基准 → rs > 0。"""
        assert rs_vs_benchmark(0.05, 0.02) > 0

    def test_weaker_than_benchmark_gives_negative(self):
        """个股涨幅 < 基准 → rs < 0（即使个股也在涨）。"""
        assert rs_vs_benchmark(0.01, 0.05) < 0

    def test_math_identity(self):
        """rs 必须精确等于 ticker_pct − benchmark_pct，不许有方向倒置或舍入扭曲。"""
        for ticker, bench in [(0.07, 0.02), (-0.03, 0.01), (0.0, -0.02)]:
            got = rs_vs_benchmark(ticker, bench)
            expected = ticker - bench
            assert got == pytest.approx(expected, abs=1e-8), (
                f"rs_vs_benchmark({ticker}, {bench}) = {got} ≠ {expected}"
            )

    def test_null_propagation(self):
        """任一缺失返 None。"""
        assert rs_vs_benchmark(None, 0.02) is None
        assert rs_vs_benchmark(0.02, None) is None
        assert rs_vs_benchmark(None, None) is None

    def test_compute_factors_benchmark_equals_zero(self):
        """经由 compute_factors：基准 ETF 自身 rs == 0.0（最关键集成检验）。"""
        closes = _linear(61, 100.0, 0.5)
        today_pct = closes[-1] / closes[-2] - 1
        df = _synth(closes)
        r = compute_factors(df, market="A", benchmark_today_pct=today_pct)
        assert r["rs_vs_benchmark"] == pytest.approx(0.0, abs=1e-8)

    def test_compute_factors_no_benchmark_gives_none(self):
        """未传 benchmark_today_pct → rs_vs_benchmark == None。"""
        df = _synth(_linear(61))
        r = compute_factors(df, market="A")
        assert r["rs_vs_benchmark"] is None

    def test_compute_factors_direction_preserved(self):
        """compute_factors 路径：个股涨幅大于基准 → rs > 0。"""
        closes = _linear(61, 100.0, 0.5)
        benchmark_pct = closes[-1] / closes[-2] - 1
        # 让个股的最后一天额外多涨一点
        closes_strong = closes[:-1] + [closes[-1] * 1.01]
        df = _synth(closes_strong)
        r = compute_factors(df, market="A", benchmark_today_pct=benchmark_pct)
        assert r["rs_vs_benchmark"] > 0


# ---------------------------------------------------------------------------
# 合成数据：er60 取值范围 + 极端场景
# ---------------------------------------------------------------------------

class TestEr60Invariants:
    def test_result_in_zero_one(self):
        """任意正常序列 er60 ∈ [0, 1]。"""
        for _ in range(5):
            import random; random.seed(_ * 7)
            closes = [100.0 * math.exp(sum(random.gauss(0, 0.01) for _ in range(i)))
                      for i in range(61)]
            result = er60(pd.Series(closes))
            if result is not None:
                assert 0.0 <= result <= 1.0, f"er60 out of range: {result}"

    def test_perfect_linear_up_approx_one(self):
        """完美单调直线上涨 → er60 ≈ 1.0。"""
        e = er60(pd.Series(_linear(61)))
        assert e == pytest.approx(1.0, abs=1e-4)

    def test_perfect_linear_down_approx_one(self):
        """完美单调直线下跌也是 er60 ≈ 1.0（方向无关，只看平滑度）。"""
        e = er60(pd.Series(_linear(61, 200.0, -1.0)))
        assert e == pytest.approx(1.0, abs=1e-4)

    def test_oscillating_lower_than_smooth(self):
        """剧烈震荡 er60 < 平滑趋势 er60。"""
        smooth = pd.Series(_linear(61))
        oscillating = pd.Series([100.0 + (5 if i % 2 == 0 else -5) for i in range(61)])
        assert er60(oscillating) < er60(smooth)

    def test_v_shape_near_zero(self):
        """V 型回到原点 → numerator ≈ 0 → er60 ≈ 0。"""
        half = 30
        down = [100.0 - i for i in range(half + 1)]  # 100 → 70
        up   = [70.0 + i for i in range(1, half + 1)]  # 71 → 100（回原点）
        e = er60(pd.Series(down + up))
        assert e == pytest.approx(0.0, abs=1e-4)

    def test_insufficient_returns_none(self):
        assert er60(pd.Series([10.0] * 30)) is None  # 30 diffs 但 len=30 < 31
        assert er60(pd.Series([10.0] * 20)) is None


# ---------------------------------------------------------------------------
# 合成数据：mdd60 恒等式
# ---------------------------------------------------------------------------

class TestMdd60Invariants:
    def test_always_nonnegative(self):
        """任意序列 mdd60 ≥ 0。"""
        for pattern in [_linear(60), _linear(60, 200.0, -1.0),
                        [100.0 + math.sin(i) * 5 for i in range(60)]]:
            m = mdd60(pd.Series(pattern))
            if m is not None:
                assert m >= 0.0

    def test_monotonic_up_near_zero(self):
        """单调上涨 → 无回撤 → mdd60 ≈ 0。"""
        assert mdd60(pd.Series(_linear(60))) == pytest.approx(0.0, abs=1e-6)

    def test_known_drawdown(self):
        """构造明确的 20% 回撤：peak=120 → trough=96 → mdd ≈ 0.20。"""
        # 30 个点：前 14 涨到 120，然后跌到 96，再涨回 100
        closes = _linear(14, 100.0, (120.0 - 100.0) / 13)  # 100..120
        closes += _linear(16, 96.0, (100.0 - 96.0) / 15)   # 96..100
        m = mdd60(pd.Series(closes))
        assert m == pytest.approx((120.0 - 96.0) / 120.0, abs=1e-4)

    def test_insufficient_returns_none(self):
        assert mdd60(pd.Series([10.0] * 29)) is None


# ---------------------------------------------------------------------------
# 合成数据：vol_std_20 恒等式
# ---------------------------------------------------------------------------

class TestVolStd20Invariants:
    def test_always_nonnegative(self):
        """std ≥ 0（由定义保证）。"""
        for closes in [_linear(25), _linear(25, 200.0, -0.5)]:
            v = vol_std_20(pd.Series(closes))
            if v is not None:
                assert v >= 0.0

    def test_constant_returns_zero_std(self):
        """每日涨幅完全一样 → returns 方差 = 0。"""
        closes = [100.0 * (1.01 ** i) for i in range(25)]
        assert vol_std_20(pd.Series(closes)) == pytest.approx(0.0, abs=1e-6)

    def test_high_volatility_larger_std(self):
        """高波动序列 std > 低波动序列 std。"""
        low_vol  = [100.0 + i * 0.1 for i in range(25)]
        high_vol = [100.0 + (3 if i % 2 == 0 else -3) * (i + 1) * 0.01 for i in range(25)]
        v_low  = vol_std_20(pd.Series(low_vol))
        v_high = vol_std_20(pd.Series(high_vol))
        assert v_high > v_low

    def test_insufficient_returns_none(self):
        assert vol_std_20(pd.Series([10.0] * 20)) is None  # 只产生 19 returns
        assert vol_std_20(pd.Series([10.0] * 15)) is None


# ---------------------------------------------------------------------------
# 合成数据：slope_seg 顺序 + 方向
# ---------------------------------------------------------------------------

class TestSlopeSegInvariants:
    def test_returns_length_three(self):
        """输出必须是长度 3 的列表。"""
        s = slope_seg(pd.Series(_linear(60)))
        assert isinstance(s, list) and len(s) == 3

    def test_far_to_near_order_not_reversed(self):
        """远段涨、近段跌 → s[0]>0, s[2]<0（验输出不是近→远倒序）。"""
        seg_far  = _linear(20, 100.0, 1.0)   # 100 → 119（涨）
        seg_mid  = [seg_far[-1]] * 20         # 平
        seg_near = _linear(20, seg_far[-1], -1.0)  # 跌
        s = slope_seg(pd.Series(seg_far + seg_mid + seg_near))
        assert s is not None
        assert s[0] > 0,  f"远段应为正，got s[0]={s[0]}"
        assert s[2] < 0,  f"近段应为负，got s[2]={s[2]}"

    def test_monotonic_all_positive(self):
        """全程单调上涨 → 三段全正。"""
        s = slope_seg(pd.Series(_linear(60)))
        assert all(v > 0 for v in s)

    def test_segment_math_identity(self):
        """每段输出等于 close_end/close_start − 1（不许有近似误差超 1e-4）。"""
        closes = pd.Series(_linear(60, 100.0, 0.3))
        s = slope_seg(closes)
        expected = []
        for i in range(3):
            seg = closes.iloc[i * 20:(i + 1) * 20]
            expected.append(seg.iloc[-1] / seg.iloc[0] - 1)
        for i, (got, exp) in enumerate(zip(s, expected)):
            assert got == pytest.approx(exp, abs=1e-4), (
                f"seg[{i}] math mismatch: got {got}, expected {exp}"
            )

    def test_insufficient_returns_none(self):
        assert slope_seg(pd.Series([10.0] * 59)) is None
        assert slope_seg(pd.Series([10.0] * 30)) is None


# ---------------------------------------------------------------------------
# 真实池数据（网络不通自动跳过）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_data_a():
    """拉 SZ159845(基准) + SH518880(黄金ETF) 的真实 OHLCV，失败则 skip。"""
    try:
        import etf_data_api as api
        df = api.get_a_etf_ohlcv(
            [BENCHMARK_CODE_A, GOLD_CODE], "2025-10-01", "2026-05-21"
        )
        if df.empty or df["code"].nunique() < 1:
            pytest.skip("真实数据为空，跳过")
        return df
    except Exception as e:
        pytest.skip(f"真实数据 fetch 失败（{e}），跳过")


class TestRealDataInvariants:
    """用真实 ETF 数据验业务规律（需要网络，fetch 失败自动跳过）。"""

    def _sub(self, df: pd.DataFrame, code: str) -> pd.DataFrame:
        sub = df[df["code"] == code].sort_values("date").copy()
        if sub.empty:
            pytest.skip(f"{code} 无数据，跳过")
        return sub

    def test_benchmark_rs_is_zero(self, real_data_a):
        """真实数据中，基准 ETF 的 rs_vs_benchmark == 0.0（最关键集成验收）。"""
        bm = self._sub(real_data_a, BENCHMARK_CODE_A)
        if len(bm) < 61:
            pytest.skip("基准数据不足 61 行")
        bm_pct = float(bm["close"].iloc[-1]) / float(bm["close"].iloc[-2]) - 1
        r = compute_factors(bm, market="A", benchmark_today_pct=bm_pct)
        assert r["rs_vs_benchmark"] == pytest.approx(0.0, abs=1e-8)

    def test_gold_rs_in_reasonable_range(self, real_data_a):
        """黄金 ETF 的 rs 应为有限小数（不应是 NaN / Inf）。"""
        bm = self._sub(real_data_a, BENCHMARK_CODE_A)
        gold = self._sub(real_data_a, GOLD_CODE)
        if len(bm) < 2 or len(gold) < 2:
            pytest.skip("数据不足")
        bm_pct = float(bm["close"].iloc[-1]) / float(bm["close"].iloc[-2]) - 1
        r = compute_factors(gold, market="A", benchmark_today_pct=bm_pct)
        rs = r.get("rs_vs_benchmark")
        assert rs is not None, "黄金 ETF 应能算出 rs"
        assert math.isfinite(rs), f"rs 不是有限数: {rs}"
        assert abs(rs) < 0.3, f"rs 超出合理范围 ±30%: {rs}"

    def test_rs_direction_matches_manual_calc(self, real_data_a):
        """真实数据：rs 方向与手算 (gold_pct − bm_pct) 一致。"""
        bm   = self._sub(real_data_a, BENCHMARK_CODE_A)
        gold = self._sub(real_data_a, GOLD_CODE)
        if len(bm) < 2 or len(gold) < 2:
            pytest.skip("数据不足")
        bm_pct   = float(bm["close"].iloc[-1]) / float(bm["close"].iloc[-2]) - 1
        gold_pct = float(gold["close"].iloc[-1]) / float(gold["close"].iloc[-2]) - 1
        r = compute_factors(gold, market="A", benchmark_today_pct=bm_pct)
        expected_sign = gold_pct - bm_pct
        if abs(expected_sign) < 1e-9:
            return  # 差值极小，跳过方向判断
        if expected_sign > 0:
            assert r["rs_vs_benchmark"] > 0
        else:
            assert r["rs_vs_benchmark"] < 0

    def test_er60_range_real(self, real_data_a):
        """真实数据 er60 ∈ [0, 1]（若有足够数据）。"""
        for code in [BENCHMARK_CODE_A, GOLD_CODE]:
            sub = real_data_a[real_data_a["code"] == code].sort_values("date")
            r = compute_factors(sub, market="A")
            e = r.get("er60")
            if e is not None:
                assert 0.0 <= e <= 1.0, f"{code} er60={e} out of [0,1]"

    def test_mdd60_nonnegative_real(self, real_data_a):
        """真实数据 mdd60 ≥ 0。"""
        for code in [BENCHMARK_CODE_A, GOLD_CODE]:
            sub = real_data_a[real_data_a["code"] == code].sort_values("date")
            r = compute_factors(sub, market="A")
            m = r.get("mdd60")
            if m is not None:
                assert m >= 0.0, f"{code} mdd60={m} < 0"

    def test_vol_std_20_nonnegative_real(self, real_data_a):
        """真实数据 vol_std_20 ≥ 0。"""
        for code in [BENCHMARK_CODE_A, GOLD_CODE]:
            sub = real_data_a[real_data_a["code"] == code].sort_values("date")
            r = compute_factors(sub, market="A")
            v = r.get("vol_std_20")
            if v is not None:
                assert v >= 0.0, f"{code} vol_std_20={v} < 0"

    def test_slope_seg_length_real(self, real_data_a):
        """真实数据 slope_seg 长度 == 3。"""
        for code in [BENCHMARK_CODE_A, GOLD_CODE]:
            sub = real_data_a[real_data_a["code"] == code].sort_values("date")
            r = compute_factors(sub, market="A")
            s = r.get("slope_seg")
            if s is not None:
                assert len(s) == 3, f"{code} slope_seg 长度 {len(s)} ≠ 3"

    def test_all_new_factors_present_in_result(self, real_data_a):
        """compute_factors 结果 dict 必须包含全部 5 个新因子键。"""
        sub = real_data_a[real_data_a["code"] == BENCHMARK_CODE_A].sort_values("date")
        r = compute_factors(sub, market="A")
        for key in ("vol_std_20", "rs_vs_benchmark", "er60", "mdd60", "slope_seg"):
            assert key in r, f"因子 {key} 不在 compute_factors 返回值中"
