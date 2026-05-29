"""LLM prompt 构造（双市场双引擎）。

设计原则：
  - 系统说明（角色 + 铁律）
  - schema 描述（enum 白名单 + 必填项 + 降级规则）
  - 短键映射表（4.9.9 节，节省 token）
  - 三级历史记忆（远7段走势弧线 / 中5段象限分布 / 近级=预期审计对照）
  - 当前 session 完整数据（短键压缩）
  - 任务说明（"产出 JSON，字段如下"）

不直接调 API。输出 prompt 文本，用户复制到 Claude/Cursor 跑。
"""
from __future__ import annotations

import json
import os
from typing import Literal

import yaml

from src import llm_schema as schema
from src import thresholds_cfg as tcfg

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
    "vol_std_20": "vstd20",
    "rs_vs_benchmark": "rsb",
    "er60": "er60",
    "mdd60": "mdd60",
    "slope_seg": "slp",
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
        SHORT_KEYS["vol_std_20"]: round(f["vol_std_20"], 4) if f.get("vol_std_20") is not None else None,
        SHORT_KEYS["rs_vs_benchmark"]: round(f["rs_vs_benchmark"] * 100, 2) if f.get("rs_vs_benchmark") is not None else None,
        SHORT_KEYS["er60"]: f.get("er60"),
        SHORT_KEYS["mdd60"]: round(f["mdd60"] * 100, 2) if f.get("mdd60") is not None else None,
        SHORT_KEYS["slope_seg"]: (
            [round(x * 100, 2) for x in f["slope_seg"]] if f.get("slope_seg") else None
        ),
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
        ("vstd20=20日收益率标准差(小数)", "rsb=相对基准强度%(本品种-基准)"),
        ("er60=60日路径效率(0~1,越大越平滑)", "mdd60=60日最大回撤%(正数)"),
        ("slp=分段斜率%[远,中,近](60日切3段段收益率)",),
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
    from src.llm_schema import TOP_LEVEL_REQUIRED, TOP_LEVEL_OPTIONAL

    s = schema.get_schema(market)
    lines = [f"=== {market} 股双引擎 schema（你必须按此 JSON 结构返回） ==="]
    lines.append(f"\n【顶层必填】: {TOP_LEVEL_REQUIRED}")
    lines.append(f"  is_skeleton: 当前你写的时段永远为 false（true 仅在 Python backfill 时使用）")
    lines.append(f"【顶层可选】: {TOP_LEVEL_OPTIONAL}")
    lines.append(f"  strategy_outlook / unique_anomaly_analysis / macro_cycle_anchor 见下方独立 schema 块")
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

SYSTEM_HEAD_A_POST = """顶层新增字段（北京炒家人格已废弃，其职责并入养家）：
- strategy_outlook：7 子项全部由养家定调（market_phase/trend_forecast/style_tone/
  attack_direction/retreat_direction/key_focus/risk_points）
- unique_anomaly_analysis：若全窗口存在"独特"标签品种，养家写 ≥200 字 无上限
  （结构对立面 + 跨期演变 + 资金意图）；无则 null
- macro_cycle_anchor：仅 is_weekend_close=true 时填（养家独署）；非周末 null
- trading_discipline_review：每跨日候选品种一份纪律审（养家执行），discipline_pass=false
  默认降一档，rating_override 可破例
- ticker_audits：少数 ticker 升级为人格审 {code:{actual_vs_expected,auditor}}；其它由 Python
  量化代审兜底；auditor 不可填 "quant"（量化是 Python 的活）

预期审计 per persona（任务 2.2）：每个人格字段可选 prev_session_audit{actual_vs_expected, audit_note}
对照"上一时段 next_session_expect"做事后评判；五档：强超/超/符合/低/强低于预期。
无上一时段或 expect 为空 → 字段填 null。audit_note 按需写够，无字数上限。

行文：evidence 建议精简（一两句话突出 alias 关键词 + 数字），其它叙述段无上限。
每个人格字段含一个 free_analysis 自由发挥段（无字数上限，按内容密度而非凑字数）。
另外产出 ticker_analyses {code: ≥30 字点评 无上限}：每个分类挑 1-2 个最值得关注的品种写点评。

装载契约：养家的心法落到上述 JSON 字段的具体对应，见单独下发的《养家·装载契约》翻译表文档；
按该文档把影子分身式的分析装入对应字段（养家心语并入 free_analysis 末尾）。
忽略灵魂文档里"请给出监控池数据/初始化确认"等对话式收尾——真实数据即本 prompt。"""

