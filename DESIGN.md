# 设计思路（DESIGN.md）

> 这份文档解释 etf_cc 项目"为什么这样设计"。
> 操作手册见 `CLAUDE.md`，需求决策记录见 `REFACTOR_BRIEF.md`，用户/开发者入口见 `README.md`。
>
> **当前状态**：2026-05-20 完成需求面封口，进入实施阶段。本文档以新架构（双市场 + 滚动窗口 + 派生因子 + 双引擎人格 + HTML 报告）为主轴写就。旧 docx + 单时段流水线作为遗留路径暂留，将在实施过程中替换。

---

## 一、项目目的与边界

### 1.1 用户在做什么

用户在 A 股稳定盈利两年，正向美股扩展。核心工作模式是**通过板块/权重股的相互强弱和集体表现，判断市场所处的状态和资金意图**。典型判断范例：

- "国债涨得很强势 → 进攻的科技可能有调整预期"
- "银行跌 + 黄金跌 + 石油跌 → 可能有大涨预期"
- "70% 的板块处于波动率收缩 → 大盘横盘概率大"

### 1.2 项目目标

把这种"板块联动判断"工作流自动化：

1. 数据自动获取（A 股 ETF + 美股权重股 + 跨资产代表）
2. 确定性指标自动计算（归类、因子、广度）
3. AI 用结构化方法论框架写定性分析（双引擎：A 股四人格 / 美股五人格）
4. 产出 HTML 报告发给协作者 B，B 批注后发回，下次合并时自动继承
5. 滚动窗口（A 股 40 时段 / 美股 20 时段）让 AI 有完整的形态全景，避免上下文不足导致的误判

### 1.3 不做什么

- 不做实盘交易接口
- 不做单只品种的深度技术分析（如缠论、波浪、画线）
- 不做基本面（财报、估值）—— 我们是量价 + 跨资产 + 情绪体系
- 不做高频或日内择时（最细粒度是"中午时段 / 收盘时段"）

---

## 二、核心设计原则

### 2.1 灵魂原则：Python 算确定性，LLM 说人话

整个项目的脊梁就这一条。展开来说：

**Python 做的事（确定性层）**：

- 数据获取与单位统一（Tushare/腾讯/yfinance）
- 四象限归类 + 位置标签 + 量能标签
- 7 个派生因子（价格分位 / 量比 / 量分位 / 均线排列 / 标准化波动 / 新高新低）
- panel_breadth（盘面广度聚合）
- 跨资产状态映射
- 数据校验 / 异常检测
- HTML 渲染（视觉规范固化）
- 滚动窗口状态机
- 批注解析（BeautifulSoup 读 HTML 内嵌 JSON）

**LLM 做的事（定性层）**：

- 单品种 ~150 字原因分析
- 分类小结（500 字+，4 维度展开）
- 双引擎人格 schema 字段（enum + 短文本理由 + what_kills_this_view）
- 跨日追踪变化评级（含纪律审查 override 机制）
- 宏观研判
- ~100 字 session_summary（不可变性原则 + 纠错记忆）

### 2.2 这条线为什么不能模糊

历史教训：早期让 LLM 直接看 xlsx 数据做归类、数品种、判断标签，结果归类抽风（同品种边界条件下今天 A 类明天 B 类）、品种漏数、格式不稳。Python 算完后 LLM 只在数字上"看图说话"，问题全消。

每次想"让 Claude 顺便算一下"的时候——**停下**，问自己：这件事是确定性的吗？是的话，写到 Python 里。

---

## 三、关键架构决策

### 3.1 双引擎人格综合体（替代角色扮演）

**问题**：用户希望 AI 用大师方法论框架分析，而不是套话研报。

**陷阱**：让 AI "扮演 Wyckoff" 写文风模仿——容易变成名字党，没有实质判断力。

**解法**：把每位大师的方法论拆成 **enum 强约束 + 短文本理由 + 反转条件**。

