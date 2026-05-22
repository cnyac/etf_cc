"""对已有 snapshot 重算 ticker.audit（不动 narrative / 其它字段）。

何时用：
  - audit.py 算法升级（如 2026-05-22 加 audit_note 字段）后，要让历史 snapshot
    立刻反映新逻辑，而不必重跑 build_snapshot（重跑会清掉 LLM 写的 narrative）。
  - prev_session 选择逻辑变（如 2026-05-22 改用 snapshots 而非 window）后，
    要让历史 audit 重新计算。

行为：
  - 加载 snapshot/<m>/<label>.json
  - 用 _load_prev_snapshot 找前一时段（snapshots 优先）
  - 对每只 ticker 跑 quant_audit_ticker
  - 覆写回 snapshot 文件（narrative 保留不动）
  - 若 label 仍在窗口里，同步覆写窗口 session 的 ticker.audit

入口：
  python -m src.recompute_audit --market US --label 2026-05-21
  python -m src.recompute_audit --market US --all       # 全部 snapshot 重算
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Literal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import window as win
from src import audit as audit_mod
from src.build_snapshot import _load_prev_snapshot


def _trade_date_and_st_from_label(label: str) -> tuple[str, str]:
    if label.endswith("-午"):
        return label[:-2].rstrip("-"), "noon"
    if label.endswith("-收"):
        return label[:-2].rstrip("-"), "close"
    return label, "close"


def recompute_one(market: Literal["A", "US"], label: str) -> dict:
    """返回 {ok, updated, total, note}"""
    fp = os.path.join(win.SNAPSHOT_DIR, market.lower(), f"{label}.json")
    if not os.path.exists(fp):
        return {"ok": False, "note": f"找不到 snapshot: {fp}"}
    with open(fp, "r", encoding="utf-8") as f:
        snap = json.load(f)

    trade_date, session_time = _trade_date_and_st_from_label(label)
    prev = _load_prev_snapshot(market, trade_date, session_time)
    if prev is None:
        return {"ok": True, "updated": 0, "total": len(snap.get("tickers", [])),
                "note": "无前一时段 snapshot，audit 全 None（首日跳过）"}

    audits = audit_mod.quant_audit_batch(prev, {"tickers": snap["tickers"]})
    updated = 0
    for t in snap["tickers"]:
        # 不覆盖 LLM 写的人格审（auditor != "quant"）
        if t.get("audit") and t["audit"].get("auditor") != "quant":
            continue
        new_audit = audits.get(t["code"])
        if new_audit is not None:
            t["audit"] = new_audit
            updated += 1
        elif t.get("audit") and t["audit"].get("auditor") == "quant":
            # prev 里没该 code（如新加品种） → 清掉旧 quant audit
            t["audit"] = None

    # 写回 snapshot
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    os.replace(tmp, fp)

    # 若 label 在窗口里，同步窗口
    data = win.load(market)
    for s in data["sessions"]:
        if s.get("label") == label:
            s["tickers"] = snap["tickers"]
            win.save(market, data)
            break

    return {"ok": True, "updated": updated, "total": len(snap["tickers"]),
            "note": f"重算 audit OK: {updated}/{len(snap['tickers'])} 只更新"}


def recompute_all(market: Literal["A", "US"]) -> list[dict]:
    snap_dir = os.path.join(win.SNAPSHOT_DIR, market.lower())
    if not os.path.isdir(snap_dir):
        return []
    labels = sorted(
        fn[:-5] for fn in os.listdir(snap_dir) if fn.endswith(".json")
    )
    results = []
    for lab in labels:
        r = recompute_one(market, lab)
        results.append({"label": lab, **r})
        print(f"  {lab}  {r.get('note', '')}")
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["A", "US"], required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--label", help="指定 label 重算")
    g.add_argument("--all", action="store_true", help="全部 snapshot 重算")
    args = p.parse_args()

    if args.all:
        results = recompute_all(args.market)
        ok_n = sum(1 for r in results if r.get("ok"))
        print(f"\n汇总: {ok_n}/{len(results)} OK")
    else:
        r = recompute_one(args.market, args.label)
        print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
