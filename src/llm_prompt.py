"""LLM prompt 构造（双市场双引擎）。

设计原则：
  - 系统说明（角色 + 铁律）
  - schema 描述（enum 白名单 + 必填项 + 降级规则）
  - 短键映射表（4.9.9 节，节省 token）
  - 窗口上下文（近 N 时段的 session_summary + 简化 panel）
  - 当前 session 完整数据（短键压缩）
  - 任务说明（"产出 JSON，字段如下"）

不直接调 API。输出 prompt 文本，用户复制到 Claude/Cursor 跑。
"""
from __future__ import annotations

import json
from typing import Literal
from src import llm_schema as schema

# 短键映射（REFACTOR_BRIEF 4.9.9 节）
SHORT_KEYS = {
    "price_pctile_60": "p60",
    "price_pctile_20": "p20",
    "vol_ratio_20": "vr20",
    "vol_pctile_20": "vp20",
    "ma_alignment": "ma",
    "pct_normalized": "pn",
    "new_high_20d": "nh",
    "new_low_20d": "nl",
    "ma150_dist": "md",
    "ma150_relation": "mr",
    "category": "cat",
    "feature": "f",
}

MA_ENCODE = {"多头": 1, "空头": -1, "震荡": 0}
MA150_ENCODE = {"站上": 1, "跌破": -1, "震荡": 0}
CAT_ENCODE = {"持续强化": 1, "反包修复": 2, "强反转": 3, "连续杀跌": 4}


def _compress_ticker(t: dict, market: str) -> dict:
    """长键 → 短键 + 值压缩。"""
    f = t.get("factors") or {}
    out = {
        "c": t.get("code"),
        "n": t.get("name"),
        "pct": round(t.get("today_pct", 0) * 100, 2) if t.get("today_pct") is not None else None,
        "pd": round((t.get("pct_diff") or 0) * 100, 2),
        "vr_d": round((t.get("volume_ratio") or 0) * 100, 1),  # 今/昨成交额环比 %
        SHORT_KEYS["price_pctile_60"]: f.get("price_pctile_60"),
        SHORT_KEYS["price_pctile_20"]: f.get("price_pctile_20"),
        SHORT_KEYS["vol_ratio_20"]: round(f["vol_ratio_20"], 1) if f.get("vol_ratio_20") is not None else None,
        SHORT_KEYS["vol_pctile_20"]: f.get("vol_pctile_20"),
        SHORT_KEYS["ma_alignment"]: MA_ENCODE.get(f.get("ma_alignment")) if f.get("ma_alignment") else None,
        SHORT_KEYS["pct_normalized"]: round(f["pct_normalized"], 1) if f.get("pct_normalized") is not None else None,
        SHORT_KEYS["new_high_20d"]: f.get("new_high_20d"),
        SHORT_KEYS["new_low_20d"]: f.get("new_low_20d"),
        SHORT_KEYS["category"]: CAT_ENCODE.get(t.get("category")),
        SHORT_KEYS["feature"]: t.get("feature") or "",
    }
    if market == "US":
        out[SHORT_KEYS["ma150_dist"]] = round(f["ma150_dist"], 1) if f.get("ma150_dist") is not None else None
        out[SHORT_KEYS["ma150_relation"]] = MA150_ENCODE.get(f.get("ma150_relation")) if f.get("ma150_relation") else None
    return out


def _short_key_map_text(market: str) -> str:
    lines = ["短键映射（输入数据用短键以节省 token；你回 JSON 可用长键或短键均可）："]
    pairs = [
        ("c=code", "n=name", "pct=今日涨幅%", "pd=涨幅差值%", "vr_d=成交额环比%"),
        ("p60=60日价格分位", "p20=20日价格分位", "vr20=20日量比", "vp20=20日量分位"),
        ("ma=均线排列(1多/-1空/0震)", "pn=标准化涨幅"),
        ("nh=20日新高(bool)", "nl=20日新低(bool)"),
        ("cat=分类(1持续/2反包/3强反/4杀跌)", "f=特征标签"),
    ]
    if market == "US":
        pairs.append(("md=距MA150偏离%", "mr=MA150关系(1站上/-1跌破/0震)"))
    for p in pairs:
        lines.append("  " + " / ".join(p))
    return "\n".join(lines)