A 股引擎（4 字段）：

| 层级 | 字段 | 大师 |
|---|---|---|
| 全局 | `yangjia_emotion_cycle` | 炒股养家（情绪周期） |
| 上涨分类层 | `zhaolaoge_liquidity_focus` | 赵老哥（合力流动性） |
| 下跌分类层 | `fengliu_contrarian_check` | 冯柳（逆向赔率） |
| 跨日候选 per row | `trading_discipline_review` | 北京炒家/退学炒股（纪律风控） |

美股引擎（5 字段）：

| 层级 | 字段 | 大师 |
|---|---|---|
| 全局 #1 | `druckenmiller_macro_check` | Druckenmiller（跨资产宏观） |
| 全局 #2 | `minervini_breadth_check` | Minervini（市场广度/失真预警） |
| 上涨分类层 | `wyckoff_breakout_check` | Wyckoff（量价突破/派发判断） |
| 下跌分类层 | `weinstein_stage_check` | Weinstein（阶段分析） |
| 跨日候选 per row | `trading_discipline_review` | 共用 A 股纪律审查 |

**为什么 A 股 4 字段 vs 美股 5 字段**：A 股有同花顺三指数 / panel_breadth 直接做广度，不需要专门的 Minervini 字段；美股没有同花顺等价物，必须有独立的"市场广度+失真预警"字段。

**字段长度演化**：

- **2026-05-21 加 free_analysis**（≤200 字自由发挥段）：结构化字段太机械，难以承载"AI 综合体"的判断深度。
- **2026-05-22 全场放开字数上限**（用户拍板）：实测发现 LLM 在长篇深度分析时被字数上限制约，关键洞察被截断。改成"只保留下限确保不偷工，上限统一 None"。
  - 影响字段：`free_analysis` / `ticker_analyses` / `panorama_text` / `cross_validation_text` / `cross_asset_panorama` / `unique_anomaly_analysis` / `audit_note` / `rating_override.reason` / `deep_analysis`
  - 设计哲学："按内容密度而非凑字数"。LLM 想说多少说多少；evidence 字段仍建议精简（要走 alias 字面校验）
  - 未来需要重新限制：只改 `src/llm_schema.py` 顶部常量元组上限即可（校验代码已有 None 短路）

此外 narrative 顶层加 `ticker_analyses: {code: text}`（每条 ≥30 字 无上限）：LLM 从每分类挑 **1-2 个**（不是 3-4 个）最值得关注的品种写点评。`fill_narrative` 自动把 `ticker_analyses[code]` 回填到对应 `session.tickers[i].analysis`，HTML §3 表的"标签 / LLM 点评"列渲染。

**阶段 B 人格扩职（2026-05-21）**：

每个人格除原职责外承担额外任务：

| 人格 | 原职责 | 扩职 |
|---|---|---|
| 养家 | 情绪周期 enum | + `panorama_text` 150-400 字 ≥3 段全景图 / `cross_validation_text` 跨板块联动 / `strategy_outlook` 6 子项策略定调 |
| 赵老哥 | 上涨向流动性 | + `key_movers` ≥2 条上涨向板块异动解读 [{sector, phenomenon, motive, scenario}] |
| 冯柳 | 下跌向逆向赔率 | + `key_movers` ≥2 条下跌向板块异动解读 |
| 炒家（纪律） | 跨日候选纪律审查 | + `unique_anomaly_analysis` 独特异象追踪 / `strategy_outlook.risk_points` 风险点专项 / 周末 `macro_cycle_anchor` 联合署名 |

新顶层 enum：`strategy_outlook` 含 `market_phase`（情绪修复/趋势主升/高位分歧/阴跌抵抗/其他）、`trend_forecast`（上涨/震荡/下跌）、`style_tone`（偏向进攻/偏向防守/混沌期）。

**预期审计的双轨设计（2026-05-21）**：

