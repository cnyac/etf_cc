"""render_html.py 单元测试 — 渲染产物含必要结构。"""
import json
import os
import pytest

from src import render_html as rh
from src import window as win
from src import color_palette as cp


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    wd = tmp_path / "window"
    sd = tmp_path / "snapshots"
    rd = tmp_path / "reports"
    wd.mkdir()
    (sd / "a").mkdir(parents=True)
    (rd / "a").mkdir(parents=True)
    monkeypatch.setattr(win, "WINDOW_DIR", str(wd))
    monkeypatch.setattr(win, "SNAPSHOT_DIR", str(sd))
    monkeypatch.setattr(rh, "REPORTS_DIR", str(rd))
    monkeypatch.setattr(cp, "PALETTE_PATH", str(wd / "color_palette.json"))
    return tmp_path


def _mk_session(label="2026-05-20-收", market="A", outlier=False):
    return {
        "label": label, "market": market, "session_time": "close",
        "trade_date": "2026-05-20",
        "tickers": [
            {"code": "SH510050", "name": "上证50ETF",
             "today_pct": 0.009, "yest_pct": 0.003, "pct_diff": 0.006,
             "category": "持续强化", "feature": "龙1", "compliance": "完全符合",
             "annotation": None,
             "new_high_20d": True, "new_low_20d": False,
             "factors": {
                 "price_pctile_60": 75, "vol_ratio_20": 1.4, "vol_pctile_20": 70,
                 "ma_alignment": "多头",
                 "pct_normalized": 3.5 if outlier else 0.5,
                 "new_high_20d": True, "new_low_20d": False,
             }},
            {"code": "SH518880", "name": "黄金ETF",
             "today_pct": -0.015, "yest_pct": 0.002, "pct_diff": -0.017,
             "category": "强反转", "feature": "最增量", "compliance": "完全符合",
             "annotation": {"color": "#FFE4B5", "note": "黄金破位"},
             "new_high_20d": False, "new_low_20d": True,
             "factors": {
                 "price_pctile_60": 3, "vol_ratio_20": 1.4, "vol_pctile_20": 95,
                 "ma_alignment": "空头", "pct_normalized": -1.3,
                 "new_high_20d": False, "new_low_20d": True,
             }},
        ],
        "panel": {
            "up_count": 15, "down_count": 24, "flat_count": 0,
            "strong_up_count": 1, "strong_down_count": 5,
            "vol_expansion_count": 2, "vol_contraction_count": 8,
            "new_high_count_20d": 4, "new_low_count_20d": 13,
            "cross_asset_state": {"treasury_10y": "flat", "treasury_30y": "flat",
                                   "gold": "down", "oil": "down"},
            "category_distribution": {"持续强化": 9, "强反转": 17,
                                      "反包修复": 6, "连续杀跌": 7},
        },
        "narrative": None,
        "tracking": {"rating_history": []},
    }


def test_render_basic_structure(tmp_env):
    win.append_session("A", _mk_session())
    fp = rh.render("A", "2026-05-20-收")
    with open(fp, "r", encoding="utf-8") as f:
        html = f.read()
    # 视觉规范字体
    assert "华文中宋" in html and "黑体" in html and "楷体" in html and "仿宋" in html
    # 颜色规范
    assert "#FF0000" in html and "#00008B" in html
    # 嵌入数据
    assert '<script type="application/json" id="snapshot">' in html
    assert '<script type="application/json" id="annotations">' in html
    assert '<script type="application/json" id="known_palette">' in html
    # 分类
    assert "持续强化" in html
    assert "强反转" in html
    # 标签
    assert "龙1" in html
    assert "最增量" in html


def test_render_outlier_marks_row(tmp_env):
    win.append_session("A", _mk_session(outlier=True))
    fp = rh.render("A", "2026-05-20-收")
    html = open(fp, "r", encoding="utf-8").read()
    assert "outlier-row" in html
    assert "⚠" in html


def test_render_new_high_low_marks(tmp_env):
    win.append_session("A", _mk_session())
    fp = rh.render("A", "2026-05-20-收")
    html = open(fp, "r", encoding="utf-8").read()
    assert "★" in html  # new_high
    assert "▼" in html  # new_low


# --- E.1：新因子 tooltip（含 5 个新因子时出现 title=）---

