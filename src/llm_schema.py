"""双引擎人格 schema 定义（封闭集合）。

铁律（CLAUDE.md "双引擎人格 schema"）：
  - enum 不在白名单 → Python 校验拒绝渲染（必须重写）
  - what_kills_this_view 每字段必填（不可变性承诺锚点）
  - 候选数 = 0 时整字段填 null，在 session_summary 说明

来源：REFACTOR_BRIEF 4.3（A 股）/ 4.9.6（美股）
"""
from __future__ import annotations

# ============ enum 白名单 ============

# A 股
ENUM_YANGJIA_STAGE = ["冰点", "试错", "发酵", "高潮", "退潮"]
ENUM_YANGJIA_INTENSITY = ["弱", "中", "强"]
ENUM_LIQUIDITY_SIGNAL = ["主线合力", "局部脉冲", "弱合力", "无合力"]
ENUM_CONTRARIAN_GRADE = ["高赔率", "中赔率", "低赔率", "陷阱区"]

# 美股
ENUM_MACRO_REGIME = ["紧缩避险", "紧缩进攻", "中性震荡", "宽松避险", "宽松进攻", "转折临界"]
ENUM_KEY_SIGNAL = ["利率主导", "美元主导", "商品主导", "VIX主导", "加密风险偏好", "多空交战"]
ENUM_BREADTH_STATE = ["健康", "失真临界", "失真严重", "筑底修复", "趋势确认"]
ENUM_KEY_METRIC_FOCUS = ["大小盘分化", "200日均线广度", "新高数量", "风格集中度", "多空交战"]
ENUM_WYCKOFF_PHASE = ["主升加速", "主升中段", "分配前夕", "派发中", "诱多突破"]
ENUM_VOL_PRICE_QUALITY = ["价量配合", "价量背离", "缩量阴阳怪气"]
ENUM_WEINSTEIN_STAGE = ["阶段1底部建仓", "阶段2主升初期", "阶段3顶部分配", "阶段4主跌中", "阶段不明"]
ENUM_MA_RELATION = ["站上30周均线", "跌破30周均线", "围绕30周均线震荡"]

# 共用（trading_discipline_review）
ENUM_LOGIC_HARDNESS = ["硬", "软", "牵强"]
ENUM_RISK_REWARD_RATIO = ["优", "中", "差"]

# 预期审计（任务 2.2）
ENUM_AUDIT_RATING = ["强超于预期", "超于预期", "符合预期", "低于预期", "强低于预期"]
ENUM_AUDITOR = ["quant", "yangjia", "zhaolaoge", "fengliu", "discipline"]

# 同义词归一化：LLM 常给的简写 → 标准 5 档。校验时先 normalize 再比对白名单；
# merge_into_session 写回前也归一化（窗口里只存 5 档之一）。
AUDIT_RATING_ALIASES = {
    "强超于预期": "强超于预期",
    "强超预期":   "强超于预期",
    "强超":       "强超于预期",
    "大超预期":   "强超于预期",
    "远超预期":   "强超于预期",

    "超于预期":   "超于预期",
    "超预期":     "超于预期",
    "超":         "超于预期",
    "略超预期":   "超于预期",

    "符合预期":   "符合预期",
    "符合":       "符合预期",
    "如期":       "符合预期",

    "低于预期":   "低于预期",
    "略低于预期": "低于预期",
    "低":         "低于预期",
    "略低":       "低于预期",
    "不及预期":   "低于预期",

    "强低于预期": "强低于预期",
    "强低预期":   "强低于预期",
    "强低":       "强低于预期",
    "大幅低于":   "强低于预期",
    "远低于预期": "强低于预期",
}


def normalize_audit_rating(value):
    """LLM 简写 → 标准 5 档；不匹配返 None。"""
    if not isinstance(value, str):
        return None
    return AUDIT_RATING_ALIASES.get(value.strip())

# 顶层 strategy_outlook（任务 3.4）
ENUM_MARKET_PHASE = ["情绪修复", "趋势主升", "高位分歧", "阴跌抵抗", "其他"]
ENUM_TREND_FORECAST = ["上涨", "震荡", "下跌"]
ENUM_STYLE_TONE = ["偏向进攻", "偏向防守", "混沌期"]

