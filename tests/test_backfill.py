"""backfill.py 单元测试。

主要验证骨架 narrative 模板格式 + is_skeleton=True。
真数据 backfill 走 smoke test，不在单元测试里。
"""
from src.backfill import skeleton_summary


def _mk_session(label="2026-05-20-收", market="A", up=15, down=24, flat=0,
                strong_up=1, vol_exp=0, cats=None, cross=None):
    if cats is None:
        cats = {"持续强化": 5, "反包修复": 10, "强反转": 8, "连续杀跌": 16}
    if cross is None:
        cross = {"treasury_10y": "flat", "treasury_30y": "flat",
                 "gold": "down", "oil": "down"}
    return {
        "label": label, "market": market,
        "panel": {
            "up_count": up, "down_count": down, "flat_count": flat,
            "strong_up_count": strong_up, "strong_down_count": 0,
            "vol_expansion_count": vol_exp, "vol_contraction_count": 6,
            "cross_asset_state": cross,
            "category_distribution": cats,
        },
    }


def test_skeleton_summary_contains_machine_marker():
    s = skeleton_summary(_mk_session())
    assert "[机器生成]" in s


def test_skeleton_summary_contains_counts():
    s = skeleton_summary(_mk_session(up=15, down=24, flat=0))
    assert "上涨 15/39" in s
    assert "强势 1 个" in s
    assert "量能扩张 0 个" in s


def test_skeleton_summary_contains_cross_asset():
    s = skeleton_summary(_mk_session())
    assert "黄金down" in s
    assert "原油down" in s


def test_skeleton_summary_contains_category_distribution():
    s = skeleton_summary(_mk_session())
    assert "持续强化 5" in s
    assert "反包修复 10" in s
    assert "强反转 8" in s
    assert "连续杀跌 16" in s


def test_skeleton_summary_us_cross_asset_format():
    cross = {"treasury_10y": "up", "dollar": "up", "vix": "down",
             "btc": "up", "eth": "flat"}
    s = skeleton_summary(_mk_session(market="US", cross=cross))
    assert "10Yup" in s
    assert "美元up" in s
    assert "VIXdown" in s
    assert "BTCup" in s
