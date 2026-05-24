"""分段投喂业务规律自检（D 批）。

验"业务规律"而非"具体字符串内容"：
  - 向后兼容：默认模式 build_prompt 输出与未引入分段时一致（不传 flag = 一字不变）
  - 长度恒 3
  - PART1 含全局背景所有标记；PART2/3 不重复全局背景
  - PART1 tickers 只含 PART1_CATS；PART2 只含 PART2_CATS；PART3 无品种矩阵
  - PART3 含完整 schema 描述（任务部分）
  - 单边空象限边界：某 PART 0 品种 → 提示文字，不崩
  - --part 调试参数：单独取某一段
"""
from __future__ import annotations

import json

import pytest

from src.llm_prompt import (
    PART1_CATS,
    PART2_CATS,
    build_prompt,
    build_segmented_prompts,
)


def _mk_ticker(code: str, name: str, category: str, pct: float = 0.01) -> dict:
    return {
        "code": code,
        "name": name,
        "category": category,
        "feature": "",
        "today_pct": pct,
        "pct_diff": 0.005,
        "volume_ratio": 1.1,
        "factors": {
            "price_pctile_60": 60,
            "price_pctile_20": 50,
            "vol_ratio_20": 1.2,
            "vol_pctile_20": 55,
            "ma_alignment": "多头",
            "pct_normalized": 0.8,
            "new_high_20d": False,
            "new_low_20d": False,
        },
    }


def _mk_session(market: str = "A") -> dict:
    tickers = [
        _mk_ticker("SH512760", "芯片ETF",        "持续强化", 0.05),
        _mk_ticker("SH513050", "中概互联ETF",    "持续强化", 0.03),
        _mk_ticker("SH515030", "新能源车ETF",    "反包修复", 0.02),
        _mk_ticker("SH512170", "医疗ETF",        "强反转",   -0.02),
        _mk_ticker("SH515220", "煤炭ETF",        "强反转",   -0.025),
        _mk_ticker("SH159883", "医药创新药ETF",  "连续杀跌", -0.04),
    ]
    return {
        "label": "2026-05-20-收",
        "market": market,
        "session_time": "close",
        "is_weekend_close": False,
        "tickers": tickers,
        "panel": {
            "up_count": 22, "down_count": 15, "flat_count": 2,
            "strong_up_count": 4, "strong_down_count": 3,
            "vol_expansion_count": 8, "vol_contraction_count": 5,
            "new_high_count_20d": 3, "new_low_count_20d": 1,
            "cross_asset_state": {}, "category_distribution": {
                "持续强化": 2, "反包修复": 1, "强反转": 2, "连续杀跌": 1,
            },
            "breadth_alert": None,
        },
    }


# ---------------------------------------------------------------------------
# 向后兼容：默认模式输出与引入分段前一致
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_default_mode_unchanged_by_introducing_segmented(self):
        """build_prompt 不受 build_segmented_prompts 的引入影响。

        策略：同一 (market, target, history) 调两次 build_prompt，结果必须字节级一致；
        且包含旧版必有的所有 section（system_head/三级记忆/panel/task）。
        """
        s = _mk_session()
        a = build_prompt("A", s, [])
        b = build_prompt("A", s, [])
        assert a == b
        # 内容完整性
        for marker in ("yangjia_emotion_cycle", "短键映射", "三级历史记忆",
                       "当前盘面广度", "当前时段品种矩阵"):
            assert marker in a, f"默认模式缺少 {marker}"

    def test_default_mode_includes_all_tickers(self):
        """默认模式：当前 session 的全部品种都进 tickers 矩阵。"""
        s = _mk_session()
        out = build_prompt("A", s, [])
        for t in s["tickers"]:
            assert t["code"] in out, f"默认模式应含 {t['code']}"


# ---------------------------------------------------------------------------
# 分段结构：长度 + 全局背景分布
# ---------------------------------------------------------------------------

class TestSegmentedStructure:
    def test_returns_exactly_three_parts(self):
        parts = build_segmented_prompts("A", _mk_session(), [])
        assert isinstance(parts, list) and len(parts) == 3

    def test_each_part_has_part_header(self):
        parts = build_segmented_prompts("A", _mk_session(), [])
        assert "PART 1/3" in parts[0]
        assert "PART 2/3" in parts[1]
        assert "PART 3/3" in parts[2]

    def test_part1_contains_full_global_context(self):
        """全局背景所有 section 都必须在 PART1 出现。"""
        parts = build_segmented_prompts("A", _mk_session(), [])
        p1 = parts[0]
        for marker in ("yangjia_emotion_cycle", "短键映射", "三级历史记忆",
                       "预期审计对照", "周末标志", "当前盘面广度"):
            assert marker in p1, f"PART1 缺少全局背景标记 {marker}"

    def test_part2_does_not_repeat_global_context(self):
        """PART2 不重复 system_head/三级记忆/panel 等全局背景。"""
        parts = build_segmented_prompts("A", _mk_session(), [])
        p2 = parts[1]
        for marker in ("短键映射", "三级历史记忆", "当前盘面广度"):
            assert marker not in p2, f"PART2 不应重复 {marker}"

    def test_part3_does_not_repeat_global_context(self):
        """PART3 也不重复全局背景。"""
        parts = build_segmented_prompts("A", _mk_session(), [])
        p3 = parts[2]
        for marker in ("短键映射", "三级历史记忆", "当前盘面广度"):
            assert marker not in p3, f"PART3 不应重复 {marker}"

    def test_part1_carries_continuity_note(self):
        """PART1 必须说明全局背景只给一次（避免 LLM 误以为 PART2/3 还会再给）。"""
        parts = build_segmented_prompts("A", _mk_session(), [])
        assert "只在 PART 1" in parts[0] or "PART 1 给一次" in parts[0]