SYSTEM_HEAD_US_PRE = """你是美股权重股/ETF 量价分析的 AI 综合体。Python 已算完所有数字，你只负责"看数字说人话"。

铁律（违反任一条都会被 Python 校验拒绝渲染）：
1. enum 字段只能用白名单值
2. 每个字段的 what_kills_this_view 必填
3. 候选数=0 → 整字段 null + session_summary 说明
4. 旧叙事冻结，被打脸要直面误判 + 纠错推演
5. evidence 降级机制：跨资产/广度字段缺失时，按规则降低引用要求，但 LLM 必须在 evidence 末尾显式声明"数据缺失/暂缺/不可用\""""

SYSTEM_HEAD_US_POST = """行文：evidence 建议精简（一两句话突出 alias 关键词 + 数字）；其它叙述段无上限。
每个人格字段含一个 free_analysis 自由发挥段（无字数上限，按内容密度写）。
另产出 ticker_analyses {code: ≥30 字点评 无上限}：每个分类挑 1-2 个最值得关注品种写点评。"""


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
        skill_ref = (p or {}).get("skill_ref", "")
        sep = "；" if scope and focus else ""
        line = f"- {key}（{name}）：{scope}{sep}{focus}"
        if skill_ref:
            line += f"\n  〔心法见单独下发的灵魂文档《{skill_ref}》+《养家·装载契约》翻译表〕"
        lines.append(line)
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


# ---------------------------------------------------------------------------
# 三级历史记忆（C 批增量，替换原 _history_block）
# ---------------------------------------------------------------------------

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cross_asset_codes_cache: dict[str, set] = {}


def _get_cross_asset_codes(market: str) -> set:
    """从 pool yaml 读取有 role 的跨资产代表代码（缓存）。用于过滤箭头计算。"""
    if market in _cross_asset_codes_cache:
        return _cross_asset_codes_cache[market]
    pool_file = "pool_a.yaml" if market == "A" else "pool_us.yaml"
    pool_path = os.path.join(_ROOT, "config", pool_file)
    try:
        with open(pool_path, encoding="utf-8") as f:
            pool = yaml.safe_load(f) or {}
        codes = {e["code"] for e in pool.get("etfs", []) if e.get("role")}
    except Exception:
        codes = set()
    _cross_asset_codes_cache[market] = codes
    return codes


def _session_arrow(session: dict, market: str) -> str:
    """↗ / → / ↘：按非跨资产品种广度方向。

    跨资产代表（treasury/gold/oil/vix/btc/eth/dollar）排除在外——它们的涨跌
    是跨资产信号，不是大盘氛围，算进去会污染箭头方向。
    """
    flat_ratio = tcfg.get("ARROW_FLAT_RATIO", 0.15)
    cross = _get_cross_asset_codes(market)
    up = down = 0
    for t in session.get("tickers") or []:
        if t.get("code") in cross:
            continue
        pct = t.get("today_pct")
        if pct is None:
            continue
        if pct > 0:
            up += 1
        elif pct < 0:
            down += 1
    total = up + down
    if total == 0:
        return "→"
    ratio = (up - down) / total
    if ratio > flat_ratio:
        return "↗"
    if ratio < -flat_ratio:
        return "↘"
    return "→"