def _mk_session_with_new_factors():
    """构造一个含全部 5 个新因子的 session（用于验 tooltip）。"""
    s = _mk_session()
    s["tickers"][0]["factors"].update({
        "rs_vs_benchmark": 0.015,
        "vol_std_20": 0.0162,
        "er60": 0.85,
        "mdd60": 0.125,
        "slope_seg": [0.08, -0.03, 0.04],
    })
    # 第 2 只品种特意只填部分新因子（null 用例）
    s["tickers"][1]["factors"].update({
        "rs_vs_benchmark": None,
        "vol_std_20": 0.024,
        "er60": None,
        "mdd60": 0.18,
        "slope_seg": None,
    })
    return s


def test_render_new_factor_tooltips_appear_when_present(tmp_env):
    """5 个新因子有值时，对应列出现 title= 属性。"""
    win.append_session("A", _mk_session_with_new_factors())
    fp = rh.render("A", "2026-05-20-收")
    html = open(fp, "r", encoding="utf-8").read()
    assert "相对基准强度" in html, "rs_vs_benchmark tooltip 应在差值列"
    assert "20日收益率标准差" in html, "vol_std_20 tooltip 应在量能列"
    assert "60日路径效率" in html, "er60 tooltip 应在价位列"
    assert "60日最大回撤" in html, "mdd60 tooltip 应在价位列"
    assert "分段斜率" in html, "slope_seg tooltip 应在价位列"


def test_render_no_title_when_all_new_factors_null(tmp_env):
    """新因子全 null → 不出现对应 tooltip 文本（不污染视觉）。"""
    # _mk_session 默认不带新因子键 = 全 null
    win.append_session("A", _mk_session())
    fp = rh.render("A", "2026-05-20-收")
    html = open(fp, "r", encoding="utf-8").read()
    assert "相对基准强度" not in html
    assert "20日收益率标准差" not in html
    assert "60日路径效率" not in html
    assert "60日最大回撤" not in html
    assert "分段斜率" not in html


# --- E.2：象限小结 + 组整体定性 渲染 ---

def _mk_session_with_summaries():
    """构造一个含 quadrant_summaries + group_qualitative 的 session。

    特意补齐 4 个象限的 ticker（否则缺数据的象限无表格、其小结也不渲染）。
    """
    s = _mk_session()
    # 补 反包修复 + 连续杀跌 各 1 只
    s["tickers"].append({
        "code": "SH515000", "name": "科技ETF",
        "today_pct": 0.012, "yest_pct": -0.008, "pct_diff": 0.020,
        "category": "反包修复", "feature": "修复龙1", "compliance": "完全符合",
        "annotation": None,
        "new_high_20d": False, "new_low_20d": False,
        "factors": {
            "price_pctile_60": 55, "vol_ratio_20": 1.1, "vol_pctile_20": 60,
            "ma_alignment": "震荡", "pct_normalized": 1.5,
            "new_high_20d": False, "new_low_20d": False,
        },
    })
    s["tickers"].append({
        "code": "SH512170", "name": "医疗ETF",
        "today_pct": -0.022, "yest_pct": -0.010, "pct_diff": -0.012,
        "category": "连续杀跌", "feature": "", "compliance": "完全符合",
        "annotation": None,
        "new_high_20d": False, "new_low_20d": False,
        "factors": {
            "price_pctile_60": 8, "vol_ratio_20": 0.7, "vol_pctile_20": 25,
            "ma_alignment": "空头", "pct_normalized": -2.1,
            "new_high_20d": False, "new_low_20d": False,
        },
    })
    s["narrative"] = {
        "is_skeleton": False,
        "session_summary": "测试摘要 包含若干象限分析",
        "quadrant_summaries": {
            "持续强化": "持续强化象限龙头 SH510050 上证50ETF 量价配合良好，分位 P75，远离均线但未现 **异常** 放量。给综合轮：核心权重持续主导。",
            "反包修复": "反包修复象限内未见龙头候选，整体反包动能偏弱，需警惕昨日抢反弹品种次日缩量阴跌。给综合轮：高低切尚未启动。",
            "强反转": "强反转象限黄金 ETF SH518880 量能爆掉但价格新低，典型 **异常** 信号，做多动能转弱。给综合轮：警惕避险资产分化。",
        },
        "group_qualitative": {
            "bull_group": "多头组整体偏稳，龙头未见松动，资金继续做多权重。",
            "bear_group": "空头组防守压力上升，避险品种异动需要关注。",
        },
    }
    return s


