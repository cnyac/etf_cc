"""llm_prompt.py 测试：短键映射 + prompt 含必要段落。"""
from src.llm_prompt import (
    build_prompt, _compress_ticker, SHORT_KEYS, MA_ENCODE, CAT_ENCODE,
)


def _mk_ticker(market="A", **overrides):
    base = {
        "code": "SH510050", "name": "上证50ETF",
        "today_pct": 0.0091, "pct_diff": 0.005, "volume_ratio": 0.12,
        "category": "持续强化", "feature": "龙1，最增量",
        "factors": {
            "price_pctile_60": 75, "price_pctile_20": 80,
            "vol_ratio_20": 1.42, "vol_pctile_20": 70,
            "ma_alignment": "多头", "pct_normalized": 1.3,
            "new_high_20d": False, "new_low_20d": False,
        },
    }
    if market == "US":
        base["factors"]["ma150_dist"] = 4.5
        base["factors"]["ma150_relation"] = "站上"
    base.update(overrides)
    return base


def test_compress_a_short_keys():
    t = _mk_ticker("A")
    c = _compress_ticker(t, "A")
    assert c["c"] == "SH510050"
    assert c["pct"] == 0.91   # 0.0091 → 0.91%
    assert c[SHORT_KEYS["price_pctile_60"]] == 75
    assert c[SHORT_KEYS["vol_ratio_20"]] == 1.4
    assert c[SHORT_KEYS["ma_alignment"]] == 1     # 多头 → 1
    assert c[SHORT_KEYS["category"]] == 1         # 持续强化 → 1
    assert SHORT_KEYS["ma150_dist"] not in c       # A 股不出现 md


def test_compress_us_includes_ma150():
    t = _mk_ticker("US")
    c = _compress_ticker(t, "US")
    assert c[SHORT_KEYS["ma150_dist"]] == 4.5
    assert c[SHORT_KEYS["ma150_relation"]] == 1   # 站上 → 1


def test_compress_none_factors_safe():
    t = _mk_ticker("A")
    t["factors"]["price_pctile_60"] = None
    t["factors"]["ma_alignment"] = None
    c = _compress_ticker(t, "A")
    assert c[SHORT_KEYS["price_pctile_60"]] is None
    assert c[SHORT_KEYS["ma_alignment"]] is None


def test_build_prompt_contains_sections_a():
    session = {
        "label": "2026-05-20-收", "market": "A", "session_time": "close",
        "tickers": [_mk_ticker("A")],
        "panel": {"up_count": 15, "down_count": 24, "cross_asset_state": {}},
    }
    history = [{"label": "2026-05-19-收", "narrative": {
        "is_skeleton": True, "session_summary": "x"}, "tickers": []}]
    p = build_prompt("A", session, history)

    # 含 A 股专属人格名
    assert "yangjia_emotion_cycle" in p
    assert "zhaolaoge_liquidity_focus" in p
    assert "fengliu_contrarian_check" in p
    # 含短键映射说明
    assert "短键映射" in p
    # 含历史段（三级记忆：远级 header 含骨架说明，历史 label 出现在 prompt 里）
    assert "2026-05-19-收" in p  # 历史 label 出现在远级
    assert "骨架" in p           # 远级 header 注明骨架说明
    # E.2：新字段 schema 说明出现在 prompt 里
    assert "quadrant_summaries" in p
    assert "group_qualitative" in p
    # 含当前 panel
    assert "up_count" in p
    # 含 schema enum 白名单
    assert "冰点" in p   # ENUM_YANGJIA_STAGE
    # 含任务说明
    assert "2026-05-20-收" in p


def test_build_prompt_contains_sections_us():
    session = {
        "label": "2026-05-20", "market": "US", "session_time": "close",
        "tickers": [_mk_ticker("US")],
        "panel": {"above_ma150_count": 24, "spy_iwm_divergence": 0.005,
                  "cross_asset_state": {}},
    }
    p = build_prompt("US", session, [])
    assert "druckenmiller_macro_check" in p
    assert "minervini_breadth_check" in p
    assert "wyckoff_breakout_check" in p
    assert "weinstein_stage_check" in p
    assert "紧缩避险" in p