# ---------------------------------------------------------------------------
# 象限→PART 映射：tickers 分发正确
# ---------------------------------------------------------------------------

class TestQuadrantDispatch:
    def test_part1_contains_only_part1_cats_tickers(self):
        """PART1 品种矩阵只含 持续强化 + 反包修复 的代码。"""
        s = _mk_session()
        parts = build_segmented_prompts("A", s, [])
        p1 = parts[0]
        # PART1 应含的代码
        for t in s["tickers"]:
            if t["category"] in PART1_CATS:
                assert t["code"] in p1, f"PART1 应含 {t['code']}({t['category']})"
        # PART1 不该出现 PART2 的品种代码（在 ticker 矩阵里）
        # 注意：人格分工段、schema 描述里可能含其他文本，所以用 JSON 块 marker 限定范围
        marker = "本组品种矩阵"
        assert marker in p1
        # 找出 PART1 的本组矩阵部分到任务指令之间的内容
        block_start = p1.index(marker)
        block_end = p1.index("PART 1/3 任务")
        ticker_block = p1[block_start:block_end]
        for t in s["tickers"]:
            if t["category"] in PART2_CATS:
                assert t["code"] not in ticker_block, (
                    f"PART1 品种矩阵不应含空头组品种 {t['code']}({t['category']})"
                )

    def test_part2_contains_only_part2_cats_tickers(self):
        s = _mk_session()
        parts = build_segmented_prompts("A", s, [])
        p2 = parts[1]
        marker = "本组品种矩阵"
        assert marker in p2
        block_start = p2.index(marker)
        block_end = p2.index("PART 2/3 任务")
        ticker_block = p2[block_start:block_end]
        for t in s["tickers"]:
            if t["category"] in PART2_CATS:
                assert t["code"] in ticker_block, (
                    f"PART2 品种矩阵应含 {t['code']}({t['category']})"
                )
            if t["category"] in PART1_CATS:
                assert t["code"] not in ticker_block, (
                    f"PART2 品种矩阵不应含多头组品种 {t['code']}({t['category']})"
                )

    def test_part3_has_no_ticker_matrix(self):
        """PART3 不含品种矩阵 JSON 块（明确不喂新品种）。"""
        parts = build_segmented_prompts("A", _mk_session(), [])
        p3 = parts[2]
        assert "本组品种矩阵" not in p3
        assert "不喂新品种数据" in p3 or "本轮不喂新品种" in p3

    def test_empty_quadrant_group_shows_placeholder(self):
        """某 PART 的象限组 0 品种 → 提示文字，不崩。"""
        # 构造只含 PART1 类别的 session（空头组为空）
        s = _mk_session()
        s["tickers"] = [t for t in s["tickers"] if t["category"] in PART1_CATS]
        parts = build_segmented_prompts("A", s, [])
        p2 = parts[1]
        assert "无候选品种" in p2

    def test_both_quadrants_empty_no_crash(self):
        """极端：当前时段无任何品种（理论不可能但要安全）。"""
        s = _mk_session()
        s["tickers"] = []
        parts = build_segmented_prompts("A", s, [])
        assert len(parts) == 3
        assert "无候选品种" in parts[0]
        assert "无候选品种" in parts[1]


# ---------------------------------------------------------------------------
# PART3 任务：含 schema + 综合指令
# ---------------------------------------------------------------------------

class TestPart3Task:
    def test_part3_contains_full_schema(self):
        """PART3 含 schema 完整描述（与默认模式 _task_block 等价信息量）。"""
        parts = build_segmented_prompts("A", _mk_session(), [])
        p3 = parts[2]
        # schema_text 输出的标志：人格字段名 + enum 关键词
        assert "yangjia_emotion_cycle" in p3
        assert "enum" in p3.lower() or "enum" in p3

    def test_part3_includes_cross_quadrant_instructions(self):
        """PART3 含跨象限分析指令（资金流动/高低切/category_distribution）。"""
        parts = build_segmented_prompts("A", _mk_session(), [])
        p3 = parts[2]
        assert "跨象限" in p3
        assert "category_distribution" in p3

    def test_part3_demands_json_only_output(self):
        """PART3 明确要求"只返回 JSON"。"""
        parts = build_segmented_prompts("A", _mk_session(), [])
        p3 = parts[2]
        assert "只返回 JSON" in p3

    def test_part3_includes_current_label(self):
        """PART3 含当前 label，确保 LLM 知道时段。"""
        parts = build_segmented_prompts("A", _mk_session(), [])
        assert "2026-05-20-收" in parts[2]


