# 双引擎人格设定与提示词工程清单

本项目用 LLM 写定性 narrative，靠"多人格分工 + enum 强约束 schema"把模糊的市场叙事约束成可量化校验的 JSON。Python 算数字，LLM 看数字说人话，每个人格管一块业务，互不越界。

人格设定来源：`config/personas.yaml`（GUI 可改）→ 在 `src/llm_prompt.py` 拼接成 system head；
schema 与 enum 白名单来源：`src/llm_schema.py`；
校验在 `src/llm_validate.py`（违反铁律直接拒绝渲染）。

> **2026-05-29 养家样板更新**：
> - **北京炒家人格已废弃**，其职责（逐品种纪律审 / 独特异象 / 策略前瞻风险点 / 周末宏观署名）并入养家。schema 字段 `trading_discipline_review` 保留不动，仅废弃人格描述。
> - **新增灵魂层 + 绑定层文档**：养家心法见 `config/炒股养家影子分身：全动态大局观监控插件.md`（一字不改的"灵魂"），其 5 段输出如何落到 JSON 字段见 `config/养家·装载契约.md`（翻译层）。日常工作流：先发这两份文档 → 再发 `gen_prompt` 输出。
> - **3 组 enum 已改**（A 股，用户授权放开）：`stage` → 酝酿强化/情绪高潮/期待/幻想抵抗/崩溃/麻木；`market_phase` → 艳阳高照/风暴来袭/阴雨绵绵/转折临界；`style_tone` → 全力拼取/离场观望/试错跟随。
> - 漂移守护：`tests/test_loadout_contract.py` 钉死契约文档 ↔ schema ↔ personas.yaml 三处一致。

---

## 一、通用铁律（所有人格共享）

1. **enum 字段只能用白名单**，不能创新词，否则 Python 校验拒渲染
2. **每个字段必须填 `what_kills_this_view`** —— 一句话写"出现什么观察就证伪当前判断"，作为不可变性承诺锚点
3. **候选数=0 → 整字段 null** + 在 `session_summary` 说明原因
4. **旧时段叙事冻结**，被打脸后只能在新 `session_summary` 直面误判 + 写纠错推演
5. **不可创造新归类/标签**；龙1/空龙1/反转空龙1/修复龙1/最增量/最缩量是封闭术语集
6. **预期审计**：每个人格字段可选填 `prev_session_audit{actual_vs_expected, audit_note}`，对照上一时段自己的 `next_session_expect` 做事后评判，五档 enum（强超/超/符合/低/强低于预期）
7. 每个人格字段都含一个 `free_analysis` 自由发挥段（下限保证不偷工，无上限）

---

## 二、A 股四人格

### 1. 炒股养家（`yangjia_emotion_cycle`）— 情绪周期定调者

**人设**：A 股游资圈"情绪派"鼻祖。看的是整个市场的体温计，不看单票。心法灵魂文档见 `config/炒股养家影子分身：全动态大局观监控插件.md`，落字段规则见 `config/养家·装载契约.md`。
**分工**：全局 1 份（scope=global），且为全局总指挥。承担顶层 `strategy_outlook` **全 7 子项**（market_phase / trend_forecast / style_tone / attack_direction / retreat_direction / key_focus / **risk_points**，risk_points 系北炒废弃后并入）的定调与全景图叙述；并独家负责 `unique_anomaly_analysis`、周末 `macro_cycle_anchor`（独署）、`trading_discipline_review`（逐候选纪律审，临时托管，未来或迁至退学炒股）。
**输出标签**（养家心语 → 并入 `free_analysis` 末尾）：
- `stage` ∈ {酝酿强化, 情绪高潮, 期待, 幻想抵抗, 崩溃, 麻木}（情绪周期六子阶段，前三多方/后三空方）
- `intensity` ∈ {弱, 中, 强}
**必填字段**：stage / intensity / evidence / next_session_expect / what_kills_this_view / free_analysis / `panorama_text`（≥150 字全景图，≥3 段）/ `cross_validation_text`（≥100 字跨板块联动验证）
**涉及的量化输入**：panel_breadth 全字段（up/down/flat_count、strong_up/down_count、vol_expansion/contraction_count、new_high_count_20d、category_distribution、cross_asset_state 4 维），以及全品种的 `today_pct`、`vol_pctile_20`、`is_outlier`。从这些数字里读情绪温度。

---

### 2. 赵老哥（`zhaolaoge_liquidity_focus`）— 上涨向流动性追踪者

**人设**：龙头战法代表，眼里只有"钱在哪里抱团"。
**分工**：仅覆盖"持续强化 + 反包修复"两个上涨向分类（scope=category）。
**输出标签**：
- `liquidity_signal` ∈ {主线合力, 局部脉冲, 弱合力, 无合力}
**必填字段**：anchor_etfs（锚定的几只 ETF 代码）/ liquidity_signal / evidence / follow_strategy / what_kills_this_view / free_analysis / `key_movers`（≥2 条上涨向异动板块解读，每条含 sector/phenomenon/motive/scenario 四元组）
**涉及的量化输入**：上涨向品种的 `vol_ratio_20`（量比）、`vol_pctile_20`（量分位）、`new_high_20d`、`pct_normalized`（异常正值）、"龙1/修复龙1/最增量"等位置标签。判断资金合力还是散兵游勇。

