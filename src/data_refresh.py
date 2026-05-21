"""数据补齐：只更新 etf_cc 池子内的标的，不动 auto-prtsc 全库。

走 auto-prtsc 暴露的 pool 粒度 API：
  - A 股：etf_data_api.run_a_etf_daily_update(pool_path=...)  接受我们的 pool_a.yaml
  - 美股：etf_data_api.run_us_single_update(code) 逐只调  （auto-prtsc 没暴露 batch）

auto-prtsc 全库的季度 gap_fill 是另一条线，与本流程无关。
"""
from __future__ import annotations

import os
import sys
from typing import Callable, Literal

import yaml

AUTO_PRTSC = r"D:\git\auto prtsc"
if AUTO_PRTSC not in sys.path:
    sys.path.insert(0, AUTO_PRTSC)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_POOL_A = os.path.join(ROOT, "config", "pool_a.yaml")
DEFAULT_POOL_US = os.path.join(ROOT, "config", "pool_us.yaml")


def _load_codes(pool_path: str) -> list[str]:
    with open(pool_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return [e["code"] for e in cfg.get("etfs", [])]


def refresh_pool(market: Literal["A", "US"],
                 pool_path: str | None = None) -> tuple[bool, str]:
    """只更新池子内 codes 的切片。返回 (ok, note)。"""
    if pool_path is None:
        pool_path = DEFAULT_POOL_A if market == "A" else DEFAULT_POOL_US

    # 友好降级：yaml 不存在不要让 update_all 整批崩
    if not os.path.exists(pool_path):
        return True, f"{pool_path} 不存在，跳过补齐（请先在 GUI 池配置 tab 创建）"

    try:
        import etf_data_api as api  # type: ignore
    except Exception as e:
        return False, f"无法 import etf_data_api: {e}"

    if market == "A":
        try:
            summary = api.run_a_etf_daily_update(pool_path=pool_path)
            return True, (f"A 股池: ok={summary['ok']} "
                          f"skip={summary['skip_latest']} fail={summary['fail']} "
                          f"/{summary['total']}")
        except Exception as e:
            return False, f"A 股更新抛错: {type(e).__name__}: {e}"

    # US：逐只
    codes = _load_codes(pool_path)
    ok = fail = 0
    failed_codes: list[str] = []
    for c in codes:
        try:
            if api.run_us_single_update(c):
                ok += 1
            else:
                fail += 1
                failed_codes.append(c)
        except Exception:
            fail += 1
            failed_codes.append(c)
    note = f"美股池: ok={ok} fail={fail} /{len(codes)}"
    if failed_codes:
        note += f"  失败: {failed_codes[:5]}"
    return (fail == 0), note


def refresh_all(markets: list[Literal["A", "US"]],
                log_cb: Callable[[str], None] = print) -> dict[str, tuple[bool, str]]:
    """按 markets 顺序更新每个池子，返回 {market: (ok, note)}。"""
    out: dict[str, tuple[bool, str]] = {}
    for m in markets:
        log_cb(f"[refresh] {m} 池子数据补齐中…")
        ok, note = refresh_pool(m)
        out[m] = (ok, note)
        log_cb(f"[refresh] {m} {'OK' if ok else 'FAIL'}  {note}")
    return out
