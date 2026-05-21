"""GUI 配置层的 enum 白名单（与 panel.py 的 cross_asset_state 强对齐）。

修改本文件等于扩展系统级 enum，需同步 src/panel.py 的 cross_asset 处理逻辑。
"""

# pool yaml 里 role 字段允许的取值；空字符串/缺失表示"无角色"（普通板块品种）
VALID_ROLES = (
    "treasury_10y",
    "treasury_30y",
    "dollar",
    "gold",
    "oil",
    "vix",
    "btc",
    "eth",
)

# Tab 8 Panel 2 可调阈值的白名单（key, default, type, scope, desc）
# scope: panel / factors / classify
TUNABLE_THRESHOLDS = [
    {"key": "STRONG_THRESHOLD", "default": 0.02, "type": "float", "scope": "panel",
     "desc": "±2% 涨跌算'强'（panel.strong_up_count / strong_down_count）"},
    {"key": "VOL_EXPAND", "default": 1.5, "type": "float", "scope": "panel",
     "desc": "vol_ratio_20 > 1.5 算'量能扩张'"},
    {"key": "VOL_CONTRACT", "default": 0.7, "type": "float", "scope": "panel",
     "desc": "vol_ratio_20 < 0.7 算'量能收缩'"},
    {"key": "CROSS_ASSET_FLAT", "default": 0.003, "type": "float", "scope": "panel",
     "desc": "跨资产 ±0.3% 内算 flat"},
    {"key": "BREADTH_ALERT_PCT", "default": 0.70, "type": "float", "scope": "panel",
     "desc": "上涨/下跌占比 ≥70% 触发极值共振预警"},
    {"key": "NEAR_MA_THRESHOLD", "default": 0.005, "type": "float", "scope": "factors",
     "desc": "close_vs_ma ±0.5% 内算 near"},
    {"key": "MA150_NEAR_PCT", "default": 2.0, "type": "float", "scope": "factors",
     "desc": "美股 MA150 ±2% 内算'震荡'，否则站上/跌破"},
]

THRESHOLD_KEYS = {t["key"] for t in TUNABLE_THRESHOLDS}
