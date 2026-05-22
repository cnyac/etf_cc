"""llm_validate.py 测试。

覆盖（CLAUDE.md 第 6 条 "LLM 输出 enum 校验拒绝渲染"）：
  - enum 白名单外的值 → 拒绝
  - 缺必填字段 / 缺 what_kills_this_view → 拒绝
  - druckenmiller 降级机制
  - minervini 降级机制
  - discipline_pass=false + rating_override 规则
  - is_skeleton=true → 跳过 LLM 字段校验
  - audit_rating 同义词归一化（2026-05-21 用户实测修复）
"""
import pytest
from src.llm_schema import normalize_audit_rating
from src.llm_validate import validate_narrative


# ─────── audit rating 归一化（2026-05-21 修复）───────
def test_normalize_audit_rating_synonyms():
    assert normalize_audit_rating("强超") == "强超于预期"
    assert normalize_audit_rating("强超预期") == "强超于预期"
    assert normalize_audit_rating("强超于预期") == "强超于预期"
    assert normalize_audit_rating("超") == "超于预期"
    assert normalize_audit_rating("超预期") == "超于预期"
    assert normalize_audit_rating("符合") == "符合预期"
    assert normalize_audit_rating("不及预期") == "低于预期"
    assert normalize_audit_rating("远低于预期") == "强低于预期"
    assert normalize_audit_rating("莫名其妙") is None
    assert normalize_audit_rating(None) is None
    assert normalize_audit_rating(42) is None


def test_validate_ticker_audits_normalizes_synonym():
    """LLM 给 '强超' / '超预期' 等简写应通过校验并归一化写回。"""
    narrative = {
        "is_skeleton": False, "session_summary": "x",
        "ticker_audits": {
            "SH516110": {"actual_vs_expected": "强超", "auditor": "yangjia"},
            "SZ159732": {"actual_vs_expected": "超预期", "auditor": "zhaolaoge"},
        },
    }
    ok, errors = validate_narrative(narrative, "A", panel={}, is_weekend_close=False)
    for e in errors:
        assert "actual_vs_expected" not in e, f"不该报 audit rating 错: {e}"
    assert narrative["ticker_audits"]["SH516110"]["actual_vs_expected"] == "强超于预期"
    assert narrative["ticker_audits"]["SZ159732"]["actual_vs_expected"] == "超于预期"


def test_validate_ticker_audits_unknown_still_errors():
    narrative = {
        "is_skeleton": False, "session_summary": "x",
        "ticker_audits": {"X": {"actual_vs_expected": "莫名其妙", "auditor": "yangjia"}},
    }
    ok, errors = validate_narrative(narrative, "A", panel={}, is_weekend_close=False)
    assert any("actual_vs_expected" in e and "莫名其妙" in e for e in errors)


def test_data_refresh_missing_yaml_friendly():
    """pool_us.yaml 缺失时 refresh_pool 不抛异常，返 (True, '跳过' 信息)。"""
    from src import data_refresh
    ok, note = data_refresh.refresh_pool("US", pool_path="/nonexistent/pool_xx.yaml")
    assert ok is True
    assert "不存在" in note and "跳过" in note


# ---------- 顶层 ----------

def test_skeleton_bypasses_llm_checks():
    n = {"is_skeleton": True, "session_summary": "骨架"}
    ok, errors = validate_narrative(n, "A")
    assert ok, errors


def test_missing_session_summary():
    n = {"is_skeleton": False}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("session_summary" in e for e in errors)


# ---------- A 股 ----------

VALID_YANGJIA = {
    "stage": "试错",
    "intensity": "中",
    "evidence": "上涨 15/39，强势 1 个，缩量为主，跨资产黄金 down",
    "next_session_expect": "情绪修复或继续阴跌均可能",
    "what_kills_this_view": "明日早盘强势 ETF >5 个且涨幅 >2%",
    "free_analysis": "今日情绪走弱，强反转占比近半数，资金避险情绪明显。",
    "panorama_text": (
        "一、上涨与下跌占比 15:24，强反转 17 只居首，资金扎堆避险但未呈共振杀跌。"
        "强势品种仅 1 只，热度退潮明显，缺乏龙头持续效应。"
        "二、跨资产侧黄金、原油均向下，国债持平，无避险溢价的反向共振；"
        "美元未现端倪，传统避险逻辑链条不完整。"
        "三、量能扩张品种仅 2 只，主线缺乏合力，市场处于试错末段；"
        "若午后无新增放量主线，全天大概率仍在缩量阴跌格局收。"
    ),
    "cross_validation_text": (
        "权重板块普跌且券商缩量同步，符合存量博弈跷跷板特征——资金从高位题材撤出，"
        "但未明确流向低位防御板块，高低切迹象初现但未成势；红利搬家逻辑暂未启动。"
        "国债与商品的同向走弱说明流动性整体在收缩，非单一风格切换，跨资产无明显避险共振。"
    ),
}


