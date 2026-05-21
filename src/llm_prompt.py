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
    """生成 schema 说明文本。"""
    s = schema.get_schema(market)
    lines = [f"=== {market} 股双引擎 schema（你必须按此 JSON 结构返回） ==="]
    for fname, spec in s.items():
        lines.append(f"\n【{fname}】scope={spec['scope']}; nullable={spec.get('nullable', False)}")
        lines.append(f"  必填: {spec['required']}")
        for ek, ev in spec.get("enums", {}).items():
            lines.append(f"  enum {ek}: {ev}")
        if "evidence_min_dims" in spec:
            lines.append(f"  evidence 至少引用 {spec['evidence_min_dims']} 个跨资产维度: {spec['cross_asset_dims']}")
        if "evidence_min_breadth_fields" in spec:
            lines.append(f"  evidence 至少引用 {spec['evidence_min_breadth_fields']} 个广度字段: {spec['breadth_fields']}")
    return "\n".join(lines)


SYSTEM_HEAD_A = """你是 A 股板块量价分析的 AI 综合体。Python 已算完所有数字，你只负责"看数字说人话"。

铁律（违反任一条都会被 Python 校验拒绝渲染）：
1. enum 字段只能用白名单值，不能创新词
2. 每个字段的 what_kills_this_view 必填（一句话写"什么观察到了就证伪当前判断"）
3. 候选数=0 → 整个字段填 null，并在 session_summary 里说明原因
4. 旧时段叙事冻结，不可回头改；若昨天判断被今天打脸，必须在 session_summary 里直面误判 + 写纠错推演
5. 不可创造新归类/标签；用户业务严格术语：龙1/空龙1/反转空龙1/修复龙1/最增量/最缩量（最增量/最缩量全品种各仅 1 个）

人格分工：
- yangjia_emotion_cycle（炒股养家 情绪周期）：全局 1 份
- zhaolaoge_liquidity_focus（赵老哥 流动性）：仅持续强化+反包修复
- fengliu_contrarian_check（冯柳 逆向赔率）：仅强反转+连续杀跌
- trading_discipline_review（北京炒家/退学炒股 纪律）：每跨日候选品种一份

行文：单字段 evidence ≤50 字，简单句优先，禁研报黑话。
每个人格字段含一个 free_analysis ≤200 字自由发挥段：展开你对此分类/全局的判断。
另外产出 ticker_analyses {code: 50-100 字点评}：每个分类挑 1-2 个最值得关注的品种写点评，其它不写。"""

SYSTEM_HEAD_US = """你是美股权重股/ETF 量价分析的 AI 综合体。Python 已算完所有数字，你只负责"看数字说人话"。

铁律（违反任一条都会被 Python 校验拒绝渲染）：
1. enum 字段只能用白名单值
2. 每个字段的 what_kills_this_view 必填
3. 候选数=0 → 整字段 null + session_summary 说明
4. 旧叙事冻结，被打脸要直面误判 + 纠错推演
5. evidence 降级机制：跨资产/广度字段缺失时，按规则降低引用要求，但 LLM 必须在 evidence 末尾显式声明"数据缺失/暂缺/不可用"

人格分工：
- druckenmiller_macro_check（德鲁肯米勒 宏观）：全局 1 份
- minervini_breadth_check（米奈尔维尼 广度）：全局 1 份
- wyckoff_breakout_check（威科夫 突破）：仅持续强化+反包修复
- weinstein_stage_check（温斯坦 阶段）：仅强反转+连续杀跌
- trading_discipline_review（纪律共用）：每跨日候选品种一份

行文：单字段 evidence ≤50 字，简单句优先。
每个人格字段含一个 free_analysis ≤200 字自由发挥段。
另产出 ticker_analyses {code: 50-100 字点评}：每个分类挑 1-2 个最值得关注品种写点评。"""


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


def _task_block(market: str, current_label: str) -> str:
    schema_text = _schema_text(market)
    return f"""=== 任务 ===
为当前时段 {current_label} 产出 narrative JSON，结构如下：

{{
  "is_skeleton": false,
  "session_summary": "<~100字：风格判断 + 主线锚定 + 预期推演 + 风险提示；若昨判被打脸则先写纠错>",
  "ticker_analyses": {{
    "<code>": "<50-100字：该品种值得关注的原因、量价信号、应对思路>",
    ...每个分类挑 1-2 个重点品种
  }},
  ...各人格字段（含 free_analysis ≤200 字，见下方 schema）
}}

只返回 JSON，不要解释。

{schema_text}"""


def build_prompt(market: Literal["A", "US"], target_session: dict,
                 history: list[dict] | None = None) -> str:
    """构造完整 prompt。
    target_session: 当前 session（含 tickers/panel）
    history: 历史 sessions（不含 target）
    """
    if history is None:
        history = []

    head = SYSTEM_HEAD_A if market == "A" else SYSTEM_HEAD_US
    parts = [
        head,
        "",
        _short_key_map_text(market),
        "",
        _history_block(history, n=20),
        "",
        _annotation_trail_block(history, n=5),
        "",
        _current_panel_block(target_session["panel"], market),
        "",
        _current_tickers_block(target_session["tickers"], market),
        "",
        _task_block(market, target_session["label"]),
    ]
    return "\n".join(parts)
