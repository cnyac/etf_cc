"""
launcher.py — ETF 分析交互式启动器

用法:
  python src/launcher.py        # 在项目根目录运行
  双击 launch.bat               # Windows 快捷方式

菜单说明：
  1. 数据准备（单时段） — 跑 prepare_single，生成 JSON 骨架
  2. 渲染单时段报告    — 跑 render_docx，把已填好的 JSON 变成 docx
  3. 数据准备（合并）  — 跑 prepare_merge，对齐多时段 + 可选批注注入
  4. 渲染合并报告      — 跑 render_merge_docx
  5. 轨迹图            — 跑 trajectory
  0. 退出
"""
from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
SRC  = ROOT / "src"
SNAP = ROOT / "data" / "snapshots"
MRGD = ROOT / "data" / "merged"
REP  = ROOT / "reports"


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _prev_workday(d: datetime.date) -> datetime.date:
    """返回 d 的上一个工作日（跳过周六、周日）。"""
    d -= datetime.timedelta(days=1)
    while d.weekday() >= 5:          # 5=Sat, 6=Sun
        d -= datetime.timedelta(days=1)
    return d


def _ask(prompt: str, default: str = "") -> str:
    hint = f"  [{default}]" if default else ""
    try:
        val = input(f"{prompt}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    return val or default


def _pick(items: list[Path], label: str, max_show: int = 10) -> list[Path]:
    """展示列表，让用户按序号多选，返回选中的 Path 列表。"""
    shown = items[:max_show]
    print(f"\n可用 {label}（最多显示 {max_show} 条，按修改时间倒序）：")
    for i, p in enumerate(shown):
        print(f"  {i + 1:2d}. {p.stem if p.suffix == '.json' else p.name}")
    raw = _ask(f"选择序号（逗号分隔，如 1,2,3）", "")
    if not raw:
        return []
    try:
        indices = [int(x.strip()) - 1 for x in raw.split(",") if x.strip()]
        return [shown[i] for i in indices if 0 <= i < len(shown)]
    except (ValueError, IndexError):
        print("  输入有误，已跳过。")
        return []


def _run(cmd: list[str]) -> int:
    print(f"\n▶  {' '.join(str(c) for c in cmd)}\n{'─' * 60}")
    result = subprocess.run([str(c) for c in cmd], cwd=str(ROOT))
    print("─" * 60)
    return result.returncode


def _ok(rc: int, desc: str) -> bool:
    if rc == 0:
        print(f"✓  {desc}")
        return True
    print(f"✗  {desc} 失败（退出码 {rc}）")
    return False


# ── 功能模块 ──────────────────────────────────────────────────────────────────

def prepare_single():
    """数据准备：单时段 → JSON 骨架。"""
    today     = datetime.date.today()
    yest      = _prev_workday(today)
    today_str = today.strftime("%Y-%m-%d")
    yest_str  = yest.strftime("%Y-%m-%d")

    print("\n── 单时段数据准备 " + "─" * 28)
    session = _ask("时段（中午 / 收盘）", "收盘")
    if session not in ("中午", "收盘"):
        print("  时段只能是「中午」或「收盘」，已取消。")
        return

    label_def = today.strftime("%m%d") + session
    label     = _ask("标签（如 0513收盘）", label_def)
    today_in  = _ask("今天日期 YYYY-MM-DD", today_str)
    yest_in   = _ask("昨天日期 YYYY-MM-DD", yest_str)
    xlsx      = _ask("xlsx 路径", str(ROOT / "data" / "raw" / "ETF数据.xlsx"))

    rc = _run([
        sys.executable, SRC / "prepare_single.py",
        "--xlsx",       xlsx,
        "--label",      label,
        "--today-date", today_in,
        "--yest-date",  yest_in,
    ])
    if _ok(rc, "prepare_single"):
        snap = SNAP / f"{label}.json"
        print(f"  JSON: {snap}")
        print("  下一步：让 Claude Code 读取该文件、填写 analysis 字段，")
        print("           然后选菜单 [2] 渲染报告。")


def render_single():
    """渲染单时段 docx。"""
    jsons = sorted(SNAP.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsons:
        print("  data/snapshots/ 为空，请先做单时段数据准备。")
        return

    print("\n── 渲染单时段报告 " + "─" * 28)
    picked = _pick(jsons, "snapshot JSON")
    if not picked:
        return

    for snap in picked:
        out = REP / f"{snap.stem}.docx"
        rc  = _run([sys.executable, SRC / "render_docx.py", snap, out])
        if _ok(rc, f"render_docx → {out.name}"):
            print(f"  路径: {out}")


def prepare_merge():
    """合并数据准备：多时段对齐 + 可选批注注入。"""
    jsons = sorted(SNAP.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsons:
        print("  data/snapshots/ 为空，请先做单时段数据准备。")
        return

    print("\n── 合并数据准备 " + "─" * 30)
    picked = _pick(jsons, "snapshot（一般选最近 2-3 个）")
    if not picked:
        return
    labels = [p.stem for p in picked]
    print(f"  将合并: {labels}")

    # 可选：昨日合并报告（批注继承）
    prev_docx = ""
    merge_docxs = sorted(REP.glob("合并_*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
    if merge_docxs:
        print()
        prev_picked = _pick(merge_docxs, "昨日合并报告（批注继承，不需要直接回车跳过）")
        if prev_picked:
            prev_docx = str(prev_picked[0])

    weekly = _ask("\n是否加宏观周期定位？（仅周末填 y）", "n").lower() == "y"

    cmd = [sys.executable, SRC / "prepare_merge.py", "--labels", *labels]
    if prev_docx:
        cmd += ["--prev-docx", prev_docx]
    if weekly:
        cmd += ["--weekly"]

    rc = _run(cmd)
    if _ok(rc, "prepare_merge"):
        merged = sorted(MRGD.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if merged:
            print(f"  JSON: {merged[0]}")
        print("  下一步：让 Claude Code 读取该文件并填写所有分析字段（含 color_palette），")
        print("           然后选菜单 [4] 渲染合并报告。")


def render_merge():
    """渲染合并 docx。"""
    jsons = sorted(MRGD.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsons:
        print("  data/merged/ 为空，请先做合并数据准备。")
        return

    print("\n── 渲染合并报告 " + "─" * 30)
    picked = _pick(jsons, "merged JSON")
    if not picked:
        return

    today_str = datetime.date.today().strftime("%m%d")
    out_name  = _ask("输出文件名（不含 .docx）", f"合并_{today_str}")
    out       = REP / f"{out_name}.docx"

    rc = _run([sys.executable, SRC / "render_merge_docx.py", picked[0], out])
    if _ok(rc, f"render_merge_docx → {out.name}"):
        print(f"  路径: {out}")


def trajectory():
    """跨时段特征轨迹图。"""
    jsons = sorted(SNAP.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsons:
        print("  data/snapshots/ 为空。")
        return

    print("\n── 轨迹图 " + "─" * 36)
    picked = _pick(jsons, "snapshot（一般选最近 3-5 个）")
    if not picked:
        return
    labels = [p.stem for p in picked]

    top = _ask("显示前 N 个品种", "10")
    _run([sys.executable, SRC / "run.py", "trajectory", "--labels", *labels, "--top", top])


# ── 主菜单 ────────────────────────────────────────────────────────────────────

MENU = [
    ("1", "数据准备（单时段）",  prepare_single),
    ("2", "渲染单时段报告",       render_single),
    ("3", "数据准备（合并分析）", prepare_merge),
    ("4", "渲染合并报告",         render_merge),
    ("5", "轨迹图",               trajectory),
    ("0", "退出",                 None),
]


def main():
    print("\n" + "═" * 46)
    print("    ETF 自动化分析启动器")
    print("═" * 46)

    while True:
        print()
        for key, desc, _ in MENU:
            print(f"  {key}.  {desc}")
        choice = _ask("\n请选择").strip()

        matched = [(k, d, fn) for k, d, fn in MENU if k == choice]
        if not matched:
            print("  无效选项，请重新输入。")
            continue
        _, _, fn = matched[0]
        if fn is None:
            print("  再见！")
            break
        try:
            fn()
        except Exception as exc:
            print(f"\n  [错误] {exc}")


if __name__ == "__main__":
    main()