# --------------- 中级趋势标签规则集（可扩展）---------------
# 每条规则签名：(sessions_window: list[dict], i: int) -> list[str]
# 返回针对 sessions_window[i] 这一时段的标签列表（空列表=无触发）。
# 新增规则：在 _MID_LABEL_RULES 末尾 append 一个函数即可，无需改调用方。

_CATS = ["持续强化", "反包修复", "强反转", "连续杀跌"]


def _rule_consec_rise(window: list[dict], i: int) -> list[str]:
    """某象限 count 连续 ≥ N 时段递增 → 'XX象限N时段连增'。"""
    consec_min = tcfg.get("CAT_CONSEC_RISE_MIN", 3)
    tags = []
    for cat in _CATS:
        count = 0
        for j in range(i, 0, -1):
            curr = ((window[j].get("panel") or {}).get("category_distribution") or {})
            prev = ((window[j - 1].get("panel") or {}).get("category_distribution") or {})
            if curr.get(cat, 0) > prev.get(cat, 0):
                count += 1
            else:
                break
        if count >= consec_min:
            tags.append(f"{cat}{count}时段连增")
    return tags


def _rule_dominant_pct(window: list[dict], i: int) -> list[str]:
    """某象限占当时段全池比例 ≥ 阈值 → 'XX象限占比偏高'。"""
    threshold = tcfg.get("CAT_DOMINANT_PCT", 0.40)
    cat_dist = ((window[i].get("panel") or {}).get("category_distribution") or {})
    total = sum(cat_dist.values()) or 1
    return [f"{cat}占比偏高" for cat in _CATS if cat_dist.get(cat, 0) / total >= threshold]


# 规则注册表 —— 未来在此追加新规则函数
_MID_LABEL_RULES = [_rule_consec_rise, _rule_dominant_pct]


def _far_memory_block(history: list[dict], market: str) -> str:
    """远级：近 FAR_MEMORY_SESSIONS 时段走势弧线，含日期 + 方向箭头 + session_summary。

    骨架段 (is_skeleton=true) 照常出现，箭头照打，summary 显示骨架说明。
    history 不足时显示实际数量，不报错。
    """
    n = tcfg.get("FAR_MEMORY_SESSIONS", 7)
    window = history[-n:] if len(history) >= n else list(history)
    if not window:
        return "【远级 · 走势弧线】（无历史数据）"

    total = len(window)
    lines = [f"【远级 · 走势弧线（近{total}时段，旧→新；骨架=Python模板/无LLM判断）】"]
    for i, session in enumerate(window):
        ago = total - i
        ago_label = "上一段" if ago == 1 else f"{ago}段前"
        label = session.get("label", "?")
        arrow = _session_arrow(session, market)
        nar = session.get("narrative") or {}
        is_skel = nar.get("is_skeleton", False)
        summary = nar.get("session_summary") or ""
        if not summary:
            summary_text = "（骨架，无叙事）" if is_skel else "（无 summary）"
        else:
            summary_text = summary
        lines.append(f"  [{ago_label}] {label} {arrow} : {summary_text}")
    return "\n".join(lines)


def _mid_memory_block(history: list[dict], market: str) -> str:
    """中级：近 MID_MEMORY_SESSIONS 时段象限分布 + Python 趋势标签。

    标签由 _MID_LABEL_RULES 规则集生成（确定性统计，非 LLM 生成）。
    没有触发的行不加 → 注释，减少噪音。
    history 不足时显示实际数量，不报错。
    """
    n = tcfg.get("MID_MEMORY_SESSIONS", 5)
    window = history[-n:] if len(history) >= n else list(history)
    if not window:
        return "【中级 · 象限分布】（无历史数据）"

    lines = [f"【中级 · 象限分布（近{len(window)}时段，旧→新）】"]
    for i, session in enumerate(window):
        cat_dist = ((session.get("panel") or {}).get("category_distribution") or {})
        dist_str = "/".join(f"{cat}{cat_dist.get(cat, 0)}" for cat in _CATS)
        tags: list[str] = []
        for rule in _MID_LABEL_RULES:
            tags.extend(rule(window, i))
        row = f"  {session.get('label', '?')}: {dist_str}"
        if tags:
            row += f" → {'，'.join(tags)}"
        lines.append(row)
    return "\n".join(lines)


