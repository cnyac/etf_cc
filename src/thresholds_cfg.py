"""量化阈值的运行时读取层（Tab 8 Panel 2 黄区）。

设计目的：让 panel.py / factors.py 读 config/thresholds.yaml，又不反向依赖 src/gui。
yaml 缺失 / key 缺失 → 返回 default（即历史硬编码值），行为完全向后兼容。

性能：每次调用 get() 都重新打开 yaml（≤数十字节），可忽略。
若需缓存，未来加 mtime 失效即可。
"""
from __future__ import annotations

import os
from typing import Any

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THRESHOLDS_FP = os.path.join(ROOT, "config", "thresholds.yaml")


def get(key: str, default: Any) -> Any:
    """读阈值；yaml 缺失或 key 缺失返 default。"""
    if not os.path.exists(THRESHOLDS_FP):
        return default
    try:
        with open(THRESHOLDS_FP, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return default
    return cfg.get(key, default)
