"""LLM 输出 schema 校验 + 校验降级 + 合并入 session。

铁律（CLAUDE.md）：
  - enum 不在白名单 → 拒绝渲染
  - what_kills_this_view 必填
  - 候选 0 → null + session_summary 说明
  - discipline_pass=false 默认降一档；rating_override 可破例（不可跨档）

降级（REFACTOR_BRIEF 4.9.9）：
  druckenmiller 可用维度数 ≥6→引 4；≥4→引 (n-2)；≥2→全引；<2→只要求声明数据缺失
  minervini 三项可用全要求；缺一项降一档
  降级触发时 LLM 必须在 evidence 末尾显式声明（关键词：数据缺失/暂缺/不可用）
"""
from __future__ import annotations

from typing import Iterable
from src.llm_schema import (
    get_schema, TOP_LEVEL_REQUIRED,
    A_CROSS_ASSET_DIMS, US_CROSS_ASSET_DIMS, MINERVINI_BREADTH_FIELDS,
    QUADRANT_CATS, QUADRANT_SUMMARY_MIN, QUADRANT_SUMMARY_MAX,
    GROUP_QUALITATIVE_KEYS, GROUP_QUALITATIVE_MIN, GROUP_QUALITATIVE_MAX,
    FREE_ANALYSIS_MAX, TICKER_ANALYSIS_MIN, TICKER_ANALYSIS_MAX,
    PANORAMA_LEN, CROSS_VALIDATION_LEN, CROSS_ASSET_PANORAMA_LEN, AUDIT_NOTE_MAX,
    DEEP_ANALYSIS_LEN,
    KEY_MOVERS_MIN, KEY_MOVER_REQUIRED,
    ENUM_AUDIT_RATING, ENUM_AUDITOR,
    ENUM_MARKET_PHASE, ENUM_TREND_FORECAST, ENUM_STYLE_TONE,
    STRATEGY_OUTLOOK_SCHEMA, MACRO_CYCLE_SCHEMA, UNIQUE_ANOMALY_LEN,
    TICKER_AUDIT_SCHEMA,
    normalize_audit_rating,
)

# 维度名 → 关键词别名（LLM evidence 必须字面出现以下任一关键词才算"引用"该维度）。
# 修改本表会同步影响 prompt 里展示给 LLM 的"可接受关键词"列表（_schema_text）。
A_DIM_ALIASES = {
    "treasury_10y": ["10年国债", "10y", "treasury_10y", "10年期国债", "10年期", "十年国债", "国债10y"],
    "treasury_30y": ["30年国债", "30y", "treasury_30y", "30年期国债", "30年期", "三十年国债"],
    "gold": ["黄金", "金", "gold", "贵金属", "金价"],
    "oil": ["原油", "油", "oil", "石油", "wti", "布伦特"],
}
US_DIM_ALIASES = {
    "treasury_10y": ["10年国债", "10y", "ief", "treasury_10y", "10年期", "10年期国债",
                     "美10债", "10年美债", "10年期美债", "10y收益率", "10年收益率",
                     "美债10y", "10年期债"],
    "treasury_30y": ["30年国债", "30y", "tlt", "treasury_30y", "30年期", "30年期国债",
                     "美30债", "30年美债", "30年期美债", "30y收益率", "长债"],
    "dollar":       ["美元", "uup", "dollar", "美元指数", "dxy", "美汇", "美元走强", "美元走弱"],
    "gold":         ["黄金", "gld", "金", "gold", "贵金属", "金价", "黄金价格"],
    "oil":          ["原油", "uso", "油", "oil", "石油", "wti", "布伦特", "原油价格"],
    "vix":          ["vix", "vixy", "波动率", "恐慌指数", "市场恐慌", "vix指数"],
    "btc":          ["btc", "比特币", "ibit", "加密", "加密货币", "比特币价格", "数字货币"],
    "eth":          ["eth", "以太", "etha", "以太坊", "ether"],
}
BREADTH_ALIASES = {
    "above_ma150_count":  ["above_ma150", "ma150", "30周均线", "above_ma150_count",
                           "站上150日", "150日线", "150日均线", "30周线", "above ma150",
                           "上方ma150", "30周均线广度"],
    "spy_iwm_divergence": ["spy_iwm", "大小盘", "spy_iwm_divergence", "spy", "iwm",
                           "大小盘分化", "大盘小盘", "大小盘背离", "spy-iwm"],
    "new_high_count_20d": ["新高数", "新高数量", "new_high", "new_high_count",
                           "20日新高", "20日内新高", "20日新高数", "新高家数"],
}

