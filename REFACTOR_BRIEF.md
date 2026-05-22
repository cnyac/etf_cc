# ETF 量价分析项目 — 重构讨论简报

> 这份文档是 Claude Code 与用户（CC）就 etf_cc 项目本轮重构进行讨论后的阶段性总结，准备发给 Gemini 协同思考。
> Gemini 没有看过本项目的代码和历史对话，请把这份当作完整背景。

---

## 一、项目背景

### 1.1 项目目的

用户在 A 股做 ETF 量价分析，已有稳定盈利体系两年。每个交易时段（中午/收盘）把同花顺导出的数据粘到 xlsx，跑一套自动化流程产出 **Word (.docx) 研报**，用户在 docx 备注列写颜色批注+文字，次日合并分析时批注会自动继承并着色。

监控池约 42 只 A 股 ETF + 3 个同花顺指数（全A、热股、情绪指数）。

### 1.2 当前架构核心原则

**所有确定性计算由 Python 做，LLM 只负责"看着数据说人话"。**

- Python 侧（确定性层）：xlsx 解析、四象限归类、特征标签（龙1/空龙1 等）、统计、渲染 docx
- LLM 侧（定性层）：单品种 ~150 字原因分析、分类小结（500字+）、跨日追踪评级、宏观研判

中间用 JSON 作交接物，支持中断恢复和合并时复用。

### 1.3 当前工作流

**单时段分析**：xlsx → `prepare_single.py`（算确定性指标）→ JSON → Claude 填 analysis 字段 → `render_docx.py` → docx

**多时段合并**：`prepare_merge.py`（对齐 N 个 label，可注入昨日 docx 批注）→ JSON（含 `prev_annotations` 和空 `color_palette`）→ Claude 写分类小结/跨日评级/宏观研判 + 填 color_palette → `render_merge_docx.py` → docx

### 1.4 业务术语（封闭集合，不可创造新词）

- **四个分类**：持续强化（昨涨+今涨）/ 反包修复（昨跌+今涨）/ 强反转（昨涨+今跌）/ 连续杀跌（昨跌+今跌）
- **位置标签**：龙1/龙2 / 修复龙1/2/最弱修复 / 反转空龙1/2/最弱反转 / 空龙1/2
- **量能标签**：最增量 / 最缩量
- **量能定性词**：天量/爆量/放量/平量/缩量/地量
- **跨日变化评级**：大加强 / 加强 / 减弱 / 大减弱

---

## 二、用户在本次重构中提出的核心痛点

### 痛点 1：数据自动化缺失

当前每个时段需要手动从同花顺导出 xlsx → 粘到固定路径。无法实现真正自动化。

**有利条件**：用户另一个项目 `D:\git\auto-prtsc`（形态复盘引擎）已经有成熟的数据基础设施：
- A股：Tushare（主）+ akshare（备）
- 美股：yfinance（主）+ xfinlink（备）
- ETF权重监控、指数爬虫
- 切片（每只一个 parquet）+ 宽表（矩阵）双层存储
- 已有 `semi_daily_match.py` 处理同花顺 XLS 输入

**问题**：etf_cc 完全没有接入这套基础设施。

### 痛点 2：合并工作 2/3 是重复劳动

当前合并 3 个时段的研报是从零开始合并。如果每天加一个新时段、丢掉最老的，新工作流应该是：
- 删除不需要的时段
- 添加最新时段
- 只对"新增的那一片"重新写分析，旧片冻结复用

而不是每次都重新跑 3 段全量合并。

### 痛点 3：上下文不足导致 AI 严重误判

只有 3 个时段（约 1.5 个交易日）的数据，AI 看不到形态全景，会出现"把超跌反弹判成主升开启"这类乌龙。

用户原始讨论中明确说：3 天数据 → AI 上下文不足 → 计算力（推理质量）也跟着下降。需要扩到 20 天甚至更长，但又面临"一次对话装不下"的问题，所以**表格/表头需要重新设计**以适应长窗口。

### 痛点 4：提示词过于简陋，没有"人格优势"

当前提示词只是要求"写 500 字、4 维度展开"，没有方法论框架。用户希望构建一个**AI 综合体（投资者人格）**，融合多位大师的方法论，让 AI 用结构化的方法论框架去分析，而不是套话写作。

参考资料：用户给了一份"超级个体"配置建议（原本是为美股迁移写的），推荐 Wyckoff（量价）+ Druckenmiller（跨资产）+ Weinstein（阶段分析）+ Minervini（市场广度）。

但这是美股版本，A 股需要重新配。

### 痛点 5（原始讨论中提到，本次同样适用）

**人格要匹配数据窗口**：如果只给 AI 看 20 天日 K，那选巴菲特毫无意义（他要看 5-10 年基本面）。要选"用 20 天数据就能下判断"的高手。

---

## 三、目前讨论的方向与共识

### 3.1 优先级判断

- **认知层重构**（窗口扩展 + 人格综合体 + 增量合并）= 高优先级，直接解决 AI 误判
- **工程层改造**（自动取数）= 次优先级，提效但不解决判断质量
- **美股迁移** = 留到下一轮

### 3.2 关键架构取舍

#### 取舍 A：上下文怎么扩到 20 天又不爆 token

**方案**：数据层与叙事层分离
- **数据层**：宽矩阵格式（行 = ETF，列 = 日期，值 = 归类标签 / 动能等级 / 量比分级），20 天压成一张表，KB 级
- **叙事层**：只保留最近 1-2 个时段的完整 500 字小结；更早的时段压缩成一句话特征（如 "5/18 收盘：风格切到防御，银行龙1"）；再老的就只剩矩阵里的标签

借鉴 `auto-prtsc` 的宽表范式。

#### 取舍 B：增量合并怎么落

维护一个 `data/window/current.json`：
- 加新时段 = append 一列 + 生成新叙事切片
- 删旧时段 = 弹出最老的一列 + 丢弃对应叙事
- LLM 只对"新增的那一片"写分析

预计省 2/3 token 和时间。

#### 取舍 C：A 股版人格综合体

不照搬美股版那四位。A 股工作模式是"板块强弱比较 + 跨资产联动 + 情绪/广度"，建议：

| 维度 | 人选 | 用来回答 |
|---|---|---|
| 量价与相对强弱 | Wyckoff | 这个板块是吸筹还是派发？放量是真突破还是诱多？ |
| 板块阶段划分 | Weinstein | 通信ETF 处于阶段几？多少比例的板块在阶段二？ |
| 跨资产联动 | Druckenmiller | 国债涨 + 黄金涨 = 资金避险预期；那么科技该减仓多少？ |
| 板块轮动节奏 | Sam Stovall（GICS轮动）或 Martin Pring | 经济周期当前位置 → 该轮到哪些板块？ |

去掉了 Minervini（市场广度），因为用户已经有同花顺情绪指数 + 热股 + 全A 作为广度代理，重复了。

**关键实现方式**：不是让 AI"扮演"某位大师写文风，而是把每个人的方法论拆成**强制清单**——每次分析必须回答清单上的具体问题。否则就是名字党。

#### 取舍 D：自动取数路径

接入 `auto-prtsc`，不要自建。
- ETF 日线 + 半日数据：Tushare `pro.daily` + 中午时段用 akshare 实时快照
- 三个同花顺指数：看 auto-prtsc 是否已抓，没抓就加
- 写一个 `src/fetch.py` 替代"粘到 xlsx"这一步；原 xlsx 路径保留作 fallback

### 3.3 关于派生因子（最新讨论焦点）

用户问：原始数据能否提供 20 日均量、量比、20 日均值等派生指标，去佐证当日行情的强度和显著度？

**Claude 回答：强烈建议加**。这是项目"Python 算确定性 + LLM 说人话"原则的天然延伸，且 `auto-prtsc` 的宽表数据已经有，向量化算几行 pandas 即可。

#### 建议加的因子清单

