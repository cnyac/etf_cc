"""log_util 单元测试。"""
import json
import os

from src import log_util


def test_write_error_creates_json(tmp_path, monkeypatch):
    monkeypatch.setattr(log_util, "ERRORS_DIR", str(tmp_path))
    try:
        raise RuntimeError("停牌测试")
    except RuntimeError as e:
        fp = log_util.write_error("159928", "2026-05-20-收", "A", e,
                                  ts="20260521-150800")

    assert os.path.exists(fp)
    with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["ticker"] == "159928"
    assert data["market"] == "A"
    assert data["label"] == "2026-05-20-收"
    assert data["error_type"] == "RuntimeError"
    assert "停牌测试" in data["message"]
    assert "RuntimeError" in data["traceback"]
    assert fp.endswith("20260521-150800_159928.json")


def test_write_run_summary_file_format(tmp_path, monkeypatch):
    monkeypatch.setattr(log_util, "LOGS_DIR", str(tmp_path))
    summary = {
        "started_at": "2026-05-21 15:08:00",
        "elapsed_sec": 8.1,
        "data_refresh": {"A": {"ok": True, "note": "A 股池: ok=45 skip=0 fail=0 /45"}},
        "labels": [
            {"market": "A", "label": "2026-05-20-收",
             "total": 45, "ok": 43,
             "failed": [
                 {"ticker": "159928", "error_type": "RuntimeError",
                  "message": "停牌", "log_path": "/x/y.json"},
                 {"ticker": "588000", "error_type": "ValueError",
                  "message": "数据不足", "log_path": "/x/z.json"},
             ]},
        ],
    }
    fp = log_util.write_run_summary(summary, ts="20260521-150800")
    assert os.path.exists(fp)
    text = open(fp, "r", encoding="utf-8").read()
    assert "数据更新汇总" in text
    assert "成功 43/45" in text
    assert "159928" in text
    assert "停牌" in text
    assert "总耗时 8.1s" in text


def test_format_run_summary_empty_labels():
    summary = {
        "started_at": "2026-05-21 15:08:00",
        "elapsed_sec": 0.5,
        "data_refresh": None,
        "labels": [],
    }
    text = log_util.format_run_summary(summary)
    assert "无报告缺口需补" in text