DATA_MISSING_KEYWORDS = ["数据缺失", "暂缺", "不可用"]


def _check_enum(field_name: str, value, enum_list: list, errors: list) -> None:
    if value not in enum_list:
        errors.append(f"{field_name}={value!r} 不在白名单 {enum_list}")


def _check_required(field_data: dict, required_keys: Iterable[str],
                    field_label: str, errors: list) -> None:
    for k in required_keys:
        # key_movers / 子 list 等允许 [] / 但要在专项里查
        if k not in field_data:
            errors.append(f"{field_label}.{k} 必填但缺失")
            continue
        v = field_data[k]
        if v in (None, "") or (isinstance(v, list) and not v):
            errors.append(f"{field_label}.{k} 必填但空")
    # free_analysis 长度上限（2026-05-22 放开，无上限）
    # 保留此 hook 供未来如需重新限制时使用
    if FREE_ANALYSIS_MAX is not None:
        fa = field_data.get("free_analysis")
        if fa and isinstance(fa, str) and len(fa) > FREE_ANALYSIS_MAX:
            errors.append(f"{field_label}.free_analysis 超过 {FREE_ANALYSIS_MAX} 字（当前 {len(fa)} 字）")


def _check_length_range(text: str | None, lo_hi: tuple,
                        label: str, errors: list) -> None:
    """lo_hi = (下限, 上限)；上限 None 表示无上限。"""
    if not text:
        return  # 空由 _check_required 报；此处只查长度
    n = len(text)
    lo, hi = lo_hi
    if n < lo:
        errors.append(f"{label} 长度 {n} 短于下限 {lo}")
        return
    if hi is not None and n > hi:
        errors.append(f"{label} 长度 {n} 超上限 {hi}")


def _validate_prev_audit(field: dict, label: str, errors: list) -> None:
    """各人格字段下的 prev_session_audit 子节（可选）。
    schema: {actual_vs_expected: enum 五档, audit_note: ≤80字} 或 null。
    """
    pa = field.get("prev_session_audit")
    if pa is None:
        return
    if not isinstance(pa, dict):
        errors.append(f"{label}.prev_session_audit 应为 dict 或 null")
        return
    rating = pa.get("actual_vs_expected")
    normalized = normalize_audit_rating(rating)
    if normalized is None:
        errors.append(f"{label}.prev_session_audit.actual_vs_expected={rating!r} 不在白名单 {ENUM_AUDIT_RATING}"
                      f"（同义词亦可：强超/强超预期/超/超预期/符合/低/不及预期/强低/远低于预期）")
    else:
        pa["actual_vs_expected"] = normalized  # 归一化写回
    if AUDIT_NOTE_MAX is not None:
        note = pa.get("audit_note", "")
        if note and len(note) > AUDIT_NOTE_MAX:
            errors.append(f"{label}.prev_session_audit.audit_note 超 {AUDIT_NOTE_MAX} 字")


def _validate_key_movers(field: dict, label: str, errors: list) -> None:
    """赵老哥 / 冯柳 / wyckoff / weinstein 的 key_movers list。
    每条 {sector, phenomenon, motive, scenario} 全必填；list 长度 ≥KEY_MOVERS_MIN。"""
    movers = field.get("key_movers")
    if movers is None:
        return  # 必填错误已由 _check_required 报
    if not isinstance(movers, list):
        errors.append(f"{label}.key_movers 应为 list")
        return
    if len(movers) < KEY_MOVERS_MIN:
        errors.append(f"{label}.key_movers 至少 {KEY_MOVERS_MIN} 条（当前 {len(movers)}）")
    for i, m in enumerate(movers):
        if not isinstance(m, dict):
            errors.append(f"{label}.key_movers[{i}] 应为 dict")
            continue
        for k in KEY_MOVER_REQUIRED:
            if not m.get(k):
                errors.append(f"{label}.key_movers[{i}].{k} 必填")


