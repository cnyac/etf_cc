"""report_gap 单元测试。"""
import datetime
import os

import pytest

from src import report_gap


def test_expected_labels_a_end_today_full():
    # a_until=None: 历史日只 -收，end 当天 -午 + -收
    labels = report_gap.expected_labels("A", "2026-05-18", "2026-05-20")
    assert labels == ["2026-05-18-收", "2026-05-19-收",
                      "2026-05-20-午", "2026-05-20-收"]


def test_expected_labels_a_end_today_noon():
    # a_until="noon": end 当天只 -午
    labels = report_gap.expected_labels("A", "2026-05-19", "2026-05-20",
                                        a_until="noon")
    assert labels == ["2026-05-19-收", "2026-05-20-午"]


def test_expected_labels_a_end_history_close():
    # a_until="close": end 是历史日（开盘前场景），end 只 -收
    labels = report_gap.expected_labels("A", "2026-05-19", "2026-05-20",
                                        a_until="close")
    assert labels == ["2026-05-19-收", "2026-05-20-收"]


def test_expected_labels_us():
    labels = report_gap.expected_labels("US", "2026-05-18", "2026-05-20")
    assert labels == ["2026-05-18", "2026-05-19", "2026-05-20"]


def test_existing_labels_reads_filenames(tmp_path, monkeypatch):
    a_dir = tmp_path / "a"
    a_dir.mkdir()
    (a_dir / "2026-05-19-收.json").write_text("{}")
    (a_dir / "2026-05-20-午.json").write_text("{}")
    (a_dir / "ignore.txt").write_text("x")
    monkeypatch.setattr(report_gap, "SNAPSHOTS_DIR", str(tmp_path))
    got = report_gap.existing_labels("A")
    assert got == {"2026-05-19-收", "2026-05-20-午"}


def test_existing_labels_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(report_gap, "SNAPSHOTS_DIR", str(tmp_path))
    assert report_gap.existing_labels("US") == set()


def test_detect_report_gaps_subtracts_existing(tmp_path, monkeypatch):
    a_dir = tmp_path / "a"
    a_dir.mkdir()
    (a_dir / "2026-05-19-收.json").write_text("{}")
    (a_dir / "2026-05-20-午.json").write_text("{}")
    monkeypatch.setattr(report_gap, "SNAPSHOTS_DIR", str(tmp_path))
    # 期望 [05-19-收, 05-20-收]，已有 05-19-收 → 缺 05-20-收
    gaps = report_gap.detect_report_gaps("A", "2026-05-19", "2026-05-20")
    assert gaps == ["2026-05-20-收"]


def test_default_end_a_after_close():
    # 2026-05-20 (周三) 15:10 之后：当天 -午 + -收 都期望
    now = datetime.datetime(2026, 5, 20, 15, 10)
    end, a_until = report_gap.default_end("A", now=now)
    assert end == "2026-05-20"
    assert a_until is None


def test_default_end_a_after_noon_before_close():
    now = datetime.datetime(2026, 5, 20, 13, 0)
    end, a_until = report_gap.default_end("A", now=now)
    assert end == "2026-05-20"
    assert a_until == "noon"


def test_default_end_a_before_noon_uses_prev_session():
    now = datetime.datetime(2026, 5, 20, 9, 0)  # 周三上午开盘前
    end, a_until = report_gap.default_end("A", now=now)
    assert end == "2026-05-19"  # 周二
    assert a_until == "close"   # 历史日：永不产 -午


def test_default_end_a_weekend():
    now = datetime.datetime(2026, 5, 23, 10, 0)  # 周六
    end, a_until = report_gap.default_end("A", now=now)
    assert end == "2026-05-22"  # 周五收盘
    assert a_until == "close"