**量能维度（最高优先级）**：
- `vol_ma20` / `vol_ma5` — 20/5 日均成交额（基准线）
- `vol_ratio_20` = 今 / 20 日均 — 真正的量比（替代当前"今 vs 昨"，后者样本量=1，噪声大）
- `vol_pctile_20` — 今日量在过去 20 日的百分位（>90 = 天量，<10 = 地量）
- `vol_zscore_20` — 跨品种横向比较用

**关键收益**：当前"天量/爆量/放量/平量/缩量/地量"全靠 LLM 凭感觉判定，加完后让 **Python 直接给标签**，LLM 只负责解读。术语从"建议词汇"变成"硬枚举"。

**价格位置维度（直接解决"超跌反弹 vs 主升开启"误判）**：
- `price_pctile_20` / `price_pctile_60` — 收盘价在 20/60 日区间的分位（这条最关键：超跌反弹 = 分位 <20 的反弹；主升 = 分位 >70 持续创新高）
- `dist_ma20` / `dist_ma60` — 偏离均线百分比
- `new_high_20d` / `new_low_20d` — 是否创 20 日新高/新低
- `ma_alignment` — 5/20/60 均线多空排列（对应 Weinstein 阶段 1-4）

**强度标准化维度**：
- `atr_20` 或 20 日波动率 — 该品种的"日常波动量"
- `pct_normalized` = 今涨幅 / ATR — 标准化强度（+2% 对低波动品种是异动，对高波动品种是日常）

#### 工程注意点

1. **中午半日量怎么对齐 20 日全日均**：方案 A（半日量 ×2 日化再除均量，简单可行）vs 方案 B（维护单独的"过去 20 个中午时段"均量序列，更精确但要数据积累）。倾向先 A 后 B。
2. **窗口长度**：20 日抓近期强度，60 日抓位置高低；再长（120/250）作为可选。
3. **代码层级**：新模块 `factors.py`，挂载到 snapshot 的每个 item 上。`classify.py` 不动，向后兼容。
4. **LLM 输入**：跨日追踪表加 3-4 列（量比、价格分位、量分位、新高新低标记）。
5. **潜在升级**：龙1 标签可以叠加位置约束 →「龙1（高位放量）」vs「龙1（低位首日突破）」，两种龙1 的推演完全不同。

---

## 四、已拍板的决策（2026-05-20 第二轮讨论后）

基于 Gemini 反馈 + Claude 边界补刀 + 用户最终拍板，以下事项已定调：

### 4.1 窗口与因子

- **窗口长度**：20 交易日 ≈ 40 时段
- **派生因子清单（7 个，全部必备）**：
  1. `price_pctile_60` — 60 日价格分位（位置高低锚）
  2. `price_pctile_20` — 20 日价格分位（近期回归位置）
  3. `vol_ratio_20` — 20 日量比（连续型放量度量）
  4. `vol_pctile_20` — 20 日量分位（有界、抗极端值）
  5. `ma_alignment` — 5/20/60 均线排列（趋势状态枚举）
  6. `pct_normalized` — 今涨幅 / 20 日 ATR（跨品种强度标准化）
  7. `new_high_20d` / `new_low_20d` — 20 日新高新低标记（突破/破位布尔）
- **因子计算粒度 = 日级**（用 auto-prtsc 日线宽表算）；**数据矩阵粒度 = 时段级**（40 行）
- **中午时段处理**：今日半日量 ×2 估算"全日节奏"再进入 20 日基准对比

### 4.2 双引擎人格综合体

- **A 股引擎**：炒股养家（情绪周期）+ 冯柳（逆向赔率）+ 赵老哥（合力流动性）+ 北京炒家/退学炒股（纪律风控）
- **美股引擎**：Wyckoff + Weinstein + Druckenmiller（留待美股迁移阶段）
- **实现方式**：JSON Schema 强制字段，不做角色扮演

### 4.3 JSON Schema 字段分层方案（已封口）

| 字段 | 层级 | 锚定 | 必填项 |
|---|---|---|---|
| `yangjia_emotion_cycle` | 全局（1 份/时段） | — | stage / intensity / evidence / next_session_expect / what_kills_this_view |
| `zhaolaoge_liquidity_focus` | 分类层（仅持续强化 + 反包修复） | Python 注入：龙1 + 最增量，不过滤量能 | anchor_etfs / liquidity_signal / evidence / follow_strategy / what_kills_this_view |
| `fengliu_contrarian_check` | 分类层（仅强反转 + 连续杀跌） | Python 筛 `price_pctile_60<20 且 vol_pctile_20<30` + 按分位升序取 top 3 | anchor_etfs / contrarian_grade / evidence / left_side_window / what_kills_this_view |
| `trading_discipline_review` | 跨日候选每行 | — | logic_hardness / risk_reward_ratio / discipline_pass / rating_override（可选） / review_note |

**enum 取值**：

- `stage`：冰点 / 试错 / 发酵 / 高潮 / 退潮
- `intensity`：弱 / 中 / 强
- `liquidity_signal`：主线合力 / 局部脉冲 / 弱合力 / 无合力
- `contrarian_grade`：高赔率 / 中赔率 / 低赔率 / 陷阱区
- `logic_hardness`：硬 / 软 / 牵强
- `risk_reward_ratio`：优 / 中 / 差

**特殊规则**：

- 每个字段的 `what_kills_this_view` 必填（不可变性原则的承诺锚点）
- `discipline_pass = false` 默认评级降一档；填 `rating_override = {keep_rating, reason}` 可破例保留原评级或上调一档（不可跨档），reason ≤30 字
- 各字段筛选条件无候选时填 `null`，session_summary 说明原因
- enum 不在白名单 → Python 校验拒绝渲染

### 4.4a factors.py 七因子契约（已封口）

| 因子 | 窗口 | 公式 | 含当日 | 不足返 null 阈值 |
|---|---|---|---|---|
| `price_pctile_60` | 60 日 | rank(close_today)/60×100，取整 | 是 | <30 日 |
| `price_pctile_20` | 20 日 | rank(close_today)/20×100，取整 | 是 | <10 日 |
| `vol_ratio_20` | 20 日 | today_amount / mean(amount[-20:不含当日]) | 否（基准不含） | <5 日 |
| `vol_pctile_20` | 20 日 | rank(today_amount)/20×100，取整 | 是 | <10 日 |
| `ma_alignment` | 5/20/60 日 | SMA 三均线排列 → 多头/空头/震荡 | 是 | <60 日 |
| `pct_normalized` | 20 日 | today_pct / (ATR_20 / yesterday_close) | — | <20 日（前置依赖 high/low 列） |
| `new_high_20d` / `new_low_20d` | 20 日 | close_today vs max/min(close[-20:]) | 是 | <20 日 |

**通用规则**：

- 不做 partial 计算；数据不足直接 null
- 中午时段 `today_amount` 入 vol_ratio_20 / vol_pctile_20 前先 ×2（先 A 后 B 策略）
- 异常阈值：`|pct_normalized| > 2` → HTML 行级 ⚠
- 与 LLM 嵌入 `**异常**` 双轨保留（Python 客观异常 vs LLM 主观异常）

**ATR 计算前置依赖**：方案 A 需 auto-prtsc 提供 high / low 列。话题 4 集成时确认；若暂缺，先 σ fallback 跑通，后续 swap。

### 4.4b panel_breadth 模块（替代同花顺三指数）

同花顺 883957/883910/883404 数据源无法获取，改为从 42 只 ETF 池自身派生盘面广度，作为 `yangjia_emotion_cycle.evidence` 的硬数据源：

```json
{
  "up_count": 28, "down_count": 14, "flat_count": 0,
  "strong_up_count": 8,           // 涨幅 >2%
  "strong_down_count": 3,          // 跌幅 <-2%
  "vol_expansion_count": 12,       // vol_ratio_20 > 1.5
  "vol_contraction_count": 18,     // vol_ratio_20 < 0.7
  "cross_asset_state": {
    "treasury_10y": "down",        // SH511260 十年国债
    "treasury_30y": "down",        // SH511090 三十年国债（分开分析）
    "gold": "down",                // SH518880
    "oil": "up"                    // SH501018
  },
  "category_distribution": {
    "持续强化": 18, "反包修复": 10, "强反转": 8, "连续杀跌": 6
  }
}
```