def test_render_quadrant_summaries_appear(tmp_env):
    """quadrant_summaries 各 cat 内容必须出现在 HTML 里，并标注【XX · 小结】。"""
    win.append_session("A", _mk_session_with_summaries())
    fp = rh.render("A", "2026-05-20-收")
    html = open(fp, "r", encoding="utf-8").read()
    assert "持续强化 · 小结" in html
    assert "反包修复 · 小结" in html
    assert "强反转 · 小结" in html
    assert "SH510050 上证50ETF" in html  # 持续强化小结内容片段
    assert "高低切尚未启动" in html        # 反包修复小结片段


def test_render_group_qualitative_positioning(tmp_env):
    """方案 (ii)：多头组定性在反包修复表后、空头组定性在连续杀跌表后。

    用 HTML 字符串位置验：bull_group 出现位置 < 强反转表 < bear_group 出现位置。
    """
    win.append_session("A", _mk_session_with_summaries())
    fp = rh.render("A", "2026-05-20-收")
    html = open(fp, "r", encoding="utf-8").read()
    assert "多头组整体定性" in html
    assert "空头组整体定性" in html
    bull_pos = html.index("多头组整体定性")
    bear_pos = html.index("空头组整体定性")
    fanzhuan_pos = html.index("强反转 · 小结")  # 强反转表+小结的位置
    assert bull_pos < fanzhuan_pos < bear_pos, (
        f"组定性位置错乱：bull={bull_pos} fanzhuan={fanzhuan_pos} bear={bear_pos}"
    )


def test_render_no_summary_section_when_narrative_null(tmp_env):
    """narrative=None 时 §3 不出现小结 div 实例（CSS 类定义在 <style> 里仍在，
    但不应有 <div class="quadrant-summary"> / <div class="group-qualitative"> 实例）。"""
    s = _mk_session()
    s["narrative"] = None
    win.append_session("A", s)
    fp = rh.render("A", "2026-05-20-收")
    html = open(fp, "r", encoding="utf-8").read()
    assert '<div class="quadrant-summary"' not in html
    assert '<div class="group-qualitative"' not in html


def test_render_partial_summaries_no_crash(tmp_env):
    """只填部分象限/只填一组定性 → 渲染正常，缺失部分不出现。"""
    s = _mk_session()
    s["narrative"] = {
        "is_skeleton": False,
        "session_summary": "部分填写测试",
        "quadrant_summaries": {
            "持续强化": "只有持续强化象限有小结，覆盖龙头与量价共性，给综合轮：风格未变。",
        },
        "group_qualitative": {"bull_group": "只填多头组定性测试段落"},
    }
    win.append_session("A", s)
    fp = rh.render("A", "2026-05-20-收")
    html = open(fp, "r", encoding="utf-8").read()
    assert "持续强化 · 小结" in html
    assert "反包修复 · 小结" not in html
    assert "多头组整体定性" in html
    assert "空头组整体定性" not in html


# --- F.1：批注按行独立显示 + 只有当前时段可编辑 ---

def _mk_session_with_annotation(label: str, code: str, color: str | None, note: str | None,
                                 trade_date: str | None = None):
    """构造单时段单 ticker 的 session，专用于多时段批注测试。"""
    s = _mk_session(label=label)
    s["trade_date"] = trade_date or label[:10]
    s["session_time"] = "close"
    ann = {"color": color, "note": note} if (color or note) else None
    s["tickers"] = [{
        "code": code, "name": "测试ETF",
        "today_pct": 0.01, "yest_pct": 0.005, "pct_diff": 0.005,
        "category": "持续强化", "feature": "", "compliance": "完全符合",
        "annotation": ann,
        "new_high_20d": False, "new_low_20d": False,
        "factors": {"price_pctile_60": 60, "vol_ratio_20": 1.1, "vol_pctile_20": 55,
                    "ma_alignment": "多头", "pct_normalized": 0.5,
                    "new_high_20d": False, "new_low_20d": False},
    }]
    return s


def _persist_session_with_snapshot(market: str, s: dict):
    """既写窗口、又写 snapshot 文件——render 的 §3 邻近时段从 snapshots/ 直读，
    不写 snapshot 的话 _load_neighbor_sessions 找不到历史行，§3 只剩 1 行。"""
    import json as _json
    win.append_session(market, s)
    snap_dir = os.path.join(win.SNAPSHOT_DIR, market.lower())
    os.makedirs(snap_dir, exist_ok=True)
    with open(os.path.join(snap_dir, f"{s['label']}.json"), "w", encoding="utf-8") as f:
        _json.dump(s, f, ensure_ascii=False)


