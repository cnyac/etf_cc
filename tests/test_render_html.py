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
    # 带 feature 的两只都应入选
    assert "SH510050" in codes
    assert "SH518880" in codes