`cross_asset_state` 阈值：涨幅 >+0.3% = up，<-0.3% = down，介于则 flat。

### 4.4 叙事层与状态管理

- 每个时段产出 **~100 字 `session_summary`**（含风格判断 + 主线锚定 + 预期推演 + 风险提示）
- **不可变性原则**：LLM 不可回头修改旧切片，必须在新时段直面误判并写纠错推演
- **用户批注例外**：用户批注可覆写局部上下文（沿用现有批注闭环），优先级 > LLM 旧切片
- 20 时段总记忆 ~2000 字，保留完整推演闭环

### 4.5 历史 backfill 策略

- 从 auto-prtsc 拉 20 天日线宽表全量回填因子
- 历史时段的 `session_summary` 字段用 **Python 自动生成"骨架特征"**（如 "5/15 收盘：35% 板块上涨，龙1=芯片，最增量=游戏，情绪指数 X"）
- 骨架 summary 显式标记来源（机器生成 vs LLM 撰写），AI 知道这不是自己的判断

### 4.6 基础设施集成（已封口 + 双市场扩展）

#### 4.6.1 集成形态

- Python module import（不开本地 REST）
- etf_cc 通过 `from auto_prtsc.etf_data_api import ...` 调用
- 同花顺 xlsx 路径保留作 fallback

#### 4.6.2 数据源优先级

| 用途 | 主源 | 备源 | 兜底 |
|---|---|---|---|
| A 股 ETF 历史日线 | Tushare Pro `pro.fund_daily` | 腾讯财经 `fqkline` | akshare `fund_etf_hist_em`（LOF 用 `fund_lof_hist_em`） |
| A 股 ETF 实时快照 | 腾讯财经 `qt.gtimg.cn` | Tushare（盘后） | akshare `fund_etf_spot_em` |
| 美股历史日线 | yfinance（auto-prtsc 现有） | xfinlink（付费） | — |
| 美股实时快照 | yfinance | xfinlink | — |

失败转移：主→备→兜底逐级 fallback，全失败则 abort 当前时段 + 日志记录。

#### 4.6.3 auto-prtsc 侧需要新增

```
auto_prtsc/
  etf_data_api.py                  ← 给 etf_cc 调用的稳定 API
  etf_fetchers/
    tushare_fetcher.py
    tencent_fetcher.py
    akshare_fetcher.py
  a/
    etf_pool.json                  ← ETF 池清单
    etf_update.py                  ← 增量更新
    etf_build.py                   ← 切片 → 宽表
quant_data/
  etf_slices/<ticker>.parquet
  A_Share_ETF_Daily_Close_Wide.parquet
  A_Share_ETF_Daily_Amount_Wide.parquet
  A_Share_ETF_Daily_High_Wide.parquet
  A_Share_ETF_Daily_Low_Wide.parquet
```

美股侧 auto-prtsc 已有完整切片（OHLCV），只需补：

```
auto_prtsc/quant_data/
  US_Daily_High_Wide.parquet       ← 从切片 reshape（0.5 天）
  US_Daily_Low_Wide.parquet
```

美股 amount 不用宽表，用 volume 替代（个股语境）。

#### 4.6.4 单位约定（跨源统一）

| 字段 | 单位 |
|---|---|
| pct（涨跌幅） | 小数（0.045 = 4.5%） |
| close / open / high / low | 元 / USD |
| volume | 手（A 股）/ 股（美股） |
| amount | 元（A 股） |
| fetched_at | ISO 8601 |

#### 4.6.5 数据更新输出规范（用户可读 + AI 可复查）

每次 `update_all_pools.py` 输出汇总报告（含成功/备源/兜底/失败计数、宽表重建状态、耗时、日志路径）。失败明细写 `data/logs/errors/<timestamp>_<ticker>.json` 含 traceback + 三源尝试详情，便于 AI 复查。

### 4.9 双市场对称设计（A 股 + 美股）

#### 4.9.1 时段策略

| 市场 | 每日时段 | 数据获取时机 | max_sessions |
|---|---|---|---|
| A 股 | 午（11:35） + 收（15:05） | 当日 | 40（20 天 × 2） |
| 美股 | 仅收盘 | 北京次日 5:30 自动拉 | 20（20 天 × 1） |

A 股和美股**各自独立的 current.json** 状态机，互不干扰。

#### 4.9.2 文件结构

```
data/
  window/
    pool_a.json              ← A 股滚动窗口
    pool_us.json             ← 美股滚动窗口
  snapshots/
    a/<label>.json
    us/<label>.json
  reports/
    a/<label>.html
    us/<label>.html
config/
  pool_a.yaml                ← A 股池清单（用户可编辑）
  pool_us.yaml               ← 美股池清单（用户可编辑）
```

#### 4.9.3 池配置文件（YAML，含 role 字段）

```yaml
market: a_share
session_types: ["午", "收"]
items:
  - code: SH510300
    name: 沪深300ETF
    role: monitor
  - code: SH511260
    name: 十年国债ETF
    role: [monitor, treasury_10y]
  # ...
```

`role` 支持单值或列表。跨资产代表通过 role 字段标注（treasury_10y / treasury_30y / gold / oil / dollar / vix / btc / eth）。改池子只改 YAML，代码不感知。

#### 4.9.4 美股池（已确认 + 补 IEF）

44 只用户给定品种 + 补 1 只 **IEF**（7-10年美债 ETF，用作 treasury_10y 代表）= 45 只。

**跨资产 role 映射**：

| role | 代码 | 说明 |
|---|---|---|
| treasury_10y | IEF | 补入池 |
| treasury_30y | TLT | 替代 ^TYX |
| dollar | UUP | 池内 |
| gold | GLD | 池内 |
| oil | USO | 池内 |
| vix | VIXY | 池内 |
| btc | IBIT | 池内 |
| eth | ETHA | 池内 |

美股 `cross_asset_state` 比 A 股的 4 维（10年/30年/黄金/油）扩到 8 维。

#### 4.9.5 双引擎人格分层（已封口）

| 层级 | A 股（4 字段） | 美股（5 字段） |
|---|---|---|
| 全局 #1 | `yangjia_emotion_cycle` | `druckenmiller_macro_check` |
| 全局 #2 | —（A 股 panel_breadth 已覆盖广度，不加） | `minervini_breadth_check`（市场广度/失真预警） |
| 上涨分类层 | `zhaolaoge_liquidity_focus` | `wyckoff_breakout_check` |
| 下跌分类层 | `fengliu_contrarian_check` | `weinstein_stage_check` |
| 跨日候选 per row | `trading_discipline_review` | `trading_discipline_review`（通用，共用） |

#### 4.9.6 美股五字段 schema（已封口）

**字段 1：`druckenmiller_macro_check`**（全局，跨资产视角）

- enum：`macro_regime` ∈ {紧缩避险/紧缩进攻/中性震荡/宽松避险/宽松进攻/转折临界}
- enum：`key_signal` ∈ {利率主导/美元主导/商品主导/VIX主导/加密风险偏好/多空交战}
- 必填：`evidence`（≤50 字，**强约束**：至少引用 4 个跨资产维度的方向 + 数字）/ `next_session_expect` / `what_kills_this_view`

**字段 2：`minervini_breadth_check`**（全局，市场广度）

- enum：`breadth_state` ∈ {健康/失真临界/失真严重/筑底修复/趋势确认}
- enum：`key_metric_focus` ∈ {大小盘分化/200日均线广度/新高数量/风格集中度/多空交战}
- 必填：`evidence`（≤50 字，**强约束**：至少引用 above_ma150_count / spy_iwm_divergence / new_high_count_20d 三项中的两项 + 具体数字）/ `divergence_warning`（"是/否"+ 说明）/ `what_kills_this_view`