def test_a_yangjia_valid():
    n = {"is_skeleton": False, "session_summary": "x", "yangjia_emotion_cycle": VALID_YANGJIA,
         "zhaolaoge_liquidity_focus": None, "fengliu_contrarian_check": None,
         "trading_discipline_review": None}
    ok, errors = validate_narrative(n, "A")
    assert ok, errors


def test_a_yangjia_bad_enum():
    bad = {**VALID_YANGJIA, "stage": "巨牛"}
    n = {"is_skeleton": False, "session_summary": "x", "yangjia_emotion_cycle": bad,
         "zhaolaoge_liquidity_focus": None, "fengliu_contrarian_check": None,
         "trading_discipline_review": None}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("stage" in e and "白名单" in e for e in errors)


def test_a_yangjia_missing_what_kills():
    bad = {**VALID_YANGJIA}
    del bad["what_kills_this_view"]
    n = {"is_skeleton": False, "session_summary": "x", "yangjia_emotion_cycle": bad,
         "zhaolaoge_liquidity_focus": None, "fengliu_contrarian_check": None,
         "trading_discipline_review": None}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("what_kills_this_view" in e for e in errors)


def test_a_null_fields_allowed():
    """全部分类字段 null 时（候选 0）应通过 enum 校验阶段。"""
    n = {"is_skeleton": False, "session_summary": "今日候选稀少",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": None}
    ok, errors = validate_narrative(n, "A")
    assert ok, errors


# ---------- A 股 discipline ----------

def test_discipline_rating_override_valid():
    review = {
        "code": "SH510050",
        "logic_hardness": "硬", "risk_reward_ratio": "优",
        "discipline_pass": False,
        "rating_override": {"keep_rating": True, "reason": "硬逻辑+量能配合"},
        "review_note": "保留原评级",
    }
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": [review]}
    ok, errors = validate_narrative(n, "A")
    assert ok, errors


def test_discipline_rating_override_reason_too_long():
    review = {
        "code": "SH510050",
        "logic_hardness": "硬", "risk_reward_ratio": "优",
        "discipline_pass": False,
        "rating_override": {"keep_rating": True, "reason": "x" * 40},
        "review_note": "x",
    }
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": [review]}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("30 字" in e for e in errors)


def test_discipline_missing_code():
    review = {
        "logic_hardness": "硬", "risk_reward_ratio": "优",
        "discipline_pass": True, "review_note": "x",
    }
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": [review]}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("code" in e for e in errors)


# ---------- 美股 druckenmiller 降级 ----------

def _us_base_narrative(druck=None, minervini=None):
    return {
        "is_skeleton": False, "session_summary": "x",
        "druckenmiller_macro_check": druck,
        "minervini_breadth_check": minervini,
        "wyckoff_breakout_check": None, "weinstein_stage_check": None,
        "trading_discipline_review": None,
    }


VALID_DRUCK = {
    "macro_regime": "宽松进攻", "key_signal": "利率主导",
    "evidence": "10年国债涨 0.4%，30年国债涨 0.5%，黄金跌 1.2%，美元跌 0.3%",
    "cross_asset_panorama": (
        "宽松交易延续：长短端国债共振走强（10Y +0.4% / 30Y +0.5%），"
        "美元指数走弱 0.3% 释放风险偏好，黄金 -1.2% 被资金获利兑现转向权益。"
        "原油 +0.8% 配合 PMI 边际改善暗示制造业修复，"
        "BTC 横盘小幅 +0.2% 风险资产分化但未现避险。综合显示资金对宽松进攻情景定价确信度上升。"
    ),
    "next_session_expect": "继续宽松交易",
    "what_kills_this_view": "明日 10Y 跳升 8bp",
    "free_analysis": "宽松交易延续，长端债券走强配合美元弱势，黄金被资金获利了结。",
}


def test_druck_full_panel_4dims_pass():
    panel = {"cross_asset_state": {
        "treasury_10y": "up", "treasury_30y": "up", "dollar": "down",
        "gold": "down", "oil": None, "vix": None, "btc": None, "eth": None,
    }}  # available=4, need=2
    ok, errors = validate_narrative(_us_base_narrative(druck=VALID_DRUCK), "US", panel)
    assert ok, errors


def test_druck_full_8dims_need_4():
    panel = {"cross_asset_state": {d: "up" for d in
             ["treasury_10y", "treasury_30y", "dollar", "gold",
              "oil", "vix", "btc", "eth"]}}  # available=8, need=4
    # VALID_DRUCK 提到 4 个 → 通过
    ok, errors = validate_narrative(_us_base_narrative(druck=VALID_DRUCK), "US", panel)
    assert ok, errors


def test_druck_insufficient_dim_mentions():
    panel = {"cross_asset_state": {d: "up" for d in
             ["treasury_10y", "treasury_30y", "dollar", "gold",
              "oil", "vix", "btc", "eth"]}}  # need=4
    bad = {**VALID_DRUCK, "evidence": "10年国债涨 0.4%（仅 1 维）"}
    ok, errors = validate_narrative(_us_base_narrative(druck=bad), "US", panel)
    assert not ok
    assert any("evidence" in e and "跨资产" in e for e in errors)


def test_druck_severely_missing_requires_declaration():
    panel = {"cross_asset_state": {d: None for d in
             ["treasury_10y", "treasury_30y", "dollar", "gold",
              "oil", "vix", "btc", "eth"]}}  # available=0, need=0
    # 不声明 → 失败
    bad = {**VALID_DRUCK, "evidence": "市场震荡"}
    ok, errors = validate_narrative(_us_base_narrative(druck=bad), "US", panel)
    assert not ok
    # 声明 → 通过
    ok2 = {**VALID_DRUCK, "evidence": "跨资产数据缺失，仅参考价格"}
    ok2_pass, _ = validate_narrative(_us_base_narrative(druck=ok2), "US", panel)
    assert ok2_pass


def test_druck_bad_enum():
    panel = {"cross_asset_state": {d: "up" for d in
             ["treasury_10y", "treasury_30y", "dollar", "gold",
              "oil", "vix", "btc", "eth"]}}
    bad = {**VALID_DRUCK, "macro_regime": "牛市"}
    ok, errors = validate_narrative(_us_base_narrative(druck=bad), "US", panel)
    assert not ok
    assert any("macro_regime" in e for e in errors)


# ---------- minervini 降级 ----------

VALID_MINERVINI = {
    "breadth_state": "健康", "key_metric_focus": "200日均线广度",
    "evidence": "above_ma150 上升至 24，新高数 5；spy_iwm 分化收窄至 0.5%",
    "divergence_warning": "否",
    "what_kills_this_view": "above_ma150 跌破 15 且 spy_iwm 扩大至 2%",
    "free_analysis": "广度状态健康，大小盘分化收敛，趋势确认信号增强。",
}


def test_minervini_full_three_fields():
    panel = {"above_ma150_count": 24, "spy_iwm_divergence": 0.005,
             "new_high_count_20d": 5}
    ok, errors = validate_narrative(_us_base_narrative(minervini=VALID_MINERVINI),
                                     "US", panel)
    assert ok, errors


def test_minervini_partial_panel_with_declaration():
    """spy_iwm_divergence 缺失 → 可用=2，需引 2；声明可降级。"""
    panel = {"above_ma150_count": 24, "spy_iwm_divergence": None,
             "new_high_count_20d": 5}
    # 引 1 个 + 声明数据缺失 → 通过
    n = {**VALID_MINERVINI, "evidence": "above_ma150 上升至 24；spy_iwm 数据暂缺"}
    ok, errors = validate_narrative(_us_base_narrative(minervini=n), "US", panel)
    assert ok, errors


def test_minervini_insufficient_mentions_no_declaration():
    panel = {"above_ma150_count": 24, "spy_iwm_divergence": 0.005,
             "new_high_count_20d": 5}
    # 引 1 个，不声明 → 失败
    n = {**VALID_MINERVINI, "evidence": "above_ma150 24，仅 1 项"}
    ok, errors = validate_narrative(_us_base_narrative(minervini=n), "US", panel)
    assert not ok


# ---------- wyckoff / weinstein 基本 enum 校验 ----------

# ---------- free_analysis / ticker_analyses ----------

def test_free_analysis_too_long():
    bad = {**VALID_YANGJIA, "free_analysis": "x" * 250}
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": bad,
         "zhaolaoge_liquidity_focus": None, "fengliu_contrarian_check": None,
         "trading_discipline_review": None}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("free_analysis" in e and "超过" in e for e in errors)


