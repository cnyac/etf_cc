"""
render.py — 把 analyzed 数据渲染成 HTML 报告。

所有颜色、字体、表格结构全在 Jinja2 模板里固化，LLM 不参与排版。
"""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def _highlight_anomaly(text: str) -> str:
    """把分析文本里的 **异常** 标记替换为红色加粗的 HTML 片段。"""
    if not text:
        return ""
    # 先把整段文本 HTML-escape，再选择性放开 **xxx**
    out = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))
    # 处理 **异常** → <strong class="anomaly">异常</strong>
    out = re.sub(r"\*\*(异常)\*\*", r'<strong class="anomaly">\1</strong>', out)
    # 处理普通 **xxx** → <strong>xxx</strong>
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return out


def _session_date_label(session_label: str, today_date: str) -> str:
    """'0511收盘' + '5月11日' → '2026-05-11(收盘)'。

    年份用当前年（这里简化处理，正式部署时 ingest 阶段最好直接带年份）。
    """
    import datetime as dt
    year = dt.datetime.now().year
    # 解析 today_date 'X月Y日'
    m = re.match(r"(\d+)月(\d+)日", today_date)
    if m:
        date_iso = f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    else:
        date_iso = today_date

    suffix = ""
    if "中午" in session_label:
        suffix = "(中午)"
    elif "收盘" in session_label:
        suffix = "(收盘)"
    return f"{date_iso}{suffix}"


def render_single(analyzed: dict, output_path: str | Path) -> Path:
    """渲染单时段报告。"""
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("single_session.html.j2")

    # 预处理 analysis 字段（异常高亮）
    for group in analyzed["groups"].values():
        for it in group:
            it["analysis"] = _highlight_anomaly(it.get("analysis", ""))

    html = template.render(
        **analyzed,
        today_date_full=analyzed["today_date"],
        session_date_label=_session_date_label(
            analyzed["session_label"], analyzed["today_date"]
        ),
    )
    out = Path(output_path)
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    import json
    import sys
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = render_single(data, sys.argv[2])
    print(f"已写入 {out}")
