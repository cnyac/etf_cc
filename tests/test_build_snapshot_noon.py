"""build_snapshot 的 noon 路径单测（mock 掉外部数据源）。

验证两件事：
  1. session=noon 且 trade_date != today → 直接 raise（不能历史回填中午）
  2. session=noon 且 trade_date == today → 调 realtime API 拉腾讯快照，
     append 到历史末尾后跑通完整流水线
"""
import datetime
import os

import pandas as pd
import pytest

from src import build_snapshot as bs


@pytest.fixture
def fake_pool(tmp_path, monkeypatch):
    import yaml
    pool = {"etfs": [
        {"code": "SH510050", "name": "上证50ETF"},
        {"code": "SZ159995", "name": "芯片ETF"},
    ]}
    fp = tmp_path / "pool_a.yaml"
    fp.write_text(yaml.safe_dump(pool, allow_unicode=True), encoding="utf-8")
    return str(fp)


def _fake_history(codes, today):
    """200 个交易日的虚假 OHLCV（不含今日）。"""
    rows = []
    dates = pd.bdate_range(end=pd.Timestamp(today) - pd.Timedelta(days=1),
                            periods=200)
    for c in codes:
        base = 10.0
        for i, d in enumerate(dates):
            close = base + i * 0.01
            rows.append({
                "date": d, "code": c,
                "open": close, "close": close,
                "high": close + 0.05, "low": close - 0.05,
                "volume": 1_000_000.0, "amount": 10_000_000.0,
            })
    return pd.DataFrame(rows)


def test_noon_historical_raises(monkeypatch, fake_pool):
    """过去日 + noon → 立刻 raise，不调任何 API。"""
    called = {"hist": 0, "rt": 0}

    def fake_ohlcv(codes, s, e):
        called["hist"] += 1
        return _fake_history(codes, "2024-01-01")  # 任意

    def fake_realtime(codes):
        called["rt"] += 1
        return {}

    monkeypatch.setattr(bs.api, "get_a_etf_ohlcv", fake_ohlcv)
    monkeypatch.setattr(bs.api, "get_a_etf_realtime", fake_realtime)

    with pytest.raises(RuntimeError, match="只能当日实时生成"):
        bs.build("A", "2020-01-02-午", "noon", pool_path=fake_pool)
    # 应该在 fetch 历史前就 raise
    assert called["hist"] == 0
    assert called["rt"] == 0


def test_weekend_flag_helper():
    """周末判定：A 股周五-收 / 美股周五 → true；其余 false。"""
    # 2026-05-22 是周五
    assert bs._is_weekend_close("2026-05-22", "A", "close", "2026-05-22-收") is True
    assert bs._is_weekend_close("2026-05-22", "A", "noon", "2026-05-22-午") is False
    assert bs._is_weekend_close("2026-05-22", "US", "close", "2026-05-22") is True
    # 2026-05-21 是周四 → false
    assert bs._is_weekend_close("2026-05-21", "A", "close", "2026-05-21-收") is False


def test_noon_today_appends_realtime(monkeypatch, fake_pool, tmp_path):
    """今日 + noon → 调 realtime，append 后跑通流水线。"""
    today = datetime.date.today().strftime("%Y-%m-%d")

    monkeypatch.setattr(bs.api, "get_a_etf_ohlcv",
                        lambda codes, s, e: _fake_history(codes, today))

    rt_payload = {
        "SH510050": {
            "日期": pd.Timestamp(today),
            "开盘": 12.0, "收盘": 12.5, "最高": 12.6, "最低": 11.9,
            "成交量": 2_000_000.0, "成交额": 25_000_000.0,
            "symbol": "SH510050",
        },
        "SZ159995": {
            "日期": pd.Timestamp(today),
            "开盘": 12.0, "收盘": 11.8, "最高": 12.1, "最低": 11.7,
            "成交量": 1_500_000.0, "成交额": 18_000_000.0,
            "symbol": "SZ159995",
        },
    }
    monkeypatch.setattr(bs.api, "get_a_etf_realtime", lambda codes: rt_payload)

    # 隔离窗口/快照写入到 tmp（不污染真实 data/）
    from src import window as win
    monkeypatch.setattr(win, "WINDOW_DIR", str(tmp_path / "window"))
    monkeypatch.setattr(win, "SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    os.makedirs(tmp_path / "window", exist_ok=True)
    os.makedirs(tmp_path / "snapshots" / "a", exist_ok=True)

    session = bs.build("A", f"{today}-午", "noon", pool_path=fake_pool)
    assert session["session_time"] == "noon"
    assert len(session["tickers"]) == 2
    # noon ×2 逻辑：today_amount_adjusted = realtime amount × 2
    t50 = next(t for t in session["tickers"] if t["code"] == "SH510050")
    assert t50["today_amount"] == pytest.approx(25_000_000.0 * 2)
