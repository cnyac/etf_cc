# 待修任务（用户 2026-05-22 反馈 9 条）

> 临时文档，全部完成后**必须删除**。

## 本轮 goal（goal 2026-05-22）

- 实施 #2-6（最简单的）
- 排查 #7 #8 但**本 goal 不修**
- #9 留到下一轮

## 进度跟踪

| # | 内容 | 状态 |
|---|---|---|
| 1 | 陈述事实 5月21日美股报告已生成 | n/a 不需操作 |
| 2 | CSS 字号：分类分布/跨资产 → 与 §2 时段叙事正文一致 | ✅ 完成 |
| 3 | 跨资产中文化（label map）+ 新增 LLM 字段 cross_asset_panorama | ✅ 完成 |
| 4 | §2 各人格字段名翻译成中文（FIELD_LABEL_CN） | ✅ 完成 |
| 5 | 品种带中文名（prompt 规则）+ 指标中文化（prompt 规则） | ✅ 完成（下次 LLM 输出生效） |
| 6 | §3 表格批注：只在批注列点击才弹 modal | ✅ 完成 |
| 7 | §3 表格合并日期错乱（显示 4月24/4月27/5月21）| 🔍 排查完成 |
| 8 | §4 跨日追踪表"变化评级"和"评级理由"全空 | 🔍 排查完成 |
| 9 | §6 策略前瞻深度扩展（仿用户旧 prompt 写长研报） | ⏸ 下一轮 |

## 已拍板细节

- #5 品种中文名 → 让 LLM 写时带（前者方案）
- #9 schema 改动 → A 股/美股对称扩展（下一轮）
- #9 deep_analysis 字段位置 → 放 strategy_outlook.deep_analysis（下一轮）
- 执行顺序：7→8 排查 → 6 → 4 → 5 → 2 → 3 → 9（本轮不到 9）

## 排查记录（#7 #8）

### #7 §3 表格合并日期错乱 — 根因已定位

**实际窗口状态**（`data/window/pool_us.json`）：
```
窗口 20 sessions（max=20）：
  2026-03-31, 04-01, 04-02, 04-06, 04-07, 04-08, 04-09, 04-10,
  04-13, 04-14, 04-15, 04-16, 04-17, 04-20, 04-21, 04-22,
  04-23, 04-24, 04-27, 2026-05-21

snapshots/us/ 里 4月28~5月20 这 17 天的归档都在
```

**用户 5月21 22:13 跑了 backfill 把 3月31~4月27（20 天）一次性追加**，触发滚动
弹出，把原本在窗口里的 4月28~5月20（17 天）全部弹掉，因为 `append_session`
按 list 顺序弹"最早"（list[0]），不是按 trade_date 弹。

`render_html._build_groups` 取 `recent = history[-2:] + [target]` = 4月24 / 4月27 / 5月21。

**修复方向**（下一轮做）：
- 选项 A：`render_html._build_groups` 不依赖窗口 history，直接从 `data/snapshots/<m>/` 找
  `target.trade_date` 之前的 2 个交易日 snapshot 读 ticker 行（最稳，渲染独立于窗口）
- 选项 B：`window.append_session` 改成按 trade_date 排序后弹"最早 trade_date"（侵入式）

倾向 A：渲染需求和窗口需求解耦。窗口是 LLM 上下文，渲染需要邻近 trade_date。

### #8 §4 跨日追踪表评级空 — 根因已定位

**实际数据**：5月21 美股 snapshot 中 `ticker.audit` 字段 **45/45 全部有值**
（多数是 `{"actual_vs_expected": "符合预期", "auditor": "quant"}`，1 个 IEF
是 `auditor=discipline`）。

**渲染层 bug**：`src/templates/report.html.j2` macro `tracking_table` 的 §4 表
（line 193-194）这两列**写死了 `—`**：
```jinja
<td class="center muted">—</td>   <!-- 变化评级 -->
<td class="muted">—</td>          <!-- 评级理由 -->
```
根本没读 `audit` 字段（§3 表 line 146-151 是对的，§4 表抄漏了）。

**修复**（下一轮做）：把 line 193-194 改成读 current session 该 code 的 audit：
```jinja
{% set cur_t = (current.tickers | selectattr('code', 'equalto', code) | first) %}
{% set au = cur_t.audit if cur_t else None %}
<td class="center">
  {% if au %}<span class="audit-badge audit-{{ au.actual_vs_expected }} auditor-{{ au.auditor }}">{{ au.actual_vs_expected }}</span>{% else %}—{% endif %}
</td>
<td>{{ au.audit_note if au and au.audit_note else '—' }}</td>
```
注意：quant 兜底的 audit 没有 audit_note（只有 LLM 写的 ticker_audits 可能有）。需考虑加 D1/D2 简述。

## 项目临时文件 review（goal 要求）

| 路径 | 状态 | 建议 |
|---|---|---|
| `reports/0513中午.docx` 等 3 个 docx | 未被 git 跟踪 | 旧 docx 流水线遗留物，**建议删** |
| `templates/_archived/*.html.j2` | git tracked | 旧版模板归档，可保留 |
| `docs/_archived/prompts/` | git tracked | REFACTOR_BRIEF 标注"保留作风格参考" |
| `HANDOFF_FRONTEND.md` | git tracked | 阶段 8 接力棒文档已完工，可删（README 已含 GUI 用法） |
| `PLAN_TODO.md` | 临时 | **完成所有任务后删** |

