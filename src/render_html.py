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


def _pick_tracking_codes(session: dict, max_n: int = 12) -> list[str]:
    """选 §4 跨日追踪表的品种：带特征标签的优先 + |pct_normalized| 高的 + 量异常。"""
    scored = []
    for t in session.get("tickers", []):
        score = 0
        if t.get("feature"):
            score += 10
        f = t.get("factors") or {}
        pn = f.get("pct_normalized")
        if pn is not None:
            score += abs(pn) * 3
        vr = f.get("vol_ratio_20")
        if vr is not None and (vr > 1.5 or vr < 0.7):
            score += 2
        p60 = f.get("price_pctile_60")
        if p60 is not None and (p60 >= 90 or p60 <= 10):
            score += 2
        scored.append((score, t["code"]))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:max_n]]


def _pick_matrix_codes(session: dict, max_n: int = 15) -> list[str]:
    """§5 矩阵：跨日的扩到 15 个。复用 _pick_tracking_codes 逻辑放宽。"""
    return _pick_tracking_codes(session, max_n)


def _bucket_by_category(tickers: list[dict]) -> dict[str, list[dict]]:
    buckets = {"持续强化": [], "反包修复": [], "强反转": [], "连续杀跌": []}
    for t in tickers:
        cat = t.get("category")
        if cat in buckets:
            buckets[cat].append(t)
    # 按 pct_diff 降序排
    for cat in buckets:
        buckets[cat].sort(key=lambda x: (x.get("pct_diff") or 0), reverse=True)
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
    tickers_by_cat = _bucket_by_category(target["tickers"])
    tracking_codes = _pick_tracking_codes(target)
    matrix_codes = _pick_matrix_codes(target)

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