def _count_dim_mentions(text: str, aliases: dict[str, list[str]]) -> int:
    """统计 text 提到了多少个不同维度（按 aliases）。"""
    if not text:
        return 0
    text_lower = text.lower()
    count = 0
    for _dim, alias_list in aliases.items():
        for a in alias_list:
            if a.lower() in text_lower:
                count += 1
                break
    return count


def _has_data_missing_declaration(text: str) -> bool:
    if not text:
        return False
    return any(kw in text for kw in DATA_MISSING_KEYWORDS)


def _available_cross_asset_dims(panel: dict, market: str) -> int:
    """panel.cross_asset_state 中非 null 的维度数。"""
    cas = (panel or {}).get("cross_asset_state", {})
    valid_dims = US_CROSS_ASSET_DIMS if market == "US" else A_CROSS_ASSET_DIMS
    return sum(1 for d in valid_dims if cas.get(d) is not None)


def _druckenmiller_required_dim_count(available: int) -> int:
    """4.9.9 降级表。"""
    if available >= 6:
        return 4
    if available >= 4:
        return available - 2
    if available >= 2:
        return available  # 全引
    return 0  # 只要求声明缺失


def _validate_druckenmiller(field: dict, panel: dict, errors: list) -> None:
    spec = get_schema("US")["druckenmiller_macro_check"]
    _check_required(field, spec["required"], "druckenmiller_macro_check", errors)
    _check_enum("druckenmiller_macro_check.macro_regime",
                field.get("macro_regime"), spec["enums"]["macro_regime"], errors)
    _check_enum("druckenmiller_macro_check.key_signal",
                field.get("key_signal"), spec["enums"]["key_signal"], errors)
    # cross_asset_panorama 长度（任务 #3）
    _check_length_range(field.get("cross_asset_panorama"),
                        CROSS_ASSET_PANORAMA_LEN,
                        "druckenmiller_macro_check.cross_asset_panorama", errors)

    available = _available_cross_asset_dims(panel, "US")
    need = _druckenmiller_required_dim_count(available)
    ev = field.get("evidence", "") or ""

    if need == 0:
        if not _has_data_missing_declaration(ev):
            errors.append(
                "druckenmiller.evidence 数据严重缺失（可用维度<2），"
                "必须显式声明（'数据缺失'/'暂缺'/'不可用'之一）"
            )
        return

    mentioned = _count_dim_mentions(ev, US_DIM_ALIASES)
    if mentioned < need:
        # 如果 LLM 显式声明了降级，放行（按 4.9.9 节）
        if not _has_data_missing_declaration(ev):
            errors.append(
                f"druckenmiller.evidence 只引用了 {mentioned} 个跨资产维度，"
                f"需 {need}（可用={available}）；或在末尾声明数据缺失以降级放行"
            )


def _validate_minervini(field: dict, panel: dict, errors: list) -> None:
    spec = get_schema("US")["minervini_breadth_check"]
    _check_required(field, spec["required"], "minervini_breadth_check", errors)
    _check_enum("minervini_breadth_check.breadth_state",
                field.get("breadth_state"), spec["enums"]["breadth_state"], errors)
    _check_enum("minervini_breadth_check.key_metric_focus",
                field.get("key_metric_focus"), spec["enums"]["key_metric_focus"], errors)

    panel = panel or {}
    available = sum(1 for f in MINERVINI_BREADTH_FIELDS if panel.get(f) is not None)
    # 三项可用全要求引用；缺一项降一档
    need = max(0, available - (3 - available))  # available=3 → 3? brief says 全要求
    # brief 原文："三项可用全要求引用，缺一项降一档"
    # 重写：可用=3→引3；=2→引2；=1→引1；=0→声明缺失
    need = available
    ev = field.get("evidence", "") or ""
    if need == 0:
        if not _has_data_missing_declaration(ev):
            errors.append("minervini.evidence panel 广度字段全缺，必须声明数据缺失")
        return

    mentioned = _count_dim_mentions(ev, BREADTH_ALIASES)
    if mentioned < need and not _has_data_missing_declaration(ev):
        errors.append(
            f"minervini.evidence 只引用了 {mentioned} 个 panel 广度字段，"
            f"需 {need}（可用={available}）；或声明数据缺失降级"
        )