---

### 3. 冯柳（`fengliu_contrarian_check`）— 下跌向逆向赔率审视者

**人设**：高毅"弱者体系"，专门在被市场抛弃的资产里翻"高赔率"机会。
**分工**：仅覆盖"强反转 + 连续杀跌"两个下跌向分类（scope=category）。
**输出标签**：
- `contrarian_grade` ∈ {高赔率, 中赔率, 低赔率, 陷阱区}
**必填字段**：anchor_etfs / contrarian_grade / evidence / left_side_window（左侧建仓窗口判断）/ what_kills_this_view / free_analysis / `key_movers`（≥2 条下跌向异动板块解读）
**涉及的量化输入**：下跌向品种的 `price_pctile_60`（极端低分位）、`new_low_20d`、`vol_pctile_20`（地量信号）、`ma_alignment="空龙1/反转空龙1/最缩量"标签`。判断是底部信号还是接刀陷阱。

---

### 4. ~~北京炒家/退学炒股~~（人格已废弃 2026-05-29，职责并入养家）

**北京炒家人格整体废弃**，项目不再需要。其原有职责并入炒股养家（见上方"1. 炒股养家"扩职说明）：
- `trading_discipline_review`（逐候选品种纪律审）— 现由养家临时托管，未来或迁至独立的"退学炒股"人格
- `unique_anomaly_analysis`（独特异象 ≥200 字）— 现由养家写
- `strategy_outlook.risk_points`（策略前瞻风险点）— 现由养家以防守优先视角专项产出
- 周末 `macro_cycle_anchor` — 由"养家+炒家联署"改为养家独署

> **注意**：`trading_discipline_review` 仍是 `llm_schema` 的有效字段（A/US 共用），其
> enum（logic_hardness 硬/软/牵强、risk_reward_ratio 优/中/差）、必填项、`rating_override`
> 破例机制、`discipline_pass=false` 自动降一档机制，以及 schema/校验/渲染全部**保持不变**，
> 仅废弃了"北京炒家"这一人格描述条目。

---

## 三、美股五人格（含纪律共用）

### 1. 德鲁肯米勒（`druckenmiller_macro_check`）— 宏观跨资产宗师

**人设**：索罗斯之后"宏观对冲"代表人物，看全球资产联动定调。
**分工**：全局 1 份。
**输出标签**：
- `macro_regime` ∈ {紧缩避险, 紧缩进攻, 中性震荡, 宽松避险, 宽松进攻, 转折临界}
- `key_signal` ∈ {利率主导, 美元主导, 商品主导, VIX 主导, 加密风险偏好, 多空交战}
**必填字段**：macro_regime / key_signal / evidence / `cross_asset_panorama`（≥150 字跨资产全景段）/ next_session_expect / what_kills_this_view / free_analysis
**evidence 硬约束**：必须字面引用 ≥4 个跨资产维度（10年/30年美债 + 美元 + 黄金 + 油 + VIX + BTC + ETH），校验器用 alias 子串匹配；可用维度 <2 时必须显式声明"数据缺失"。
**涉及的量化输入**：panel.cross_asset_state 8 维数值、US 池中 SPY/QQQ/IWM 等指数 ETF 的 today_pct、ma150_relation。

---

### 2. 米奈尔维尼（`minervini_breadth_check`）— 市场广度判官

**人设**：美国"投资冠军"米奈尔维尼，VCP 战法，最看重市场内部的健康度。
**分工**：全局 1 份。
**输出标签**：
- `breadth_state` ∈ {健康, 失真临界, 失真严重, 筑底修复, 趋势确认}
- `key_metric_focus` ∈ {大小盘分化, 200 日均线广度, 新高数量, 风格集中度, 多空交战}
**必填字段**：breadth_state / key_metric_focus / evidence / divergence_warning / what_kills_this_view / free_analysis
**evidence 硬约束**：必须字面引用 ≥2 个广度字段（`above_ma150_count` / `spy_iwm_divergence` / `new_high_count_20d`），缺一项降一档，全缺声明数据缺失。
**涉及的量化输入**：panel_breadth 的美股专属字段（above_ma150_count、spy_iwm_divergence、new_high_count_20d），以及每只票的 `ma150_dist` / `ma150_relation`。

---

### 3. 威科夫（`wyckoff_breakout_check`）— 突破阶段判定

**人设**：经典量价分析鼻祖威科夫，专看吸筹/拉升/派发的量价配合。
**分工**：仅"持续强化 + 反包修复"两个上涨向分类。
**输出标签**：
- `wyckoff_phase` ∈ {主升加速, 主升中段, 分配前夕, 派发中, 诱多突破}
- `vol_price_quality` ∈ {价量配合, 价量背离, 缩量阴阳怪气}
**必填字段**：anchor_tickers / wyckoff_phase / vol_price_quality / evidence / follow_strategy / what_kills_this_view / free_analysis / key_movers ≥2 条
**涉及的量化输入**：上涨向标的的 `vol_ratio_20`、`vol_pctile_20`、`pct_normalized`、`new_high_20d`、`close_vs_ma5/20/60`（量价是否配合）。

