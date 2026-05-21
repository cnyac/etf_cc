# 通用规则

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them—don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No error handling for impossible scenarios.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must.**

- Don't "improve" adjacent code, comments, or formatting.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it—don't delete it.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"

---

# 项目当前状态（重要）

**2026-05-20 完成需求面封口；2026-05-21 阶段 1-6 + A + B 全部实现完成 + 旧 docx 已归档**。

| 阶段 | 工作 | 状态 |
|---|---|---|
| 1a/1b/1c | auto-prtsc ETF 管道 + etf_data_api 单一入口 | ✅ |
| 2 | factors.py（7+3 三球）/ panel.py（含 breadth_alert） | ✅ |
| 3 | 滚动窗口状态机 + build_snapshot + sync_annotations + backfill | ✅ |
| 4 | 双引擎 schema + 校验 + prompt 构造 + fill_narrative CLI | ✅ |
| 5 | HTML 渲染 + 色板 + 批注交互 JS | ✅ |
| 6 | 数据更新汇总（update_all / data_refresh / report_gap / log_util） | ✅ |
| A | §0 极值共振预警 + §3 每品种 3 行滚动渲染（不动 LLM） | ✅ |
| B | 人格扩职 + audit.py 量化代审 + 周末 macro_cycle_anchor | ✅ |
| 7 | 端到端真实 LLM 联调 | ⏸ |

旧 docx 流水线（11 个文件）已全量归档到 `src/_archived/`；`src/classify.py` 被新架构复用，保留在 `src/`。模块布局见 README §二。

- **本轮重构的所有决策详见** `REFACTOR_BRIEF.md`
- **设计动机和不要做什么详见** `DESIGN.md`
- **本文档（CLAUDE.md）** 是 AI agent 在这个项目里干活时的速查手册

---

# 新架构速查（实施时用）

## 项目目的

把"A 股 ETF + 美股权重股"的板块联动量价分析做成自动化流水线：

- **Python** 负责所有确定性计算（取数、因子、归类、广度、渲染）
- **LLM**（你）负责定性文字（单品种分析、分类小结、双引擎人格 schema 字段）
- 中间用 JSON 作交接物，HTML 作最终报告

## 双市场对称

| 维度 | A 股 | 美股 |
|---|---|---|
| 池子 | 42 ETF + 跨资产代表 → pool_a.yaml | 45 个股/ETF → pool_us.yaml |
| 时段 | 午（11:35）+ 收（15:05） | 仅收盘（次日 5:30 拉数） |
| max_sessions | 40（20 天 × 2） | 20（20 天 × 1） |
| 人格字段数 | 4（养家/赵老哥/冯柳/纪律） | 5（德鲁肯米勒/米奈尔维尼/威科夫/温斯顿/纪律共用） |
| cross_asset 维度 | 4（10年/30年国债 + 黄金 + 油） | 8（10/30年 + 美元 + 黄金 + 油 + VIX + BTC + ETH） |

## 数据流水线

```
auto-prtsc 取数 (Tushare/腾讯/yfinance)
       ↓
ingest → factors → classify → panel
       ↓
LLM 写 narrative (双引擎 schema)
       ↓
渲染 HTML (Jinja2 模板, 视觉规范固化)
       ↓
用户 B 在浏览器批注 (JS 交互 + localStorage + FSA API)
       ↓
sync_annotations 解析 HTML 内嵌 JSON
       ↓
更新 current.json (滚动窗口状态机)
```

## 派生因子（factors.py 必出）

| 因子 | 含义 | 窗口 |
|---|---|---|
| `price_pctile_60` / `_20` | 价格分位 0-100，0=最低 100=最高 | 60/20 日 |
| `vol_ratio_20` | 量比（vs 20 日均，不含当日） | 20 日 |
| `vol_pctile_20` | 量分位 | 20 日 |
| `ma_alignment` | 5/20/60 SMA 排列 → 多头/空头/震荡 | enum |
| `close_vs_ma5` / `_ma20` / `_ma60` | 收盘 vs SMA 位置 → above/below/near（±0.5%） | 5/20/60 日 |
| `pct_normalized` | 今涨幅 / (ATR_20 / 昨收) | 20 日 |
| `new_high_20d` / `new_low_20d` | 突破/破位 bool | 20 日 |
| `ma150_dist` / `ma150_relation` | 30 周均线偏离 % + 站上/跌破/震荡（仅美股） | 150 日 |

数据不足返 null，不做 partial。中午时段 today_amount ×2 进入计算（factors 内部处理）。

`close_vs_ma{5,20,60}` 三个独立字段对应 HTML 表格里的"三球"渲染（红=above 深蓝=below 灰=near）。**不要用绿色**，用户色盲。

## panel_breadth 字段

A 股版：up/down/flat_count + strong_up/down_count + vol_expansion/contraction_count + cross_asset_state(4 维) + category_distribution + **new_high_count_20d**

美股版增量：+ `above_ma150_count` + `spy_iwm_divergence`，cross_asset_state 扩到 8 维

## 双引擎人格 schema（最关键）

每个字段都是 **enum 强约束 + 短文本理由 + `what_kills_this_view`**。

