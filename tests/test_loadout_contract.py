"""《养家·装载契约》防漂移守护测试。

装载契约文档（config/养家·装载契约.md）手写、团队可读，但它引用的字段名与 enum 值
在 src/llm_schema.py 和 config/personas.yaml 里也有定义。三处一旦不同步就会悄悄漂移。
本测试在 CI 里把它们钉死：

  1. personas.yaml 养家 output_fields 必须都是 schema 里真实存在的字段
  2. 三组改过的 enum（stage / market_phase / style_tone）每个值都必须在契约文档里出现
  3. 养家管辖的每个顶层字段名都必须在契约文档里出现
"""
import os

from src.gui import config_io
from src.llm_schema import (
    A_SCHEMA, STRATEGY_OUTLOOK_SCHEMA, MACRO_CYCLE_SCHEMA, TICKER_AUDIT_SCHEMA,
    TOP_LEVEL_REQUIRED, TOP_LEVEL_OPTIONAL,
    ENUM_YANGJIA_STAGE, ENUM_MARKET_PHASE, ENUM_STYLE_TONE,
)

CONTRACT_FP = os.path.join(config_io.CONFIG_DIR, "养家·装载契约.md")

# 养家废弃北炒后独家/统筹负责的顶层字段（契约文档必须逐一覆盖）
YANGJIA_TOP_LEVEL_FIELDS = [
    "yangjia_emotion_cycle",
    "strategy_outlook",
    "unique_anomaly_analysis",
    "macro_cycle_anchor",
    "trading_discipline_review",
    "session_summary",
    "ticker_analyses",
    "quadrant_summaries",
]


def _valid_field_universe() -> set[str]:
    """从 llm_schema 推导出所有合法字段名（顶层 + 各 group 子字段 + 嵌套子字段）。"""
    u: set[str] = set()
    u |= set(TOP_LEVEL_REQUIRED) | set(TOP_LEVEL_OPTIONAL) | set(A_SCHEMA.keys())
    for spec in A_SCHEMA.values():
        u |= set(spec.get("enums", {}).keys())
        u |= set(spec.get("required", []))
        u |= set(spec.get("optional", []))
    u |= set(STRATEGY_OUTLOOK_SCHEMA.get("enums", {}).keys())
    u |= set(STRATEGY_OUTLOOK_SCHEMA.get("required", []))
    u |= set(MACRO_CYCLE_SCHEMA.get("required", []))
    for subs in MACRO_CYCLE_SCHEMA.get("sub_required", {}).values():
        u |= set(subs)
    u |= set(TICKER_AUDIT_SCHEMA.get("required", []))
    # 子节字段（schema 用嵌套 dict 表达，未单列常量）
    u |= {"prev_session_audit", "audit_note", "rating_override", "keep_rating", "reason"}
    return u


def _contract_text() -> str:
    assert os.path.exists(CONTRACT_FP), f"装载契约文档缺失：{CONTRACT_FP}"
    with open(CONTRACT_FP, encoding="utf-8") as f:
        return f.read()


def test_yangjia_output_fields_all_exist_in_schema():
    """personas.yaml 养家 output_fields 不能引用 schema 里不存在的字段。"""
    personas = config_io.load_personas() or {}
    yangjia = (personas.get("A", {}) or {}).get("yangjia_emotion_cycle", {}) or {}
    output_fields = yangjia.get("output_fields", [])
    assert output_fields, "养家 output_fields 为空，personas.yaml 可能未正确加载"
    universe = _valid_field_universe()
    unknown = [f for f in output_fields if f not in universe]
    assert not unknown, f"养家 output_fields 出现 schema 中不存在的字段（漂移）：{unknown}"


def test_contract_covers_current_enums():
    """三组改过的 enum，每个白名单值都必须在契约文档里出现（否则文档落后于 schema）。"""
    text = _contract_text()
    for enum_name, values in (
        ("ENUM_YANGJIA_STAGE", ENUM_YANGJIA_STAGE),
        ("ENUM_MARKET_PHASE", ENUM_MARKET_PHASE),
        ("ENUM_STYLE_TONE", ENUM_STYLE_TONE),
    ):
        missing = [v for v in values if v not in text]
        assert not missing, f"契约文档缺少 {enum_name} 的 enum 值（漂移）：{missing}"


def test_contract_covers_yangjia_top_level_fields():
    """养家管辖的每个顶层字段名都要在契约文档里出现，且确实是 schema 合法字段。"""
    text = _contract_text()
    universe = _valid_field_universe()
    for field in YANGJIA_TOP_LEVEL_FIELDS:
        assert field in universe, f"{field} 不是 schema 合法字段（测试自身的字段清单需更新）"
        assert field in text, f"契约文档未覆盖养家管辖字段：{field}"