def test_annotation_trail_block_with_data():
    session = {"label": "L_now", "tickers": [_mk_ticker()], "panel": {}}
    history = [
        {"label": "L1", "narrative": None, "tickers": [
            {"code": "SH510050", "annotation": {"color": "#FFE4B5", "note": "缩量"}}]},
        {"label": "L2", "narrative": None, "tickers": [
            {"code": "SH510050", "annotation": {"color": "#DDA0DD", "note": "反包"}}]},
    ]
    p = build_prompt("A", session, history)
    assert "批注轨迹" in p
    assert "SH510050" in p
    assert "缩量" in p
    assert "反包" in p


def test_annotation_trail_empty():
    session = {"label": "L_now", "tickers": [_mk_ticker()], "panel": {}}
    p = build_prompt("A", session, [])
    assert "批注轨迹" in p and "（无）" in p


def test_prompt_includes_audit_context_when_prev_has_expect():
    """上一时段有 next_session_expect 时，prompt 应含审计对照锚点。"""
    session = {"label": "2026-05-20-收", "tickers": [_mk_ticker()], "panel": {}}
    history = [{"label": "2026-05-19-收", "narrative": {
        "is_skeleton": False, "session_summary": "x",
        "yangjia_emotion_cycle": {
            "stage": "高潮", "intensity": "强", "evidence": "x",
            "next_session_expect": "情绪退潮但仍存余温",
            "what_kills_this_view": "y", "free_analysis": "z",
        },
    }, "tickers": []}]
    p = build_prompt("A", session, history)
    assert "预期审计对照" in p
    assert "情绪退潮但仍存余温" in p


def test_prompt_skips_audit_when_prev_skeleton():
    session = {"label": "2026-05-20-收", "tickers": [_mk_ticker()], "panel": {}}
    history = [{"label": "2026-05-19-收", "narrative": {
        "is_skeleton": True, "session_summary": "x"}, "tickers": []}]
    p = build_prompt("A", session, history)
    assert "为骨架/无 LLM 叙事，跳过审计" in p


def test_prompt_weekend_flag_required():
    session = {"label": "2026-05-22-收", "tickers": [_mk_ticker()], "panel": {},
               "is_weekend_close": True}
    p = build_prompt("A", session, [])
    assert "macro_cycle_anchor 字段本时段必填" in p


def test_prompt_weekend_flag_skipped_on_weekday():
    session = {"label": "2026-05-20-收", "tickers": [_mk_ticker()], "panel": {},
               "is_weekend_close": False}
    p = build_prompt("A", session, [])
    assert "macro_cycle_anchor 填 null" in p


def test_prompt_us_evidence_aliases_exposed():
    """US druckenmiller / minervini 的 evidence alias 关键词必须在 prompt 里显式列出，
    否则 LLM 不知道写哪些字面才会被识别（2026-05-21 用户实测修复）。"""
    session = {
        "label": "2026-05-20", "market": "US", "session_time": "close",
        "tickers": [_mk_ticker("US")],
        "panel": {"above_ma150_count": 24, "spy_iwm_divergence": 0.005,
                  "cross_asset_state": {}},
    }
    p = build_prompt("US", session, [])
    # druckenmiller 的关键 alias
    assert "10Y" in p or "10y" in p  # treasury_10y alias
    assert "美元指数" in p  # dollar alias
    assert "vix" in p.lower()
    assert "比特币" in p  # btc alias
    # minervini 的关键 alias
    assert "30周均线" in p or "ma150" in p.lower()
    assert "大小盘" in p
    assert "20日新高" in p or "新高数" in p
    # 必须出现"字面出现"或类似的说明引导 LLM
    assert "字面" in p


def test_prompt_includes_strategy_outlook_schema():
    session = {"label": "L", "tickers": [_mk_ticker()], "panel": {}}
    p = build_prompt("A", session, [])
    assert "strategy_outlook" in p
    assert "key_movers" in p
    assert "unique_anomaly_analysis" in p
