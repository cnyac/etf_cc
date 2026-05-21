"""panel_breadth 盘面广度聚合。

输入：
  - per_ticker: list[dict]，每个含 code/today_pct/vol_ratio_20/new_high_20d/
                new_low_20d/category（A 股；美股额外 ma150_relation）
  - pool_config: 已加载的 yaml dict（含 etfs 列表，部分有 role）
  - market: "A" / "US"

输出：dict，字段见 REFACTOR_BRIEF 4.4b / 4.9.8。
"""
from __future__ import annotations

from typing import Literal

from src import thresholds_cfg as tcfg

# 默认值（保留作为常量；运行时从 config/thresholds.yaml 读，缺失则回退默认）
STRONG_THRESHOLD = 0.02       # ±2% 涨跌算"强"
VOL_EXPAND = 1.5              # vol_ratio_20 > 1.5 → 扩张
VOL_CONTRACT = 0.7            # < 0.7 → 收缩
CROSS_ASSET_FLAT = 0.003      # ±0.3% 内算 flat
BREADTH_ALERT_PCT = 0.70      # 占比 ≥70% 触发极值共振预警


def _cross_asset_dir(pct: float, flat_thr: float) -> str:
    if pct > flat_thr:
        return "up"
    if pct < -flat_thr:
        return "down"
    return "flat"


def build_panel(per_ticker: list[dict], pool_config: dict,
                market: Literal["A", "US"]) -> dict:
    # 每次构造时拉一次阈值（GUI 改完即可生效，无需重启进程）
    strong_thr = tcfg.get("STRONG_THRESHOLD", STRONG_THRESHOLD)
    vol_exp_thr = tcfg.get("VOL_EXPAND", VOL_EXPAND)
    vol_con_thr = tcfg.get("VOL_CONTRACT", VOL_CONTRACT)
    flat_thr = tcfg.get("CROSS_ASSET_FLAT", CROSS_ASSET_FLAT)
    alert_pct = tcfg.get("BREADTH_ALERT_PCT", BREADTH_ALERT_PCT)

    # 基础计数
    up = down = flat = 0
    strong_up = strong_down = 0
    vol_exp = vol_con = 0
    nh = nl = 0
    above_ma150 = 0
    cats: dict[str, int] = {}

    for t in per_ticker:
        pct = t.get("today_pct")
        if pct is None:
            continue
        if pct > 0:
            up += 1
        elif pct < 0:
            down += 1
        else:
            flat += 1
        if pct > strong_thr:
            strong_up += 1
        elif pct < -strong_thr:
            strong_down += 1

        vr = t.get("vol_ratio_20")
        if vr is not None:
            if vr > vol_exp_thr:
                vol_exp += 1
            elif vr < vol_con_thr:
                vol_con += 1

        if t.get("new_high_20d") is True:
            nh += 1
        if t.get("new_low_20d") is True:
            nl += 1

        if market == "US" and t.get("ma150_relation") == "站上":
            above_ma150 += 1

        cat = t.get("category")
        if cat:
            cats[cat] = cats.get(cat, 0) + 1

    # cross_asset_state：通过 pool yaml 的 role 反查
    role_to_code: dict[str, str] = {}
    for e in pool_config.get("etfs", []):
        r = e.get("role")
        if r:
            role_to_code[r] = e["code"]
    pct_by_code = {t["code"]: t.get("today_pct") for t in per_ticker}
    cross_asset: dict[str, str | None] = {}
    for role, code in role_to_code.items():
        p = pct_by_code.get(code)
        cross_asset[role] = _cross_asset_dir(p, flat_thr) if p is not None else None

    # 极值共振预警（任务 2.0）：上涨/下跌占比 ≥70%
    total = up + down + flat
    breadth_alert: str | None = None
    if total > 0:
        if up / total >= alert_pct:
            breadth_alert = "bullish_resonance"
        elif down / total >= alert_pct:
            breadth_alert = "bearish_resonance"

    panel = {
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "strong_up_count": strong_up,
        "strong_down_count": strong_down,
        "vol_expansion_count": vol_exp,
        "vol_contraction_count": vol_con,
        "new_high_count_20d": nh,
        "new_low_count_20d": nl,
        "cross_asset_state": cross_asset,
        "category_distribution": cats,
        "breadth_alert": breadth_alert,
    }

    if market == "US":
        panel["above_ma150_count"] = above_ma150
        # SPY/IWM 分化（硬编码 ticker，与 role 无关）
        spy = pct_by_code.get("SPY")
        iwm = pct_by_code.get("IWM")
        if spy is not None and iwm is not None:
            panel["spy_iwm_divergence"] = round(spy - iwm, 6)
        else:
            panel["spy_iwm_divergence"] = None

    return panel