per-ticker `audit: {actual_vs_expected, auditor}` 字段，五档评级（强超/超/符合/低/强低于预期）：

- **量化代审（auditor=quant）**：`build_snapshot` 跑完后调 `audit.quant_audit_batch` 兜底每只 ticker，D1 归类跃迁打分 + D2 量能配合打分加总映射五档。无上一时段则 None。
- **人格代审（auditor=yangjia/zhaolaoge/fengliu/discipline）**：LLM 在 narrative.ticker_audits 字段里给少数 ticker 升级为人格审，`fill_narrative` 覆盖 quant 兜底。

为什么双轨：渲染层每只品种都需要一个 audit badge（任务 2.2 要求），但 LLM 没法给 90 只品种逐只写论述。量化兜底解决"没人审"的空缺，人格审给重点品种升级语义。

panel 级整体审被取消（养家 `panorama_text` 已用自然语言承载整盘判断）。

### 3.2 派生因子设计意图

**问题**：仅看"今涨幅 / 昨涨幅 / 今成交额 / 昨成交额"信息密度太低，AI 会误判"超跌反弹 vs 主升开启"（仅看单日涨幅根本区分不了）。

**解法**：增加 7 个派生因子，提供**位置 + 量能 + 强度**三维度的硬数据。

| 因子 | 解决什么 |
|---|---|
| `price_pctile_60` / `price_pctile_20` | 位置高低（超跌区 vs 高位区） |
| `vol_ratio_20` | 真正的量比（替代"今 vs 昨"的样本量=1 噪声） |
| `vol_pctile_20` | 量能分位（天量/地量的硬阈值） |
| `ma_alignment` | 趋势状态（多头/空头/震荡） |
| `pct_normalized` | 标准化强度（抹平品种间波动率差异） |
| `new_high_20d` / `new_low_20d` | 突破/破位的客观标记 |
| `ma150_dist`（仅美股） | Weinstein 阶段分析必需的 30 周均线 |

**关键收益**：原本"放量/缩量"全靠 LLM 凭感觉判定，加完后 Python 直接给标签，LLM 只负责解读。术语从"建议词汇"变成"硬枚举"。

### 3.3 滚动窗口（current.json）状态机

**问题**：

- 当前每次合并都从 3 个时段从零跑，2/3 工作重复
- 只有 3 时段（1.5 个交易日）数据 → AI 上下文不足 → 把超跌反弹判成主升开启
- 但直接把 20 天裸数据塞 prompt 会爆 token

**解法**：

1. **数据层与叙事层分离**：数据层 20 天压成宽矩阵（KB 级），叙事层只保留最近 1-2 时段的完整 500 字小结，更早的时段压缩成 ~100 字 session_summary
2. **滚动窗口状态机**：加新时段 = append + 写新切片；超过 max_sessions 弹出最老的；LLM 只对新增片写分析
3. **A 股 max=40 / 美股 max=20**：因时段频率不同（A 股每天午+收两时段，美股仅收盘）
4. **不可变性原则**：旧叙事冻结，LLM 不可回头改；遇到打脸必须在新 session_summary 里直面误判+写纠错推演
5. **用户批注例外**：用户通过 HTML 批注覆写局部上下文，优先级 > LLM 旧切片

### 3.4 HTML 报告 + 批注闭环

**为什么从 docx 换成 HTML**：

- docx 报告 + 批注同列耦合 → 用户改格式就解析炸掉
- 协作者 B 不在本地，需要单文件传送 + 任何浏览器可读
- 浏览器 JS 能做点击批注交互 + localStorage 持久化 + File System Access API 直接覆写源文件

**事实层 vs 视图层分离**：

```
事实层（HTML 内嵌 JSON）: <script id="snapshot">  <script id="annotations">
视图层（HTML 渲染部分）: 用户随便改，下游不读
下游只读事实层
```

B 怎么改报告视觉都不影响解析；下游只关心 `<script id="annotations">` 块。

