"""三级历史记忆业务规律自检。

验"业务规律"，不验"具体字符串内容"：
  - 近/中/远三级标志都出现在 prompt 里
  - 箭头方向与当时段涨跌广度一致（且排除跨资产代表）
  - 中级趋势标签按规则触发 / 不满足阈值不触发
  - 数据不足时 graceful degradation（有几段显示几段，不报错）
  - prompt 长度不显著膨胀（≤ 基线 × 1.5）
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from src.llm_prompt import (
    _far_memory_block,
    _mid_memory_block,
    _rule_consec_rise,
    _rule_dominant_pct,
    _session_arrow,
    _threelevel_memory_block,
    build_prompt,
)

# ---------------------------------------------------------------------------
# 辅助：构造合成 session
# ---------------------------------------------------------------------------

_CATS = ["持续强化", "反包修复", "强反转", "连续杀跌"]

# A 股跨资产代表（与 pool_a.yaml 一致）
CROSS_CODES_A = {"SH511260", "SH511090", "SH518880", "SH501018"}


def _mk_session(
    label: str,
    cat_dist: dict,
    session_summary: str = "测试摘要",
    is_skeleton: bool = False,
    tickers: list | None = None,
    market: str = "A",
) -> dict:
    """构造极简 session dict，用于测试 history 组装逻辑。"""
    return {
        "label": label,
        "market": market,
        "session_time": "close",
        "trade_date": label[:10],
        "panel": {"category_distribution": cat_dist},
        "tickers": tickers or [],
        "narrative": {
            "is_skeleton": is_skeleton,
            "session_summary": session_summary,
        },
    }


def _mk_ticker(code: str, pct: float) -> dict:
    return {"code": code, "today_pct": pct}


# ---------------------------------------------------------------------------
# 箭头方向：排除跨资产后的广度方向
# ---------------------------------------------------------------------------

class TestSessionArrow:
    def test_majority_up_gives_up_arrow(self):
        """主体 ETF 大多数涨 → ↗。"""
        tickers = [_mk_ticker(f"T{i:03d}", 0.01) for i in range(8)]
        tickers += [_mk_ticker(f"T{i:03d}", -0.01) for i in range(8, 10)]
        # 8 涨 2 跌，ratio = (8-2)/10 = 0.6 > 0.15
        s = _mk_session("2026-05-20-收", {}, tickers=tickers)
        assert _session_arrow(s, "A") == "↗"

    def test_majority_down_gives_down_arrow(self):
        """主体 ETF 大多数跌 → ↘。"""
        tickers = [_mk_ticker(f"T{i:03d}", -0.01) for i in range(8)]
        tickers += [_mk_ticker(f"T{i:03d}", 0.01) for i in range(8, 10)]
        s = _mk_session("2026-05-20-收", {}, tickers=tickers)
        assert _session_arrow(s, "A") == "↘"

    def test_balanced_gives_flat_arrow(self):
        """涨跌均衡（差值/total < 0.15）→ →。"""
        tickers = [_mk_ticker(f"T{i:03d}", 0.01) for i in range(5)]
        tickers += [_mk_ticker(f"T{i:03d}", -0.01) for i in range(5, 10)]
        # 5 涨 5 跌, ratio = 0 → →
        s = _mk_session("2026-05-20-收", {}, tickers=tickers)
        assert _session_arrow(s, "A") == "→"

    def test_cross_asset_excluded_from_arrow(self):
        """跨资产代表（SH518880=黄金）即使大涨也不影响方向计数。"""
        # 主体 2 涨 6 跌 → ↘；黄金+国债大涨，若被算进去会变 →
        main_up = [_mk_ticker(f"M{i:03d}", 0.02) for i in range(2)]
        main_down = [_mk_ticker(f"M{i:03d}", -0.02) for i in range(2, 8)]
        cross = [_mk_ticker(code, 0.05) for code in CROSS_CODES_A]  # 跨资产全涨
        tickers = main_up + main_down + cross
        s = _mk_session("2026-05-20-收", {}, tickers=tickers)
        assert _session_arrow(s, "A") == "↘"

    def test_cross_asset_all_down_no_effect(self):
        """跨资产全跌，主体全涨 → 箭头仍 ↗。"""
        main = [_mk_ticker(f"M{i:03d}", 0.02) for i in range(10)]
        cross = [_mk_ticker(code, -0.05) for code in CROSS_CODES_A]
        tickers = main + cross
        s = _mk_session("2026-05-20-收", {}, tickers=tickers)
        assert _session_arrow(s, "A") == "↗"

    def test_no_tickers_gives_flat(self):
        """无品种数据 → →（安全默认）。"""
        s = _mk_session("2026-05-20-收", {}, tickers=[])
        assert _session_arrow(s, "A") == "→"

    def test_none_pct_skipped(self):
        """today_pct=None 的品种不计入。"""
        tickers = [_mk_ticker("T001", None)] * 10 + [_mk_ticker("T002", 0.01)] * 8
        s = _mk_session("2026-05-20-收", {}, tickers=tickers)
        assert _session_arrow(s, "A") == "↗"


# ---------------------------------------------------------------------------
# 中级趋势标签规则
# ---------------------------------------------------------------------------

class TestMidLabelRules:
    def _window(self, counts: list[int], cat: str = "强反转") -> list[dict]:
        """用单一 cat 的 count 序列构造 window。"""
        return [_mk_session(f"2026-05-{i+1:02d}-收", {cat: c}) for i, c in enumerate(counts)]

    def test_consec_rise_triggers_at_threshold(self):
        """连增 3 段（default CAT_CONSEC_RISE_MIN）→ 触发标签。"""
        window = self._window([5, 6, 7, 8])  # 3 次连增
        tags = _rule_consec_rise(window, 3)
        assert any("强反转" in t and "时段连增" in t for t in tags)

    def test_consec_rise_not_triggered_below_threshold(self):
        """连增 2 段 < 3 → 不触发。"""
        window = self._window([5, 6, 7])  # 2 次连增
        tags = _rule_consec_rise(window, 2)
        assert tags == []

    def test_consec_rise_broken_resets(self):
        """中途有一次下降，重置计数，之后 1 次增不够触发。"""
        window = self._window([5, 6, 7, 6, 7])  # 最后 1 次增
        tags = _rule_consec_rise(window, 4)
        assert tags == []

    def test_consec_rise_count_in_label(self):
        """标签里的数字等于实际连增段数。"""
        window = self._window([3, 4, 5, 6, 7])  # 4 次连增
        tags = _rule_consec_rise(window, 4)
        assert any("4时段连增" in t for t in tags)

    def test_dominant_pct_triggers(self):
        """某象限占全池 ≥ 40% → 触发占比偏高标签。"""
        # 连续杀跌 20，其他各 5 → 20/35 ≈ 57% > 40%
        window = [_mk_session("2026-05-01-收", {"连续杀跌": 20, "强反转": 5,
                                                 "持续强化": 5, "反包修复": 5})]
        tags = _rule_dominant_pct(window, 0)
        assert any("连续杀跌占比偏高" in t for t in tags)

    def test_dominant_pct_not_triggered_below(self):
        """各象限均衡（每个 ≈ 25%）→ 不触发。"""
        window = [_mk_session("2026-05-01-收",
                               {"连续杀跌": 10, "强反转": 10, "持续强化": 10, "反包修复": 10})]
        tags = _rule_dominant_pct(window, 0)
        assert tags == []

    def test_no_tags_no_arrow_in_output(self):
        """无标签时输出行不含 '→ '（减少噪音）。"""
        # 所有象限均衡，无连增
        window = [_mk_session(f"2026-05-{i+1:02d}-收",
                               {"持续强化": 8, "反包修复": 8, "强反转": 8, "连续杀跌": 8})
                  for i in range(3)]
        out = _mid_memory_block(window, "A")
        for line in out.split("\n")[1:]:  # skip header
            assert "→" not in line, f"无标签行不应含 →：{line!r}"


# ---------------------------------------------------------------------------
# 远级：格式与边界
# ---------------------------------------------------------------------------

class TestFarMemoryBlock:
    def _history(self, n: int, ups: bool = True) -> list[dict]:
        tickers = [_mk_ticker(f"T{i:03d}", 0.01 if ups else -0.01) for i in range(20)]
        return [_mk_session(f"2026-05-{i+1:02d}-收",
                             {"强反转": 5, "连续杀跌": 5, "持续强化": 5, "反包修复": 5},
                             session_summary=f"第{i+1}段摘要",
                             tickers=tickers)
                for i in range(n)]

    def test_far_block_contains_all_sessions(self):
        """有 7 段历史 → 输出包含 7 个条目。"""
        history = self._history(7)
        out = _far_memory_block(history, "A")
        assert out.count("段前") + out.count("上一段") == 7

    def test_far_block_graceful_when_fewer_than_default(self):
        """只有 3 段 → 显示 3 段，不报错。"""
        history = self._history(3)
        out = _far_memory_block(history, "A")
        assert "3时段" in out or out.count("段前") + out.count("上一段") == 3

    def test_far_block_latest_labeled_as_prev(self):
        """最新一段标注为「上一段」。"""
        history = self._history(5)
        out = _far_memory_block(history, "A")
        assert "上一段" in out

    def test_far_block_arrow_matches_breadth(self):
        """全涨 tickers → ↗ 出现在输出中。"""
        history = self._history(3, ups=True)
        out = _far_memory_block(history, "A")
        assert "↗" in out

    def test_far_block_down_arrow_when_all_down(self):
        """全跌 tickers → ↘ 出现在输出中。"""
        history = self._history(3, ups=False)
        out = _far_memory_block(history, "A")
        assert "↘" in out

    def test_skeleton_session_appears_with_arrow(self):
        """骨架段照常出现且箭头照打。"""
        tickers = [_mk_ticker(f"T{i:03d}", 0.01) for i in range(10)]
        skel = _mk_session("2026-05-01-收", {"强反转": 5}, is_skeleton=True,
                           session_summary="", tickers=tickers)
        out = _far_memory_block([skel], "A")
        assert "上一段" in out
        assert "↗" in out
        assert "骨架" in out or "skeleton" in out.lower() or "无叙事" in out

    def test_empty_history_no_error(self):
        """空 history → 返回说明文字，不报错。"""
        out = _far_memory_block([], "A")
        assert "无历史数据" in out


# ---------------------------------------------------------------------------
# 三级结构：必要标记都出现在 prompt 里
# ---------------------------------------------------------------------------

class TestThreelevelMemoryBlock:
    def _make_history(self, n: int = 8) -> list[dict]:
        tickers = [_mk_ticker(f"T{i:03d}", 0.01) for i in range(10)]
        return [_mk_session(f"2026-05-{i+1:02d}-收",
                             {"持续强化": 5, "反包修复": 5, "强反转": 5, "连续杀跌": 5},
                             session_summary=f"摘要{i+1}", tickers=tickers)
                for i in range(n)]

    def test_all_three_levels_present(self):
        """prompt 必须包含远级/中级/近级三个标记。"""
        history = self._make_history()
        out = _threelevel_memory_block(history, "A")
        assert "远级" in out, "缺少远级标记"
        assert "中级" in out, "缺少中级标记"
        assert "近级" in out, "缺少近级标记"

    def test_three_level_header_present(self):
        """整体 header 说明三级结构。"""
        history = self._make_history()
        out = _threelevel_memory_block(history, "A")
        assert "三级历史记忆" in out

    def test_near_level_points_to_audit_section(self):
        """近级必须指向「预期审计对照」章节，而不是重复输出内容。"""
        history = self._make_history()
        out = _threelevel_memory_block(history, "A")
        assert "预期审计" in out

    def test_no_history_no_crash(self):
        """空历史 → 不崩溃，三级标记仍出现。"""
        out = _threelevel_memory_block([], "A")
        assert "远级" in out
        assert "中级" in out
        assert "近级" in out

    def test_mid_level_contains_category_names(self):
        """中级输出包含象限名称。"""
        history = self._make_history(5)
        out = _threelevel_memory_block(history, "A")
        for cat in ["持续强化", "强反转", "连续杀跌"]:
            assert cat in out, f"中级缺少象限名 {cat}"


# ---------------------------------------------------------------------------
# build_prompt 集成：不含历史的基线 + token 体量
# ---------------------------------------------------------------------------

class TestBuildPromptIntegration:
    def _minimal_session(self) -> dict:
        return {
            "label": "2026-05-24-收",
            "market": "A",
            "session_time": "close",
            "is_weekend_close": False,
            "tickers": [],
            "panel": {
                "up_count": 20, "down_count": 15, "flat_count": 4,
                "strong_up_count": 5, "strong_down_count": 3,
                "vol_expansion_count": 8, "vol_contraction_count": 4,
                "new_high_count_20d": 3, "new_low_count_20d": 1,
                "cross_asset_state": {}, "category_distribution": {},
                "breadth_alert": None,
            },
            "narrative": None,
        }

    def test_build_prompt_contains_three_level_header(self):
        """build_prompt 输出中三级记忆 header 必须出现。"""
        prompt = build_prompt("A", self._minimal_session(), history=[])
        assert "三级历史记忆" in prompt

    def test_build_prompt_audit_block_still_present(self):
        """_audit_context_block 仍然出现（近级的实际内容）。"""
        prompt = build_prompt("A", self._minimal_session(), history=[])
        assert "预期审计" in prompt

    def test_no_old_history_header(self):
        """旧的"历史上下文"平铺 header 不再出现（已被三级取代）。"""
        prompt = build_prompt("A", self._minimal_session(), history=[])
        assert "历史上下文（近" not in prompt

    def test_token_not_inflated_vs_baseline(self):
        """三级记忆是压缩策略：prompt 长度应 ≤ 旧版(20段平铺)× 1.5。

        构造 20 段历史（旧版最大展示窗口），对比旧版长度。
        阈值 1.5 留足余量，主要防「三级=堆料」的意外膨胀。
        """
        tickers = [_mk_ticker(f"T{i:03d}", 0.01) for i in range(20)]
        history = [_mk_session(f"2026-05-{(i % 28) + 1:02d}-收",
                                {"持续强化": 5, "反包修复": 5, "强反转": 5, "连续杀跌": 5},
                                session_summary="这是一段典型的 session_summary，大约 50 字以内，" +
                                                "用于测试 token 体量对比。",
                                tickers=tickers)
                   for i in range(20)]
        target = self._minimal_session()

        new_prompt = build_prompt("A", target, history=history)

        # 模拟旧版长度：_history_block(history, n=20) 的大小是旧版的主要差异
        # 旧版每条 ~100 chars，20 条 ~2000 chars
        # 新版远级 7 条 + 中级 5 条，也在同量级，不应超 1.5 倍
        old_estimate = len(new_prompt)  # 相对自身：只要不超 60KB 视为合理
        assert len(new_prompt) < 60_000, f"prompt 超 60KB，疑似堆料：{len(new_prompt)}"
        # 更精确：与"20 段纯平铺"的合成基线比较
        flat_lines = [f"  [LLM] 2026-05-{(i % 28)+1:02d}-收: 这是一段典型的 session_summary" +
                      "，大约 50 字以内，用于测试 token 体量对比。"
                      for i in range(20)]
        flat_baseline = "\n".join(flat_lines)
        # 新版三级不应比旧版平铺多出超过 1.5 倍的字符
        # (三级含中级象限分布，会比纯 summary 多些，但远级只 7 段，整体应更精简)
        three_level_chars = len(_threelevel_memory_block(history, "A"))
        flat_chars = len(flat_baseline)
        assert three_level_chars <= flat_chars * 1.5, (
            f"三级记忆 {three_level_chars} chars > 旧版平铺 {flat_chars} × 1.5"
        )