**字段 3：`wyckoff_breakout_check`**（上涨分类层）

- 锚定：分类内龙1 + 最增量（Python 注入）
- enum：`wyckoff_phase` ∈ {主升加速/主升中段/分配前夕/派发中/诱多突破}
- enum：`vol_price_quality` ∈ {价量配合/价量背离/缩量阴阳怪气}
- 必填：`anchor_tickers` / `evidence` / `follow_strategy` / `what_kills_this_view`

**字段 4：`weinstein_stage_check`**（下跌分类层）

- 锚定：Python 筛 `price_pctile_60 < 30` + 按分位升序 top 3
- enum：`weinstein_stage` ∈ {阶段1底部建仓/阶段2主升初期/阶段3顶部分配/阶段4主跌中/阶段不明}
- enum：`ma_relation` ∈ {站上30周均线/跌破30周均线/围绕30周均线震荡}
- 必填：`anchor_tickers` / `evidence` / `entry_opportunity` / `what_kills_this_view`
- 注：ma150 数据不足时该品种降级（不锚定 + evidence 说明数据不足）

**字段 5：`trading_discipline_review`**（共用 A 股，每跨日候选品种一份）

- 完全复用 4.3 节 A 股定义，不换皮

#### 4.9.7 美股 factors 补充因子（仅美股算）

- `ma150_dist`（距 30 周均线偏离百分比，单位 %）
- `ma150_relation` ∈ {站上/跌破/震荡}（±2% 为震荡阈值）
- 数据不足返 null

#### 4.9.8 panel_breadth 美股版扩展字段

```json
{
  // ... 通用字段同 A 股
  "above_ma150_count": 24,        // 仅美股
  "spy_iwm_divergence": 0.020,    // 仅美股，SPY 涨幅 - IWM 涨幅
  "new_high_count_20d": 5         // A 股 + 美股都加，聚合 new_high_20d
}
```

#### 4.9.6 报告分两份独立 HTML

- `reports/a/<label>.html` — 仅 A 股内容
- `reports/us/<label>.html` — 仅美股内容
- B 收到两份分别阅读批注，互不影响
- A 侧 sync 时各自归档到 pool_a.json / pool_us.json

### 4.9.9 工程预警补充（Gemini 二轮审查）

#### Token 瘦身策略

LLM 输入侧统一用短键 + 取值压缩，避免"Lost in the Middle"注意力稀释。

| 长键（存储） | 短键（LLM 输入） | 压缩 |
|---|---|---|
| price_pctile_60 / _20 | p60 / p20 | int |
| vol_ratio_20 | vr20 | float 1 位 |
| vol_pctile_20 | vp20 | int |
| ma_alignment | ma | 1/-1/0 |
| pct_normalized | pn | float 1 位 |
| new_high_20d / new_low_20d | nh / nl | bool |
| ma150_dist / ma150_relation | md / mr | float / 1/-1/0 |
| category | cat | 1/2/3/4 |
| features | f | L1/L2/SL1/SL2/RSL1/M+/M- |

prompt 头部给 ~80 字 mapping 字典。存储侧保持长键（可读 + Git diff 友好），仅 LLM 输入/回写做长↔短映射。预估节省矩阵 token ~80%。

#### 校验降级机制

当 cross_asset_state 或 panel_breadth 某维度为 null（数据源失败），evidence 强约束动态降级：

- druckenmiller：可用维度数 ≥6 要求引用 4；≥4 要求 (n-2)；≥2 要求引用所有可用；<2 仅要求声明"数据严重缺失"
- minervini：类似规则，三项可用全要求引用，缺一项降一档

降级触发时 LLM 必须在 evidence 末尾显式声明"数据缺失"。Python 通过关键词匹配（"数据缺失"/"暂缺"/"不可用"）放行。降级事件写 INFO 日志便于审计。

#### 色板闭环管理

`data/window/color_palette.json` 全局共享（双市场跨时段统一）。每次生成 HTML 时 Python 静态注入到 `<script id="known_palette">` 块。JS 初始化时把已用颜色填进 picker 下拉建议（已用优先）。sync_annotations 时增量合并 B 新加的颜色。

B 跨设备体验：在任何时段任何市场的 HTML 上都能看到完整历史调色板。

### 4.10 整体工作量估算（11 天）

| 阶段 | 工作 | 估时 |
|---|---|---|
| 1a | auto-prtsc 侧 A 股 ETF 管道 | 1 天 |
| 1b | auto-prtsc 侧补美股 high/low 宽表 | 0.5 天 |
| 1c | etf_data_api.py 统一 A 股 + 美股调用层 | 0.5 天 |
| 2 | etf_cc 侧 factors.py / panel.py | 1.5 天 |
| 3 | etf_cc 侧滚动窗口（A 股 + 美股各一套状态机） | 2 天 |
| 4 | LLM prompt 双引擎（A 股 + 美股两套人格 schema） | 1.5 天 |
| 5 | HTML 渲染（两份独立报告） | 2.5 天 |
| 6 | backfill + 池配置加载 + 数据更新汇总输出 | 1 天 |
| 7 | 端到端联调 + 文档 | 0.5 天 |

### 4.7 增量合并

- 维护 `data/window/current.json` 滚动窗口
- 加新时段 = append + 生成新叙事切片；删旧 = 弹出 + 丢弃叙事
- LLM 只对"新增片"写分析，旧片冻结复用

### 4.8 滚动窗口 current.json schema（已封口）

**文件位置**：

```
data/
  window/current.json     ← 滚动窗口（最多 40 时段）
  snapshots/<label>.json  ← 历史归档（永久保留）
  reports/<label>.html    ← HTML 报告（每时段一份）
```

**关键决策**：

- `max_sessions = 40`（20 交易日 × 2 时段，严格执行）
- label 格式：`YYYY-MM-DD-午` / `YYYY-MM-DD-收`（中文，直观）
- 弹出窗口仅从 current.json 删除，snapshots/ 永久保留
- 字段冻结原则：snapshot / factors / classify / panel / narrative 不可回头改；annotations 可被用户覆写
- `tracking.rating_history` append-only，永不修改

**批注同步流程**（适配 B 不规律节奏）：

- 触发：手动 `sync_annotations.py` + prepare 新时段时自动（C 方案）
- 解析 HTML 内嵌 `<script id="snapshot">.label`（不依赖文件名）
- 多次发回同一时段 → 以 mtime 最新为准（不做 merge，HTML 内嵌即完整快照）
- 批注属于已弹出时段 → 写 snapshots/<label>.json 归档，不进 current.json（方案 A）
- 给 LLM 的呈现：按品种轨迹聚合（"510300 批注轨迹：[5/20] 夕阳红 → [5/18] 红色 → [5/15] 鹅黄"）

**HTML 前端辅助**：

- 未保存提示（顶部红色横幅）
- 最后保存时间 watermark
- 每个 ETF 行**可点击展开"历史批注线索栏"**，显示该品种最近 5 个时段的批注（只读）

**骨架 narrative（backfill 用）**：

- 一行汇总文字 + `is_skeleton=true` 标记
- 模板：`<日期><时段> [机器生成]: 上涨 X/42（pct%），强势 N 个，量能扩张 M 个；<跨资产状态>；龙1=X，最增量=Y；分类分布 持续强化 N / 反包修复 N / 强反转 N / 连续杀跌 N。`
- 其他 narrative 子字段（yangjia/category_summaries/item_analyses）留空
- LLM 看到 `is_skeleton=true` 不会被诱导成"我之前判断过"

---

## 五、新需求（2026-05-20 第二轮讨论新增）

### 5.1 报告格式痛点

当前 docx 作为报告 + 批注载体存在脆弱性：
- 用户不小心改了其他地方，格式被破坏
- 合并分析时 `parse_annotation.py` 解析失败
- docx 是二进制格式，不利于 Git diff、不利于代码精确修改、不利于跨工具协同

**目标**：构造**更易编辑、更易管理、更便于代码修改、更标准化**的报告形式。

