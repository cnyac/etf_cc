"""CLI：为指定 market+label 生成 prompt，输出 stdout。

用法：
  python -m src.gen_prompt --market A --label 2026-05-20-收 > prompt.txt
  python -m src.gen_prompt --market A           # 默认取最新 session

工作流：
  1. 此脚本生成 prompt
  2. 用户复制到 Claude/Cursor 跑
  3. 把返回的 JSON 存盘
  4. python -m src.fill_narrative --market A --label … --json narrative.json
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import window as win
from src.llm_prompt import build_prompt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["A", "US"], required=True)
    p.add_argument("--label", default=None, help="缺省取最新 session")
    args = p.parse_args()

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
    prompt = build_prompt(args.market, target, history)
    sys.stdout.write(prompt)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