# 跨资产维度名（panel.cross_asset_state 的 key）
A_CROSS_ASSET_DIMS = ["treasury_10y", "treasury_30y", "gold", "oil"]
US_CROSS_ASSET_DIMS = ["treasury_10y", "treasury_30y", "dollar", "gold",
                       "oil", "vix", "btc", "eth"]

# minervini 必引 panel 字段（任选 2/3）
MINERVINI_BREADTH_FIELDS = ["above_ma150_count", "spy_iwm_divergence", "new_high_count_20d"]


# ============ A 股 schema ============

A_SCHEMA = {
    "yangjia_emotion_cycle": {
        "scope": "global",  # 全局 1 份
        "enums": {
            "stage": ENUM_YANGJIA_STAGE,
            "intensity": ENUM_YANGJIA_INTENSITY,
        },
        "required": ["stage", "intensity", "evidence",
                     "next_session_expect", "what_kills_this_view",
                     "free_analysis",
                     "panorama_text",        # 任务 3.1 全景图 ≥3 段
                     "cross_validation_text" # 任务 3.3 交叉验证
                     ],
        "optional": ["prev_session_audit"],  # 任务 2.2，{rating, audit_note} 或 null
        "nullable": True,
    },
    "zhaolaoge_liquidity_focus": {
        "scope": "category:持续强化+反包修复",
        "enums": {"liquidity_signal": ENUM_LIQUIDITY_SIGNAL},
        "required": ["anchor_etfs", "liquidity_signal", "evidence",
                     "follow_strategy", "what_kills_this_view",
                     "free_analysis",
                     "key_movers"   # 任务 3.2 上涨向异动板块 ≥2 条
                     ],
        "optional": ["prev_session_audit"],
        "nullable": True,
    },
    "fengliu_contrarian_check": {
        "scope": "category:强反转+连续杀跌",
        "enums": {"contrarian_grade": ENUM_CONTRARIAN_GRADE},
        "required": ["anchor_etfs", "contrarian_grade", "evidence",
                     "left_side_window", "what_kills_this_view",
                     "free_analysis",
                     "key_movers"   # 任务 3.2 下跌向异动板块 ≥2 条
                     ],
        "optional": ["prev_session_audit"],
        "nullable": True,
    },
    "trading_discipline_review": {
        "scope": "per_candidate",  # 每跨日候选品种一份
        "enums": {
            "logic_hardness": ENUM_LOGIC_HARDNESS,
            "risk_reward_ratio": ENUM_RISK_REWARD_RATIO,
        },
        "required": ["logic_hardness", "risk_reward_ratio",
                     "discipline_pass", "review_note"],
        # rating_override 可选，但 discipline_pass=false 时若要保留/上调评级需填
        "optional": ["rating_override", "prev_session_audit"],
        "nullable": True,
    },
}


# ============ 美股 schema ============

US_SCHEMA = {
    "druckenmiller_macro_check": {
        "scope": "global",
        "enums": {
            "macro_regime": ENUM_MACRO_REGIME,
            "key_signal": ENUM_KEY_SIGNAL,
        },
        "required": ["macro_regime", "key_signal", "evidence",
                     "next_session_expect", "what_kills_this_view",
                     "free_analysis"],
        "evidence_min_dims": 4,
        "cross_asset_dims": US_CROSS_ASSET_DIMS,
        "nullable": True,
    },
    "minervini_breadth_check": {
        "scope": "global",
        "enums": {
            "breadth_state": ENUM_BREADTH_STATE,
            "key_metric_focus": ENUM_KEY_METRIC_FOCUS,
        },
        "required": ["breadth_state", "key_metric_focus", "evidence",
                     "divergence_warning", "what_kills_this_view",
                     "free_analysis"],
        "evidence_min_breadth_fields": 2,
        "breadth_fields": MINERVINI_BREADTH_FIELDS,
        "nullable": True,
    },
    "wyckoff_breakout_check": {
        "scope": "category:持续强化+反包修复",
        "enums": {
            "wyckoff_phase": ENUM_WYCKOFF_PHASE,
            "vol_price_quality": ENUM_VOL_PRICE_QUALITY,
        },
        "required": ["anchor_tickers", "wyckoff_phase", "vol_price_quality",
                     "evidence", "follow_strategy", "what_kills_this_view",
                     "free_analysis"],
        "nullable": True,
    },
    "weinstein_stage_check": {
        "scope": "category:强反转+连续杀跌",
        "enums": {
            "weinstein_stage": ENUM_WEINSTEIN_STAGE,
            "ma_relation": ENUM_MA_RELATION,
        },
        "required": ["anchor_tickers", "weinstein_stage", "ma_relation",
                     "evidence", "entry_opportunity", "what_kills_this_view",
                     "free_analysis"],
        "nullable": True,
    },
    "trading_discipline_review": A_SCHEMA["trading_discipline_review"],  # 共用
}