**批注交互**：

- B 点击行 → modal 选颜色（B 自选 hex，浅色系限制）+ 写备注
- localStorage 自动备份（防丢失）
- File System Access API 直接覆写源 HTML（B 一次授权后无感保存）
- 不规律节奏适配：B 任何时间发回都能 sync；已弹出窗口的时段写入 snapshots/ 归档

### 3.5 视觉规范固化在代码

**问题**：早期让 LLM 生成 HTML/docx 时，颜色会乱涂、emoji 会乱加、列结构会换。

**解法**：

- Jinja2 模板把所有视觉规范钉死（字体、颜色、列结构）
- 红蓝色规则严格（上涨/正值 #FF0000，下跌/负值 #00008B，0 涨幅黑色）
- 字体规范（华文中宋一级标题、黑体二级、楷体_GB2312 三级、仿宋_GB2312 正文）
- **严禁绿色**（用户色盲，2026-05-21 拍板）—— badge / 矩阵单元格 / sparkline 全部走红/深蓝/灰
- LLM 唯一影响视觉的口子：在分析文字里嵌 `**异常**`，自动着色

**§3 表列结构（2026-05-21 用户调整）**：

旧版"分析"列被 LLM 占满 → B 没地方写批注。改为：

- "标签 / LLM 点评"列：badges + 50-100 字 LLM 点评（仅 LLM 挑中的 1-2 个/分类）
- "批注"列（280px）：B 写完后单元格直接显示备注文字；与 modal 点击交互兼容

**均线"三球"（2026-05-21 用户调整）**：

旧版只有一个 emoji 球（多头/空头/震荡），信息量太低。改为三个独立圆点：

- close vs MA5 / MA20 / MA60，红=above / 深蓝=below / 灰=near（±0.5%）
- `factors.compute_factors` 输出 `close_vs_ma5/_ma20/_ma60` 三个独立字段

**sparkline 用真数据**：从 `etf_data_api.get_a_etf_ohlcv` 拉每只品种近 30 天真实收盘价绘制（不用窗口里的 today_pct 序列，那样会受 backfill 天数限制）。

### 3.6 auto-prtsc 集成边界

**为什么不在 etf_cc 内造数据层**：

- 用户已有 `auto-prtsc` 作为"数据基础设施"
- 切片 + 宽表双层存储范式成熟（覆盖 ~5000 个股 + ~900 美股）
- 重复造数据层是技术债

**集成方式**：Python module import（不开本地 REST，过度工程）

```python
from auto_prtsc.etf_data_api import fetch_etf_history, fetch_etf_wide_tables, fetch_etf_spot
```

**数据源优先级**（用户拍板）：

- A 股历史：Tushare Pro 主 → 腾讯财经 备 → akshare 兜底
- A 股实时：腾讯财经 主（无延迟）→ Tushare 备 → akshare 兜底
- 美股：yfinance 主 → xfinlink 备

少用 akshare 因为版本漂移导致历史问题。

### 3.7 状态延续假设（涨跌 = 0 的边界）

**保留旧设计**：涨幅 = 0 时按"路径依赖"判断，不是简单 `>= 0`。

- 昨涨 + 今 0 → 持续强化（强势横盘）
- 昨跌 + 今 0 → 连续杀跌（弱势整理）
- 双 0 → 持续强化（默认偏防御）

**重要**：这条规则是用户经过讨论确定的，不要随意改。

### 3.8 单时段分析 + 滚动渲染（阶段 A 拍板，2026-05-21）

**问题**：旧版"每次合并 3 时段重写报告"导致 LLM 调用 3× 工作量；中间时段的叙事被反复重写违反不可变性。

**解法**：

- LLM 每个时段只写 **1 份** narrative，永远冻结
- 渲染层（`render_html._build_groups`）从窗口取最近 3 个 narrative 拼成 §3 每品种 3 行展示
- 跨日报告 = 滚动窗口里 3 个独立 narrative 在渲染时拼装