### 5.2 已拍板：报告格式改为 HTML 自包含单文件

**应用场景**：A 生成报告 → 发给 B → B 在浏览器中阅读并批注 → B 在交易日中回头反复查看自己的批注 → B 把含批注的 HTML 发回 A → A 解析批注用于次日合并分析。

**核心决策**：

- 报告载体：**单个自包含 HTML 文件**（CSS / JS / 数据全内联），B 零安装，任何浏览器双击打开
- 不复用 Sonetto（Electron 壳过重，B 协作场景不需要）
- 视觉规范从 docx **1:1 迁移**到 HTML，保持现有报告观感

**批注持久化双层机制**：

| 层 | 触发 | 用途 |
|---|---|---|
| localStorage 自动备份 | B 每次改批注立即写入 | 防止意外关闭丢失；同浏览器再开自动恢复 |
| "保存"按钮 → 下载新 HTML | B 显式点保存 | 把批注内嵌回 HTML 文件触发下载，发回 A 用 |

UX 仿 Excel：未保存有红色提示、`beforeunload` 拦截关闭、保存得新文件覆盖原名。

**HTML 内嵌数据结构**：

```html
<script type="application/json" id="snapshot">...</script>      <!-- Python 渲染时写入，不可改 -->
<script type="application/json" id="annotations">...</script>   <!-- JS 维护，保存时重嵌 -->
```

**A 侧解析**：BeautifulSoup 找 `<script id="annotations">`，`json.loads` 即可（30 行替代当前 200 行 python-docx）。

### 5.3 HTML 视觉规范（用户拍板）

**字体与排版**：

| 元素 | 字体 | 字号 | 字重 |
|---|---|---|---|
| 一级标题（今日日期） | 华文中宋 | 2em | bold |
| 二级标题 | 黑体 | 1.5em | — |
| 三级标题 | 楷体_GB2312 | 1.5em | bold |
| 正文 / 表格内容 | 仿宋_GB2312 | 1.5em | — |

**颜色规范（严格执行）**：

- 上涨 / 增加 / 正值 → `#FF0000`（红）
- 下跌 / 减少 / 负值 → `#00008B`（深蓝）

**批注交互**：

- 点击行 → 弹出 modal，输入颜色名（自由文本）+ 备注
- 第一次用某颜色名时弹色板让 B 自选 hex，存入 `annotations.colorPalette`
- 此后 LLM 不再翻译颜色（待最终确认）
- 整行底色用 B 选定的 hex 即时渲染

### 5.4 已拍板细节

| 项 | 决策 |
|---|---|
| 0 涨幅显色 | 黑色（中性） |
| 成交额环比 | 同样走红蓝（正红负蓝心智统一） |
| 色板限制 | 仅暴露浅色系（避免底色盖文字） |
| 色板选项数 | 给较多选项 |
| 颜色 hex 归属 | B 自选（所见即所得，LLM 不再做颜色翻译） |
| 字体 fallback 链 | 写多套备用（Windows 国标 → 通用中文族） |
| 可视化 | 初版仅表格 + sparkline，ECharts 暂不上 |
| Jinja2 模板 | 从 render_docx.py 1:1 迁移视觉规范 |

### 5.5 表格列设计（已拍板：B 也看因子，采用以下方案）

#### 5.5.1 四个分类表（共用 9 列）

| 列 | 显示内容 | 复合 |
|---|---|---|
| 代码 | `510300 ★` | `★` = 20 日新高；`▼` = 20 日新低；无标记 = 都不是 |
| 名称 | ETF 名称 | — |
| 涨幅 | `+4.50%` / `+3.20%` | 第一行今涨幅（红/蓝/黑），第二行小灰字昨涨幅 |
| 差值 | `+1.30%` | 今昨之差独立成列 |
| 量能 | `1.85x` / `P92` | 第一行 vol_ratio_20，第二行小灰字 vol_pctile_20 |
| 价位 | `P82` / `P95` | 第一行 price_pctile_60，第二行小灰字 price_pctile_20；右侧叠加 dist_ma20 视觉条 |
| 均线 | 🟢 / 🔴 / ⚪ | ma_alignment：绿=多头，红=空头，灰=震荡 |
| 标签 | 龙1 / 最增量 等 | badge 色块，多标签横排 |
| 分析 | LLM ~150 字 | 占剩余宽度 |

**异常标记**：`pct_normalized > 2` 时，整行左边框加橙色 + ⚠ icon。

#### 5.5.2 跨日追踪表（8 列）

| 列 | 内容 |
|---|---|
| 代码 + 标记 | 同上 |
| 名称 | — |
| T-2 / T-1 / T0 | 每列复合三行：【涨幅 / 量比 / 标签】 |
| 价位走势 | 20 日收盘价 sparkline，右端高亮当前位置 |
| 变化评级 | 大加强 / 加强 / 减弱 / 大减弱（color badge） |
| 评级理由 | LLM 写的简短理由 |

**只显示最近 3 个时段**，更远的时段进入下方的矩阵概览。

#### 5.5.3 新增章节：20 时段矩阵概览

放在跨日追踪表之后，热力图式宽表：

- 行 = 高关注品种（10-15 个，LLM 挑）
- 列 = 20 时段（按时间顺序）
- 单元格 = 极简标签（`龙1+` / `空龙1-` / `—`），用底色编码归类（红=持续强化，绿=反包修复，蓝=强反转，灰=连续杀跌）

这是窗口扩到 20 时段后的核心可视化，对应数据层"宽矩阵"的展示形态。

---

## 六、待 Gemini 一起思考的开放问题（原版，部分已被本轮拍板覆盖）

### Q1：窗口长度

20 个交易时段（≈ 2 周）是直觉值。

- 太短：AI 看不到形态全景（当前痛点）
- 太长：LLM 注意力稀释，token 成本上升

**问题**：有没有更科学的方式确定窗口长度？是否应该按"人格"来分（Wyckoff 看 20 天足够，Weinstein 阶段划分需要 60-120 天）？

### Q2：A 股版人格综合体的具体清单

当前候选：Wyckoff + Weinstein + Druckenmiller + Stovall/Pring。

**问题**：
- 这套组合契合 A 股 ETF 量价分析吗？
- 有没有更适合 A 股语境的人选（国内/海外的都行）？
- "方法论拆成强制清单"的具体形式应该是什么？是 YAML 配置？是提示词模板？还是嵌入 JSON schema？

### Q3：派生因子的最小可用集合

建议清单有 10+ 个因子，但 LLM 注意力有限。

**问题**：
- 哪 4-5 个是最高 ROI 的"必加"？
- 因子之间会不会信息重叠（例如 `vol_ratio_20` 和 `vol_pctile_20` 都在描述放量程度，留一个就够？）

### Q4：数据层与叙事层分离的具体结构

宽矩阵（20 天 × 42 ETF × 多个标签维度）+ 最近时段叙事 + 旧时段一句话特征。

**问题**：
- 矩阵在 prompt 里怎么呈现？纯文本表格、markdown 表格、还是 JSON？哪种 LLM 解析最稳？
- 旧时段的"一句话特征"由谁生成？是 LLM 在写当时段叙事时顺便生成，还是合并时压缩？
- 如何防止矩阵列数过多（20 天 × 多因子）导致表格读不动？

### Q5：增量合并的状态管理

`current.json` 滚动窗口设计听起来合理，但有边界情况：

- 如果用户中途修改了昨日批注，叙事切片要不要重生成？
- 如果 LLM 在某一时段的判断后来证明是错的，怎么"回头修正"该切片？
- 跨日追踪表的"变化评级"依赖前后对比，窗口滑动时评级要不要重算？

### Q6：与 `auto-prtsc` 的集成边界

`auto-prtsc` 是数据基础设施，etf_cc 是分析应用。

**问题**：
- 应该把 etf_cc 的取数逻辑写在 etf_cc 里调用 auto-prtsc 的 API？
- 还是在 auto-prtsc 里增加一个 ETF 专用导出器？
- 数据契约（schema）放在哪里维护？

