"""
trajectory.py — 跨时段特征轨迹图

把同一品种在 N 个时段的归类+特征标签映射到 -3 到 +3 的强度等级，
画成折线图，让"龙1降级到普通"、"修复龙1升级为龙1"这类轨迹变化一目了然。

依赖：plotly（生成可交互 HTML 图表）
"""
from __future__ import annotations

import json
from pathlib import Path

# 强度等级映射：(category, pos_tag) → 等级
def feature_score(category: str, feature: str) -> int:
    """把 (归类, 特征) 映射到 -3..+3 的强度等级。"""
    tags = [t.strip() for t in (feature or "").split("，") if t.strip()]
    pos_tags = {t for t in tags if t not in ("最增量", "最缩量")}

    # 独特单独算
    if "独特" in pos_tags:
        return 0

    # 上涨侧
    if category == "持续强化":
        if "龙1" in pos_tags: return 3
        if "龙2" in pos_tags: return 2
        return 1
    if category == "反包修复":
        if "修复龙1" in pos_tags: return 3
        if "修复龙2" in pos_tags: return 2
        if "最弱修复" in pos_tags: return -1   # 弱修复算"勉强翻红"
        return 1
    # 下跌侧
    if category == "强反转":
        if "反转空龙1" in pos_tags: return -3
        if "反转空龙2" in pos_tags: return -2
        if "最弱反转" in pos_tags: return -1
        return -1
    if category == "连续杀跌":
        if "空龙1" in pos_tags: return -3
        if "空龙2" in pos_tags: return -2
        return -1
    return 0


def build_trajectory_data(snapshots: list[dict]) -> dict:
    """snapshots 按时间倒序传入（T0 在前）。

    返回 {name -> [{session, score, feature, category, today_pct}, ...]}
    内部数组已按时间正序排列（最旧 → 最新），方便画图。
    """
    series: dict[str, list[dict]] = {}
    # 倒过来：从最旧到最新
    for snap in reversed(snapshots):
        for group in snap["groups"].values():
            for it in group:
                series.setdefault(it["name"], []).append({
                    "session": snap["session_label"],
                    "score": feature_score(it["category"], it.get("feature", "")),
                    "feature": it.get("feature", "") or "—",
                    "category": it["category"],
                    "today_pct": it["today_pct"],
                    "volume_ratio": it["volume_ratio"],
                })
    return series


def render_trajectory_html(snapshots: list[dict], output_path: Path,
                            highlight_top: int = 8) -> Path:
    """渲染交互式轨迹图。

    highlight_top: 默认高亮显示 N 个"轨迹变化最大"的品种，
                   其它品种以浅灰色绘制（可点击 legend 显示/隐藏）。
    """
    try:
        import plotly.graph_objects as go
    except ImportError as e:
        raise ImportError("需要 plotly：pip install plotly") from e

    series = build_trajectory_data(snapshots)
    sessions_ordered = [s["session_label"] for s in reversed(snapshots)]

    # 计算每个品种的"轨迹变动幅度"= max-min，挑变化最大的高亮
    def variation(records: list[dict]) -> int:
        scores = [r["score"] for r in records]
        return max(scores) - min(scores) if scores else 0

    sorted_names = sorted(series.keys(), key=lambda n: variation(series[n]), reverse=True)
    highlight_set = set(sorted_names[:highlight_top])

    fig = go.Figure()

    # 先画背景（非高亮品种）
    for name in sorted_names:
        if name in highlight_set:
            continue
        recs = series[name]
        hover = [f"{r['session']}<br>归类: {r['category']}<br>特征: {r['feature']}<br>"
                 f"今涨幅: {r['today_pct']*100:+.2f}%<br>量比: {r['volume_ratio']*100:+.2f}%"
                 for r in recs]
        fig.add_trace(go.Scatter(
            x=[r["session"] for r in recs],
            y=[r["score"] for r in recs],
            mode="lines+markers",
            name=name,
            line=dict(color="rgba(180,180,180,0.35)", width=1),
            marker=dict(size=4),
            hovertemplate="<b>%{text}</b><br>%{customdata}<extra></extra>",
            text=[name] * len(recs),
            customdata=hover,
            visible="legendonly",  # 默认隐藏，点 legend 才显示
        ))

    # 再画前景（高亮品种）
    palette = ["#d62728", "#ff7f0e", "#9467bd", "#2ca02c", "#1f77b4",
               "#8c564b", "#e377c2", "#bcbd22", "#17becf", "#7f7f7f"]
    for i, name in enumerate(sorted_names[:highlight_top]):
        recs = series[name]
        hover = [f"{r['session']}<br>归类: {r['category']}<br>特征: {r['feature']}<br>"
                 f"今涨幅: {r['today_pct']*100:+.2f}%<br>量比: {r['volume_ratio']*100:+.2f}%"
                 for r in recs]
        fig.add_trace(go.Scatter(
            x=[r["session"] for r in recs],
            y=[r["score"] for r in recs],
            mode="lines+markers+text",
            name=name,
            line=dict(color=palette[i % len(palette)], width=3),
            marker=dict(size=10),
            text=[r["feature"] for r in recs],
            textposition="top center",
            textfont=dict(size=9),
            hovertemplate="<b>%{text}</b><br>" + name + "<br>%{customdata}<extra></extra>",
            customdata=hover,
        ))

    # Y 轴标签
    y_labels = {
        3: "龙1/修复龙1（最强）",
        2: "龙2/修复龙2",
        1: "普通上涨",
        0: "独特/无标签",
        -1: "普通下跌/最弱反转修复",
        -2: "空龙2/反转空龙2",
        -3: "空龙1/反转空龙1（最弱）",
    }

    fig.update_layout(
        title=dict(
            text=f"跨时段特征轨迹图（{sessions_ordered[0]} → {sessions_ordered[-1]}）<br>"
                 f"<sub>默认显示轨迹变化最大的 {highlight_top} 个品种，点击 legend 显示其它</sub>",
            x=0.5
        ),
        xaxis=dict(title="时段", categoryorder="array", categoryarray=sessions_ordered),
        yaxis=dict(
            title="特征强度",
            tickmode="array",
            tickvals=list(y_labels.keys()),
            ticktext=list(y_labels.values()),
            range=[-3.5, 3.5],
            zeroline=True, zerolinecolor="#999", zerolinewidth=1,
        ),
        height=700,
        hovermode="closest",
        plot_bgcolor="white",
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#eee")
    fig.update_yaxes(showgrid=True, gridcolor="#eee")

    # 加水平分隔线
    fig.add_hline(y=0.5, line_dash="dash", line_color="#ddd")
    fig.add_hline(y=-0.5, line_dash="dash", line_color="#ddd")

    out = Path(output_path)
    fig.write_html(str(out), include_plotlyjs="cdn")
    return out


if __name__ == "__main__":
    import sys
    snaps = [json.loads(Path(p).read_text(encoding="utf-8")) for p in sys.argv[1:-1]]
    out = render_trajectory_html(snaps, Path(sys.argv[-1]))
    print(f"已生成：{out}")