def _schema_text(market: str) -> str:
    """生成 schema 说明文本。

    对 druckenmiller / minervini 这类 evidence 有"必须引用 N 个维度"约束的字段，
    把可接受的关键词 alias 一并打出来 —— 校验器做的是字面子串匹配，LLM 必须
    在 evidence 里字面出现这些关键词之一才会被计数。
    """
    from src.llm_validate import US_DIM_ALIASES, A_DIM_ALIASES, BREADTH_ALIASES

    s = schema.get_schema(market)
    lines = [f"=== {market} 股双引擎 schema（你必须按此 JSON 结构返回） ==="]
    for fname, spec in s.items():
        lines.append(f"\n【{fname}】scope={spec['scope']}; nullable={spec.get('nullable', False)}")
        lines.append(f"  必填: {spec['required']}")
        for ek, ev in spec.get("enums", {}).items():
            lines.append(f"  enum {ek}: {ev}")
        if "evidence_min_dims" in spec:
            dim_aliases = US_DIM_ALIASES if market == "US" else A_DIM_ALIASES
            lines.append(f"  evidence 至少引用 {spec['evidence_min_dims']} 个跨资产维度："
                         f"必须字面出现以下任一关键词才算引用：")
            for dim in spec["cross_asset_dims"]:
                aliases = dim_aliases.get(dim, [dim])
                lines.append(f"    {dim}: {' / '.join(aliases)}")
        if "evidence_min_breadth_fields" in spec:
            lines.append(f"  evidence 至少引用 {spec['evidence_min_breadth_fields']} 个广度字段："
                         f"必须字面出现以下任一关键词才算引用：")
            for f in spec["breadth_fields"]:
                aliases = BREADTH_ALIASES.get(f, [f])
                lines.append(f"    {f}: {' / '.join(aliases)}")
    return "\n".join(lines)


SYSTEM_HEAD_A_PRE = """你是 A 股板块量价分析的 AI 综合体。Python 已算完所有数字，你只负责"看数字说人话"。

铁律（违反任一条都会被 Python 校验拒绝渲染）：
1. enum 字段只能用白名单值，不能创新词
2. 每个字段的 what_kills_this_view 必填（一句话写"什么观察到了就证伪当前判断"）
3. 候选数=0 → 整个字段填 null，并在 session_summary 里说明原因
4. 旧时段叙事冻结，不可回头改；若昨天判断被今天打脸，必须在 session_summary 里直面误判 + 写纠错推演
5. 不可创造新归类/标签；用户业务严格术语：龙1/空龙1/反转空龙1/修复龙1/最增量/最缩量（最增量/最缩量全品种各仅 1 个）"""

SYSTEM_HEAD_A_POST = """顶层新增字段：
- strategy_outlook：7 子项；前 6 项（market_phase/trend_forecast/style_tone/attack_direction/
  retreat_direction/key_focus）由养家定调；risk_points 由炒家专项
- unique_anomaly_analysis：若全窗口存在"独特"标签品种，炒家写 200-500 字
  （结构对立面 + 跨期演变 + 资金意图）；无则 null
- macro_cycle_anchor：仅 is_weekend_close=true 时填（养家+炒家联合）；非周末 null
- ticker_audits：少数 ticker 升级为人格审 {code:{actual_vs_expected,auditor}}；其它由 Python
  量化代审兜底；auditor 不可填 "quant"（量化是 Python 的活）

预期审计 per persona（任务 2.2）：每个人格字段可选 prev_session_audit{actual_vs_expected, audit_note≤80字}
对照"上一时段 next_session_expect"做事后评判；五档：强超/超/符合/低/强低于预期。
无上一时段或 expect 为空 → 字段填 null。

行文：单字段 evidence ≤50 字，简单句优先，禁研报黑话。
每个人格字段含一个 free_analysis ≤200 字自由发挥段。
另外产出 ticker_analyses {code: 50-100 字点评}：每个分类挑 1-2 个最值得关注的品种写点评。"""

SYSTEM_HEAD_US_PRE = """你是美股权重股/ETF 量价分析的 AI 综合体。Python 已算完所有数字，你只负责"看数字说人话"。

铁律（违反任一条都会被 Python 校验拒绝渲染）：
1. enum 字段只能用白名单值
2. 每个字段的 what_kills_this_view 必填
3. 候选数=0 → 整字段 null + session_summary 说明
4. 旧叙事冻结，被打脸要直面误判 + 纠错推演
5. evidence 降级机制：跨资产/广度字段缺失时，按规则降低引用要求，但 LLM 必须在 evidence 末尾显式声明"数据缺失/暂缺/不可用\""""

SYSTEM_HEAD_US_POST = """行文：单字段 evidence ≤50 字，简单句优先。
每个人格字段含一个 free_analysis ≤200 字自由发挥段。
另产出 ticker_analyses {code: 50-100 字点评}：每个分类挑 1-2 个最值得关注品种写点评。"""