def test_ticker_analyses_valid():
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": None,
         "ticker_analyses": {"SH510050": "上证50ETF 今日缩量整理，价格分位居中，资金谨慎观望中长期方向。"}}
    ok, errors = validate_narrative(n, "A")
    assert ok, errors


def test_ticker_analyses_too_short():
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": None,
         "ticker_analyses": {"SH510050": "太短"}}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("太短" in e for e in errors)


def test_ticker_analyses_too_long():
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": None,
         "ticker_analyses": {"SH510050": "x" * 200}}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("太长" in e for e in errors)


def test_merge_ticker_analyses_to_session():
    from src.llm_validate import merge_into_session
    session = {"tickers": [
        {"code": "SH510050", "analysis": ""},
        {"code": "SZ159995", "analysis": ""},
    ]}
    narrative = {
        "is_skeleton": False, "session_summary": "x",
        "ticker_analyses": {"SH510050": "测试分析内容" * 8},
    }
    merge_into_session(session, narrative)
    assert "测试分析内容" in session["tickers"][0]["analysis"]
    assert session["tickers"][1]["analysis"] == ""  # 未提供的不动


def test_merge_ticker_audits_overrides_quant():
    """LLM 给的人格审应覆盖 build_snapshot 兜底的 quant 审。"""
    from src.llm_validate import merge_into_session
    session = {"tickers": [
        {"code": "SH510050", "audit": {"actual_vs_expected": "符合预期", "auditor": "quant"}},
        {"code": "SZ159995", "audit": {"actual_vs_expected": "低于预期", "auditor": "quant"}},
    ]}
    narrative = {
        "is_skeleton": False, "session_summary": "x",
        "ticker_audits": {
            "SH510050": {"actual_vs_expected": "强超于预期", "auditor": "zhaolaoge"},
        },
    }
    merge_into_session(session, narrative)
    # 被覆盖
    assert session["tickers"][0]["audit"] == {"actual_vs_expected": "强超于预期", "auditor": "zhaolaoge"}
    # 未提供的保留 quant 兜底
    assert session["tickers"][1]["audit"]["auditor"] == "quant"