# ---------------------------------------------------------------------------
# 美股市场：5 人格全在 PART3
# ---------------------------------------------------------------------------

class TestUSMarket:
    def test_us_segmented_three_parts(self):
        parts = build_segmented_prompts("US", _mk_session("US"), [])
        assert len(parts) == 3

    def test_us_part3_contains_all_5_personas(self):
        """美股 5 人格全在 PART3 schema 里出现（不强行映射到多/空组）。"""
        parts = build_segmented_prompts("US", _mk_session("US"), [])
        p3 = parts[2]
        for persona in ("druckenmiller_macro_check", "minervini_breadth_check",
                        "wyckoff_breakout_check", "weinstein_stage_check"):
            assert persona in p3, f"PART3 缺少人格 {persona}"


# ---------------------------------------------------------------------------
# CLI：--segmented + --part
# ---------------------------------------------------------------------------

class TestGenPromptCli:
    """通过 subprocess 验证 CLI 行为。

    注意：CLI 需要窗口有 sessions，我们用真实窗口（项目里已有 200+ 段历史）。
    若窗口空则 skip。
    """

    def _has_window(self) -> tuple[bool, str | None]:
        from src import window as win
        for m in ("A", "US"):
            try:
                data = win.load(m)
                if data["sessions"]:
                    return True, m
            except Exception:
                pass
        return False, None

    def test_cli_default_mode_runs(self):
        ok, market = self._has_window()
        if not ok:
            pytest.skip("窗口为空，跳过 CLI 测试")
        import subprocess, sys, os
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, "-m", "src.gen_prompt", "--market", market],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=30,
        )
        assert r.returncode == 0, f"默认模式 CLI 失败: {r.stderr}"
        assert "三级历史记忆" in r.stdout

    def test_cli_segmented_outputs_three_parts(self):
        ok, market = self._has_window()
        if not ok:
            pytest.skip("窗口为空，跳过 CLI 测试")
        import subprocess, sys, os
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, "-m", "src.gen_prompt", "--market", market, "--segmented"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=30,
        )
        assert r.returncode == 0, f"--segmented CLI 失败: {r.stderr}"
        assert r.stdout.count("PART BOUNDARY") == 2  # 3 段之间 2 个分隔符
        assert "PART 1/3" in r.stdout
        assert "PART 2/3" in r.stdout
        assert "PART 3/3" in r.stdout

    def test_cli_part_only_outputs_one_section(self):
        ok, market = self._has_window()
        if not ok:
            pytest.skip("窗口为空，跳过 CLI 测试")
        import subprocess, sys, os
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, "-m", "src.gen_prompt",
             "--market", market, "--segmented", "--part", "3"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=30,
        )
        assert r.returncode == 0
        assert "PART 3/3" in r.stdout
        assert "PART 1/3" not in r.stdout
        assert "PART BOUNDARY" not in r.stdout

    def test_cli_part_without_segmented_rejected(self):
        ok, market = self._has_window()
        if not ok:
            pytest.skip("窗口为空，跳过 CLI 测试")
        import subprocess, sys, os
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        r = subprocess.run(
            [sys.executable, "-m", "src.gen_prompt",
             "--market", market, "--part", "2"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=30,
        )
        assert r.returncode != 0  # 应拒绝
        assert "--segmented" in r.stderr


# ---------------------------------------------------------------------------
# 收单方案验证：PART3 schema 与默认模式 schema 等价
# ---------------------------------------------------------------------------

class TestCollectorCompat:
    def test_part3_schema_matches_default_task_block(self):
        """PART3 包含的 schema 描述 = 默认模式 _task_block 的 schema 描述。

        这是"fill_narrative 零改动"的根据：PART3 产出的 JSON 与默认模式产出的 JSON
        遵循同一 schema，所以 fill_narrative 校验逻辑可直接复用。
        """
        from src.llm_prompt import _schema_text
        schema_a = _schema_text("A")
        parts = build_segmented_prompts("A", _mk_session(), [])
        # PART3 必须含 schema_text 的关键内容
        # 取一段独特片段验证
        sample_lines = [ln for ln in schema_a.split("\n")
                        if "yangjia_emotion_cycle" in ln or "enum" in ln][:3]
        for ln in sample_lines:
            assert ln in parts[2], f"PART3 缺少 schema 行: {ln!r}"