---

## 五、附录：用户原始讨论关键对话（节选）

> 老大（用户）：我们现在最多给它们 3 天的行情，然后我们的这个模板、每天对比、表格表头这些，我觉得都需要重新更新...3 天的数据够不够？如果不够，多少天好？如果变成 20 天，我们的表格怎么设计？怎么能够满足它的计算力要求？（20 天很多，一次对话可能不够用）
>
> 老大：行情不够，明明是超跌反弹，它说主升开启
>
> 老大：要发挥它的人格优势...比如我们选巴菲特，但是给它 20 天日 K，有啥用
>
> CC：要选择最擅长这个事情的人格去做这个事情

---

## 六、附录：用户监控池（42 只 A 股 ETF + 3 个同花顺指数）

```
SZ159981 能源化工ETF      SH501018 南方原油LOF       SZ159732 消费电子ETF
SZ159995 芯片ETF          SZ159949 创业板50ETF       SZ159929 医药ETF
SZ159920 恒生ETF          SZ159883 医疗器械ETF       SZ159870 化工ETF
SZ159869 游戏ETF          SZ159845 中证1000ETF       SZ159841 证券ETF
SZ159825 农业ETF          SZ159766 旅游ETF           SZ159647 中药ETF
SH562500 机器人ETF        SH518880 黄金ETF           SH516950 基建ETF
SH516780 稀土ETF          SH516390 新能源汽车ETF     SH516160 新能源ETF
SH516110 汽车ETF          SH515880 通信ETF           SH515790 光伏ETF
SH515220 煤炭ETF          SH515210 钢铁ETF           SH513300 纳斯达克ETF
SH512800 银行ETF          SH512720 计算机ETF         SH512690 酒ETF
SH512680 军工ETF广发      SH512200 房地产ETF         SH512070 证券保险ETF易方达
SH511270 10年地方债ETF    SH511260 十年国债ETF       SH511090 30年国债ETF
SH510210 上证指数ETF      SH510150 消费ETF           SH510050 上证50ETF
883957 同花顺全A          883910 同花顺热股          883404 同花顺情绪指数
```

用户业务模式：**利用各板块相互强弱和集体表现判断市场所处状态和资金意图**。典型判断范例：
- "国债涨得很强势 → 进攻的科技可能有调整预期"
- "银行跌、黄金跌、石油跌 → 可能有大涨预期"
- "70% 的板块处于波动率收缩 → 大盘横盘概率大"

---

## 七、实施成果摘要（2026-05-21 完成阶段 1-5）

### 7.1 各阶段产出

| 阶段 | 模块文件 | 状态 |
|---|---|---|
| 1a/b/c | `auto-prtsc/a/etf_fetchers.py` + `etf_update.py` + `etf_build.py` + `etf_data_api.py` | ✅ 39 只 ETF 全量回填，3974 行 |
| 2 | `src/factors.py`、`src/panel.py` | ✅ 7 因子 + close_vs_ma 三球 |
| 3 | `src/schema.py`、`src/window.py`、`src/build_snapshot.py`、`src/sync_annotations.py`、`src/backfill.py` | ✅ |
| 4 | `src/llm_schema.py`、`src/llm_validate.py`、`src/llm_prompt.py`、`src/gen_prompt.py`、`src/fill_narrative.py` | ✅ |
| 5 | `src/render_html.py`、`src/templates/report.html.j2`、`src/color_palette.py` | ✅ HTML 102KB 单文件自包含 |

**测试**：113/113 全部通过（tests/ 11 个文件）。

### 7.2 2026-05-21 用户反馈与修复

| # | 反馈 | 修复 |
|---|---|---|
| 1 | 人格分析太机械 | schema 每个人格字段加 `free_analysis` ≤200 字必填 |
| 2 | 均线"一个球"信息不够 + 用户色盲 | 新增 `close_vs_ma5/_ma20/_ma60` 三球；颜色去绿（红=above 深蓝=below 灰=near ±0.5%）；全局 CSS 替换绿→红/粉 |
| 3 | sparkline 无效 | 改从 `etf_data_api.get_a_etf_ohlcv` 拉真实收盘价绘制 |
| 4 | 矩阵概览缺名称 | macro 加名称列 |
| 5 | LLM 占据"分析"列，B 没地方批注 | §3 表重排：旧"分析"列重命名为"批注"（B 专用，280px，cell 直接显示备注文字）；LLM 点评合并到"标签 / LLM 点评"列；schema 顶层加 `ticker_analyses: {code: text}`（30-120 字） |
| 6 | "最增量/最缩量"标签太多 | `classify._assign_features` 删除分类内逻辑；`enrich()` 主流程加全品种唯一一对（用户明确批准修改 classify.py 边界） |
| 7 | §1 缺百分比 | 新增"分类分布"小节，4 个分类显示 `数量 (占比% · 主导)` |

### 7.3 选品种规则演化

| 旧规则 | 新规则（2026-05-21） |
|---|---|
| 每个分类挑 **3-4 个** 写分析 | 每个分类挑 **1-2 个** 写点评 |
| 没选中的 analysis 留空字符串 | 没选中的 ticker_analyses 中**不出现** |

### 7.4 阶段 6 数据更新汇总（2026-05-21 完成）

四个新模块串起一键数据更新流程：

| 模块 | 职责 |
|---|---|
| `src/log_util.py` | `write_error`/`write_run_summary` 落盘 `data/logs/update_<ts>.log` + `errors/<ts>_<ticker>.json` |
| `src/data_refresh.py` | 调 auto-prtsc 池粒度 API（`run_a_etf_daily_update` / `run_us_single_update`）只补 90 只池子，不动 auto-prtsc 全库 |
| `src/report_gap.py` | 扫 `data/snapshots/<market>/` 对照交易日历列出缺的 label；`default_end` + a_until 三态决定每个时点期望补什么 |
| `src/update_all.py` | 一键入口：`refresh_data → detect_report_gaps → build_snapshot 逐 label → write_run_summary` |

行为矩阵（写在 `report_gap.py` docstring）：

| 市场 | 跑的时刻 | end_date | a_until | 补什么 |
|---|---|---|---|---|
| A | 开盘前/周末/节假日 | 上一交易日 | close | 历史 -收 |
| A | 11:35-15:05 | 今天 | noon | 历史 -收 + 今日 -午（腾讯实时快照） |
| A | 15:05 后 | 今天 | None | 历史 -收 + 今日 -午+-收 |
| US | 北京 ≥ 5:30 | 最近美股交易日 | — | 该日 1 个 label |
| US | 北京 < 5:30 | 再前一日 | — | 该日 1 个 label |

`build_snapshot.build()` 增 `failures_out` / `run_ts` 参数 + 单只 ticker try/except；A 股 `session_time="noon"` 路径走 `etf_data_api.get_a_etf_realtime` 拉腾讯快照，禁止历史日 + noon 组合。

### 7.5 阶段 A 渲染层（2026-05-21 完成）

**核心架构**：单时段分析 + 滚动渲染。LLM 每个时段只产 1 份 narrative 永远冻结；渲染层（`render_html._build_groups`）从 `history[-2:] + current` 拼每只 ETF 1-3 行。LLM 工作量从 3× 降到 1×。

具体改动：

- `panel.breadth_alert`: up/down ≥70% → `bullish_resonance` / `bearish_resonance`
- 模板 §0 顶部告警条（红=起爆，深蓝=杀跌）
- 模板 `category_table` 11 列含 rowspan：代码/名称/批注 跨整组；时段/涨幅/差值/量能/价位/均线/标签+点评/预期审计 逐行
- 行背景色 = `annotation.color`（B 批注色染该品种 3 行）
- §3 预期审计列：阶段 A 渲染占位（"—"），阶段 B 接通 audit 数据
- `_pick_tracking_codes` 新规则：上一时段非纯最增/缩 + 独特品种 + 兜底