# ---------- 新顶层字段 ----------

_DEEP_OK = (
    "今日 A 股呈现典型分化：上涨 15/45 占比 33%，强势仅 1 只，量能整体收缩。"
    "市场资金全景图层面，板块结构呈现高低切但缺乏增量血液；行业属性上传统消费与高位"
    "题材同步调整，反映场内资金对估值锚不再笃定。从宏观资金维度看，避险资产受到追逐，"
    "成长股则普遍承压，市场风险偏好整体回落。\n\n"
    "关键异动板块解读：(1) 银行 ETF 放量大涨 2%，量价齐升 → 资金避险拥抱低波动确定性"
    "标的；(2) 证券保险弱势 → 与银行板块背离印证当前是防守而非进攻格局；"
    "(3) 半导体缩量阴跌 → 多头止损被动，主线资金外撤；(4) 黄金 ETF 放量上行 → 跨"
    "资产避险情绪共振，与权益市场情绪形成鲜明对照；(5) 创业板情绪 ETF 萎靡 → 投机资金"
    "退场。\n\n"
    "交叉验证：权重大涨 + 题材普跌 = 典型存量博弈跷跷板效应，结合国债同涨"
    "和 10 年期收益率回落判定为典型 Risk-off 阶段。市场风格在快速从增量进攻切换到防御"
    "存量博弈，资金对 AI/半导体核心成长链估值的容忍度边际下降。\n\n"
    "结论：当前处于高位分歧阶段，资金主攻方向为低波动防御资产与黄金避险标的，"
    "出逃方向为高位题材股与小市值情绪题材，潜在风险点为机构集体调仓引发踩踏；"
    "大势震荡偏弱，风格偏向防守，核心关注证券板块是否补涨与 10 年期国债收益率的"
    "二次确认信号。"
)