**收益**：

- LLM 工作量从 3× 降到 1×
- 中间时段叙事不再被回头改，符合不可变性原则
- §3.5/§6/§7 等"全景类内容"由当前 session 单独承载，不需要每日重写

行为矩阵（A 股 / 美股 × 跑的时刻）写在 `src/report_gap.py` 顶部 docstring，决定每个时点 `update_all` 期望补哪些 label。

### 3.9 数据更新两层缺口（阶段 6 拍板，2026-05-21）

**问题**：早期 `update_all` 调 auto-prtsc 的 `gap_fill.fill_gaps()` 会扫全库 5000+ 标的，单次跑分钟级。

**解法**：拆"数据层缺口"和"报告层缺口"两条独立流程：

- **数据层**（`data_refresh.refresh_pool`）只调 auto-prtsc 暴露的池粒度 API（`etf_data_api.run_a_etf_daily_update(pool_path=...)` / `run_us_single_update(code)`），只补我们 90 只池子的切片
- **报告层**（`report_gap.detect_report_gaps`）扫 `data/snapshots/<market>/` 对照交易日历列缺的 label

底层全量 gap_fill 是 auto-prtsc 自己的季度任务，与 etf_cc 解耦。

### 3.10 A 股 -午 时段的特殊性

A 股盘中 `-午` label 的数据**无法历史回填**——切片永远是收盘后的全天日线，不存在"半天 amount"。两条强约束：

- `build_snapshot` 在 `session_time="noon"` 且 `trade_date != today` 时 raise，禁止历史回填
- `report_gap.expected_labels` 只在 end_date == today 且 `a_until in (None, "noon")` 时产 -午

当日盘中（11:35-15:05）真正跑 `-午`：调 `etf_data_api.get_a_etf_realtime` 拉腾讯快照 append 到历史末尾后算 factors，`factors` 内部用 today_amount × 2 估算全天成交额。

---

## 四、术语库（封闭集合，严格遵守）

所有术语在 Python 代码里写死，LLM 写分析时也必须用这套词。新增"创造性"术语会被 schema 校验拒绝渲染。

### 4.1 四象限归类

| 分类 | 定义 |
|---|---|
| 持续强化 | 昨涨 + 今涨（含状态延续的 0 边界） |
| 反包修复 | 昨跌 + 今涨 |
| 强反转 | 昨涨 + 今跌（含状态延续的 0 边界） |
| 连续杀跌 | 昨跌 + 今跌 |

### 4.2 位置特征标签

| 分类 | 最强 | 次强 | 最弱 |
|---|---|---|---|
| 持续强化 | 龙1 | 龙2 | — |
| 反包修复 | 修复龙1 | 修复龙2 | 最弱修复 |
| 强反转 | 反转空龙1 | 反转空龙2 | 最弱反转 |
| 连续杀跌 | 空龙1 | 空龙2 | — |

分类内品种 < 3 个时全部标"独特"。

### 4.3 量能标签

每个分类内成交额环比最高 → "最增量"，最低 → "最缩量"。

### 4.4 量能定性词

天量 / 爆量 / 放量 / 平量 / 缩量 / 地量。**未来由 Python 基于 vol_pctile_20 直接打标**，LLM 只解读。

### 4.5 跨日变化评级

四档：大加强 / 加强 / 减弱 / 大减弱。`discipline_pass=false` 默认降一档，`rating_override` 可破例。

### 4.6 双引擎 enum 集合

详见 `REFACTOR_BRIEF.md` 4.3 / 4.9.6 节。所有 enum 不在白名单 → Python 校验拒绝渲染。

---

## 五、绝对禁区