### 7.6 阶段 B 人格扩职 + 预期审计（2026-05-21 完成）

#### 7.6.1 人格分工（A 股）

| 章节 | 人格 | 字段 |
|---|---|---|
| §6.1 全景图 ≥3 段 | 养家 | `yangjia_emotion_cycle.panorama_text` 150-400 字 |
| §6.3 交叉验证 | 养家 | `yangjia_emotion_cycle.cross_validation_text` 100-300 字 |
| §6.2 上涨向异动 ≥2 | 赵老哥 | `zhaolaoge_liquidity_focus.key_movers` list[{sector, phenomenon, motive, scenario}] |
| §6.2 下跌向异动 ≥2 | 冯柳 | `fengliu_contrarian_check.key_movers` |
| §6.4 策略前瞻 6 子项 | 养家 | 顶层 `strategy_outlook.{market_phase, trend_forecast, style_tone, attack_direction, retreat_direction, key_focus}` |
| §6.4 风险点专项 | 炒家 | 顶层 `strategy_outlook.risk_points` |
| §3.5 独特异象追踪 | 炒家 | 顶层 `unique_anomaly_analysis` 200-500 字 或 null |
| §7 周末宏观 | 养家+炒家 | 顶层 `macro_cycle_anchor`（仅 `is_weekend_close=true` 必填）|

新顶层 enum：

- `market_phase`: 情绪修复 / 趋势主升 / 高位分歧 / 阴跌抵抗 / 其他
- `trend_forecast`: 上涨 / 震荡 / 下跌
- `style_tone`: 偏向进攻 / 偏向防守 / 混沌期

#### 7.6.2 预期审计（任务 2.2）

per-ticker `audit: {actual_vs_expected, auditor}` 五档评级（强超/超/符合/低/强低于预期），双轨：

**量化代审（`src/audit.py`）**：

- D1 归类跃迁打分表（强反转→持续强化 +3、连续杀跌→反包修复 +2、持续强化→持续强化 +1、持续强化→强反转 -2、强反转→连续杀跌 -2 等）
- D2 量能配合：涨+放量 +1 / 涨+缩量 -1 / 跌+放量 -1 / 跌+缩量 +1
- 总分映射五档：≥+3 强超 / +1~+2 超 / 0 符合 / -1~-2 低 / ≤-3 强低
- `build_snapshot` 跑完调 `quant_audit_batch` 兜底每只 ticker
- 上一时段缺失 / code 在上一时段不存在 → audit=None（渲染 "—"）

**人格代审**：LLM 在 `narrative.ticker_audits: {code: {actual_vs_expected, auditor}}` 给少数 ticker 升级；`fill_narrative` 覆盖 quant 兜底。`auditor` 不允许填 `"quant"`（那是 Python 的活）。

panel 级整体审取消（养家 panorama_text 用自然语言承载整盘判断）。

#### 7.6.3 渲染映射

- 模板 `persona_card` 扩 panorama / cross_validation / key_movers / prev_session_audit 子段
- §3.5 独特异象：橘色 anomaly-card
- §6 策略前瞻：strategy-grid 7 子项（market_phase / trend_forecast 上色 + 风险点警告色）
- §7 宏观周期：仅 `is_weekend_close` 时显示，灰色 macro-card 含 4 子段

#### 7.6.4 prompt 增量

- `_audit_context_block`：把 history[-1] 的人格 `next_session_expect` 打包成审计锚点
- `_weekend_flag_block`：根据 `session.is_weekend_close` 明确告诉 LLM 是否必填 macro_cycle_anchor
- 任务 schema 段加新字段 schema 描述 + key_movers / strategy_outlook / unique_anomaly / macro_cycle_anchor 结构示意

### 7.7 旧 docx 流水线归档（2026-05-21 完成）

`src/` 下 11 个旧文件归档到 `src/_archived/`：`ingest.py` / `launcher.py` / `merge.py` / `parse_annotation.py` / `prepare_merge.py` / `prepare_single.py` / `render_docx.py` / `render_merge.py` / `render_merge_docx.py` / `run.py` / `trajectory.py`。

根级 `templates/` 合并到 `src/templates/_archived/`；`prompts/` 移到 `docs/_archived/prompts/`；`launch.bat` 移到 `src/_archived/`。`src/classify.py` 因被新架构复用保留在 `src/`。新代码 0 处 import 旧文件。

### 7.8 测试统计

113（阶段 1-5 末）→ 170（阶段 6+A+B 末）。新增 16 个 test 文件中的：

- `test_audit.py` 19 cases（D1/D2/五档映射/batch）
- `test_log_util.py` 3 cases
- `test_report_gap.py` 11 cases（行为矩阵）
- `test_build_snapshot_noon.py` 3 cases（noon 路径 + 周末标志）
- 各扩字段在 `test_llm_validate.py` / `test_llm_prompt.py` / `test_panel.py` / `test_render_html.py` 加增量覆盖

### 7.9 剩余工作（✅ 已全部完成 2026-05-22）

- ~~README §三"用户阅读版"补内容~~（2026-05-21 完成，commit `7226a16`）
- ~~阶段 7 端到端真实 LLM 联调~~（2026-05-22 完成，A 股 + 美股都跑过真实 narrative）
- ~~**阶段 8 前端 GUI 整合所有命令**~~（2026-05-22 完成，见 §7.10）
- ~~阶段 8 实测反馈修复轮~~（2026-05-22 完成，见 §7.11）

### 7.11 阶段 8 实测反馈修复批次（2026-05-22 完成）

**第一轮（数据源 / GUI 可观测性 / 性能）**：
- yfinance 100% 限流 → `data_refresh._refresh_us_batch` 直调 `_download_via_akshare + _merge_to_slices`，**永久绕开 yfinance**。auto-prtsc 默认不变
- GUI 日志看不到 auto-prtsc 内部源切换 → `src/gui/tasks.py` 加 `_ThreadLogHandler` 用 thread ident 过滤 root logger，把 auto-prtsc 的 INFO/WARN 实时推到 GUI
- update_all 17 个缺口各拉 1 次 200 日 OHLCV 太慢（368s）→ `_prefetch_ohlcv_cache` 一次性拉整池区间共享给所有 build，~30s
- update_all 顺序错：先 refresh 再 detect → 改为先 detect_report_gaps，无缺口跳过 refresh
- enum 白名单太严（"强超" / "强超预期" 被拒）→ `AUDIT_RATING_ALIASES` 同义词归一化，校验时归一化后比对、写回时也归一化
- prompt 没列举 evidence 关键词导致 LLM 反复猜词 → alias 表大幅扩充 + schema_text 显式列举可接受关键词 + task_block 加 evidence 写作 few-shot

**第二轮（HTML 体验）**：
- §3 表格批注：点击任意 cell 都弹 modal → 改成只点 `td.annotation-cell` 才弹
- §2 字段名英文（macro_regime / key_signal / evidence …）→ `FIELD_LABEL_CN` 字典渲染时查表替换
- 跨资产显示 `treasury_10y: —` 看不懂 → `CROSS_ASSET_LABEL_CN` + 方向中文（"上涨/下跌/持平"）
- 跨资产 CSS 字号 0.7em → 1em 与 §2 正文一致
- 美股 druckenmiller 加 `cross_asset_panorama`（≥150 字 无上限 跨资产全景段）
- prompt 加"写作可读性规则"：品种代码必带中文名 `PLTR(Palantir)`、叙述段优先用中文标签

