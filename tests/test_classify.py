"""classify.py 测试：全局最增量/最缩量（用户业务语义：全品种各 1 个）。"""
from src.classify import enrich


def _mk_item(name, today_pct, yest_pct, today_amount, yest_amount):
    return {"code": name, "name": name,
            "today_pct": today_pct, "yest_pct": yest_pct,
            "today_amount": today_amount, "yest_amount": yest_amount}


def test_global_most_volume_tags_only_once():
    """全品种 1 个最增量 + 1 个最缩量，跨分类全局唯一。"""
    items = [
        _mk_item("A", 0.02, 0.01, 5e9, 1e9),    # vol_ratio +4.0 → 最增量
        _mk_item("B", 0.01, 0.01, 1.1e9, 1e9),  # vol_ratio +0.1
        _mk_item("C", -0.02, -0.01, 5e8, 1e9),  # vol_ratio -0.5 → 最缩量
        _mk_item("D", -0.01, -0.01, 9e8, 1e9),  # vol_ratio -0.1
        _mk_item("E", 0.005, 0.005, 1e9, 1e9),
        _mk_item("F", -0.005, -0.005, 1e9, 1e9),
    ]
    out = enrich({"items": items})
    by_code = {it["code"]: it for it in out["items"]}
    plus = [c for c, it in by_code.items() if "最增量" in (it.get("feature") or "")]
    minus = [c for c, it in by_code.items() if "最缩量" in (it.get("feature") or "")]
    assert plus == ["A"], f"最增量应只在 A，实际 {plus}"
    assert minus == ["C"], f"最缩量应只在 C，实际 {minus}"


def test_positional_tags_still_per_category():
    """龙1/空龙1 等位置标签保留分类内逻辑。"""
    items = [
        _mk_item("U1", 0.03, 0.02, 1e9, 1e9),
        _mk_item("U2", 0.02, 0.01, 1e9, 1e9),
        _mk_item("U3", 0.01, 0.005, 1e9, 1e9),
        _mk_item("D1", -0.03, -0.02, 1e9, 1e9),
        _mk_item("D2", -0.02, -0.01, 1e9, 1e9),
        _mk_item("D3", -0.01, -0.005, 1e9, 1e9),
    ]
    out = enrich({"items": items})
    by_code = {it["code"]: it for it in out["items"]}
    # 持续强化（U1/U2/U3 累计涨幅排序）→ 龙1=U1，龙2=U2
    assert "龙1" in (by_code["U1"].get("feature") or "")
    assert "龙2" in (by_code["U2"].get("feature") or "")
    # 连续杀跌（D1/D2/D3 累计跌幅排序）→ 空龙1=D1
    assert "空龙1" in (by_code["D1"].get("feature") or "")


def test_zero_boundary_unchanged():
    """涨跌=0 边界路径依赖规则不变（回归保护）。"""
    items = [
        _mk_item("X", 0.0, 0.01, 1e9, 1e9),    # 强势横盘 → 持续强化
        _mk_item("Y", 0.0, -0.01, 1e9, 1e9),   # 弱势整理 → 连续杀跌
        _mk_item("Z", 0.0, 0.0, 1e9, 1e9),     # 双零 → 持续强化
    ]
    out = enrich({"items": items})
    by_code = {it["code"]: it["category"] for it in out["items"]}
    assert by_code["X"] == "持续强化"
    assert by_code["Y"] == "连续杀跌"
    assert by_code["Z"] == "持续强化"