详细 enum 取值见 `REFACTOR_BRIEF.md` 4.3 / 4.9.6 节。

**铁律**：

- enum 不在白名单 → Python 校验拒绝渲染（必须重写）
- `what_kills_this_view` 每字段必填（不可变性承诺锚点）
- 候选数 = 0 时整字段填 `null`，在 session_summary 说明
- `trading_discipline_review.discipline_pass=false` 默认降一档，`rating_override` 可破例
- **每个人格字段含 `free_analysis` ≤200 字自由发挥段**（用户 2026-05-21 加）
- **narrative 顶层含 `ticker_analyses: {code: text}`**，每条 30-120 字；每个分类挑 **1-2 个**（不是 3-4 个）最值得关注的品种写点评；其他不写。fill_narrative 自动回填到 `ticker.analysis`，HTML §3 表的"标签 / LLM 点评"列渲染

## 滚动窗口操作

`current.json` 是窗口唯一上下文来源。四种操作：

| 操作 | 说明 |
|---|---|
| **append** | ingest→factors→classify→panel→LLM 写 narrative→push 入窗口；超过 max 弹出最老 |
| **删除** | 用户主动剔某 label，只删 current.json，snapshots/ 保留 |
| **sync_annotations** | 扫 reports/ 找比 last_synced 新的 HTML，解析 `<script id="annotations">` 写回 |
| **backfill** | 从 auto-prtsc 拉历史，骨架 narrative 用 Python 模板（`is_skeleton=true`） |

**冻结/重算**：snapshot/factors/classify/panel/narrative 不可回头改；annotations 可被用户覆写。

## HTML 报告

- 单文件自包含（CSS/JS/数据全内联）
- 数据嵌入 `<script id="snapshot">` / `<script id="annotations">` / `<script id="known_palette">`
- 字体：华文中宋 2em（一级标题）/ 黑体 1.5em（二级）/ 楷体_GB2312 1.5em 加粗（三级）/ 仿宋_GB2312 1.5em（正文）
- 颜色：上涨/正值 #FF0000，下跌/负值 #00008B，0 涨幅黑色，成交额环比同走红蓝；**严禁绿色**（用户色盲）
- 三球：MA5/MA20/MA60 三个独立圆点，红=above 深蓝=below 灰=near（±0.5%）
- 批注：JS 弹 modal 选浅色 hex + 写备注；localStorage 备份；FSA API 覆写源文件
- 表格列结构（用户拍板 2026-05-21）：
  - §3 分类表 **9 列**：代码 / 名称 / 涨幅 / 差值 / 量能 / 价位 / 均线（三球）/ **标签+LLM点评** / **批注**
    - "标签+LLM点评"列：badges + 50-100 字 LLM 点评（仅挑中品种）
    - "批注"列（280px）：B 写完后 cell 直接显示备注文字；空时显示"点击行编辑批注"
  - §4 跨日追踪表 8 列（最近 3 时段 + 20 日 sparkline 真实收盘价 + 变化评级 + 评级理由）
  - §5 20 时段矩阵概览（含代码 + 名称 两列首字段 + 各时段单元格）
- sparkline 用 `etf_data_api.get_a_etf_ohlcv` 拉真实收盘价画线（不用窗口的 today_pct 序列）

## 分析撰写规则（LLM 写定性文字必遵守）

### 行文风格

1. **言简意赅**：禁用研报黑话、华丽辞藻
2. **句式精简**：简单句优先，切断长从句
3. 单品种分析约 **150 字**，分类小结 **500 字+**，session_summary **~100 字**

### 选品种规则（每个分类挑 **1-2 个** 写分析，2026-05-21 用户调整）

优先级：

1. 带位置标签的（龙1/空龙1/反转空龙1/修复龙1/最增量/最缩量）
2. `pct_diff` 绝对值最大的
3. `vol_ratio_20` 异常或 `vol_pctile_20` 极端的
4. `price_pctile_60` 极端的
5. `compliance = "勉强符合"` 且差值显著的

没被选中的品种 `ticker_analyses` 中**不出现**（不是写空字符串）。

**最增量/最缩量是全品种唯一一对**（用户业务严格语义），由 `classify.enrich()` 在所有品种上排序后只标记 1 个最增量 + 1 个最缩量，不再分类内打标。位置标签（龙1/空龙1 等）保留分类内逻辑。

### 每条分析必须含的维度

1. 资金进攻/防守意图（涨跌方向 + 成交量方向）
2. 量能定性（天量/爆量/放量/平量/缩量/地量，未来由 vol_pctile 自动打标）
3. 动能判定（放涨增强 / 放跌杀跌 / 缩涨惜售 / 缩跌阴跌）

走势极端异常时嵌入 `**异常**`，渲染时自动上色。

### 字段语义提示

- `today_pct / yest_pct / pct_diff / vol_ratio_20 / pct_normalized` 都是小数
- 渲染模板自动转 % 显示
- 写分析时直接说 "+4.50%"、"量比 1.85x"、"分位 P82" 等

---

# 绝对禁区（从 DESIGN.md 同步）