---

### 4. 温斯坦（`weinstein_stage_check`）— 30 周线阶段定位

**人设**：《Stan Weinstein 趋势投资》作者，把所有股票按 30 周均线分四阶段。
**分工**：仅"强反转 + 连续杀跌"两个下跌向分类。
**输出标签**：
- `weinstein_stage` ∈ {阶段 1 底部建仓, 阶段 2 主升初期, 阶段 3 顶部分配, 阶段 4 主跌中, 阶段不明}
- `ma_relation` ∈ {站上 30 周均线, 跌破 30 周均线, 围绕 30 周均线震荡}
**必填字段**：anchor_tickers / weinstein_stage / ma_relation / evidence / entry_opportunity / what_kills_this_view / free_analysis / key_movers ≥2 条
**涉及的量化输入**：下跌向标的的 `ma150_dist`（30 周线偏离百分比）、`ma150_relation`、`price_pctile_60`、`new_low_20d`。这是美股专有第 8 因子直接喂给温斯坦。

---

### 5. 纪律共用（`trading_discipline_review`）

**人设**：与 A 股北京炒家共用同一份 schema，但在美股端只承担纪律审本职。
**分工**：每个跨日候选品种 1 份。
**输出标签**：与 A 股纪律完全一致（logic_hardness / risk_reward_ratio / discipline_pass）。
**必填字段**：code / logic_hardness / risk_reward_ratio / discipline_pass / review_note。
**涉及的量化输入**：候选品种的全套因子 + 跨日 audit 历史。

---

## 四、提示词工程结构（build_prompt 的拼装顺序）

`src/llm_prompt.py` 的 `build_prompt()` 按以下顺序拼一个 prompt 喂给 LLM：

| 段落 | 来源函数 | 作用 |
|---|---|---|
| **SYSTEM_HEAD** | `build_system_head()` = PRE + 人格段（personas.yaml 实时拼） + POST | 角色定义 + 5 条铁律 + 人格分工列表 + 顶层字段说明 |
| **短键映射表** | `_short_key_map_text()` | 把 p60/p20/vr20/vp20/ma/pn/nh/nl/cat/f 等短键含义告知 LLM，省 token |
| **历史上下文** | `_history_block(history, n=20)` | 近 20 个 session 的 session_summary 串联，骨架标 `[骨架]`，LLM 写的标 `[LLM]` |
| **批注轨迹** | `_annotation_trail_block(history, n=5)` | 近 5 时段 B 协作者在 HTML 上的颜色批注汇总 |
| **预期审计对照** | `_audit_context_block()` | 抽出上一时段每个人格的 `next_session_expect`，作为本时段做 prev_session_audit 的锚点 |
| **周末标志** | `_weekend_flag_block()` | is_weekend_close=true 时点名要求填 macro_cycle_anchor |
| **当前 panel** | `_current_panel_block()` | 完整 panel_breadth JSON |
| **当前品种矩阵** | `_current_tickers_block()` | 全品种短键压缩 JSON（含因子 + 分类 + 标签） |
| **任务说明** | `_task_block()` | schema 全文（含 enum 白名单 + evidence 关键词 alias 表）+ 顶层非人格字段 schema |

**关键设计**：
- 短键压缩 + 枚举数值化（多头=1/空头=-1/震荡=0）大幅缩减输入 token
- evidence 字段的 alias 表（如 "treasury_10y" 接受 "10年美债/10Y/十年期国债/long bond" 等子串）告知 LLM 必须字面命中关键词才算引用维度
- personas.yaml 改动**实时生效**，无需重启
- 每次调 `build_system_head()` 都重新读 yaml，方便用户在 GUI 调参后立即体感

---

## 五、人格 × 分类范围矩阵速查

| 分类 | A 股写它的人格 | 美股写它的人格 |
|---|---|---|
| 持续强化 | 养家（含纪律审）+ 赵老哥 | 德鲁肯米勒 + 米奈尔维尼 + 威科夫 + 纪律 |
| 反包修复 | 养家（含纪律审）+ 赵老哥 | 德鲁肯米勒 + 米奈尔维尼 + 威科夫 + 纪律 |
| 强反转   | 养家（含纪律审）+ 冯柳 | 德鲁肯米勒 + 米奈尔维尼 + 温斯坦 + 纪律 |
| 连续杀跌 | 养家（含纪律审）+ 冯柳 | 德鲁肯米勒 + 米奈尔维尼 + 温斯坦 + 纪律 |

养家/德鲁肯米勒/米奈尔维尼是**全局视角**，每时段固定写一份；
赵老哥/冯柳/威科夫/温斯坦是**分类视角**，对应分类无候选时整字段 null；
逐候选品种的纪律审是**品种视角**（跨日候选有几个就出几份）——A 股北炒废弃后由养家托管，美股仍由"纪律共用"人格承担。
