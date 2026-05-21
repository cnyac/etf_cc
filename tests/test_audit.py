"""audit.py 量化代审单测。

边界覆盖：
  - D1 归类跃迁各档
  - D2 量能配合方向（涨/跌 × 放量/缩量）
  - 总分五档映射边界
  - prev 缺失返 None
  - batch 接口去重
"""
from src import audit


def _t(code, today_pct=None, category=None, vol_ratio_20=None):
    return {"code": code, "today_pct": today_pct, "category": category,
            "factors": {"vol_ratio_20": vol_ratio_20}}


# ---------------- D1 ----------------

def test_d1_strong_reversal_up():
    assert audit._d1_score("强反转", "持续强化") == +3

def test_d1_capitulation_recovery():
    assert audit._d1_score("连续杀跌", "反包修复") == +2

def test_d1_persist_persist():
    assert audit._d1_score("持续强化", "持续强化") == +1

def test_d1_breakdown():
    assert audit._d1_score("持续强化", "强反转") == -2

def test_d1_unmatched_is_zero():
    assert audit._d1_score("强反转", "强反转") == 0

def test_d1_none_input_safe():
    assert audit._d1_score(None, "持续强化") == 0
    assert audit._d1_score("持续强化", None) == 0


# ---------------- D2 ----------------

def test_d2_up_with_volume_expansion():
    assert audit._d2_score(0.02, 1.5) == +1

def test_d2_up_with_volume_shrink():
    assert audit._d2_score(0.02, 0.5) == -1

def test_d2_down_with_volume_expansion():
    assert audit._d2_score(-0.02, 1.5) == -1

def test_d2_down_with_volume_shrink():
    assert audit._d2_score(-0.02, 0.5) == +1

def test_d2_flat_is_zero():
    assert audit._d2_score(0, 1.5) == 0

def test_d2_none_safe():
    assert audit._d2_score(None, 1.5) == 0
    assert audit._d2_score(0.02, None) == 0


# ---------------- 总分映射 ----------------

def test_rating_bands():
    assert audit._score_to_rating(4) == "强超于预期"   # +3 起
    assert audit._score_to_rating(3) == "强超于预期"
    assert audit._score_to_rating(2) == "超于预期"
    assert audit._score_to_rating(1) == "超于预期"
    assert audit._score_to_rating(0) == "符合预期"
    assert audit._score_to_rating(-1) == "低于预期"
    assert audit._score_to_rating(-2) == "低于预期"
    assert audit._score_to_rating(-3) == "强低于预期"
    assert audit._score_to_rating(-8) == "强低于预期"


# ---------------- quant_audit_ticker ----------------

def test_audit_strong_reversal_up_with_volume():
    """强反转→持续强化 (+3) + 涨+放量 (+1) = +4 → 强超于预期"""
    prev = _t("X", category="强反转")
    curr = _t("X", today_pct=0.03, category="持续强化", vol_ratio_20=1.6)
    r = audit.quant_audit_ticker(prev, curr)
    assert r == {"actual_vs_expected": "强超于预期", "auditor": "quant"}


def test_audit_persistent_strength_with_shrink():
    """持续强化→持续强化 (+1) + 涨+缩量 (-1) = 0 → 符合预期"""
    prev = _t("X", category="持续强化")
    curr = _t("X", today_pct=0.005, category="持续强化", vol_ratio_20=0.6)
    r = audit.quant_audit_ticker(prev, curr)
    assert r["actual_vs_expected"] == "符合预期"


def test_audit_breakdown_with_heavy_volume():
    """持续强化→强反转 (-2) + 跌+放量 (-1) = -3 → 强低于预期"""
    prev = _t("X", category="持续强化")
    curr = _t("X", today_pct=-0.03, category="强反转", vol_ratio_20=1.8)
    r = audit.quant_audit_ticker(prev, curr)
    assert r["actual_vs_expected"] == "强低于预期"


def test_audit_no_prev_returns_none():
    curr = _t("X", today_pct=0.01, category="持续强化", vol_ratio_20=1.0)
    assert audit.quant_audit_ticker(None, curr) is None


# ---------------- batch ----------------

def test_batch_skips_codes_not_in_prev():
    prev = {"tickers": [_t("A", category="持续强化")]}
    curr = {"tickers": [
        _t("A", today_pct=0.01, category="持续强化", vol_ratio_20=1.5),
        _t("B", today_pct=0.02, category="反包修复", vol_ratio_20=1.5),  # 新品种
    ]}
    out = audit.quant_audit_batch(prev, curr)
    assert "A" in out
    assert "B" not in out


def test_batch_no_prev_returns_empty():
    curr = {"tickers": [_t("A", today_pct=0.01, category="持续强化", vol_ratio_20=1.5)]}
    assert audit.quant_audit_batch(None, curr) == {}