def test_render_per_row_annotation_independent(tmp_env):
    """3 段各写不同批注 → §3 表格里每行显示各自时段的批注。"""
    # 5/20 黄色 "破位预警"，5/21 无批注，5/22 红色 "止损"
    _persist_session_with_snapshot("A", _mk_session_with_annotation(
        "2026-05-20-收", "SH510050", "#FFE4B5", "破位预警", "2026-05-20"))
    _persist_session_with_snapshot("A", _mk_session_with_annotation(
        "2026-05-21-收", "SH510050", None, None, "2026-05-21"))
    _persist_session_with_snapshot("A", _mk_session_with_annotation(
        "2026-05-22-收", "SH510050", "#FFCCCC", "止损", "2026-05-22"))
    fp = rh.render("A", "2026-05-22-收")
    html = open(fp, "r", encoding="utf-8").read()
    # 三个时段的批注内容都应出现
    assert "破位预警" in html, "5/20 批注应显示在该行"
    assert "止损" in html, "5/22 批注应显示在该行"
    # 5/21 行无批注 → 不该出现误置的内容（用占位符 "—" 显示，下面会单独验）
    # 三个颜色都应出现在 --row-bg 里（按行独立染色）
    assert "#FFE4B5" in html and "#FFCCCC" in html


def test_render_current_row_editable_only(tmp_env):
    """只有当前时段（最末行）的批注 cell 含 data-anno-cell-for；历史行不含。"""
    _persist_session_with_snapshot("A", _mk_session_with_annotation(
        "2026-05-20-收", "SH510050", "#FFE4B5", "破位预警", "2026-05-20"))
    _persist_session_with_snapshot("A", _mk_session_with_annotation(
        "2026-05-22-收", "SH510050", None, None, "2026-05-22"))
    fp = rh.render("A", "2026-05-22-收")
    html = open(fp, "r", encoding="utf-8").read()
    # 全文 data-anno-cell-for 应仅出现 1 次（仅当前时段编辑入口）
    assert html.count('data-anno-cell-for="SH510050"') == 1, (
        f"data-anno-cell-for 应只出现 1 次（当前时段），实际 "
        f"{html.count('data-anno-cell-for=\"SH510050\"')} 次"
    )
    # 历史行的 cell 用 annotation-cell-historical class
    assert "annotation-cell-historical" in html


def test_render_no_more_rowspan_on_annotation(tmp_env):
    """批注 cell 不再用 rowspan。"""
    _persist_session_with_snapshot("A", _mk_session_with_annotation(
        "2026-05-20-收", "SH510050", "#FFE4B5", "笔记 A", "2026-05-20"))
    _persist_session_with_snapshot("A", _mk_session_with_annotation(
        "2026-05-22-收", "SH510050", "#CCFFCC", "笔记 B", "2026-05-22"))
    fp = rh.render("A", "2026-05-22-收")
    html = open(fp, "r", encoding="utf-8").read()
    # 旧版的 rowspan annotation cell 标志应消失
    assert 'rowspan="2" class="annotation-cell"' not in html
    assert 'rowspan="3" class="annotation-cell"' not in html


def test_render_per_row_background_via_css_var(tmp_env):
    """按行染色用 --row-bg CSS 变量，不是 background-color 直接绑 tr。"""
    _persist_session_with_snapshot("A", _mk_session_with_annotation(
        "2026-05-22-收", "SH510050", "#FFE4B5", "测试笔记", "2026-05-22"))
    fp = rh.render("A", "2026-05-22-收")
    html = open(fp, "r", encoding="utf-8").read()
    # 应出现 --row-bg:<color>; 而不是直接 background-color
    assert "--row-bg:#FFE4B5" in html
    # 校验 CSS 规则存在（只染非 rowspan 列）
    assert "tr[style*=\"--row-bg\"] > td:not([rowspan])" in html


def test_render_group_name_cells_have_rowspan(tmp_env):
    """代码/名称列保留 rowspan（不参与按行染色，作为视觉头部）。"""
    _persist_session_with_snapshot("A", _mk_session_with_annotation(
        "2026-05-22-收", "SH510050", "#FFE4B5", "笔记", "2026-05-22"))
    fp = rh.render("A", "2026-05-22-收")
    html = open(fp, "r", encoding="utf-8").read()
    # group-name-cell 类用于代码/名称 rowspan 单元格
    assert "group-name-cell" in html


