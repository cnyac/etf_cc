"""滚动窗口与 session 的数据契约（仅注释 + 默认骨架，不强校验）。

session 是窗口里的一个"时段切片"，schema 如下：

{
  "label": "2026-05-20-收",       # 形如 YYYY-MM-DD-{午|收}（A 股）/ YYYY-MM-DD（美股）
  "market": "A",                   # "A" | "US"
  "session_time": "close",         # "noon" | "close"
  "trade_date": "2026-05-20",
  "timestamp": "2026-05-20T15:05:00",  # 生成时刻
  "tickers": [                     # 每只 ETF 的快照（classify + factors 合并后）
    {
      "code": "SH510050", "name": "上证50ETF",
      "today_pct": 0.0091, "yest_pct": 0.0035,
      "today_amount": 3.87e9, "yest_amount": 4.21e9,
      "pct_diff": 0.0056, "cum_pct": 0.0126, "volume_ratio": -0.080,
      "category": "持续强化", "feature": "龙1，最增量", "compliance": "完全符合",
      "factors": {
        "price_pctile_60": 75, "price_pctile_20": 80,
        "vol_ratio_20": 1.42, "vol_pctile_20": 70,
        "ma_alignment": "多头", "pct_normalized": 1.3,
        "new_high_20d": false, "new_low_20d": false,
        "is_outlier": false
        # 美股额外: ma150_dist, ma150_relation
      },
      "annotation": null            # {color: "#FFE4B5", note: "缩量整理"} 或 null
    }
  ],
  "panel": { ... },                # panel.build_panel 输出
  "narrative": {                   # stage 4 LLM 填，现在留 None 或骨架
    "is_skeleton": true,           # backfill 时为 true；LLM 写满后改 false
    "session_summary": "...",
    "yangjia_emotion_cycle": null,
    # ... 其它人格字段
  },
  "tracking": {                    # 跨日变化追踪（stage 5 渲染用）
    "rating_history": []           # append-only：[{label, code, rating}]
  }
}

窗口顶层结构（`data/window/pool_a.json` / `pool_us.json`）：

{
  "market": "A",
  "max_sessions": 40,
  "sessions": [ session, session, ... ]   # 升序日期
}
"""
from typing import Literal

MARKET_A = "A"
MARKET_US = "US"

MAX_SESSIONS = {"A": 40, "US": 20}
SESSION_TIMES = ("noon", "close")


def empty_window(market: Literal["A", "US"]) -> dict:
    return {
        "market": market,
        "max_sessions": MAX_SESSIONS[market],
        "sessions": [],
    }