def _threelevel_memory_block(history: list[dict], market: str) -> str:
    """三级历史记忆（替换原 _history_block）。

    远级：走势弧线（方向箭头 + session_summary）
    中级：象限分布 + Python 趋势标签
    近级：指向下方 _audit_context_block（它已独立输出，此处仅标注位置）
    """
    far = _far_memory_block(history, market)
    mid = _mid_memory_block(history, market)
    near_note = "【近级 · 上一时段预期对账见下方「预期审计对照」节】"
    return "\n\n".join([
        "=== 三级历史记忆（远→中→近，越近越具体；对抗近因偏误，建立时间弧线感） ===",
        far,
        mid,
        near_note,
    ])


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
    market_phase: enum["艳阳高照","风暴来袭","阴雨绵绵","转折临界"],
    trend_forecast: enum["上涨","震荡","下跌"],
    style_tone: enum["全力拼取","离场观望","试错跟随"],
    attack_direction: "<资金主攻方向短句>",
    retreat_direction: "<资金出逃方向短句>",
    key_focus: ["<关注点1>", "<关注点2>", ...],
    risk_points: ["<风险点1 by 炒家>", ...]
  } 或 null
  unique_anomaly_analysis: "<≥200 字 无上限 由炒家撰写>" 或 null
  macro_cycle_anchor: {
    asset_profile: "<一句话>",
    historical_anchor: {year, event, phase, brief},
    then_vs_now: {similarity, divergence},
    forward_strategy: {risks, opportunities}
  } 或 null（非周末必为 null）
  ticker_audits: {"<code>": {actual_vs_expected: enum 五档, auditor: enum["yangjia"|"zhaolaoge"|"fengliu"|"discipline"]}}

人格字段内的 prev_session_audit 子节（可选）：
  {actual_vs_expected: enum 五档, audit_note: "<简述依据 无字数上限>"}

key_movers 子项 schema（赵老哥/冯柳/wyckoff/weinstein 必填 ≥2）：
  {sector: "<板块名>", phenomenon: "<量价异动>", motive: "<机构意图>", scenario: "<正反推演>"}

quadrant_summaries: {持续强化, 反包修复, 强反转, 连续杀跌} → 每象限一段小结（每段 ≥40 字，无上限）
  内容覆盖：龙头(代码+中文名) / 共性特征(量价/均线/分位) / 异动隐忧 / 给综合轮的一句话
  纯文本 + `**异常**` 加粗；禁 markdown 标题/列表/表格
  候选数=0 的象限对应 key 缺省或填 null
group_qualitative: {bull_group, bear_group} → 多头组(持续强化+反包修复)/空头组(强反转+连续杀跌)整体定性
  每段 ≥20 字，本势力组整体强弱/资金意图的一句过渡视角；候选数=0 → null"""


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
        _threelevel_memory_block(history, market),
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


# ===========================================================================
# D 批：分段投喂（同对话多轮）—— 默认模式不受影响，纯叠加路径
# ===========================================================================

# 象限→PART 映射（与 src.classify 的封闭 enum 严格对齐）
PART1_CATS = ("持续强化", "反包修复")  # 多头组
PART2_CATS = ("强反转", "连续杀跌")    # 空头组


def _quadrant_tickers_block(tickers: list[dict], cats: tuple, market: str,
                            group_label: str) -> str:
    """筛出指定象限的品种并按短键压缩。空集时输出明确提示。"""
    matched = [t for t in tickers if t.get("category") in cats]
    if not matched:
        return (f"=== 本组品种矩阵（{group_label}：{' + '.join(cats)}） ===\n"
                f"（本组本时段无候选品种 —— PART3 收单 JSON 时，相关人格字段按候选数=0 规则填 null）")
    compressed = [_compress_ticker(t, market) for t in matched]
    return (f"=== 本组品种矩阵（{group_label}：{' + '.join(cats)}，短键） ===\n"
            + json.dumps(compressed, ensure_ascii=False))


_QUADRANT_TEMPLATE = """【XX象限 · 小结】
- 龙头（最强1-2只）：____（代码+中文名，如 SH512760(芯片ETF)）
- 共性特征：____（量价配合？是否远离均线？分位高低？）
- 异动/隐忧：____（需警惕的点）
- 给综合轮的一句话：____（本象限对全局的意义）"""


def _part1_task_instructions() -> str:
    cats = " + ".join(PART1_CATS)
    return f"""=== PART 1/3 任务（多头组：{cats}） ===
