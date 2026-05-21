"""
render_merge.py — 把已经填好内容的合并 JSON 渲染成 HTML。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from render import _highlight_anomaly
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).parent.parent


def render_merge(merged_json_path: str, output_html_path: str) -> Path:
    data = json.loads(Path(merged_json_path).read_text(encoding="utf-8"))

    # 把骨架 JSON 还原成模板能用的格式
    aligned = data["aligned"]

    # 异常高亮
    for group in aligned["groups"].values():
        for it in group:
            it["analysis"] = _highlight_anomaly(it.get("analysis", ""))
            for h in it.get("timeline", []):
                h["analysis"] = _highlight_anomaly(h.get("analysis", ""))

    # 整理 macro 数据成模板期望的结构
    macro = data["macro"]
    macro_for_template = {
        "category_summaries": {
            k: _highlight_anomaly(v) for k, v in data["category_summaries"].items()
        },
        "unique_anomaly_analysis": _highlight_anomaly(data.get("unique_anomaly_analysis", "")),
        "feature_change_ratings": [
            {"name": c["name"], "rating": c["rating"], "reason": c["reason"]}
            for c in data["rating_candidates"]
        ],
        "macro_panorama": {
            "headline": macro["panorama_headline"],
            "paragraphs": macro["panorama_paragraphs"],
        },
        "key_movers": macro["key_movers"],
        "cross_validation": _highlight_anomaly(macro["cross_validation"]),
        "conclusion": macro["conclusion"],
        "macro_cycle": data.get("macro_cycle"),
        "_votes": None,  # Claude Code 模式不投票
    }

    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("merged.html.j2")
    html = template.render(
        aligned=aligned,
        snapshots=data["snapshots_summary"],
        rating_candidates=data["rating_candidates"],
        macro=macro_for_template,
        is_weekly_close=data["is_weekly_close"],
    )
    out = Path(output_html_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"✅ 已渲染: {out}")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python render_merge.py <merged.json> <output.html>")
        sys.exit(1)
    render_merge(sys.argv[1], sys.argv[2])