def _validate_category_field(field: dict, field_name: str, market: str,
                              errors: list) -> None:
    """通用：分类层字段（zhaolaoge/fengliu/wyckoff/weinstein）。"""
    spec = get_schema(market)[field_name]
    _check_required(field, spec["required"], field_name, errors)
    for enum_key, enum_list in spec["enums"].items():
        _check_enum(f"{field_name}.{enum_key}", field.get(enum_key), enum_list, errors)


def _validate_discipline(reviews, market: str, errors: list) -> None:
    """trading_discipline_review 是 list[dict]，每跨日候选一份。"""
    if reviews is None:
        return
    if not isinstance(reviews, list):
        errors.append("trading_discipline_review 应为 list 或 null")
        return
    spec = get_schema(market)["trading_discipline_review"]
    for i, r in enumerate(reviews):
        label = f"trading_discipline_review[{i}]"
        if "code" not in r:
            errors.append(f"{label}.code 必填（标识哪只 ETF）")
        _check_required(r, spec["required"], label, errors)
        _check_enum(f"{label}.logic_hardness",
                    r.get("logic_hardness"), spec["enums"]["logic_hardness"], errors)
        _check_enum(f"{label}.risk_reward_ratio",
                    r.get("risk_reward_ratio"), spec["enums"]["risk_reward_ratio"], errors)
        # discipline_pass=false + rating_override 校验
        if r.get("discipline_pass") is False and "rating_override" in r:
            ro = r["rating_override"]
            if not isinstance(ro, dict) or "keep_rating" not in ro or "reason" not in ro:
                errors.append(f"{label}.rating_override 需含 keep_rating 和 reason")


def _validate_strategy_outlook(so, errors: list) -> None:
    """任务 3.4 / #9：8 子项 enum + 必填 + deep_analysis 长度。"""
    if so is None:
        return
    if not isinstance(so, dict):
        errors.append("strategy_outlook 应为 dict 或 null")
        return
    _check_required(so, STRATEGY_OUTLOOK_SCHEMA["required"], "strategy_outlook", errors)
    for enum_key, enum_list in STRATEGY_OUTLOOK_SCHEMA["enums"].items():
        if enum_key in so:
            _check_enum(f"strategy_outlook.{enum_key}", so.get(enum_key), enum_list, errors)
    # risk_points / key_focus 应为 list[str]
    for k in ("risk_points", "key_focus"):
        v = so.get(k)
        if v is not None and not isinstance(v, list):
            errors.append(f"strategy_outlook.{k} 应为 list[str]")
    # deep_analysis 长度（#9 2026-05-22）
    _check_length_range(so.get("deep_analysis"), DEEP_ANALYSIS_LEN,
                        "strategy_outlook.deep_analysis", errors)


def _validate_unique_anomaly(text, errors: list) -> None:
    """任务 2.3 独特异象（炒家）：null（无独特品种）或 200-500 字。"""
    if text is None:
        return
    if not isinstance(text, str):
        errors.append("unique_anomaly_analysis 应为字符串或 null")
        return
    _check_length_range(text, UNIQUE_ANOMALY_LEN, "unique_anomaly_analysis", errors)


def _validate_macro_cycle(mc, is_weekend_close: bool, errors: list) -> None:
    """任务 4 周末宏观：周末必填四子段；非周末必为 null。"""
    if mc is None:
        if is_weekend_close:
            errors.append("macro_cycle_anchor 在周末收盘时必填（is_weekend_close=true）")
        return
    if not isinstance(mc, dict):
        errors.append("macro_cycle_anchor 应为 dict 或 null")
        return
    _check_required(mc, MACRO_CYCLE_SCHEMA["required"], "macro_cycle_anchor", errors)
    for parent, subs in MACRO_CYCLE_SCHEMA["sub_required"].items():
        sub = mc.get(parent)
        if isinstance(sub, dict):
            _check_required(sub, subs, f"macro_cycle_anchor.{parent}", errors)


