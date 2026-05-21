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
    FREE_ANALYSIS_MAX, TICKER_ANALYSIS_MIN, TICKER_ANALYSIS_MAX,
)

# 维度名 → 中文别名（LLM 写 evidence 时可能用中文）
A_DIM_ALIASES = {
    "treasury_10y": ["10年国债", "10y", "treasury_10y", "10年期国债"],
    "treasury_30y": ["30年国债", "30y", "treasury_30y", "30年期国债"],
    "gold": ["黄金", "金", "gold"],
    "oil": ["原油", "油", "oil"],
}
US_DIM_ALIASES = {
    "treasury_10y": ["10年国债", "10y", "ief", "treasury_10y"],
    "treasury_30y": ["30年国债", "30y", "tlt", "treasury_30y"],
    "dollar": ["美元", "uup", "dollar", "美元指数"],
    "gold": ["黄金", "gld", "金", "gold"],
    "oil": ["原油", "uso", "油", "oil"],
    "vix": ["vix", "vixy", "波动率"],
    "btc": ["btc", "比特币", "ibit"],
    "eth": ["eth", "以太", "etha"],
}
BREADTH_ALIASES = {
    "above_ma150_count": ["above_ma150", "ma150", "30周均线", "above_ma150_count"],
    "spy_iwm_divergence": ["spy_iwm", "大小盘", "spy_iwm_divergence"],
    "new_high_count_20d": ["新高数", "新高数量", "new_high", "new_high_count"],
}

DATA_MISSING_KEYWORDS = ["数据缺失", "暂缺", "不可用"]


def _check_enum(field_name: str, value, enum_list: list, errors: list) -> None:
    if value not in enum_list:
        errors.append(f"{field_name}={value!r} 不在白名单 {enum_list}")


def _check_required(field_data: dict, required_keys: Iterable[str],
                    field_label: str, errors: list) -> None:
    for k in required_keys:
        if k not in field_data or field_data[k] in (None, ""):
            errors.append(f"{field_label}.{k} 必填但缺失/空")
    # free_analysis 长度上限
    fa = field_data.get("free_analysis")
    if fa and isinstance(fa, str) and len(fa) > FREE_ANALYSIS_MAX:
        errors.append(f"{field_label}.free_analysis 超过 {FREE_ANALYSIS_MAX} 字（当前 {len(fa)} 字）")


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
            elif len(ro.get("reason", "")) > 30:
                errors.append(f"{label}.rating_override.reason 超 30 字")


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
        elif n > TICKER_ANALYSIS_MAX:
            errors.append(f"ticker_analyses[{code}] 太长（{n} 字 > {TICKER_ANALYSIS_MAX}）")


def validate_narrative(narrative: dict, market: str,
                       panel: dict | None = None) -> tuple[bool, list[str]]:
    """校验 LLM 写完的 narrative。返回 (ok, errors)。"""
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

        if narrative.get("zhaolaoge_liquidity_focus") is not None:
            _validate_category_field(narrative["zhaolaoge_liquidity_focus"],
                                     "zhaolaoge_liquidity_focus", "A", errors)
        if narrative.get("fengliu_contrarian_check") is not None:
            _validate_category_field(narrative["fengliu_contrarian_check"],
                                     "fengliu_contrarian_check", "A", errors)
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
    覆盖整个 narrative 字段；同时把 ticker_analyses 回填到 tickers[i].analysis。
    """
    session["narrative"] = narrative
    ta = narrative.get("ticker_analyses") or {}
    if ta:
        for t in session.get("tickers", []):
            if t["code"] in ta:
                t["analysis"] = ta[t["code"]]
    return session