def test_render_partial_new_factors_tooltip(tmp_env):
    """部分新因子有值、部分 null → 只显示有值的，不报错。"""
    win.append_session("A", _mk_session_with_new_factors())
    fp = rh.render("A", "2026-05-20-收")
    html = open(fp, "r", encoding="utf-8").read()
    # 第二只 ticker rs_vs_benchmark=None, mdd60=有值, slope_seg=None
    # 整页应能含 mdd60 tooltip（来自任一品种），不应崩
    assert "60日最大回撤" in html


def test_render_annotation_payload_embedded(tmp_env):
    win.append_session("A", _mk_session())
    fp = rh.render("A", "2026-05-20-收")
    html = open(fp, "r", encoding="utf-8").read()
    # 抽出 annotations script 内容
    import re
    m = re.search(r'<script type="application/json" id="annotations">(.*?)</script>', html, re.S)
    assert m
    ann = json.loads(m.group(1))
    assert "SH518880" in ann
    assert ann["SH518880"]["color"] == "#FFE4B5"


def test_render_us_includes_extras(tmp_env):
    s = _mk_session(market="US")
    s["panel"]["above_ma150_count"] = 24
    s["panel"]["spy_iwm_divergence"] = 0.005
    win.append_session("US", s)
    fp = rh.render("US", "2026-05-20-收")
    html = open(fp, "r", encoding="utf-8").read()
    assert "站上 MA150" in html
    assert "SPY-IWM" in html


def test_render_fallback_to_snapshot_archive(tmp_env):
    """label 不在 window 时回退到 snapshots/<label>.json。"""
    s = _mk_session(label="L_old")
    win.archive_to_snapshot("A", s)  # 只归档不入窗口
    fp = rh.render("A", "L_old")
    assert os.path.exists(fp)


def test_pct_fmt_and_class():
    assert rh._pct_fmt(0.01) == "+1.00%"
    assert rh._pct_fmt(-0.015) == "-1.50%"
    assert rh._pct_fmt(None) == "—"
    assert rh._pct_class(0.01) == "up"
    assert rh._pct_class(-0.01) == "down"
    assert rh._pct_class(0) == "flat"
    assert rh._pct_class(None) == "flat"


def test_pick_tracking_codes_prefers_features(tmp_env):
    s = _mk_session()
    codes = rh._pick_tracking_codes(s, max_n=5)
    # 当前 session 的特征做兜底排序也会入选
    assert "SH510050" in codes
    assert "SH518880" in codes


def test_pick_tracking_excludes_pure_volume_only_tag(tmp_env):
    # 上一时段 feature 只有"最增量" → 不应入名单（除非有其它来源补足）
    prev = _mk_session(label="2026-05-19-收")
    prev["tickers"][0]["feature"] = "最增量"      # 纯量能标签
    prev["tickers"][1]["feature"] = "龙1，最增量"   # 含位置标签 → 入名单
    curr = _mk_session(label="2026-05-20-收")
    codes = rh._pick_tracking_codes(curr, history=[prev], max_n=2)
    assert "SH518880" in codes      # 龙1，最增量
    # SH510050 仅最增量被剔，但 max_n=2 时兜底逻辑可能补回；用 max_n=1 验证
    codes_strict = rh._pick_tracking_codes(curr, history=[prev], max_n=1)
    assert codes_strict == ["SH518880"]


def test_build_groups_three_rows_with_history(tmp_env):
    s_prev2 = _mk_session(label="2026-05-18-收")
    s_prev1 = _mk_session(label="2026-05-19-收")
    s_curr = _mk_session(label="2026-05-20-收")
    groups = rh._build_groups(s_curr, [s_prev2, s_prev1])
    g0 = next(g for g in groups if g["code"] == "SH510050")
    assert len(g0["rows"]) == 3
    assert [r["label_short"] for r in g0["rows"]] == ["05-18 收", "05-19 收", "05-20 收"]


def test_build_groups_annotation_color_propagated(tmp_env):
    s_curr = _mk_session(label="2026-05-20-收")
    groups = rh._build_groups(s_curr, [])
    g_gold = next(g for g in groups if g["code"] == "SH518880")
    assert g_gold["annotation_color"] == "#FFE4B5"
    assert g_gold["annotation_note"] == "黄金破位"