1. 不要让 Python 写定性分析文字 —— Python 只算数字
2. 不要让 LLM 算归类、数品种、判断标签 —— 这些是 Python 的活
3. 不要修改 `classify.py` 的边界规则（涨跌 = 0 的路径依赖）—— 除非用户明确要求
4. 不要修改 HTML 模板的颜色、字体、列结构 —— 这些是固化的视觉规范
5. 不要在 `analysis` 字段里写表格、列表、markdown 标题 —— 模板期望纯文本（仅支持 `**xxx**` 加粗）
6. 不要把术语用错 —— "龙1" 不是"龙头"，"空龙1" 不是"龙头股的反面"
7. 不要创造新的归类或新的标签 —— 四个分类和那十几个标签是封闭集合
8. 不要在 enum 字段里塞白名单外的值 —— schema 校验会拒绝渲染
9. 不要修改派生因子的数学定义 —— 这些是跨日追踪一致性的基石
10. 不要让旧叙事被 LLM 回头改 —— 不可变性原则是纠错记忆的根

---

## 六、为什么这次重构必须做（动机）

### 6.1 旧架构的痛点

| 痛点 | 影响 |
|---|---|
| 仅 3 时段窗口 | AI 把超跌反弹判成主升开启 |
| 每次合并 2/3 重复 | 工时浪费 |
| 提示词无方法论框架 | 写出来是研报套话 |
| docx 批注脆弱 | 用户改格式就解析炸 |
| 缺自动取数 | 永远要手粘 xlsx |
| 美股迁移没思路 | 之前直接套 A 股 ETF 思路效果差 |

### 6.2 重构解决的根本问题

| 旧问题 | 新方案 |
|---|---|
| 上下文不足 | 20 日窗口 + 7 派生因子 + 数据矩阵 |
| 工作重复 | 滚动窗口 + 增量合并 |
| 套话研报 | 双引擎 5+4 字段 schema 强约束 |
| 批注脆弱 | HTML 自包含 + JS 交互 + JSON 内嵌 + FSA API |
| 手粘数据 | 接入 auto-prtsc 自动取数 |
| 美股没思路 | 权重股替代 ETF + 8 维 cross_asset |

### 6.3 为什么不一次性更大

考虑过的没做事项：

- **错题本接入**：把用户复盘记录、CRO 提示词、PA 教练角色整合 → 未来扩展，本轮不做
- **同花顺自动取数**：iFinD API 或 Playwright → 用户决定先搁置（auto-prtsc 现有路径够用）
- **历史归类变化序列**：把 N 时段归类序列化喂 LLM 识别"长期主线 vs 短期噪声" → 滚动窗口已覆盖此能力的基本面
- **完整性校验扩展**：白名单品种校验 → 后续按需加

---

## 七、调试建议

遇到问题时按顺序排查：

1. **数字字段不对** → 排查 `factors.py` / `classify.py` / `ingest.py`，绝不是 LLM 问题
2. **品种漏数** → 看 fetch 层是否过滤、池配置是否齐全
3. **enum 校验失败** → LLM 输出不在白名单，检查 prompt 是否清晰列出允许值
4. **HTML 视觉异常** → 改 Jinja2 模板，不要碰 LLM 提示词
5. **跨日评级没逻辑** → 改 schema 里的 discipline / rating 规则
6. **批注解析失败** → 看 HTML 内嵌 `<script id="annotations">` 块是否存在
7. **数据更新失败** → 看 `data/logs/errors/<timestamp>_<ticker>.json`，AI 可直接复查

---

## 八、相关文档

- `REFACTOR_BRIEF.md` — 完整需求决策记录（最详细，所有"拍板"的检索源）
- `CLAUDE.md` — AI agent 工作指南（怎么在这个项目里干活）
- `README.md` — 项目入口（AI / 开发者 / 用户三视角）
- Obsidian: `F:\obsidian\Vault\Projects\ETF量价分析自动化.md` — 项目笔记
- Obsidian: `F:\obsidian\Vault\Projects\形态复盘引擎-数据基础设施.md` — auto-prtsc 数据层
