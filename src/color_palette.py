"""色板闭环（REFACTOR_BRIEF 4.9.9）。

`data/window/color_palette.json` 全局共享（双市场跨时段统一）。
HTML 渲染时静态注入 <script id="known_palette">，JS 初始化时把已用颜色填进
picker 下拉建议。sync_annotations 时增量合并 B 新加的颜色。
"""
from __future__ import annotations

import json
import os
from typing import Iterable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PALETTE_PATH = os.path.join(ROOT, "data", "window", "color_palette.json")

# 浅色起步选项（避免底色盖文字）
DEFAULT_PALETTE = [
    {"hex": "#FFE4B5", "name": "鹅黄"},
    {"hex": "#FFDAB9", "name": "桃色"},
    {"hex": "#FFB6C1", "name": "浅粉"},
    {"hex": "#DDA0DD", "name": "梅紫"},
    {"hex": "#E6E6FA", "name": "薰衣草"},
    {"hex": "#B0E0E6", "name": "粉蓝"},
    {"hex": "#AFEEEE", "name": "浅水蓝"},
    {"hex": "#98FB98", "name": "嫩绿"},
    {"hex": "#F0E68C", "name": "卡其黄"},
    {"hex": "#FFA07A", "name": "夕阳红"},
    {"hex": "#D3D3D3", "name": "灰"},
    {"hex": "#FFFACD", "name": "柠檬绸"},
]


def load() -> list[dict]:
    """读色板；不存在则用默认 12 色。"""
    if not os.path.exists(PALETTE_PATH):
        return list(DEFAULT_PALETTE)
    with open(PALETTE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("colors", list(DEFAULT_PALETTE))


def save(colors: list[dict]) -> None:
    os.makedirs(os.path.dirname(PALETTE_PATH), exist_ok=True)
    tmp = PALETTE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"colors": colors}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PALETTE_PATH)


def merge(new_colors: Iterable[dict]) -> list[dict]:
    """把新色板项合并进现有色板（按 hex 去重；保留旧 name 优先）。返回合并后的列表。"""
    current = load()
    seen = {c["hex"].upper() for c in current}
    for nc in new_colors:
        if not nc or "hex" not in nc:
            continue
        hex_u = nc["hex"].upper()
        if hex_u not in seen:
            current.append({"hex": nc["hex"],
                            "name": nc.get("name", nc["hex"])})
            seen.add(hex_u)
    save(current)
    return current


def extract_from_annotations(session: dict) -> list[dict]:
    """从 session.tickers[*].annotation 提取色板项。"""
    out = []
    for t in session.get("tickers", []):
        ann = t.get("annotation")
        if ann and "color" in ann:
            out.append({"hex": ann["color"], "name": ann.get("color_name", "")})
    return out
