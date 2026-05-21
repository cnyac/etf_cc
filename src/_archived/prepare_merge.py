"""
prepare_merge.py — Claude Code 模式：只做时序对齐 + 跨日表筛选，不调 API。

输出一个完整的 JSON 文件，Claude Code 读它，自己填进去：
  - 每个分类的本分类小结
  - 独特异象分析
  - 跨日追踪表的变化评级和理由
  - 宏观研判四部分
  - 第四部分（仅 weekly）
  - color_palette（若传入了 --prev-docx，由 Claude Code 在合并分析时填写）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from merge import align_timeline, select_rating_candidates

ROOT      = Path(__file__).parent.parent
SNAP_DIR  = ROOT / "data" / "snapshots"
MERGED_DIR = ROOT / "data" / "merged"


def prepare(
    labels: list[str],
    is_weekly: bool = False,
    prev_docx: str | None = None,
) -> Path:
    print(f"载入 {len(labels)} 个时段：{labels}")
    snapshots = []
    for label in labels:
        f = SNAP_DIR / f"{label}.json"
        if not f.exists():
            raise FileNotFoundError(f"找不到 {f}，请先跑 prepare_single")
        snapshots.append(json.loads(f.read_text(encoding="utf-8")))

    print("时序对齐...")
    aligned = align_timeline(snapshots)
    print(f"  T0 品种: {aligned['total']}")

    print("筛选跨日追踪表候选品种...")
    candidates = select_rating_candidates(aligned, snapshots)
    print(f"  候选: {len(candidates)} 个")

    # ── 批注解析（可选）──────────────────────────────────────────────────────
    prev_annotations: dict = {}
    if prev_docx:
        prev_docx_path = Path(prev_docx)
        if not prev_docx_path.exists():
            print(f"⚠️  --prev-docx 指定的文件不存在：{prev_docx}，跳过批注解析。")
        else:
            from parse_annotation import extract_annotations
            prev_annotations = extract_annotations(prev_docx_path)
            print(f"  从昨日报告解析到 {len(prev_annotations)} 条批注")

    # 把批注 join 进 T0 各品种
    if prev_annotations:
        for group in aligned["groups"].values():
            for it in group:
                ann = prev_annotations.get(it.get("code", ""), {})
                it["prev_annotation"] = ann  # {"color_name": ..., "note_text": ...}

    # ── 骨架 JSON ─────────────────────────────────────────────────────────────
    skeleton = {
        "is_weekly_close": is_weekly,
        "labels":          labels,
        "aligned":         aligned,
        "snapshots_summary": [
            {
                "session_label": s["session_label"],
                "today_date":    s["today_date"],
                "stats":         s["stats"],
                "resonance":     s.get("resonance"),
            }
            for s in snapshots
        ],
        "rating_candidates": [
            {**c, "rating": "", "reason": ""}
            for c in candidates
        ],
        "category_summaries": {
            "持续强化": "",
            "强反转":   "",
            "反包修复": "",
            "连续杀跌": "",
        },
        "unique_anomaly_analysis": "",
        "macro": {
            "panorama_headline":  "",
            "panorama_paragraphs": ["", "", ""],
            "key_movers": [
                {"sector": "", "phenomenon": "", "driver": "", "scenario": ""},
                {"sector": "", "phenomenon": "", "driver": "", "scenario": ""},
                {"sector": "", "phenomenon": "", "driver": "", "scenario": ""},
                {"sector": "", "phenomenon": "", "driver": "", "scenario": ""},
            ],
            "cross_validation": "",
            "conclusion": {
                "stage":             "",
                "attack_direction":  "",
                "retreat_direction": "",
                "risks":             "",
                "trend":             "",
                "style":             "",
                "watch":             "",
            },
        },
        "macro_cycle": None if not is_weekly else {
            "current_profile": "",
            "historical": {"year": "", "event": "", "phase": "", "brief": ""},
            "similarity":  "",
            "difference":  "",
            "risk":        "",
            "opportunity": "",
        },
        # 批注相关字段
        "prev_annotations": prev_annotations,
        # color_palette 由 Claude Code 在合并分析阶段填写：
        # { "颜色名": "RRGGBB", ... }，例如 {"夕阳红": "C04020", "鹅黄": "FFEC8B"}
        # 为 prev_annotations 中出现的每一种 color_name 填一条 RGB hex（浅色调）
        "color_palette": {},
    }

    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"merge_{'_'.join(labels)}_{ts}.json"
    out   = MERGED_DIR / fname
    out.write_text(json.dumps(skeleton, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 骨架已写入: {out}")
    if prev_annotations:
        colors = {v["color_name"] for v in prev_annotations.values() if v.get("color_name")}
        print(f"   批注中出现的颜色名：{sorted(colors)}")
        print(f"   ⚠️  请在填写合并分析时，同时填写 color_palette 字段（颜色名 → RGB hex）。")
    print(f"   下一步：你（Claude Code）读这个文件，填好所有空字段，再渲染。")
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--labels",    nargs="+", required=True,
                   help="时段标签列表，如 0513收盘 0513中午 0512收盘")
    p.add_argument("--weekly",    action="store_true",
                   help="是否为周末收盘（开启宏观周期定位）")
    p.add_argument("--prev-docx", dest="prev_docx", default=None,
                   help="昨日合并报告 docx 路径，用于提取用户批注（可选）")
    args = p.parse_args()
    prepare(args.labels, args.weekly, args.prev_docx)
