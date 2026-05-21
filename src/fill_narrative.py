"""CLI：用 LLM 返回的 narrative JSON 校验 + 回填到 session。

用法：
  python -m src.fill_narrative --market A --label 2026-05-20-收 --json narrative.json

校验失败 → 打印错误清单 + exit 1；不写回。
校验通过 → 覆写 window 中对应 session.narrative + 重写 snapshots/<label>.json。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import window as win
from src.llm_validate import validate_narrative, merge_into_session


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["A", "US"], required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--json", required=True, help="narrative JSON 路径")
    args = p.parse_args()

    with open(args.json, "r", encoding="utf-8") as f:
        narrative = json.load(f)

    data = win.load(args.market)
    target = next((s for s in data["sessions"] if s["label"] == args.label), None)
    if target is None:
        print(f"找不到 label={args.label}", file=sys.stderr)
        sys.exit(1)

    ok, errors = validate_narrative(narrative, args.market, target.get("panel"))
    if not ok:
        print(f"校验失败 ({len(errors)} 个错误):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    merge_into_session(target, narrative)
    # 写回 window + snapshots
    win.save(args.market, data)
    win.archive_to_snapshot(args.market, target)
    print(f"OK narrative 已回填到 {args.market}/{args.label}")


if __name__ == "__main__":
    main()