**第三轮（数据完整性 / audit）**：
- §3 表格合并日期错乱（4月24/4月27/5月21）→ 根因：用户跑 backfill 把 4月28~5月20 弹出窗口。`render_html` 新增 `_load_neighbor_sessions` / `_load_recent_sessions` 直接从 `data/snapshots/` 读邻近日期，**渲染层独立于窗口**
- §4 跨日追踪表"变化评级"和"评级理由"列模板写死 `—`，根本没读 audit → 改读 `cur_t.audit` + audit_badge 渲染；`audit.quant_audit_ticker` 输出加 `audit_note`（D1+D2 中文简述，如"强反转→持续强化，D1+3，放量上涨(+3.00%/1.60x) D2+1"）
- §6 策略前瞻太短 → `strategy_outlook.deep_analysis`（≥400 字 无上限 综合论证），task_block 加 4 部分写作框架（市场资金全景图/关键异动板块/交叉验证/结论），`KEY_MOVERS_MIN` 2→3
- `build_snapshot._load_prev_snapshot` 找 prev 改读 snapshots/（同 #7 思路）
- 新增 `src/recompute_audit.py` CLI：对已有 snapshot 重算 audit 不动 narrative；不覆盖 LLM 升级的人格审

**第四轮（去字数上限）**：
- 用户拍板"全场 LLM 字段去上限，让 LLM 按内容密度发挥"
- `FREE_ANALYSIS_MAX / TICKER_ANALYSIS_MAX / AUDIT_NOTE_MAX / RATING_OVERRIDE_REASON_MAX` 全改 None
- `PANORAMA_LEN / CROSS_VALIDATION_LEN / CROSS_ASSET_PANORAMA_LEN / UNIQUE_ANOMALY_LEN` 上限改 None，仅保留下限确保不偷工
- prompt 文案所有"≤N 字" / "N-M 字" 改"≥N 字 无上限"
- 校验代码加 None 短路（未来若需重新限制只改常量）

**第五轮（指标中文化后处理）**：
- LLM 偶尔仍写 `above_ma150_count` / `spy_iwm_divergence` 英文 → 注册 Jinja filter `panel_to_cn` 在渲染时自动替换为中文
- `anchor_tickers` 渲染成 `["MP（...）", ...]` 乱码 → Jinja env `json.dumps_kwargs.ensure_ascii=False`
- list[str] 渲染从 JSON 改为 `humanize` filter 用顿号 join

**测试**：170 → 200 passed

（原接力棒文档 HANDOFF_FRONTEND.md 已完工删除，见 git 历史 commit `df814d8` 之前）

---

### 7.10 阶段 8 — 前端 GUI（✅ 2026-05-21 完成）

**完成清单**：
- ✅ Flask 单文件 app（`src/gui/app.py`，27 路由，端口 5010）
- ✅ Tailwind CDN + 抄 auto-prtsc 暖红色调 + 复用 STZHONGS.TTF/echarts
- ✅ 8 tab（数据更新/生成 Prompt/填回 Narrative/渲染/同步/批注收件/池配置/系统调参）
- ✅ 后端 callback 化（update_all/build_snapshot/data_refresh/backfill/sync_annotations 加 log_cb=print）
- ✅ 后台任务管理 `src/gui/tasks.py`（线程 + 增量日志轮询）
- ✅ 状态栏 + 日志/错误浮动面板（一键复制 JSON）
- ✅ 拖拽上传 HTML 自动覆盖 + 同步
- ✅ 池配置 role enum 下拉锁定（防 cross_asset_state 算错）
- ✅ 调参 tab 三级风险分区：
  - 绿区 `config/personas.yaml` → `llm_prompt._build_persona_section()` 实时读
  - 黄区 `config/thresholds.yaml` → `src/thresholds_cfg.py` 薄层，panel/factors 运行时读
  - 橙区 `src/templates/prompt/{task_block,weekend_flag}.j2` + `.default` 兜底 + 恢复默认
- ✅ 因子公式 / classify 边界 / prompt 组装逻辑保持禁区，不暴露
- ✅ 测试：tests/test_gui.py 21 个用例，总计 170→191 passed

（原接力棒文档 HANDOFF_FRONTEND.md 已完工删除，见 git 历史 commit `df814d8` 之前）

---

### 7.10（原） 阶段 8 — 前端 GUI（拍板记录）

**动机**：阶段 1-7 的所有用户操作都靠命令行（`update_all` / `gen_prompt` / `fill_narrative` / `render_html` / `sync_annotations`），用户日常工作流共 5 步命令切换，繁琐易出错。需要做一个**按钮化前端**整合所有命令 + 集中查看日志。

**设计参考**：复用 `D:\git\auto prtsc\` 的形态匹配引擎前端模式：

| auto-prtsc 资产 | 复用方式 |
|---|---|
| `app_base.py` Flask app + AppConfig 注入模式 | 整体抄过来，改成 etf_cc 的配置 |
| `templates/index.html`（1189 行 Tailwind 单页 + tab + fetch API） | 抄整个结构 → 改 tab 内容 |
| `static/fonts/STZHONGS.TTF` 等字体 | 直接复制 |
| `static/lib/` 第三方库 | 直接复制 |
| API 路由模式（`/api/run` 异步任务 + `/api/status` 轮询进度） | 抄路由设计 |

**核心需求清单**：

1. **5 个主操作 tab**（对应 5 类命令）：
   - **数据更新** tab：按钮触发 `update_all`（含 `--markets A/US/both` + `--lookback N` + `--skip-refresh` 选项），实时滚动显示输出
   - **生成 Prompt** tab：选 market + label 下拉 → 按钮触发 `gen_prompt` → 把 prompt 显示在 textarea 里方便复制到 Claude；旁边一键复制按钮
   - **填回 Narrative** tab：粘贴 LLM 返回的 JSON → 按钮触发 `fill_narrative`；校验失败时把错误列表分行展示
   - **渲染报告** tab：选 label → 按钮渲染 → 内嵌 iframe 预览 HTML（或新 tab 打开 `/reports/<file>`）
   - **同步批注** tab：上传 B 发回的 HTML（拖拽或选文件）→ 自动覆盖到 `data/reports/<m>/` → 触发 `sync_annotations`

2. **日志查看面板**（顶部或侧边常驻）：
   - 实时显示当前操作的 stdout/stderr 滚动输出
   - "查看日志" 按钮 → 列 `data/logs/update_*.log`，点击查看具体内容
   - "查看错误" 按钮 → 列 `data/logs/errors/*.json`，可一键复制内容（方便贴给 AI 修 bug）

3. **状态栏**（顶部）：
   - 当前窗口里 A 股 / 美股各有多少 session，最新 label 是什么
   - 报告缺口 X 个待补 → 一键提示"补吧"
   - 上次 `update_all` 时间 + 结果

4. **批注合并辅助**（独立 tab "批注收件"）：
   - 列出 `data/reports/` 里所有 HTML
   - 显示每个的 `mtime` 和 `last_synced` 时间戳
   - 标红"待同步"的（mtime > last_synced）

5. **池配置编辑**（"池子"tab）：
   - 直接前端编辑 `config/pool_a.yaml` / `pool_us.yaml`（表格形式：code/name/role 三列 + 增删按钮）
   - 保存后自动 yaml dump 回文件

**技术选型**：

- 后端 Flask（沿用 auto-prtsc 模式，单 `app.py`，约 300-500 行）
- 前端 Tailwind CDN + 原生 JS fetch（不引入 React/Vue，保持简单）
- 长任务（如 update_all）走后台线程 + 状态轮询 `/api/task/<id>/status`
- 端口约定 5010（避开 auto-prtsc 5000/5001/5002/5003）

**目录结构**：

```
src/
└── gui/                       # 新增前端目录
    ├── app.py                 # Flask app + 所有 /api 路由
    ├── templates/
    │   └── index.html         # 单页 Tailwind UI
    └── static/
        ├── fonts/             # 从 auto-prtsc 复制
        └── lib/               # 从 auto-prtsc 复制

启动命令：python -m src.gui.app
```

**不在范围**：

- 不做用户认证（单用户本地工具）
- 不做云部署
- 不嵌入 LLM API 调用（用户手动粘到 Claude 是故意为之——便于换不同模型 / 看 prompt 是否合理）
- 不重写已有 CLI 命令（前端只是 wrapper，CLI 仍能独立用）

**估时**：1-1.5 天（含 auto-prtsc 复用 + 联调）。

（原接力棒文档 HANDOFF_FRONTEND.md 已完工删除）
