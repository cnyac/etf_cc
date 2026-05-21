"""
prepare_single.py — Claude Code 模式：只做确定性计算，把结果写到 JSON。

不调 API。Claude Code 看到 JSON 自己会写定性分析。
"""
from __future__ import annotations

import json
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ingest import load_snapshot
from classify import enrich

ROOT = Path(__file__).parent.parent
SNAP_DIR = ROOT / "data" / "snapshots"


def _ymd_to_chinese(date_str: str) -> str:
    """'2026-05-13' → '5月13日'"""
    d = _date.fromisoformat(date_str)
    return f"{d.month}月{d.day}日"


def prepare(xlsx_path: str, label: str, today_date: str, yest_date: str) -> Path:
    """读 xlsx → 跑分类 → 存 JSON。返回 JSON 路径。"""
    print(f"读取 {xlsx_path}")
    snap = load_snapshot(xlsx_path, session_label=label,
                         today_date=today_date, yest_date=yest_date)
    print(f"  共 {snap['total']} 个品种")

    print("分类计算中...")
    enriched = enrich(snap)
    for cat, st in enriched["stats"].items():
        print(f"  {cat}: {st['count']} ({st['pct']}%)")
    print(f"  极值共振: {enriched['resonance']}")

    # 给每个 item 加一个空的 analysis 字段，等 Claude Code 来填
    for group in enriched["groups"].values():
        for it in group:
            it["analysis"] = ""

    out = SNAP_DIR / f"{label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 数据已写入: {out}")
    print(f"   下一步：让 Claude Code 读这个 JSON、给每个品种写 analysis、再渲染。")
    return out


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--xlsx",       required=True,  help="xlsx 路径，如 data/raw/ETF数据.xlsx")
    p.add_argument("--label",      required=True,  help="时段标签，如 0513中午 / 0513收盘")
    p.add_argument("--today-date", required=True,  dest="today_date",
                   help="今日日期，格式 YYYY-MM-DD，如 2026-05-13")
    p.add_argument("--yest-date",  required=True,  dest="yest_date",
                   help="昨日日期，格式 YYYY-MM-DD，如 2026-05-12")
    args = p.parse_args()

    prepare(
        xlsx_path  = args.xlsx,
        label      = args.label,
        today_date = _ymd_to_chinese(args.today_date),
        yest_date  = _ymd_to_chinese(args.yest_date),
    )