1. **不要让 Python 写定性分析文字** —— Python 只算数字
2. **不要让 LLM 算归类、数品种、判断标签** —— 这些是 Python 的活
3. **不要修改 `classify.py` 的边界规则**（涨跌=0 路径依赖）—— 除非用户明确要求
4. **不要修改 HTML 模板的颜色、字体、列结构** —— 视觉规范固化
5. **不要在 `analysis` 字段里写表格、列表、markdown 标题** —— 仅支持纯文本 + `**xxx**` 加粗
6. **不要把术语用错** —— 龙1/空龙1/最增量 等是用户业务严格术语
7. **不要创造新的归类或标签** —— 四象限 + 十几个标签是封闭集合
8. **不要在 enum 字段塞白名单外的值** —— schema 校验会拒绝渲染
9. **不要修改派生因子的数学定义** —— 跨日追踪一致性的基石
10. **不要让旧叙事被回头改** —— 不可变性原则是纠错记忆的根

---

# 用户偏好

- 用户邮箱: chenchang20010509@gmail.com
- 用户当前日期感知: 2026-05-21
- 用户在 Windows 工作，习惯 Obsidian 笔记体系（库在 `F:\obsidian\Vault`）
- 用户用中文沟通，技术细节也用中文
- 用户喜欢"先讨论清楚再写代码"，不要默认开工

---

# 旧工作流（已归档）

旧 docx 流水线（`ingest.py` / `prepare_*.py` / `render_docx*.py` / `merge.py` / `parse_annotation.py` / `trajectory.py` / `launcher.py` / `run.py`，共 11 个）**已归档到 `src/_archived/`**，不被新代码 import，不要在新代码里依赖。

旧 `prompts/*.md`（单时段/合并分析的历史提示词）归档到 `docs/_archived/prompts/`，**保留作为风格参考**，不必每次读全文。新双引擎 schema 取代它们成为定性输出的契约。

旧 `templates/*.html.j2` 归档到 `src/templates/_archived/`；新版唯一模板是 `src/templates/report.html.j2`。

---

# 工作时的检索路径

| 我要找什么 | 去哪里 |
|---|---|
| 某个决策为什么这样定的 | `REFACTOR_BRIEF.md` 检索关键词 |
| 设计动机 / 不要做什么 | `DESIGN.md` |
| 我作为 AI 怎么干活 | 本文件（CLAUDE.md） |
| 项目入口介绍 + 模块分类目录树 | `README.md` §二 |
| 双引擎字段 schema 细节 | `src/llm_schema.py`（实现）/ `REFACTOR_BRIEF.md` 4.3 / 4.9.6 节（决策来源） |
| 因子数学定义 | `src/factors.py`（实现）/ `REFACTOR_BRIEF.md` 4.4a 节 |
| 数据源 + auto-prtsc 集成 | `D:\git\auto prtsc\docs\ETF_PIPELINE.md` / `REFACTOR_BRIEF.md` 4.6 节 |
| 池配置 yaml 格式 | `config/pool_a.yaml`（实物）/ `REFACTOR_BRIEF.md` 4.9.3 节 |
| HTML 视觉规范 | `src/templates/report.html.j2`（实物 CSS）/ `REFACTOR_BRIEF.md` 5.3 节 |
| 滚动窗口 schema | `src/schema.py` |
| 预期审计量化公式（D1+D2） | `src/audit.py`（实现）/ `REFACTOR_BRIEF.md` 阶段 B 章节 |
| 数据更新行为矩阵 | `src/report_gap.py` 顶部 docstring |
| auto-prtsc 项目结构 | `F:\obsidian\Vault\Projects\形态复盘引擎-数据基础设施.md` |

# 模块分层（22 个 .py 按 6 层划分）

```
A. 数据流水线  update_all / data_refresh / report_gap / build_snapshot / backfill
B. 计算核心    factors / classify / panel / audit
C. 状态管理    window / schema / sync_annotations
D. LLM 协作    llm_schema / llm_prompt / llm_validate / gen_prompt / fill_narrative
E. 渲染层      render_html / color_palette / templates/report.html.j2
F. 工具        log_util
```

工作时按层定位文件 → 找代码 → 改动；不跨层乱引用。

# 常用命令

```bash
# 一键数据更新（推荐：自动检测缺口 + 补齐）
python -m src.update_all                    # A + US 全跑
python -m src.update_all --markets A        # 只 A 股
python -m src.update_all --skip-refresh     # 跳过 auto-prtsc 底层补齐

# 单时段生产（手动指定 label）
python -m src.build_snapshot --market A --label 2026-05-20-收 --session close

# 历史回填（含骨架 narrative）
python -m src.backfill --market A --start 2026-05-12 --end 2026-05-20

# 生成 LLM prompt
python -m src.gen_prompt --market A --label 2026-05-20-收 > prompt.txt

# 用 LLM 返回的 JSON 校验 + 回填
python -m src.fill_narrative --market A --label 2026-05-20-收 --json narrative.json

# 渲染 HTML
python -m src.render_html --market A --label 2026-05-20-收

# 同步 B 发回的批注
python -m src.sync_annotations --market A

# 跑所有测试
python -m pytest tests/
```
