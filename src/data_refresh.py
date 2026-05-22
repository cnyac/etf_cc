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

    # US：优先批量接口（us.update.us_daily_update，一次拉 45 只）；不可用时退化为逐只
    codes = _load_codes(pool_path)
    try:
        return _refresh_us_batch(codes)
    except Exception as e:
        # 批量失败 → 退化为逐只（兼容老接口缺失场景）
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
        note = (f"美股池: 批量失败({type(e).__name__})，退化逐只 ok={ok} fail={fail} /{len(codes)}")
        if failed_codes:
            note += f"  失败: {failed_codes[:5]}"
        return (fail == 0), note


def _refresh_us_batch(codes: list[str]) -> tuple[bool, str]:
    """走 auto-prtsc 的 _download_via_akshare + _merge_to_slices 底层函数。

    2026-05-22 用户反馈：yfinance 一直被 YFRateLimitError 限流（0 命中），
    每只走兜底浪费时间。**永久绕开 yfinance**，直接 akshare。

    不调 us_daily_update（它的源分发链默认 yfinance + akshare fallback），
    改为直接调底层批量拉 akshare → 合并到 slices/。

    auto-prtsc 默认行为不变（其他项目仍可用 yfinance）。
    """
    import sys
    import time

    if r"D:\git\auto prtsc" not in sys.path:
        sys.path.insert(0, r"D:\git\auto prtsc")
    from us.update import _download_via_akshare, _merge_to_slices  # noqa: E402
    import config as _cfg  # noqa: E402

    clean_codes = [c.replace(".", "-") for c in codes]
    slices_dir = os.path.join(_cfg.QUANT_DATA, "us", "slices")
    started = time.time()

    data = _download_via_akshare(clean_codes)
    if data is None or (hasattr(data, "empty") and data.empty):
        return False, f"美股池(akshare 批量): 拉空，0/{len(codes)}"

    _merge_to_slices(data, codes, clean_codes)

    # 数 slices 文件中 mtime > started 的（即本次跑新写入的）
    refreshed = 0
    if os.path.isdir(slices_dir):
        for c in codes:
            for name in (c, c.replace(".", "-")):
                fp = os.path.join(slices_dir, f"{name}.parquet")
                if os.path.exists(fp) and os.path.getmtime(fp) >= started - 1:
                    refreshed += 1
                    break
    elapsed = time.time() - started
    ok = refreshed >= len(codes) * 0.8
    note = (f"美股池(akshare 批量): refreshed={refreshed}/{len(codes)} 耗时 {elapsed:.1f}s")
    return ok, note


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