# ============ 顶层（非人格）字段 schema ============
# 这些字段不属于任何单个人格，由 LLM 综合产出或多人格联合署名。

# strategy_outlook：任务 3.4 七子项策略前瞻
# 责任划分：6 子项养家定调，risk_points 由炒家专项
STRATEGY_OUTLOOK_SCHEMA = {
    "enums": {
        "market_phase": ENUM_MARKET_PHASE,
        "trend_forecast": ENUM_TREND_FORECAST,
        "style_tone": ENUM_STYLE_TONE,
    },
    "required": ["market_phase", "trend_forecast", "style_tone",
                 "attack_direction", "retreat_direction", "key_focus",
                 "risk_points"],
    "nullable": True,
}

# unique_anomaly_analysis：任务 2.3 独特异象追踪（炒家写）
UNIQUE_ANOMALY_LEN = (200, 500)   # 字数区间

# macro_cycle_anchor：任务 4 周末宏观周期（仅周末必填）
MACRO_CYCLE_SCHEMA = {
    "required": ["asset_profile", "historical_anchor",
                 "then_vs_now", "forward_strategy"],
    "sub_required": {
        "historical_anchor": ["year", "event", "phase", "brief"],
        "then_vs_now": ["similarity", "divergence"],
        "forward_strategy": ["risks", "opportunities"],
    },
    "nullable": True,  # 非周末时整体 null
}

# ticker_audits：任务 2.2 LLM 给少数 ticker 升级为人格审；
# 其它由 build_snapshot 已用 audit.quant_audit_batch 兜底。
# 形如 {code: {actual_vs_expected, auditor}}；fill_narrative 时覆盖 quant 结果。
TICKER_AUDIT_SCHEMA = {
    "enums": {
        "actual_vs_expected": ENUM_AUDIT_RATING,
        "auditor": ENUM_AUDITOR,
    },
    "required": ["actual_vs_expected", "auditor"],
}


def get_schema(market: str) -> dict:
    if market == "A":
        return A_SCHEMA
    if market == "US":
        return US_SCHEMA
    raise ValueError(f"未知市场: {market}")


# session.narrative 顶层还需要：
#   - is_skeleton: bool (Python backfill 时 True；LLM 写满后 False)
#   - session_summary: str (~100 字，含风格判断 + 主线锚定 + 预期推演 + 风险提示)
#   - ticker_analyses: {code: text}  每分类挑 1-2 个重点品种写 50-100 字点评
#   - strategy_outlook: dict | null  任务 3.4 七子项（养家+炒家分工）
#   - unique_anomaly_analysis: str | null  任务 2.3 独特异象（炒家写，无独特品种 → null）
#   - macro_cycle_anchor: dict | null  任务 4 周末宏观（非周末 → null）
#   - ticker_audits: {code: {actual_vs_expected, auditor}}  少数 ticker 升级人格审
TOP_LEVEL_REQUIRED = ["is_skeleton", "session_summary"]
TOP_LEVEL_OPTIONAL = ["strategy_outlook", "unique_anomaly_analysis",
                      "macro_cycle_anchor", "ticker_analyses", "ticker_audits"]

# 长度约束
FREE_ANALYSIS_MAX = 200
TICKER_ANALYSIS_MIN = 30
TICKER_ANALYSIS_MAX = 120
PANORAMA_LEN = (150, 400)
CROSS_VALIDATION_LEN = (100, 300)
AUDIT_NOTE_MAX = 80
KEY_MOVERS_MIN = 2  # 赵老哥 / 冯柳 各 ≥2 条
KEY_MOVER_REQUIRED = ["sector", "phenomenon", "motive", "scenario"]
