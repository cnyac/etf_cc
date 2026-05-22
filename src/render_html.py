"""HTML 渲染入口。

铁律（CLAUDE.md "HTML 报告"）：
  - 单文件自包含（CSS/JS/数据全内联）
  - 数据嵌入 <script id="snapshot"> 和 <script id="annotations">
  - 视觉规范固化在常量里（颜色 / 字体 / 列结构）
  - 渲染只读：不重新计算因子/归类/panel

入口：
  python -m src.render_html --market A --label 2026-05-20-收
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Literal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src import window as win
from src import color_palette

sys.path.insert(0, r"D:\git\auto prtsc")


TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
REPORTS_DIR = os.path.join(ROOT, "data", "reports")
MARKET_LABEL = {"A": "A 股", "US": "美股"}

# 字段名英→中翻译（模板里 {{ field_label_cn.get(k, k) }} 查表，未命中显示原英文）
FIELD_LABEL_CN = {
    # 通用
    "evidence": "依据",
    "next_session_expect": "下一时段预期",
    "what_kills_this_view": "证伪条件",
    "free_analysis": "自由分析",
    "panorama_text": "全景图",
    "cross_validation_text": "交叉验证",
    "key_movers": "关键异动板块",
    "prev_session_audit": "前一时段审计",
    "actual_vs_expected": "实际 vs 预期",
    "audit_note": "审计备注",
    "auditor": "审计人",
    # yangjia (A)
    "stage": "情绪阶段",
    "intensity": "强度",
    # zhaolaoge / fengliu / wyckoff / weinstein  key_movers 子项
    "sector": "板块",
    "phenomenon": "量价异动",
    "motive": "机构意图",
    "scenario": "推演",
    # druckenmiller (US)
    "macro_regime": "宏观格局",
    "key_signal": "关键信号",
    # minervini (US)
    "breadth_state": "广度状态",
    "key_metric_focus": "关键指标聚焦",
    "divergence_warning": "背离警示",
    # wyckoff
    "wyckoff_phase": "Wyckoff 阶段",
    "vol_price_quality": "量价质量",
    "anchor_tickers": "锚定品种",
    "follow_strategy": "跟随策略",
    # weinstein
    "weinstein_stage": "Weinstein 阶段",
    "ma_relation": "MA 关系",
    "entry_opportunity": "建仓机会",
    # discipline
    "code": "代码",
    "logic_hardness": "逻辑硬度",
    "risk_reward_ratio": "盈亏比",
    "discipline_pass": "纪律通过",
    "review_note": "复盘备注",
    "rating_override": "评级覆盖",
    "keep_rating": "保留评级",
    "reason": "理由",
    # strategy_outlook
    "market_phase": "市场阶段",
    "trend_forecast": "趋势预判",
    "style_tone": "风格定调",
    "attack_direction": "主攻方向",
    "retreat_direction": "出逃方向",
    "key_focus": "核心关注",
    "risk_points": "风险点",
    # macro_cycle_anchor
    "asset_profile": "资产图谱",
    "historical_anchor": "历史锚点",
    "then_vs_now": "古今对比",
    "forward_strategy": "前瞻策略",
    "year": "年份",
    "event": "事件",
    "phase": "阶段",
    "brief": "简述",
    "similarity": "相似点",
    "divergence": "差异点",
    "risks": "风险",
    "opportunities": "机会",
}

# panel / cross_asset / breadth 字段中文（用于 §0 §1 显示）
CROSS_ASSET_LABEL_CN = {
    "treasury_10y": "10 年期国债",
    "treasury_30y": "30 年期国债",
    "dollar":       "美元指数",
    "gold":         "黄金",
    "oil":          "原油",
    "vix":          "VIX 恐慌指数",
    "btc":          "比特币",
    "eth":          "以太坊",
}

CROSS_ASSET_DIR_CN = {
    "up":   "上涨",
    "down": "下跌",
    "flat": "持平",
    None:   "—",
}

PANEL_FIELD_LABEL_CN = {
    "above_ma150_count":    "站上 30 周均线品种数",
    "spy_iwm_divergence":   "大小盘分化 (SPY-IWM)",
    "new_high_count_20d":   "20 日新高数",
    "new_low_count_20d":    "20 日新低数",
    "up_count":             "上涨家数",
    "down_count":           "下跌家数",
    "flat_count":           "持平家数",
    "strong_up_count":      "强势上涨家数 (>+2%)",
    "strong_down_count":    "强势下跌家数 (<-2%)",
    "vol_expansion_count":  "放量品种数",
    "vol_contraction_count": "缩量品种数",
    "breadth_alert":        "极值共振预警",
}


def _pct_fmt(v):
    if v is None:
        return "—"
    return f"{v * 100:+.2f}%"


def _pct_class(v):
    if v is None or v == 0:
        return "flat"
    return "up" if v > 0 else "down"


def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=False,
        lstrip_blocks=False,
    )
    env.globals["pct_fmt"] = _pct_fmt
    env.globals["pct_class"] = _pct_class
    env.globals["field_label_cn"] = FIELD_LABEL_CN
    env.globals["cross_asset_label_cn"] = CROSS_ASSET_LABEL_CN
    env.globals["cross_asset_dir_cn"] = CROSS_ASSET_DIR_CN
    env.globals["panel_field_label_cn"] = PANEL_FIELD_LABEL_CN
    return env


def _load_spark_closes(market: str, codes: list[str],
                       trade_date: str | None) -> dict[str, list[float]]:
    """从 auto-prtsc 拉每只品种近 30 个交易日的真实收盘价。
    返回 {code: [close, ...]}（不足 5 个点的返空列表）。
    """
    try:
        import etf_data_api as api
        import pandas as pd
    except Exception as e:
        print(f"[render] 无法加载 etf_data_api，sparkline 退化为空: {e}")
        return {c: [] for c in codes}

    if not trade_date:
        return {c: [] for c in codes}
    end_ts = pd.Timestamp(trade_date)
    start_ts = end_ts - pd.Timedelta(days=50)
    start = start_ts.strftime("%Y-%m-%d")
    end = end_ts.strftime("%Y-%m-%d")

    fetch = api.get_a_etf_ohlcv if market == "A" else api.get_us_ohlcv
    df = fetch(codes, start, end)
    out: dict[str, list[float]] = {}
    if df.empty:
        return {c: [] for c in codes}
    for code in codes:
        sub = df[df["code"] == code].sort_values("date")
        closes = sub["close"].tail(30).tolist()
        out[code] = closes if len(closes) >= 5 else []
    return out


_VOLUME_ONLY_TAGS = {"最增量", "最缩量"}


def _is_volume_only_feature(feature: str) -> bool:
    """feature 是否只由 最增量/最缩量 组成（无其它位置/特征标签）。"""
    if not feature:
        return True
    tags = {t.strip() for t in feature.split("，") if t.strip()}
    return bool(tags) and tags.issubset(_VOLUME_ONLY_TAGS)


def _pick_tracking_codes(session: dict, history: list[dict] | None = None,
                         max_n: int = 12) -> list[str]:
    """§4 跨日追踪表提取规则（任务 2.3 对齐）：
      - 上一时段（"昨日收盘"）feature 含非纯最增/缩标签的品种（基础名单）
      - 独特品种（feature 含"独特"，全时段窗口扫）
      - 兜底：若不足 max_n，按 |pct_normalized| / 量异常补足当前 session 品种

    history 为 None 或空时退化为只看当前 session（兼容首次窗口）。
    """
    picked: list[str] = []
    seen: set[str] = set()

    def _add(code: str) -> None:
        if code and code not in seen:
            picked.append(code); seen.add(code)

    # 基础名单：上一时段有非纯最增/缩标签
    prev = (history or [])[-1] if history else None
    if prev:
        for t in prev.get("tickers", []):
            if t.get("feature") and not _is_volume_only_feature(t["feature"]):
                _add(t["code"])

    # 独特品种：全窗口扫（含当前）
    all_sessions = (history or []) + [session]
    for s in all_sessions:
        for t in s.get("tickers", []):
            if "独特" in (t.get("feature") or ""):
                _add(t["code"])

    # 兜底：按 |pct_normalized| / 量异常补足
    if len(picked) < max_n:
        scored = []
        for t in session.get("tickers", []):
            if t["code"] in seen:
                continue
            score = 0
            f = t.get("factors") or {}
            pn = f.get("pct_normalized")
            if pn is not None:
                score += abs(pn) * 3
            vr = f.get("vol_ratio_20")
            if vr is not None and (vr > 1.5 or vr < 0.7):
                score += 2
            scored.append((score, t["code"]))
        scored.sort(key=lambda x: -x[0])
        for _, code in scored:
            if len(picked) >= max_n:
                break
            _add(code)

    return picked[:max_n]


def _pick_matrix_codes(session: dict, history: list[dict] | None = None,
                       max_n: int = 15) -> list[str]:
    """§5 矩阵：跨日的扩到 15 个。复用 _pick_tracking_codes 逻辑放宽。"""
    return _pick_tracking_codes(session, history, max_n)


def _short_label(label: str) -> str:
    """label → 紧凑显示：A 股 2026-05-20-收 → 05-20 收；US 2026-05-20 → 05-20"""
    parts = (label or "").split("-")
    if len(parts) >= 4:
        return f"{parts[1]}-{parts[2]} {parts[3]}"
    if len(parts) >= 3:
        return f"{parts[1]}-{parts[2]}"
    return label or ""


def _build_groups(target: dict, history: list[dict]) -> list[dict]:
    """为 §3 三行渲染构造品种组：每个 group = 当前 session 的 ticker + 它在
    history[-2:] 同 code 的历史行（按时间升序，最多 3 行）。

    annotation_color 取自当前 session 的 ticker.annotation（B 在最新报告里批注，
    染该品种所有时段行）。"""
    recent = (history or [])[-2:] + [target]
    groups = []
    for t in target.get("tickers", []):
        code = t["code"]
        ann = t.get("annotation") or {}
        g = {
            "code": code,
            "name": t.get("name"),
            "category": t.get("category"),
            "annotation_color": ann.get("color"),
            "annotation_note": ann.get("note"),
            "rows": [],
        }
        for sess in recent:
            for ts in sess.get("tickers", []):
                if ts["code"] == code:
                    g["rows"].append({
                        "label_short": _short_label(sess.get("label", "")),
                        "today_pct": ts.get("today_pct"),
                        "yest_pct": ts.get("yest_pct"),
                        "pct_diff": ts.get("pct_diff"),
                        "factors": ts.get("factors"),
                        "feature": ts.get("feature"),
                        "new_high_20d": ts.get("new_high_20d"),
                        "new_low_20d": ts.get("new_low_20d"),
                        "analysis": ts.get("analysis"),
                        "audit": ts.get("audit"),  # 阶段 B 填入
                    })
                    break
        groups.append(g)
    return groups


def _bucket_groups_by_category(groups: list[dict]) -> dict[str, list[dict]]:
    buckets = {"持续强化": [], "反包修复": [], "强反转": [], "连续杀跌": []}
    for g in groups:
        cat = g.get("category")
        if cat in buckets:
            buckets[cat].append(g)
    # 按 current（最后一行）的 pct_diff 降序排
    for cat in buckets:
        buckets[cat].sort(
            key=lambda g: (g["rows"][-1].get("pct_diff") if g["rows"] else 0) or 0,
            reverse=True)
    return buckets


def render(market: Literal["A", "US"], label: str) -> str:
    """渲染指定 label 的 HTML，写入文件并返回路径。"""
    data = win.load(market)
    target = next((s for s in data["sessions"] if s["label"] == label), None)
    if target is None:
        # 回退：从 snapshot 归档读取
        snap_fp = os.path.join(win.SNAPSHOT_DIR, market.lower(), f"{label}.json")
        if not os.path.exists(snap_fp):
            raise FileNotFoundError(f"找不到 session：{market}/{label}")
        import json
        with open(snap_fp, "r", encoding="utf-8") as f:
            target = json.load(f)
        history = data["sessions"]
    else:
        history = [s for s in data["sessions"] if s["label"] != label]

    name_map = {t["code"]: t.get("name", t["code"]) for t in target["tickers"]}
    groups = _build_groups(target, history)
    tickers_by_cat = _bucket_groups_by_category(groups)
    tracking_codes = _pick_tracking_codes(target, history)
    matrix_codes = _pick_matrix_codes(target, history)

    # 内嵌的 snapshot 简化：只保留必要字段，避免 HTML 过大
    snapshot_payload = {
        "label": target["label"],
        "market": target["market"],
        "trade_date": target.get("trade_date"),
        "name_map": name_map,
    }
    # annotations：从 session 抽出来
    annotations_payload = {}
    for t in target["tickers"]:
        ann = t.get("annotation")
        if ann:
            annotations_payload[t["code"]] = ann

    known_palette = color_palette.load()

    # 拉每只品种近 30 个交易日真实收盘价用于 sparkline
    spark_data = _load_spark_closes(market, list(name_map), target.get("trade_date"))

    env = _make_env()
    tmpl = env.get_template("report.html.j2")
    html = tmpl.render(
        market=market,
        label=label,
        market_label=MARKET_LABEL[market],
        session=target,
        history=history,
        name_map=name_map,
        tickers_by_cat=tickers_by_cat,
        tracking_codes=tracking_codes,
        matrix_codes=matrix_codes,
        spark_data=spark_data,
        snapshot_payload=snapshot_payload,
        annotations_payload=annotations_payload,
        known_palette=known_palette,
    )

    out_dir = os.path.join(REPORTS_DIR, market.lower())
    os.makedirs(out_dir, exist_ok=True)
    out_fp = os.path.join(out_dir, f"{label}.html")
    tmp = out_fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, out_fp)
    return out_fp


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["A", "US"], required=True)
    p.add_argument("--label", required=True)
    args = p.parse_args()
    fp = render(args.market, args.label)
    print(f"OK {fp}")


if __name__ == "__main__":
    main()