def _validate_ticker_audits(audits, errors: list) -> None:
    """LLM 给少数 ticker 升级为人格审：{code: {actual_vs_expected, auditor}}。"""
    if audits is None:
        return
    if not isinstance(audits, dict):
        errors.append("ticker_audits 应为 dict 或 null")
        return
    for code, a in audits.items():
        if not isinstance(a, dict):
            errors.append(f"ticker_audits[{code}] 应为 dict")
            continue
        rating = a.get("actual_vs_expected")
        normalized = normalize_audit_rating(rating)
        if normalized is None:
            errors.append(f"ticker_audits[{code}].actual_vs_expected={rating!r} 不在白名单 {ENUM_AUDIT_RATING}"
                          f"（同义词亦可：强超/强超预期/超/超预期/符合/低/不及预期/强低/远低于预期）")
        else:
            a["actual_vs_expected"] = normalized  # 归一化写回
        auditor = a.get("auditor")
        if auditor not in ENUM_AUDITOR:
            errors.append(f"ticker_audits[{code}].auditor={auditor!r} 不在白名单")
        if auditor == "quant":
            errors.append(f"ticker_audits[{code}].auditor=quant 不允许（量化审由 build_snapshot 兜底，"
                          "LLM 提供的必须是人格审）")


def _validate_ticker_analyses(ta, errors: list) -> None:
    """ticker_analyses: {code: text}，每条 30-120 字。"""
    if ta is None:
        return
    if not isinstance(ta, dict):
        errors.append("ticker_analyses 应为 dict 或 null")
        return
    for code, text in ta.items():
        if not isinstance(text, str):
            errors.append(f"ticker_analyses[{code}] 应为字符串")
            continue
        n = len(text)
        if n < TICKER_ANALYSIS_MIN:
            errors.append(f"ticker_analyses[{code}] 太短（{n} 字 < {TICKER_ANALYSIS_MIN}）")
        elif TICKER_ANALYSIS_MAX is not None and n > TICKER_ANALYSIS_MAX:
            errors.append(f"ticker_analyses[{code}] 太长（{n} 字 > {TICKER_ANALYSIS_MAX}）")


def _validate_quadrant_summaries(qs, errors: list) -> None:
    """quadrant_summaries: null 或 {cat: text}，key 限白名单 4 enum。"""
    if qs is None:
        return
    if not isinstance(qs, dict):
        errors.append("quadrant_summaries 应为 dict 或 null")
        return
    for cat, text in qs.items():
        if cat not in QUADRANT_CATS:
            errors.append(f"quadrant_summaries key {cat!r} 不在白名单 {QUADRANT_CATS}")
            continue
        if text is None:
            continue  # 候选数=0 的象限允许 null
        if not isinstance(text, str):
            errors.append(f"quadrant_summaries[{cat}] 应为字符串或 null")
            continue
        n = len(text)
        if n < QUADRANT_SUMMARY_MIN:
            errors.append(
                f"quadrant_summaries[{cat}] 太短（{n} 字 < {QUADRANT_SUMMARY_MIN}）"
            )
        elif QUADRANT_SUMMARY_MAX is not None and n > QUADRANT_SUMMARY_MAX:
            errors.append(
                f"quadrant_summaries[{cat}] 太长（{n} 字 > {QUADRANT_SUMMARY_MAX}）"
            )


def _validate_group_qualitative(gq, errors: list) -> None:
    """group_qualitative: null 或 {bull_group?, bear_group?}。"""
    if gq is None:
        return
    if not isinstance(gq, dict):
        errors.append("group_qualitative 应为 dict 或 null")
        return
    for key, text in gq.items():
        if key not in GROUP_QUALITATIVE_KEYS:
            errors.append(f"group_qualitative key {key!r} 不在白名单 {GROUP_QUALITATIVE_KEYS}")
            continue
        if text is None:
            continue
        if not isinstance(text, str):
            errors.append(f"group_qualitative[{key}] 应为字符串或 null")
            continue
        n = len(text)
        if n < GROUP_QUALITATIVE_MIN:
            errors.append(
                f"group_qualitative[{key}] 太短（{n} 字 < {GROUP_QUALITATIVE_MIN}）"
            )
        elif GROUP_QUALITATIVE_MAX is not None and n > GROUP_QUALITATIVE_MAX:
            errors.append(
                f"group_qualitative[{key}] 太长（{n} 字 > {GROUP_QUALITATIVE_MAX}）"
            )