本轮目标：为多头组的两个象限**分别**产出小结 + 单品种点评。**不要现在写最终 narrative JSON**——JSON 在 PART 3 统一产出。

输出结构（纯文本，按顺序）：

1. 持续强化 · 小结（用下方模板，4 行）
2. 反包修复 · 小结（同模板）
3. 【多头组整体定性】 一句话，本势力组当前的整体强弱/资金意图
4. 【单品种点评】 本组挑 1-2 个/象限（共 2-4 只）最值得关注的品种，每只 30-120 字
   - 格式：`<code>(<中文名>): <点评>`，与最终 ticker_analyses 字段直接对齐，PART 3 会原样吸收

象限小结模板（每个象限独立用一次，**不许合并写**）：
{_QUADRANT_TEMPLATE}

写作规则：
- 纯文本 + `**异常**` 加粗，禁 markdown 标题/列表/表格
- 言简意赅，禁研报黑话
- 量能定性用：天量/爆量/放量/平量/缩量/地量
- 动能判定：放涨增强 / 放跌杀跌 / 缩涨惜售 / 缩跌阴跌
- 本组空 → 直接写"本组本时段无候选品种"，跳过模板"""


def _part2_task_instructions() -> str:
    cats = " + ".join(PART2_CATS)
    return f"""=== PART 2/3 任务（空头组：{cats}） ===
承接 PART 1 的多头组分析。**全局背景（panel/三级记忆/人设/审计/周末标志）已在 PART 1 给完，不再重复**。

输出结构（与 PART 1 同形态，4 节）：

1. 强反转 · 小结（模板 4 行）
2. 连续杀跌 · 小结（模板 4 行）
3. 【空头组整体定性】 一句话，本势力组当前的整体强弱/资金意图
4. 【单品种点评】 本组挑 1-2 个/象限（共 2-4 只）最值得关注的品种，30-120 字/只
   - 格式：`<code>(<中文名>): <点评>`

象限小结模板（每个象限独立用一次，**不许合并写**）：
{_QUADRANT_TEMPLATE}

写作规则同 PART 1。本组空 → 写"本组本时段无候选品种"。"""


def _part3_task_instructions(market: str, current_label: str) -> str:
    schema_text = _schema_text(market)
    cross_quadrant_brief = """=== PART 3/3 任务（综合 + 最终 JSON） ===
**本轮不喂新品种数据**。前两轮已完成 4 个象限的小结 + 单品种点评，全部留在本对话上下文。本轮做两件事：

【1. 跨象限综合分析】（不复述个股，只做下面这些 PART 1/2 没做的事）：
- 资金在 4 象限之间的流动方向（如：从持续强化撤出 → 转向反包修复 = 高低切轮动）
- 解读 `category_distribution` 的数量分布变化（如：强反转象限突然增多 = 见顶预警；连续杀跌占比高位 = 恐慌见底信号）
- 全局定性：当前是哪个市场阶段，整体风偏
- 承接近级记忆（上方"预期审计对照"节）做昨日预期对账
- 风险点 by 炒家专项

