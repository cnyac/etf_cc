"""color_palette.py 测试。"""
import json
import os
import pytest

from src import color_palette as cp


@pytest.fixture
def tmp_palette(tmp_path, monkeypatch):
    p = tmp_path / "color_palette.json"
    monkeypatch.setattr(cp, "PALETTE_PATH", str(p))
    return p


def test_load_defaults_when_missing(tmp_palette):
    colors = cp.load()
    assert len(colors) >= 8
    assert any(c["hex"].startswith("#") for c in colors)


def test_save_and_load(tmp_palette):
    cp.save([{"hex": "#FFE4B5", "name": "鹅黄"}])
    loaded = cp.load()
    assert len(loaded) == 1
    assert loaded[0]["name"] == "鹅黄"


def test_merge_new_color(tmp_palette):
    cp.save([{"hex": "#FFE4B5", "name": "鹅黄"}])
    cp.merge([{"hex": "#DDA0DD", "name": "梅紫"}])
    loaded = cp.load()
    assert len(loaded) == 2
    hexes = {c["hex"].upper() for c in loaded}
    assert "#FFE4B5" in hexes and "#DDA0DD" in hexes


def test_merge_deduplicates_by_hex(tmp_palette):
    cp.save([{"hex": "#FFE4B5", "name": "鹅黄"}])
    cp.merge([{"hex": "#ffe4b5", "name": "别名"}])  # 大小写不敏感
    loaded = cp.load()
    assert len(loaded) == 1
    assert loaded[0]["name"] == "鹅黄"  # 旧名优先


def test_extract_from_annotations():
    session = {"tickers": [
        {"code": "A", "annotation": {"color": "#FFE4B5"}},
        {"code": "B", "annotation": None},
        {"code": "C", "annotation": {"color": "#DDA0DD", "color_name": "梅紫"}},
    ]}
    out = cp.extract_from_annotations(session)
    assert len(out) == 2
    assert {c["hex"] for c in out} == {"#FFE4B5", "#DDA0DD"}
