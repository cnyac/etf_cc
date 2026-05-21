"""数据更新日志工具（REFACTOR_BRIEF §4.6.5）。

两类落盘：
  - write_run_summary(): data/logs/update_<ts>.log  纯文本，给人看
  - write_error(): data/logs/errors/<ts>_<ticker>.json  结构化，给 AI 复查

底层数据源 fallback 由 auto-prtsc/gap_fill.py 接管，本模块只记 etf_cc
build_snapshot 这一层的 ticker 级失败。
"""
from __future__ import annotations

import datetime
import json
import os
import traceback as tb_mod
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(ROOT, "data", "logs")
ERRORS_DIR = os.path.join(LOGS_DIR, "errors")


def _ts() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def write_error(ticker: str, label: str, market: str,
                exc: BaseException, ts: str | None = None) -> str:
    """写一条 ticker 级错误明细，返回文件绝对路径。"""
    os.makedirs(ERRORS_DIR, exist_ok=True)
    ts = ts or _ts()
    safe_ticker = ticker.replace("/", "_").replace("\\", "_")
    fp = os.path.join(ERRORS_DIR, f"{ts}_{safe_ticker}.json")
    payload = {
        "timestamp": datetime.datetime.now().isoformat(),
        "market": market,
        "label": label,
        "ticker": ticker,
        "error_type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(tb_mod.format_exception(type(exc), exc, exc.__traceback__)),
    }
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return fp


def format_run_summary(summary: dict[str, Any]) -> str:
    """把 summary dict 渲染成人类可读文本。

    summary 结构：
      {
        "started_at": iso,
        "elapsed_sec": float,
        "data_refresh": {"ok": bool, "note": str} | None,
        "labels": [
          {"market": "A", "label": "...", "total": 45, "ok": 43,
           "failed": [{"ticker": "...", "error_type": "...",
                       "message": "...", "log_path": "..."}, ...]},
          ...
        ],
      }
    """
    lines = []
    lines.append(f"=== 数据更新汇总 {summary['started_at']} ===")
    dr = summary.get("data_refresh")
    if dr:
        # dr 现为 {market: {ok, note}}
        lines.append("池子数据补齐:")
        for market, info in dr.items():
            flag = "OK" if info.get("ok") else "FAIL"
            lines.append(f"  {market}  {flag}  {info.get('note', '')}")
    if not summary.get("labels"):
        lines.append("（无报告缺口需补）")
    for lab in summary.get("labels", []):
        head = (f"{lab['market']} / {lab['label']}  "
                f"成功 {lab['ok']}/{lab['total']}")
        if lab["failed"]:
            head += f"  失败 {len(lab['failed'])}"
        lines.append(head)
        for f in lab["failed"]:
            lines.append(f"    {f['ticker']:<10} {f['error_type']:<16} "
                         f"{f['message'][:80]}")
            if f.get("log_path"):
                lines.append(f"      → {f['log_path']}")
    lines.append(f"总耗时 {summary.get('elapsed_sec', 0):.1f}s")
    return "\n".join(lines)


def write_run_summary(summary: dict[str, Any], ts: str | None = None) -> str:
    """落 data/logs/update_<ts>.log，返回路径。"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    ts = ts or _ts()
    fp = os.path.join(LOGS_DIR, f"update_{ts}.log")
    text = format_run_summary(summary)
    with open(fp, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return fp