def validate_narrative(narrative: dict, market: str,
                       panel: dict | None = None,
                       is_weekend_close: bool = False) -> tuple[bool, list[str]]:
    """校验 LLM 写完的 narrative。返回 (ok, errors)。

    is_weekend_close: 是否为周末收盘（来自 session.is_weekend_close），决定
    macro_cycle_anchor 是否必填。
    """
    errors: list[str] = []
    if not isinstance(narrative, dict):
        return False, ["narrative 不是 dict"]

    # 顶层
    for k in TOP_LEVEL_REQUIRED:
        if k not in narrative:
            errors.append(f"narrative.{k} 必填")
    if narrative.get("is_skeleton") is True:
        # 骨架 narrative 跳过 LLM 字段校验
        return len(errors) == 0, errors

    _validate_ticker_analyses(narrative.get("ticker_analyses"), errors)
    _validate_strategy_outlook(narrative.get("strategy_outlook"), errors)
    _validate_unique_anomaly(narrative.get("unique_anomaly_analysis"), errors)
    _validate_macro_cycle(narrative.get("macro_cycle_anchor"), is_weekend_close, errors)
    _validate_ticker_audits(narrative.get("ticker_audits"), errors)
    _validate_quadrant_summaries(narrative.get("quadrant_summaries"), errors)
    _validate_group_qualitative(narrative.get("group_qualitative"), errors)

    schema = get_schema(market)

    if market == "A":
        # yangjia
        f = narrative.get("yangjia_emotion_cycle")
        if f is not None:
            spec = schema["yangjia_emotion_cycle"]
            _check_required(f, spec["required"], "yangjia_emotion_cycle", errors)
            _check_enum("yangjia_emotion_cycle.stage", f.get("stage"),
                        spec["enums"]["stage"], errors)
            _check_enum("yangjia_emotion_cycle.intensity", f.get("intensity"),
                        spec["enums"]["intensity"], errors)
            _check_length_range(f.get("panorama_text"), PANORAMA_LEN,
                                "yangjia_emotion_cycle.panorama_text", errors)
            _check_length_range(f.get("cross_validation_text"), CROSS_VALIDATION_LEN,
                                "yangjia_emotion_cycle.cross_validation_text", errors)
            _validate_prev_audit(f, "yangjia_emotion_cycle", errors)

        for fname in ("zhaolaoge_liquidity_focus", "fengliu_contrarian_check"):
            f = narrative.get(fname)
            if f is not None:
                _validate_category_field(f, fname, "A", errors)
                _validate_key_movers(f, fname, errors)
                _validate_prev_audit(f, fname, errors)

        _validate_discipline(narrative.get("trading_discipline_review"), "A", errors)

    else:  # US
        if narrative.get("druckenmiller_macro_check") is not None:
            _validate_druckenmiller(narrative["druckenmiller_macro_check"], panel, errors)
        if narrative.get("minervini_breadth_check") is not None:
            _validate_minervini(narrative["minervini_breadth_check"], panel, errors)
        if narrative.get("wyckoff_breakout_check") is not None:
            _validate_category_field(narrative["wyckoff_breakout_check"],
                                     "wyckoff_breakout_check", "US", errors)
        if narrative.get("weinstein_stage_check") is not None:
            _validate_category_field(narrative["weinstein_stage_check"],
                                     "weinstein_stage_check", "US", errors)
        _validate_discipline(narrative.get("trading_discipline_review"), "US", errors)

    return len(errors) == 0, errors


def merge_into_session(session: dict, narrative: dict) -> dict:
    """把 narrative 合并进 session（in-place 也返回）。

    - 覆盖整个 narrative 字段
    - ticker_analyses 回填到 tickers[i].analysis
    - ticker_audits（LLM 人格审）覆盖 tickers[i].audit（build_snapshot 的 Python
      量化审已兜底；这里只对 LLM 显式给出的少数 code 升级为人格审）
    """
    session["narrative"] = narrative
    ta = narrative.get("ticker_analyses") or {}
    if ta:
        for t in session.get("tickers", []):
            if t["code"] in ta:
                t["analysis"] = ta[t["code"]]
    audits = narrative.get("ticker_audits") or {}
    if audits:
        for t in session.get("tickers", []):
            new = audits.get(t["code"])
            if new:
                t["audit"] = new  # 覆盖 quant 兜底
    return session