def _build_persona_section(market: Literal["A", "US"]) -> str:
    """从 config/personas.yaml 拼接"人格分工"段。读不到时退化为硬编码默认。

    输出格式（与历史 SYSTEM_HEAD 兼容）：
      人格分工（含扩职）：
      - <key>（<display_name>）：<scope>；<focus_block>
      - ...
    """
    try:
        from src.gui import config_io
        data = config_io.load_personas() or {}
    except Exception:
        data = {}

    market_data = data.get(market, {})
    lines = ["人格分工（含扩职）：" if market == "A" else "人格分工："]
    for key, p in market_data.items():
        name = (p or {}).get("display_name", key)
        scope = (p or {}).get("scope", "")
        focus = (p or {}).get("focus_block", "").strip()
        sep = "；" if scope and focus else ""
        lines.append(f"- {key}（{name}）：{scope}{sep}{focus}")
    return "\n".join(lines)


def build_system_head(market: Literal["A", "US"]) -> str:
    """组装完整 SYSTEM_HEAD = PRE + 人格段 + POST。"""
    if market == "A":
        return SYSTEM_HEAD_A_PRE + "\n\n" + _build_persona_section("A") + "\n\n" + SYSTEM_HEAD_A_POST
    return SYSTEM_HEAD_US_PRE + "\n\n" + _build_persona_section("US") + "\n\n" + SYSTEM_HEAD_US_POST


# 兼容旧 import（如果有第三方代码 from src.llm_prompt import SYSTEM_HEAD_A）
# 这两个常量在 personas.yaml 不存在时与硬编码一致。
SYSTEM_HEAD_A = build_system_head("A")
SYSTEM_HEAD_US = build_system_head("US")


def _history_block(history: list[dict], n: int = 20) -> str:
    """近 N 时段的 session_summary 串联。"""
    recent = history[-n:]
    lines = ["=== 历史上下文（近 {} 时段，旧→新；is_skeleton=true 表示 Python 模板生成 不是 LLM 判断） ===".format(len(recent))]
    for s in recent:
        nar = s.get("narrative") or {}
        summary = nar.get("session_summary") or "(无 summary)"
        flag = "[骨架]" if nar.get("is_skeleton") else "[LLM]"
        lines.append(f"  {flag} {s.get('label')}: {summary}")
    return "\n".join(lines)


def _current_panel_block(panel: dict, market: str) -> str:
    """当前 panel_breadth 摘要。"""
    return f"=== 当前盘面广度 ===\n{json.dumps(panel, ensure_ascii=False, indent=2)}"


def _current_tickers_block(tickers: list[dict], market: str) -> str:
    compressed = [_compress_ticker(t, market) for t in tickers]
    return ("=== 当前时段品种矩阵（短键，按分类聚合自行解读） ===\n"
            + json.dumps(compressed, ensure_ascii=False))


def _annotation_trail_block(history: list[dict], n: int = 5) -> str:
    """近 n 时段每只品种的批注轨迹（如果有）。"""
    recent = history[-n:]
    trails: dict[str, list[str]] = {}
    for s in recent:
        for t in s.get("tickers", []):
            ann = t.get("annotation")
            if not ann:
                continue
            code = t["code"]
            label = s["label"]
            color = ann.get("color", "")
            note = ann.get("note", "")
            trails.setdefault(code, []).append(f"[{label}] {color} {note}".strip())
    if not trails:
        return "=== 批注轨迹 === （无）"
    lines = ["=== 批注轨迹（最近 {} 时段，B 协作者标记的关注线索） ===".format(n)]
    for code, items in trails.items():
        lines.append(f"  {code}: " + " → ".join(items))
    return "\n".join(lines)


def _audit_context_block(history: list[dict]) -> str:
    """把"上一时段每个人格 next_session_expect"打包成预期审计的对照锚点。"""
    if not history:
        return "=== 预期审计对照 === （无上一时段，不做审计）"
    prev = history[-1]
    nar = prev.get("narrative") or {}
    if nar.get("is_skeleton") or not nar:
        return f"=== 预期审计对照 === （上一时段 {prev.get('label')} 为骨架/无 LLM 叙事，跳过审计）"
    lines = [f"=== 预期审计对照（上一时段 {prev.get('label')}，对照其 next_session_expect 做事后评判） ==="]
    for fname in ("yangjia_emotion_cycle", "zhaolaoge_liquidity_focus",
                  "fengliu_contrarian_check",
                  "druckenmiller_macro_check", "minervini_breadth_check",
                  "wyckoff_breakout_check", "weinstein_stage_check"):
        f = nar.get(fname)
        if f and f.get("next_session_expect"):
            lines.append(f"  [{fname}] expect: {f['next_session_expect']}")
    if len(lines) == 1:
        lines.append("  （上一时段所有人格字段均无 next_session_expect，跳过）")
    return "\n".join(lines)


