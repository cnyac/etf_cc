"""panel.py 单元测试。

覆盖（CLAUDE.md 第 6 条要求的"panel.py cross_asset_state 阈值（±0.3%）"）：
  - cross_asset_state 阈值边界
  - 基础计数字段
  - 美股扩展字段（above_ma150_count / spy_iwm_divergence）
"""
import pytest
from src.panel import build_panel, CROSS_ASSET_FLAT


POOL_A = {
    "etfs": [
        {"code": "SH511260", "name": "十年国债ETF", "role": "treasury_10y"},
        {"code": "SH511090", "name": "30年国债ETF", "role": "treasury_30y"},
        {"code": "SH518880", "name": "黄金ETF", "role": "gold"},
        {"code": "SH501018", "name": "南方原油LOF", "role": "oil"},
        {"code": "SZ159995", "name": "芯片ETF"},
    ]
}


def _t(code, today_pct, vol_ratio_20=None, new_high_20d=None,
       new_low_20d=None, category=None, ma150_relation=None):
    return {
        "code": code, "today_pct": today_pct,
        "vol_ratio_20": vol_ratio_20,
        "new_high_20d": new_high_20d, "new_low_20d": new_low_20d,
        "category": category, "ma150_relation": ma150_relation,
    }


def test_cross_asset_threshold_up():
    pt = [_t("SH511260", 0.004)]  # 0.4% > 0.3%
    p = build_panel(pt, POOL_A, "A")
    assert p["cross_asset_state"]["treasury_10y"] == "up"


def test_cross_asset_threshold_down():
    pt = [_t("SH518880", -0.004)]
    p = build_panel(pt, POOL_A, "A")
    assert p["cross_asset_state"]["gold"] == "down"


def test_cross_asset_threshold_flat_at_boundary():
    # 恰好 0.3% → flat（不 > 0.3）
    pt = [_t("SH511090", CROSS_ASSET_FLAT)]
    p = build_panel(pt, POOL_A, "A")
    assert p["cross_asset_state"]["treasury_30y"] == "flat"


def test_cross_asset_threshold_just_above():
    pt = [_t("SH501018", CROSS_ASSET_FLAT + 1e-6)]
    p = build_panel(pt, POOL_A, "A")
    assert p["cross_asset_state"]["oil"] == "up"


def test_cross_asset_missing_data_is_none():
    pt = [_t("SH511260", None)]
    p = build_panel(pt, POOL_A, "A")
    assert p["cross_asset_state"]["treasury_10y"] is None


def test_basic_counts():
    pt = [
        _t("A", 0.03, vol_ratio_20=2.0, category="持续强化"),     # 强涨 + 量扩
        _t("B", -0.025, vol_ratio_20=0.5, category="连续杀跌"),   # 强跌 + 量缩
        _t("C", 0.005, vol_ratio_20=1.0, category="持续强化"),    # 普涨 + 平量
        _t("D", 0.0, category="持续强化"),                         # 平
        _t("E", -0.001, category="连续杀跌"),                      # 普跌
    ]
    p = build_panel(pt, POOL_A, "A")
    assert p["up_count"] == 2
    assert p["down_count"] == 2
    assert p["flat_count"] == 1
    assert p["strong_up_count"] == 1
    assert p["strong_down_count"] == 1
    assert p["vol_expansion_count"] == 1
    assert p["vol_contraction_count"] == 1
    assert p["category_distribution"]["持续强化"] == 3
    assert p["category_distribution"]["连续杀跌"] == 2


def test_new_high_low_counts():
    pt = [
        _t("A", 0.01, new_high_20d=True),
        _t("B", 0.01, new_high_20d=True),
        _t("C", -0.01, new_low_20d=True),
        _t("D", 0.0, new_high_20d=False, new_low_20d=False),
    ]
    p = build_panel(pt, POOL_A, "A")
    assert p["new_high_count_20d"] == 2
    assert p["new_low_count_20d"] == 1


def test_us_above_ma150_and_divergence():
    pool_us = {"etfs": [{"code": "SPY"}, {"code": "IWM"}, {"code": "AAPL"}]}
    pt = [
        _t("SPY", 0.01, ma150_relation="站上"),
        _t("IWM", -0.005, ma150_relation="跌破"),
        _t("AAPL", 0.02, ma150_relation="站上"),
    ]
    p = build_panel(pt, pool_us, "US")
    assert p["above_ma150_count"] == 2
    assert p["spy_iwm_divergence"] == pytest.approx(0.015, abs=1e-6)


def test_us_divergence_missing_returns_none():
    pool_us = {"etfs": [{"code": "AAPL"}]}
    pt = [_t("AAPL", 0.02)]
    p = build_panel(pt, pool_us, "US")
    assert p["spy_iwm_divergence"] is None


def test_a_share_has_no_us_only_fields():
    pt = [_t("SZ159995", 0.01)]
    p = build_panel(pt, POOL_A, "A")
    assert "above_ma150_count" not in p
    assert "spy_iwm_divergence" not in p