【2. 装载完整 narrative JSON】（schema 见下方，**最终落库的就是这一份**）：
- 把前两轮 4 个象限小结的内容，**原样或微调后**装进 `quadrant_summaries` 字段（每象限一段 ≥40 字）；同时也吸收到对应人格字段的 evidence / free_analysis / key_movers 里
- 把前两轮【多头组整体定性】/【空头组整体定性】装进 `group_qualitative.bull_group` / `bear_group`（每段 ≥20 字）
- 把前两轮【单品种点评】**原样**或微调后放入 `ticker_analyses` 字段
- 多头组整体定性 → 可作为 zhaolaoge_liquidity_focus 的素材（A 股）或对应人格（美股按职责映射）
- 空头组整体定性 → 可作为 fengliu_contrarian_check 的素材（A 股）或对应人格
- yangjia_emotion_cycle（A）/druckenmiller、minervini（US）是**全局视角**，本轮直接写
- strategy_outlook / unique_anomaly_analysis / macro_cycle_anchor / ticker_audits / session_summary 全部在本轮产出
- 候选数=0 的象限对应人格字段填 null，session_summary 说明

**只返回 JSON，不要解释、不要 markdown 代码块包裹**。"""
    return cross_quadrant_brief + "\n\n" + TASK_BLOCK_EXTRA_TOP + "\n\n" + schema_text + \
           f"\n\n当前时段 label：{current_label}"


def build_segmented_prompts(market: Literal["A", "US"], target_session: dict,
                            history: list[dict] | None = None) -> list[str]:
    """分段投喂模式：产 3 段 prompt，用户在同一对话依次粘贴。

    返回 list 长度恒为 3：[PART1, PART2, PART3]
    - PART1：全局背景（与默认模式同前 6 块）+ 多头组 tickers + PART1 任务
    - PART2：极简衔接 preamble + 空头组 tickers + PART2 任务
    - PART3：极简衔接 preamble + 综合任务 + 完整 schema

    收单：fill_narrative 仍只收一份 JSON（PART3 产出）。default mode 不变。
    """
    if history is None:
        history = []

    head = build_system_head(market)
    tickers = target_session["tickers"]

    # PART 1：全部全局背景 + 多头组 tickers + 任务
    part1 = "\n".join([
        f"=== PART 1/3 — 多头组（{' + '.join(PART1_CATS)}） ===",
        "你将在同一对话里依次收到 3 段输入（PART 1/2/3）。**全局背景只在 PART 1 给一次**。",
        "",
        head,
        "",
        _short_key_map_text(market),
        "",
        _threelevel_memory_block(history, market),
        "",
        _annotation_trail_block(history, n=5),
        "",
        _audit_context_block(history),
        "",
        _weekend_flag_block(target_session),
        "",
        _current_panel_block(target_session["panel"], market),
        "",
        _quadrant_tickers_block(tickers, PART1_CATS, market, "多头组"),
        "",
        _part1_task_instructions(),
    ])

    # PART 2：极简衔接 + 空头组 tickers + 任务
    part2 = "\n".join([
        f"=== PART 2/3 — 空头组（{' + '.join(PART2_CATS)}） ===",
        "承接 PART 1。全局背景沿用，不再重复。",
        "",
        _quadrant_tickers_block(tickers, PART2_CATS, market, "空头组"),
        "",
        _part2_task_instructions(),
    ])

    # PART 3：极简衔接 + 综合任务（无新 tickers 数据）
    part3 = "\n".join([
        "=== PART 3/3 — 综合 + 最终 JSON ===",
        "承接 PART 1/2。**本轮不喂新品种数据**，前两轮 4 象限小结 + 单品种点评全部留在对话上下文里。",
        "",
        _part3_task_instructions(market, target_session["label"]),
    ])

    return [part1, part2, part3]