TASK_BLOCK_EXTRA_TOP = """
顶层非人格字段 schema：
  strategy_outlook: {
    market_phase: enum["情绪修复","趋势主升","高位分歧","阴跌抵抗","其他"],
    trend_forecast: enum["上涨","震荡","下跌"],
    style_tone: enum["偏向进攻","偏向防守","混沌期"],
    attack_direction: "<资金主攻方向短句>",
    retreat_direction: "<资金出逃方向短句>",
    key_focus: ["<关注点1>", "<关注点2>", ...],
    risk_points: ["<风险点1 by 炒家>", ...]
  } 或 null
  unique_anomaly_analysis: "<200-500字 由炒家撰写>" 或 null
  macro_cycle_anchor: {
    asset_profile: "<一句话>",
    historical_anchor: {year, event, phase, brief},
    then_vs_now: {similarity, divergence},
    forward_strategy: {risks, opportunities}
  } 或 null（非周末必为 null）
  ticker_audits: {"<code>": {actual_vs_expected: enum 五档, auditor: enum["yangjia"|"zhaolaoge"|"fengliu"|"discipline"]}}

人格字段内的 prev_session_audit 子节（可选）：
  {actual_vs_expected: enum 五档, audit_note: "<≤80字 简述依据>"}

key_movers 子项 schema（赵老哥/冯柳/wyckoff/weinstein 必填 ≥2）：
  {sector: "<板块名>", phenomenon: "<量价异动>", motive: "<机构意图>", scenario: "<正反推演>"}"""


def _render_prompt_tpl(key: str, **ctx) -> str | None:
    """渲染 src/templates/prompt/<key>.j2 (优先) 或 <key>.j2.default。
    都不存在 → 返 None 让调用方走硬编码。
    """
    try:
        from src.gui.config_io import read_prompt_template
        from jinja2 import Template
        text, _ = read_prompt_template(key)
        return Template(text).render(**ctx)
    except Exception:
        return None


def _weekend_flag_block(target_session: dict) -> str:
    is_wk = bool(target_session.get("is_weekend_close"))
    rendered = _render_prompt_tpl("weekend_flag", is_weekend=is_wk)
    if rendered is not None:
        return rendered
    # 硬编码兜底（与 .default 等价）
    if is_wk:
        return ("=== 周末标志 ===\n"
                "is_weekend_close=true → macro_cycle_anchor 字段本时段必填"
                "（4 子段：asset_profile / historical_anchor / then_vs_now / forward_strategy）")
    return "=== 周末标志 === is_weekend_close=false → macro_cycle_anchor 填 null"


def _task_block(market: str, current_label: str) -> str:
    schema_text = _schema_text(market)
    rendered = _render_prompt_tpl(
        "task_block",
        current_label=current_label,
        schema_text=schema_text,
        extra_top=TASK_BLOCK_EXTRA_TOP,
    )
    if rendered is not None:
        return rendered
    # 硬编码兜底
    return (f"=== 任务 ===\n为当前时段 {current_label} 产出 narrative JSON，结构如下：\n\n"
            "{\n  \"is_skeleton\": false,\n  \"session_summary\": \"...\",\n  ...\n}\n\n"
            "只返回 JSON，不要解释。\n"
            f"{TASK_BLOCK_EXTRA_TOP}\n\n{schema_text}")


def build_prompt(market: Literal["A", "US"], target_session: dict,
                 history: list[dict] | None = None) -> str:
    """构造完整 prompt。
    target_session: 当前 session（含 tickers/panel）
    history: 历史 sessions（不含 target）
    """
    if history is None:
        history = []

    head = build_system_head(market)  # 每次重新拼接（personas.yaml 实时生效）
    parts = [
        head,
        "",
        _short_key_map_text(market),
        "",
        _history_block(history, n=20),
        "",
        _annotation_trail_block(history, n=5),
        "",
        _audit_context_block(history),
        "",
        _weekend_flag_block(target_session),
        "",
        _current_panel_block(target_session["panel"], market),
        "",
        _current_tickers_block(target_session["tickers"], market),
        "",
        _task_block(market, target_session["label"]),
    ]
    return "\n".join(parts)
