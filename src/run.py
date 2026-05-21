"""
run.py — 轨迹图入口（Claude Code 模式下保留的少数 CLI 入口之一）。

单时段分析改用 src/prepare_single.py + Claude Code 写 + src/render.py
合并分析改用 src/prepare_merge.py + Claude Code 写 + src/render_merge.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).parent.parent
SNAP_DIR = ROOT / "data" / "snapshots"
REPORT_DIR = ROOT / "reports"


def cmd_trajectory(args):
    from trajectory import render_trajectory_html

    labels = args.labels
    print(f"[1/2] 载入 {len(labels)} 个已存档时段：{labels}")
    snapshots = []
    for label in labels:
        f = SNAP_DIR / f"{label}.json"
        if not f.exists():
            raise FileNotFoundError(f"找不到 {f}，请先用 prepare_single.py 跑过")
        snapshots.append(json.loads(f.read_text(encoding="utf-8")))

    print(f"[2/2] 渲染轨迹图（高亮 top {args.top}）")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    fname = "trajectory_" + "_".join(labels) + ".html"
    out = render_trajectory_html(snapshots, REPORT_DIR / fname, highlight_top=args.top)
    print(f"\n✅ 完成：{out}")


def main():
    parser = argparse.ArgumentParser(description="ETF 工具入口")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("trajectory", help="跨时段特征轨迹图")
    p.add_argument("--labels", nargs="+", required=True,
                   help="时段标签，按时间倒序传入（T0 在前），5-10 个最佳")
    p.add_argument("--top", type=int, default=8,
                   help="默认高亮显示轨迹变化最大的 N 个品种")
    p.set_defaults(func=cmd_trajectory)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
