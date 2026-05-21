"""per-ticker 预期审计的量化代审实现。

设计来自 2026-05-21 用户拍板：
  - 量化审打分 = D1 归类跃迁 + D2 量能配合
  - 总分映射五档：强超 / 超 / 符合 / 低 / 强低于预期
  - 上一时段缺失 / 该 code 未出现 → 返回 None（渲染显示 "—"）
  - LLM 人格审同字段 schema，覆盖量化结果；二者唯一区别是 auditor 字段
"""
from __future__ import annotations

from typing import Literal, Optional

AUDIT_RATINGS = ["强超于预期", "超于预期", "符合预期", "低于预期", "强低于预期"]
AUDITORS = ["quant", "yangjia", "zhaolaoge", "fengliu", "discipline"]

# D1：归类跃迁打分表 (prev_cat, curr_cat) → 分
_D1_TABLE: dict[tuple[str, str], int] = {
    ("强反转",   "持续强化"): +3,
    ("连续杀跌", "反包修复"): +2,
    ("反包修复", "持续强化"): +2,
    ("持续强化", "持续强化"): +1,
    ("持续强化", "反包修复"): -2,
    ("持续强化", "强反转"):   -2,
    ("反包修复", "强反转"):   -1,
    ("强反转",   "连续杀跌"): -2,
    ("连续杀跌", "连续杀跌"): -1,
}

VOL_HIGH = 1.2
VOL_LOW = 0.8


def _d1_score(prev_cat: Optional[str], curr_cat: Optional[str]) -> int:
    """归类跃迁分。未匹配的组合统一记 0（中性维持）。"""
    if not prev_cat or not curr_cat:
        return 0
    return _D1_TABLE.get((prev_cat, curr_cat), 0)


def _d2_score(today_pct: Optional[float], vol_ratio_20: Optional[float]) -> int:
    """量能配合分。
      涨 + 放量 (>=1.2) → +1   涨 + 缩量 (<0.8) → -1
      跌 + 放量         → -1   跌 + 缩量         → +1
      其它 → 0
    """
    if today_pct is None or vol_ratio_20 is None:
        return 0
    if today_pct > 0:
        if vol_ratio_20 >= VOL_HIGH:
            return +1
        if vol_ratio_20 < VOL_LOW:
            return -1
    elif today_pct < 0:
        if vol_ratio_20 >= VOL_HIGH:
            return -1
        if vol_ratio_20 < VOL_LOW:
            return +1
    return 0


def _score_to_rating(score: int) -> str:
    if score >= 3:
        return "强超于预期"
    if score >= 1:
        return "超于预期"
    if score == 0:
        return "符合预期"
    if score >= -2:
        return "低于预期"
    return "强低于预期"


def quant_audit_ticker(prev_ticker: Optional[dict],
                       curr_ticker: dict) -> Optional[dict]:
    """对一只 ticker 做量化审。
    返回 {actual_vs_expected, auditor: "quant"} 或 None（无上一时段数据）。
    """
    if prev_ticker is None:
        return None
    prev_cat = prev_ticker.get("category")
    curr_cat = curr_ticker.get("category")
    today_pct = curr_ticker.get("today_pct")
    factors = curr_ticker.get("factors") or {}
    vr = factors.get("vol_ratio_20")

    score = _d1_score(prev_cat, curr_cat) + _d2_score(today_pct, vr)
    return {
        "actual_vs_expected": _score_to_rating(score),
        "auditor": "quant",
    }


def quant_audit_batch(prev_session: Optional[dict],
                      curr_session: dict) -> dict[str, dict]:
    """对当前 session 的所有 ticker 做量化审，返回 {code: audit_dict}。
    缺 prev 或 prev 中无该 code → 该 code 不入结果（caller 渲染 "—"）。
    """
    out: dict[str, dict] = {}
    prev_by_code: dict[str, dict] = {}
    if prev_session:
        for t in prev_session.get("tickers", []):
            prev_by_code[t["code"]] = t
    for t in curr_session.get("tickers", []):
        code = t["code"]
        prev_t = prev_by_code.get(code)
        result = quant_audit_ticker(prev_t, t)
        if result is not None:
            out[code] = result
    return out