def test_strategy_outlook_valid():
    so = {
        "market_phase": "趋势主升", "trend_forecast": "上涨", "style_tone": "偏向进攻",
        "attack_direction": "AI 算力 + 半导体设备",
        "retreat_direction": "传统消费 + 高位地产",
        "key_focus": ["证券板块是否补涨", "10 年期国债收益率"],
        "risk_points": ["机构调仓引发踩踏", "外资突然撤离"],
        "deep_analysis": _DEEP_OK,
    }
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": None,
         "strategy_outlook": so}
    ok, errors = validate_narrative(n, "A")
    assert ok, errors


def test_strategy_outlook_deep_analysis_too_short():
    """deep_analysis 必填，且至少 400 字（#9 2026-05-22）。"""
    so = {
        "market_phase": "趋势主升", "trend_forecast": "上涨", "style_tone": "偏向进攻",
        "attack_direction": "x", "retreat_direction": "x",
        "key_focus": ["a"], "risk_points": ["b"],
        "deep_analysis": "太短了" * 5,  # < 400 字
    }
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": None,
         "strategy_outlook": so}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("deep_analysis" in e for e in errors)


def test_strategy_outlook_bad_enum():
    so = {
        "market_phase": "牛市顶", "trend_forecast": "上涨", "style_tone": "偏向进攻",
        "attack_direction": "x", "retreat_direction": "x",
        "key_focus": ["a"], "risk_points": ["b"],
        "deep_analysis": _DEEP_OK,
    }
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": None,
         "strategy_outlook": so}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("market_phase" in e and "白名单" in e for e in errors)


def test_macro_cycle_required_on_weekend():
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": None}
    ok, errors = validate_narrative(n, "A", is_weekend_close=True)
    assert not ok
    assert any("macro_cycle_anchor" in e and "周末" in e for e in errors)


def test_macro_cycle_optional_on_weekday():
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": None}
    ok, errors = validate_narrative(n, "A", is_weekend_close=False)
    assert ok, errors


def test_unique_anomaly_length_band():
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": None,
         "unique_anomaly_analysis": "短" * 50}  # < 200 字
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("unique_anomaly_analysis" in e for e in errors)


def test_ticker_audits_rejects_quant_auditor():
    """LLM 不允许声明 auditor=quant（那是 Python 的活）。"""
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": None,
         "fengliu_contrarian_check": None, "trading_discipline_review": None,
         "ticker_audits": {
             "SH510050": {"actual_vs_expected": "超于预期", "auditor": "quant"},
         }}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("quant" in e and "不允许" in e for e in errors)


def test_key_movers_too_few():
    """zhaolaoge 必须 ≥3 条 key_movers（#9 2026-05-22 上调阈值）。"""
    zhao = {
        "anchor_etfs": ["SH510050"],
        "liquidity_signal": "主线合力",
        "evidence": "上涨 15 只，量比 1.5x",
        "follow_strategy": "顺势跟进半导体",
        "what_kills_this_view": "明日量能塌缩",
        "free_analysis": "x" * 50,
        "key_movers": [
            {"sector": "AI", "phenomenon": "放量上涨", "motive": "机构进攻", "scenario": "持续主升"},
            {"sector": "半导体", "phenomenon": "放量", "motive": "补涨", "scenario": "续涨"},
        ],  # 只有 2 条，< 3
    }
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": None, "zhaolaoge_liquidity_focus": zhao,
         "fengliu_contrarian_check": None, "trading_discipline_review": None}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("key_movers 至少" in e for e in errors)


def test_prev_session_audit_bad_rating():
    yj = {**VALID_YANGJIA,
          "prev_session_audit": {"actual_vs_expected": "差不多", "audit_note": "x"}}
    n = {"is_skeleton": False, "session_summary": "x",
         "yangjia_emotion_cycle": yj,
         "zhaolaoge_liquidity_focus": None, "fengliu_contrarian_check": None,
         "trading_discipline_review": None}
    ok, errors = validate_narrative(n, "A")
    assert not ok
    assert any("prev_session_audit.actual_vs_expected" in e for e in errors)


def test_weinstein_bad_enum():
    field = {
        "anchor_tickers": ["AAPL"],
        "weinstein_stage": "牛市初期",  # 不在白名单
        "ma_relation": "站上30周均线",
        "evidence": "x", "entry_opportunity": "x", "what_kills_this_view": "x",
    }
    n = _us_base_narrative()
    n["weinstein_stage_check"] = field
    ok, errors = validate_narrative(n, "US", {})
    assert not ok
    assert any("weinstein_stage" in e for e in errors)
