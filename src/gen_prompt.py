"""CLI：为指定 market+label 生成 prompt，输出 stdout。

用法：
  python -m src.gen_prompt --market A --label 2026-05-20-收 > prompt.txt
  python -m src.gen_prompt --market A                       # 默认取最新 session
  python -m src.gen_prompt --market A --segmented           # 3 段同时输出（含分隔符）
  python -m src.gen_prompt --market A --segmented --part 3  # 只输出 PART 3（调试用）

工作流：
  默认模式：一段 prompt → 复制到 Claude/Cursor 一次性跑 → fill_narrative 收 JSON
  分段模式：3 段 prompt → 在同一对话依次粘贴 PART1/2/3 → fill_narrative 只收 PART3 的 JSON
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import window as win
from src.llm_prompt import build_prompt, build_segmented_prompts


SEGMENT_SEPARATOR = (
    "\n\n"
    "================================================================================\n"
    "===           PART BOUNDARY — 把下一段作为对话里独立的一条消息粘贴           ===\n"
    "================================================================================\n"
    "\n"
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["A", "US"], required=True)
    p.add_argument("--label", default=None, help="缺省取最新 session")
    p.add_argument("--segmented", action="store_true",
                   help="分段投喂模式：产 3 段 prompt，用户在同一对话依次粘贴。"
                        "默认 false，行为完全不变。")
    p.add_argument("--part", type=int, choices=[1, 2, 3], default=None,
                   help="仅 --segmented 模式有效：只输出指定 PART（调试单段重产用）。"
                        "缺省 → 全部 3 段含分隔符。")
    args = p.parse_args()

    if args.part is not None and not args.segmented:
        print("--part 仅在 --segmented 模式下有效", file=sys.stderr)
        sys.exit(2)

    data = win.load(args.market)
    if not data["sessions"]:
        print(f"窗口为空：{args.market}", file=sys.stderr)
        sys.exit(1)

    if args.label is None:
        target = data["sessions"][-1]
    else:
        target = next((s for s in data["sessions"] if s["label"] == args.label), None)
        if target is None:
            print(f"找不到 label={args.label}", file=sys.stderr)
            sys.exit(1)

    history = [s for s in data["sessions"] if s["label"] != target["label"]]

    if args.segmented:
        parts = build_segmented_prompts(args.market, target, history)
        if args.part is not None:
            sys.stdout.write(parts[args.part - 1])
        else:
            sys.stdout.write(SEGMENT_SEPARATOR.join(parts))
    else:
        sys.stdout.write(build_prompt(args.market, target, history))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
