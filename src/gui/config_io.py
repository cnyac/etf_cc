"""GUI 配置层 IO：personas / thresholds / prompt 模板的读写。

设计：
  - personas:  config/personas.yaml（Tab 8 Panel 1 任务做正式接入）
  - thresholds: config/thresholds.yaml（Tab 8 Panel 2 任务做正式接入）
  - prompt 模板: src/templates/prompt/*.j2  + 配套 .default 兜底

本文件先提供骨架：读时若文件不存在返回默认；写时确保目录存在；
真正接入 panel.py / llm_prompt.py 在 Tab 8 各 Panel 任务做。
"""
from __future__ import annotations

import os
from typing import Any

import yaml

from src.gui.config_schema import TUNABLE_THRESHOLDS, THRESHOLD_KEYS

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.path.join(ROOT, "config")
PROMPT_TEMPLATE_DIR = os.path.join(ROOT, "src", "templates", "prompt")

PERSONAS_FP = os.path.join(CONFIG_DIR, "personas.yaml")
THRESHOLDS_FP = os.path.join(CONFIG_DIR, "thresholds.yaml")


# ─────────────────────────── personas ───────────────────────────

def load_personas() -> dict:
    """读 config/personas.yaml。
    返回 {market: {persona_key: {display_name, scope, focus_block, output_fields}}}。
    yaml 不存在或为空 → 返回 {}（llm_prompt 会退化）。
    """
    if not os.path.exists(PERSONAS_FP):
        return {}
    with open(PERSONAS_FP, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_personas(data: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = PERSONAS_FP + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, PERSONAS_FP)


# ─────────────────────────── thresholds ───────────────────────────

def load_thresholds() -> dict:
    """读 thresholds.yaml；返回 {key: value} + 配 meta 描述。
    若 yaml 不存在，全部取 default。
    """
    current: dict[str, Any] = {}
    if os.path.exists(THRESHOLDS_FP):
        with open(THRESHOLDS_FP, "r", encoding="utf-8") as f:
            current = yaml.safe_load(f) or {}
    items = []
    for t in TUNABLE_THRESHOLDS:
        items.append({**t, "current": current.get(t["key"], t["default"])})
    return {"items": items}


def save_thresholds(payload: dict) -> None:
    """payload = {key: value, ...}；只保存白名单内 key。"""
    if not isinstance(payload, dict):
        raise ValueError("thresholds payload 应为 dict")
    out: dict[str, Any] = {}
    for t in TUNABLE_THRESHOLDS:
        k = t["key"]
        if k in payload:
            v = payload[k]
            if t["type"] == "float":
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    raise ValueError(f"{k} 必须为数字，得到 {v!r}")
            out[k] = v
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = THRESHOLDS_FP + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, THRESHOLDS_FP)


# ───────────────────────── prompt 模板 ─────────────────────────

# 已开放的可编辑模板段（MVP 选 2 个最常调的）；其它段（system_head/history/short_key
# 等）功能性强，暂硬编码不暴露。SYSTEM_HEAD 的人格分工部分走 personas.yaml 而非这里。
PROMPT_TEMPLATE_KEYS = [
    "task_block",
    "weekend_flag",
]


def _template_path(key: str) -> str:
    return os.path.join(PROMPT_TEMPLATE_DIR, f"{key}.j2")


def _default_path(key: str) -> str:
    return os.path.join(PROMPT_TEMPLATE_DIR, f"{key}.j2.default")


def list_prompt_templates() -> dict:
    items = []
    for k in PROMPT_TEMPLATE_KEYS:
        fp = _template_path(k)
        dp = _default_path(k)
        items.append({
            "key": k,
            "exists": os.path.exists(fp),
            "has_default": os.path.exists(dp),
        })
    return {"items": items}


def read_prompt_template(key: str) -> tuple[str, bool]:
    """返回 (content, is_default)。若 .j2 不存在但 .default 存在 → 返默认值。
    都不存在 → 抛 FileNotFoundError。
    """
    if key not in PROMPT_TEMPLATE_KEYS:
        raise FileNotFoundError(key)
    fp = _template_path(key)
    if os.path.exists(fp):
        with open(fp, "r", encoding="utf-8") as f:
            return f.read(), False
    dp = _default_path(key)
    if os.path.exists(dp):
        with open(dp, "r", encoding="utf-8") as f:
            return f.read(), True
    raise FileNotFoundError(key)


def write_prompt_template(key: str, content: str) -> None:
    if key not in PROMPT_TEMPLATE_KEYS:
        raise KeyError(key)
    os.makedirs(PROMPT_TEMPLATE_DIR, exist_ok=True)
    fp = _template_path(key)
    tmp = fp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, fp)


def reset_prompt_template(key: str) -> None:
    """删除自定义版本，让下次读时退回 .default。"""
    if key not in PROMPT_TEMPLATE_KEYS:
        raise KeyError(key)
    fp = _template_path(key)
    if os.path.exists(fp):
        os.remove(fp)
