"""llm_schema.py 测试：白名单非空，双市场字段完整。"""
import pytest
from src.llm_schema import (
    get_schema, A_SCHEMA, US_SCHEMA,
    ENUM_YANGJIA_STAGE, ENUM_MACRO_REGIME, ENUM_WEINSTEIN_STAGE,
    ENUM_LOGIC_HARDNESS, MINERVINI_BREADTH_FIELDS,
)


def test_get_schema_a():
    s = get_schema("A")
    assert "yangjia_emotion_cycle" in s
    assert "zhaolaoge_liquidity_focus" in s
    assert "fengliu_contrarian_check" in s
    assert "trading_discipline_review" in s
    assert len(s) == 4  # A 股 4 字段


def test_get_schema_us():
    s = get_schema("US")
    assert "druckenmiller_macro_check" in s
    assert "minervini_breadth_check" in s
    assert "wyckoff_breakout_check" in s
    assert "weinstein_stage_check" in s
    assert "trading_discipline_review" in s
    assert len(s) == 5  # 美股 5 字段


def test_get_schema_unknown_market():
    with pytest.raises(ValueError):
        get_schema("HK")


def test_what_kills_required_in_every_global_field():
    """每个非纪律字段都必须含 what_kills_this_view 在 required。"""
    for market in ["A", "US"]:
        for fname, spec in get_schema(market).items():
            if fname == "trading_discipline_review":
                continue
            assert "what_kills_this_view" in spec["required"], \
                f"{market}.{fname} 缺 what_kills_this_view"


def test_enums_nonempty():
    assert len(ENUM_YANGJIA_STAGE) >= 3
    assert len(ENUM_MACRO_REGIME) >= 4
    assert len(ENUM_WEINSTEIN_STAGE) >= 4
    assert len(ENUM_LOGIC_HARDNESS) == 3


def test_minervini_breadth_fields():
    assert "above_ma150_count" in MINERVINI_BREADTH_FIELDS
    assert "spy_iwm_divergence" in MINERVINI_BREADTH_FIELDS
    assert "new_high_count_20d" in MINERVINI_BREADTH_FIELDS


def test_druckenmiller_evidence_min_dims():
    spec = US_SCHEMA["druckenmiller_macro_check"]
    assert spec["evidence_min_dims"] == 4
    assert len(spec["cross_asset_dims"]) == 8
