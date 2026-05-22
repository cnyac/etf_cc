# etf_cc — A 股 + 美股量价分析自动化

> **状态**：2026-05-22 阶段 1-8 全部上线 + 多轮实测反馈修复完成。
>
> Git: https://github.com/cnyac/etf_cc · main · 200/200 测试通过

> 🆕 **新会话冷启动**：按 §一"AI 阅读版"的顺序读 4 个文档（README → CLAUDE → DESIGN → REFACTOR_BRIEF），然后 `git log --oneline -5` 看最近做了什么 + `python -m pytest tests/` 验证环境。5 分钟上手。

本项目把"板块/权重股的相互强弱判断"工作流自动化：从数据获取 → 派生因子计算 → 双引擎 AI 分析 → HTML 报告 → 协作者批注 → 滚动窗口记忆。

A 股看 42 只 ETF 池，美股看 45 只权重股/ETF 池。每日产出独立 HTML 报告，发给协作者批注后发回，AI 在下次合并时自动继承批注。

---

# 一、AI 阅读版

> 你（未来某个 AI agent）第一次进入这个项目时，按下面的顺序看，5 分钟内能上手。

## 读这些文档（按顺序）

1. **本文件（README.md）** — 你正在读
2. **`CLAUDE.md`** — AI agent 工作速查手册，含禁区、术语、字段约定
3. **`DESIGN.md`** — 设计动机，回答"为什么这样做"
4. **`REFACTOR_BRIEF.md`** — 完整需求决策记录，11 个章节，所有"拍过什么板"在这里
5. 旁参：`F:\obsidian\Vault\Projects\ETF量价分析自动化.md`（项目笔记）和 `形态复盘引擎-数据基础设施.md`（auto-prtsc 数据层）

## 项目核心约束（不可违反）

1. **Python 算确定性，LLM 说人话**：归类/因子/计数永远是 Python 的活；定性分析永远是 LLM 的活。两条线不能模糊。
2. **双引擎人格 schema** 用 enum 强约束：白名单外的值会被 Python 校验拒绝渲染。
3. **不可变性原则**：旧叙事冻结，不可回头改；遇到打脸必须在新 session_summary 里直面误判 + 写纠错推演。
4. **HTML 报告分两份**：A 股一份，美股一份，互不影响。
5. **数据来源是 `auto-prtsc`**（位于 `D:\git\auto prtsc`），通过 Python module import 集成，不开本地 REST。
6. **批注闭环靠 HTML 内嵌 JSON**：B 在浏览器点击批注，写入 `<script id="annotations">`，A 侧用 BeautifulSoup 解析。

## 当前代码状态（2026-05-22）

| 阶段 | 模块 | 状态 |
|---|---|---|
| 1a/1b/1c | auto-prtsc 侧 ETF 管道 + `etf_data_api.py` 统一入口 | ✅ |
| 2 | `src/factors.py` / `src/panel.py`（含 breadth_alert） | ✅ |
| 3 | `src/window.py` / `src/build_snapshot.py` / `src/sync_annotations.py` / `src/backfill.py` | ✅ |
| 4 | `src/llm_schema.py` / `src/llm_validate.py` / `src/llm_prompt.py` + 模板 `src/templates/prompt/*.j2[.default]` | ✅ |
| 5 | `src/render_html.py` / `src/templates/report.html.j2` / `src/color_palette.py` + 批注 JS | ✅ |
| 6 | 数据更新汇总：`update_all` / `data_refresh` / `report_gap` / `log_util` | ✅ |
| A | 极值预警 + §3 三行滚动渲染 | ✅ |
| B | 人格扩职 + 预期审计（`audit.py` + schema 扩字段 + §3.5/§6/§7） | ✅ |
| 7 | 端到端联调（A 股 + 美股都跑过真实 LLM narrative） | ✅ |
| 8 | Flask GUI 控制台（`src/gui/` 8 tab 含三级风险调参）+ 多轮实测修复 | ✅ |

**测试覆盖**：200/200 passed（tests/ 17 个文件）

**新增字段** (2026-05-22)：
- `druckenmiller_macro_check.cross_asset_panorama` (≥150 字 无上限 跨资产全景)
- `strategy_outlook.deep_analysis` (≥400 字 无上限 综合论证)
- `audit.audit_note` (D1+D2 中文简述，渲染到 §3/§4 表格"评级理由"列)

**LLM 字段长度策略**：全场放开上限，仅保留下限。详见 CLAUDE.md "LLM 字段长度策略"。

**旧 docx 流水线**已全量归档到 `src/_archived/`；`src/classify.py` 被新架构复用保留在 `src/`。模块布局见 §"开发者阅读版" 下的目录树。

## 任何时候不确定，停下来检索

| 我要确认什么 | 去哪里 |
|---|---|
| 因子数学定义 | `REFACTOR_BRIEF.md` 4.4a 节 |
| 双引擎字段 schema | `REFACTOR_BRIEF.md` 4.3 / 4.9.6 节 |
| 数据源优先级 | `REFACTOR_BRIEF.md` 4.6 节 |
| 池配置 yaml 格式 | `REFACTOR_BRIEF.md` 4.9.3 节 |
| HTML 视觉规范 | `REFACTOR_BRIEF.md` 5.3 节 |
| 滚动窗口状态机 | `REFACTOR_BRIEF.md` 4.8 节 |
| 设计动机 | `DESIGN.md` |
| 用户偏好 | `CLAUDE.md` 末尾 |

## 沟通约定

- 用户用中文沟通，技术细节也用中文
- 用户喜欢先讨论清楚再写代码——**不要默认开工**
- 写代码前先告诉用户你打算做什么，让他拍板
- 用户拍板用简短的"接受"/"OK"/具体编号回应

---

# 二、开发者阅读版

> 你想要在这个项目里写代码（包括未来扩展功能），看这部分。

## 仓库布局（按模块分类）

```
etf_cc/
├── README.md / CLAUDE.md / DESIGN.md / REFACTOR_BRIEF.md   # 四份核心文档
├── requirements.txt
│
├── config/
│   ├── pool_a.yaml         # A 股池清单（用户可编辑 / GUI 池配置 tab）
│   ├── pool_us.yaml        # 美股池清单（45 只 = 用户给 44 + IEF）
│   ├── personas.yaml       # 双引擎人格设定（GUI 系统调参 绿区）
│   └── thresholds.yaml     # 量化阈值（GUI 系统调参 黄区，缺则用 _MAX 默认）
│
├── src/                    # 按下方 7 层划分
│   │
│   │   ── A. 数据流水线 ─────────────────────────
│   ├── update_all.py       # 一键入口：先 detect_report_gaps → 无缺口跳过 refresh
│   ├── data_refresh.py     # 美股直调 auto-prtsc _download_via_akshare（弃 yfinance）
│   ├── report_gap.py       # 报告层缺口检测 + 行为矩阵（A/US × 时刻）
│   ├── build_snapshot.py   # 单时段生产 + OHLCV cache 预拉 + prev 从 snapshots/ 找
│   ├── backfill.py         # 历史回填 + 骨架 narrative (is_skeleton=true)
│   ├── recompute_audit.py  # 对已有 snapshot 重算 audit 不动 narrative
│   │
│   │   ── B. 计算核心 ───────────────────────────
│   ├── factors.py          # 7 因子 + close_vs_ma 三球（阈值读 thresholds_cfg）
│   ├── classify.py         # 四象限归类 + 位置标签（分类内）+ 全局最增/最缩量
│   ├── panel.py            # panel_breadth 聚合 + breadth_alert（阈值读 thresholds_cfg）
│   ├── audit.py            # per-ticker 量化代审（D1 + D2 + audit_note 中文简述）
│   ├── thresholds_cfg.py   # 量化阈值运行时读取（薄层，避反向依赖 gui）
│   │
│   │   ── C. 状态管理 ───────────────────────────
│   ├── schema.py           # session/window 数据契约
│   ├── window.py           # 滚动窗口（load/save/append+弹出/remove/archive）
│   ├── sync_annotations.py # 从 HTML 解析 <script id="annotations"> 回写窗口
│   │
│   │   ── D. LLM 协作 ───────────────────────────
│   ├── llm_schema.py       # 双引擎 schema + enum 白名单 + audit_rating 同义词归一化
│   ├── llm_prompt.py       # prompt 构造（personas.yaml 实时读 + Jinja 段模板）
│   ├── llm_validate.py     # 校验 + 校验降级 + audit_rating 归一化写回
│   ├── gen_prompt.py       # CLI：生成 prompt → stdout
│   ├── fill_narrative.py   # CLI：校验 LLM JSON + 回填 session
│   │
│   │   ── E. 渲染层 ─────────────────────────────
│   ├── render_html.py      # Jinja2 渲染 + 字段中文翻译 + panel_to_cn 后处理
│   ├── color_palette.py    # 色板闭环（12 浅色默认 + merge）
│   ├── templates/
│   │   ├── report.html.j2  # 单文件自包含主模板（CSS/JS 全内联）
│   │   ├── prompt/         # LLM 提示段 Jinja 模板（GUI 系统调参 橙区可改）
│   │   │   ├── task_block.j2[.default]
│   │   │   └── weekend_flag.j2[.default]
│   │   └── _archived/      # 旧版 html.j2 模板
│   │
│   │   ── F. 工具 ───────────────────────────────
│   ├── log_util.py         # 数据更新汇总 + 错误明细 JSON
│   │
│   │   ── G. GUI ────────────────────────────────
│   ├── gui/
│   │   ├── app.py          # Flask 单 app + 27 路由（端口 5010）
│   │   ├── tasks.py        # 后台任务管理 + logging hook 捕获 auto-prtsc 日志
│   │   ├── config_io.py    # personas / thresholds / prompt_template 读写
│   │   ├── config_schema.py # role enum 白名单 + 可调阈值清单
│   │   ├── templates/index.html # 单页 8 tab Tailwind UI
│   │   └── static/{fonts,lib}/  # 抄 auto-prtsc 字体 + echarts
│   │
│   └── _archived/          # 旧 docx 流水线（13 个文件，仅作历史参考，不被 import）
│
├── data/
│   ├── window/             # pool_a.json / pool_us.json 滚动窗口
│   ├── snapshots/          # a/<label>.json / us/<label>.json 永久归档
│   ├── reports/            # a/<label>.html / us/<label>.html
│   └── logs/
│       ├── update_<ts>.log         # 数据更新汇总
│       └── errors/<ts>_<ticker>.json # 失败明细（AI 可复查）
│
├── docs/
│   └── _archived/
│       └── prompts/        # 旧 docx 时代提示词（参考用）
│
└── tests/                  # 17 个 test_ 文件，200 个 case
```

### 模块依赖关系（高→低）

```
update_all → data_refresh / report_gap / build_snapshot
build_snapshot → ingest(等价 etf_data_api) → factors → classify → panel → audit → window
gen_prompt → llm_prompt → llm_schema
fill_narrative → llm_validate → window
render_html → window → templates/report.html.j2
sync_annotations → window
```

工具层（log_util / color_palette / schema）被多处复用。

## 外部依赖

- **auto-prtsc**（`D:\git\auto prtsc`）：数据基础设施。本项目通过 `from auto_prtsc.etf_data_api import ...` 调用，**不要重新造轮子**。
- **Tushare token**：复用 auto-prtsc 的 `config.py` 中 `TUSHARE_TOKEN`，不另开
- **腾讯财经**：无需认证
- **akshare**：A 股兜底 + **美股唯一源**（2026-05-22 切换，见下）
- **yfinance**（auto-prtsc 已集成）：原美股主源，**etf_cc 已弃用**
- **xfinlink**（auto-prtsc 已集成）：美股备源，付费

## 数据源优先级

| 用途 | 主 | 备 | 兜底 |
|---|---|---|---|
| A 股 ETF 历史日线 | Tushare Pro | 腾讯财经 | akshare |
| A 股 ETF 实时快照 | 腾讯财经 | Tushare（盘后） | akshare |
| **美股历史日线** | **akshare (Sina)** | — | — |
| 美股实时快照 | （日内不需要：仅次日 5:30 后跑收盘） | — | — |

失败转移：主 → 备 → 兜底逐级 fallback。全部失败则 abort 当前时段 + 错误日志归档。

**美股源切换（2026-05-22）**：`src/data_refresh.py` 直接调 auto-prtsc 的
`_download_via_akshare + _merge_to_slices`，绕过 `us_daily_update` 的源分发链。
原因：用户网络下 yfinance 100% 被 `YFRateLimitError: Too Many Requests` 限流，
每只都走 yfinance 失败 → akshare 兜底，等于双倍 round-trip 浪费时间。
切换后单次批量 ~30-40s。auto-prtsc 默认仍是 yfinance，不影响其他项目。

## 开发约定

1. **任何确定性计算必须在 Python**，不要让 LLM 算（包括"算个平均"）
2. **任何定性文字必须由 LLM**，不要 Python 模板拼接（骨架 narrative 是唯一例外，且必须标记 `is_skeleton=true`）
3. **新加字段先更 `REFACTOR_BRIEF.md` 的 schema 章节**，再写代码
4. **修改 `classify.py` 边界规则需用户明确批准**——这条规则跨期一致性的基石
5. **HTML 模板视觉规范固化在常量里**（颜色 / 字体 / 列结构），不要让 LLM 影响
6. **测试覆盖至少包含**：
   - `factors.py` 各因子在数据不足时返 null
   - `classify.py` 涨跌=0 边界路径依赖
   - `panel.py` cross_asset_state 阈值（±0.3%）
   - 滚动窗口 append / 弹出 / sync 三类操作
   - LLM 输出 enum 校验拒绝渲染

## 命令速查

```bash
# === 推荐入口：GUI 控制台（端口 5010）===
python -m src.gui.app                       # 浏览器开 http://127.0.0.1:5010

# === CLI ===
# 一键数据更新（先 detect_report_gaps，无缺口则跳过 refresh + build）
python -m src.update_all                    # A + US 全跑，lookback 7 天
python -m src.update_all --markets A        # 只 A 股
python -m src.update_all --lookback 22      # 回看 22 天
python -m src.update_all --skip-refresh     # 跳过底层补齐

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

# 对已有 snapshot 重算 audit（audit.py 升级后用，不动 narrative）
python -m src.recompute_audit --market US --label 2026-05-21    # 单个
python -m src.recompute_audit --market US --all                 # 全部

# 跑所有测试（当前 200 passed）
python -m pytest tests/
```

## 实施工作流

| 阶段 | 工作 | 状态 |
|---|---|---|
| 1a-1c | auto-prtsc 侧 ETF 管道 + etf_data_api 统一入口 | ✅ |
| 2 | factors.py / panel.py | ✅ |
| 3 | 滚动窗口状态机（双市场） | ✅ |
| 4 | LLM prompt 双引擎 + schema 校验 | ✅ |
| 5 | HTML 渲染（双独立报告） | ✅ |
| 6 | 数据更新汇总 + 错误日志结构化 | ✅ |
| A | 极值预警 + §3 三行滚动渲染 | ✅ |
| B | 人格扩职（养家/赵老哥/冯柳/炒家扩 4 项任务）+ 预期审计 + 周末宏观 | ✅ |
| 7 | 端到端联调（需真实 LLM 跑一次） | ⏸ |

---

# 三、用户阅读版

> 你（用户）日常用这个项目的实际操作步骤。从首次冷启动到每天交易日的循环，再到故障处理。

## 0. 推荐：用 GUI 控制台

3.5 天工时上线的 Flask 前端把所有 CLI 命令做成了按钮：

```bash
python -m src.gui.app          # 默认端口 5010
# → 浏览器开 http://127.0.0.1:5010
```

8 个 tab 对应日常工作流的全部操作：

| Tab | 替代命令 |
|---|---|
| ① 数据更新 | `update_all`（实时滚动日志 + ERROR/WARN 染色） |
| ② 生成 Prompt | `gen_prompt`（label 下拉 + 一键复制） |
| ③ 填回 Narrative | `fill_narrative`（粘贴 JSON + 错误清单展示） |
| ④ 渲染报告 | `render_html`（iframe 缩略 + 新窗口完整打开） |
| ⑤ 同步批注 | `sync_annotations`（拖拽 HTML → 自动覆盖 + 同步） |
| ⑥ 批注收件 | 列 `data/reports/` 所有 HTML 与 `last_synced.json` 对比标红 |
| ⑦ 池配置 | 表格编辑 `pool_*.yaml`，role 下拉锁定 enum |
| ⑧ 系统调参 | 三级风险分区（绿区人格 / 黄区阈值 / 橙区 LLM 模板） |

顶部状态栏常驻显示：A/US 窗口 session 数 + 最新 label + 报告缺口数 + 上次更新时间。
右上角"日志"按钮浮出面板列 `update_*.log` 与 `errors/*.json`，**一键复制 JSON** 方便贴给 AI 修 bug。

调参 tab 的红线（CLAUDE.md 禁区）：
- **绿区**：人格设定（`config/personas.yaml`），改 LLM 风格倾向，不影响计算
- **黄区**：量化阈值（`config/thresholds.yaml`），改 panel.strong/vol/cross_asset 等，**会破坏跨日可比性**
- **橙区**：LLM 模板（`src/templates/prompt/*.j2`），改任务/周末段说明文字，有"恢复默认"兜底
- 因子公式 / classify 边界 / prompt 组装逻辑 **不暴露**到 GUI，要改请改代码 + 跑测试

CLI 命令仍可独立用，不会因 GUI 出现而废弃。

---

## 0. 一次性首次设置

### 0.1 环境前置

确认两件事：

```bash
# 1. auto-prtsc 数据基础设施在位
ls "D:/git/auto prtsc/etf_data_api.py"      # 应存在

# 2. Python 依赖
pip install -r requirements.txt
```

### 0.2 池配置（按需编辑）

```
config/
├── pool_a.yaml      # A 股池子：42 ETF + 跨资产代表
└── pool_us.yaml     # 美股池子：45 个股/ETF
```

每条 entry 格式：

```yaml
etfs:
  - code: SH510050
    name: 上证50ETF
    role: ""            # 可选；treasury_10y / gold / oil / dollar / vix / btc / eth 等
                        # 含 role 的进入 panel.cross_asset_state
```

加品种 / 删品种 / 改名 → 直接改 yaml；下一次 `update_all` 自动生效。**不要改 role 字段的取值集合**（panel 计算依赖固定 key）。

### 0.3 首次跑历史回填

让窗口里先有 ~10 天历史数据（A 股），AI 才有上下文判断"今天 vs 过去"：

```bash
# A 股回填最近 10 个交易日（只补 -收，-午 无法回填）
python -m src.backfill --market A --start 2026-05-08 --end 2026-05-20

# 美股同步
python -m src.backfill --market US --start 2026-05-08 --end 2026-05-20
```

backfill 出的 narrative 是 **骨架**（`is_skeleton=true`，Python 模板拼的一句话汇总），不是 LLM 写的。后续每个新时段的 narrative 由 LLM 写满。

---

## 1. 日常工作流（每个交易日）

A 股一天 2 个时段，美股 1 个时段（次日早晨）。完整循环是 **数据 → AI 写 → 出报告 → 协作者批注 → 同步回**。

### 1.1 全天节奏一览

| 时刻 | 操作 | 命令 |
|---|---|---|
| **早 9:00** | 看夜里跑出的美股报告 | 浏览器开 `data/reports/us/2026-05-20.html` |
| **中午 11:35-15:05** | 跑 A 股午时段（实时盘中快照） | `python -m src.update_all --markets A` |
| **下午 15:05 后** | 跑 A 股收时段 | `python -m src.update_all --markets A` |
| **次日早 5:30 后** | 跑美股（昨晚收盘） | `python -m src.update_all --markets US` |

`update_all` 内部做 4 件事：①调 auto-prtsc 补底层切片 ②扫缺哪些 label ③逐 label 跑 build_snapshot ④落汇总日志。它**只做到 snapshot 落地**，narrative 还是 None。后面要手动跑 LLM。

### 1.2 跑一个时段完整步骤（以 A 股 2026-05-20-收 为例）

**Step 1：数据 + Snapshot**

```bash
python -m src.update_all --markets A
```

跑完看输出：

```
=== 数据更新汇总 2026-05-20 15:08:00 ===
池子数据补齐:
  A  OK  A 股池: ok=2 skip=37 fail=0 /39
A / 2026-05-20-收  成功 39/39
总耗时 8.3s
日志: data/logs/update_20260520-150800.log
```

39/39 表示全池成功；如有失败看 `data/logs/errors/` 里的 json。

**Step 2：生成 prompt**

```bash
python -m src.gen_prompt --market A --label 2026-05-20-收 > prompt.txt
```

`prompt.txt` 是给 LLM 的完整提示词（含历史上下文、当前盘面、schema 约束、人格分工说明）。一般 5-15 KB。

**Step 3：把 prompt 喂给 LLM**

打开 Claude Desktop / Claude.ai / ChatGPT / 你常用的，把 `prompt.txt` 全文粘进去。LLM 会按 schema 返回一个 JSON。

完整 JSON 大致是这样：

```json
{
  "is_skeleton": false,
  "session_summary": "今日 A 股呈现典型分化：上涨 15/39（占比 38.5%）……",
  "yangjia_emotion_cycle": {
    "stage": "试错", "intensity": "中",
    "evidence": "上涨 15/39，强势仅 1 个，缩量主导",
    "next_session_expect": "明日早盘若仍无放量主线 → 情绪继续退潮",
    "what_kills_this_view": "明日早盘 ≥5 只强势 ETF 涨幅 >2%",
    "free_analysis": "……",
    "panorama_text": "一、上涨与下跌占比……\n二、跨资产侧……\n三、量能扩张……",
    "cross_validation_text": "权重板块普跌……",
    "prev_session_audit": {
      "actual_vs_expected": "符合预期",
      "audit_note": "情绪如预期退潮，与昨日 expect 一致"
    }
  },
  "zhaolaoge_liquidity_focus": {
    "...": "...",
    "key_movers": [
      {"sector": "通信", "phenomenon": "放量上涨 2.3%",
       "motive": "机构进攻 5G", "scenario": "若量能持续 → 主线确立"},
      {"sector": "酒", "phenomenon": "缩量反包",
       "motive": "超跌反弹 防御资金", "scenario": "持续性弱"}
    ]
  },
  "fengliu_contrarian_check": {
    "...": "...",
    "key_movers": [{"sector": "...", ...}, {"sector": "...", ...}]
  },
  "trading_discipline_review": [
    {"code": "SH510050", "logic_hardness": "硬", "risk_reward_ratio": "优",
     "discipline_pass": true, "review_note": "..."},
    "..."
  ],
  "strategy_outlook": {
    "market_phase": "高位分歧",
    "trend_forecast": "震荡",
    "style_tone": "偏向防守",
    "attack_direction": "弱合力，无明确主攻",
    "retreat_direction": "高位题材资金撤出",
    "key_focus": ["明日券商是否补涨", "10Y 国债收益率"],
    "risk_points": ["机构调仓引发踩踏", "外资突然撤离"]
  },
  "unique_anomaly_analysis": "今日跨资产侧……（200-500 字）",
  "macro_cycle_anchor": null,
  "ticker_analyses": {
    "SH510050": "上证50放量上涨 0.9%……",
    "SH518880": "黄金 ETF 缩量大跌 -1.5%……"
  },
  "ticker_audits": {
    "SH510050": {"actual_vs_expected": "超于预期", "auditor": "zhaolaoge"}
  }
}
```

把这个 JSON 保存为 `narrative.json`（任意路径）。

**Step 4：校验 + 回填**

```bash
python -m src.fill_narrative --market A --label 2026-05-20-收 --json narrative.json
```

校验通过 → 打印 `OK narrative 已回填到 A/2026-05-20-收`。

校验失败 → 列出具体错误（哪个字段 enum 不对 / 缺什么 / 长度超限）。**修 JSON 重跑**，直到通过。

**Step 5：渲染 HTML**

```bash
python -m src.render_html --market A --label 2026-05-20-收
```

输出文件路径：`data/reports/a/2026-05-20-收.html`，浏览器打开就是最终报告。

### 1.3 把报告发给 B + 收回批注

**发出去**：直接发 `data/reports/a/2026-05-20-收.html` 给 B（微信 / 邮件 / 网盘均可，单文件自包含）。

**B 在浏览器做的事**（B 不需要装任何东西）：

1. 浏览器双击打开 HTML
2. **点击任意品种行** → 弹出 modal
3. 在 modal 里：
   - **选浅色**（红/橙/黄系列预设；或自己填 hex，会被自动校验"足够浅"）
   - **写备注**（自由文本）
4. 点"确定"，颜色立刻染到行背景（3 行整组）
5. 右下角"保存"按钮：
   - **首次点保存** → 浏览器弹原生文件对话框，让 B 选保存位置（**必须覆盖原 HTML 文件本身**）
   - **之后再点** → File System Access API 直接覆写源文件，无对话框
6. 不喜欢某个批注 → 再点同品种 → "清除批注"按钮

B 改完直接把同一个 HTML 文件发回（不是另存为）。

**收回来**：

1. 把 B 发回的 HTML 文件**直接覆盖** `data/reports/a/2026-05-20-收.html`
2. 跑同步：

```bash
python -m src.sync_annotations --market A
```

它扫整个 `data/reports/a/` 找比 `data/window/last_synced.json` 里时间戳更新的 HTML，解析 `<script id="annotations">` 块，把批注写回：

- 该 label 还在窗口 → 写 `data/window/pool_a.json` 对应 session.tickers[i].annotation
- 该 label 已被弹出窗口 → 写 `data/snapshots/a/<label>.json` 兜底（永久留档）

**下一次跑 prompt 时**，prompt 里的"批注轨迹"段会自动带上 B 标过的颜色 + 备注，LLM 据此分析这只品种的连续关注度。

---

## 2. 周末特殊流程

**周五 A 股收盘报告** + **周一早晨美股报告（对应周五收盘）** 会触发 `is_weekend_close=true`。

`build_snapshot` 自动检测周五；prompt 自动加：

> 周末标志: is_weekend_close=true → macro_cycle_anchor 字段本时段必填（4 子段：asset_profile / historical_anchor / then_vs_now / forward_strategy）

LLM 会额外产 `macro_cycle_anchor` 字段：

```json
"macro_cycle_anchor": {
  "asset_profile": "当前资金极致追逐抗通胀与避险实物资产……（一句话）",
  "historical_anchor": {
    "year": "1979-1980",
    "event": "第二次石油危机 + 美联储沃尔克鹰派加息",
    "phase": "典型滞胀末期",
    "brief": "彼时通胀高企、能源/黄金狂涨、权益压制……"
  },
  "then_vs_now": {
    "similarity": "黄金 + 原油同涨 + 利率上行压制估值……",
    "divergence": "当前有 AI 算力革命作新动能 + 央行干预工具进化……"
  },
  "forward_strategy": {
    "risks": "若美联储重启加息 → 高估值科技踩踏风险陡升",
    "opportunities": "周期末期资源股 + AI 算力链可能迎主升"
  }
}
```

HTML 报告会在底部多出 §7 灰色"宏观周期定位"卡片。

平日（周一-周四）`macro_cycle_anchor: null`，§7 不显示。

---

## 3. 故障排查

### 3.1 数据没拉到

**症状**：`update_all` 输出 `失败 X/Y` 或 `0/0`。

**查**：

```bash
# 看最新汇总
cat data/logs/update_$(ls -t data/logs/ | head -1)

# 看具体某只 ticker 的错误
cat data/logs/errors/<时间戳>_<code>.json
```

里面有 `error_type` + `message` + `traceback`。把这个 JSON 路径丢给 AI："看下这个错误"，它能直接判断是池子配置问题、数据源故障、还是切片本身缺数据。

### 3.2 narrative 校验失败

**症状**：`fill_narrative` 打印 `校验失败 (N 个错误)`。

**最常见 5 个错误**：

| 错误信息 | 原因 | 修法 |
|---|---|---|
| `xxx.stage='牛顶' 不在白名单 [...]` | LLM 创了新词 | 让 LLM 重写，只能用白名单值 |
| `xxx.what_kills_this_view 必填但缺失/空` | LLM 偷工 | 让 LLM 补上"证伪条件" |
| `zhaolaoge_liquidity_focus.key_movers 至少 2 条` | LLM 只写了 1 条 | 让它再凑 1 条 |
| `panorama_text 长度 95 不在 [150, 400] 区间` | 写短了 | 让 LLM 展开到 ≥150 字 |
| `ticker_audits[...].auditor='quant' 不允许` | LLM 误填了 quant | 改成具体人格名（yangjia/zhaolaoge/fengliu/discipline） |

修完重跑 `fill_narrative` 即可，**不需要重跑 update_all 或 gen_prompt**。

### 3.3 HTML 渲染缺模块

**症状**：报告里没 §6 策略前瞻 / 没 §3.5 独特异象。

**原因**：narrative 是 None（没跑 LLM）或 `is_skeleton=true`（backfill 的骨架）。模板 if-guard 会跳过新模块。

**修法**：跑 `gen_prompt → fill_narrative → render_html` 走一遍。

### 3.4 批注同步丢失

**症状**：`sync_annotations` 提示 `没新报告需同步`。

**查**：

```bash
cat data/window/last_synced.json
ls -la data/reports/a/   # 看 HTML 文件 mtime
```

如果 HTML mtime 比 `last_synced` 早，sync 就跳过它。**解决**：B 发回的 HTML 必须替换源文件（mtime 会更新），不能是另存的副本。

实在不行：删 `data/window/last_synced.json` 强制全部重扫。

### 3.5 想剔除某个时段

比如某天数据有问题不想让它影响后续 AI 判断：

```bash
python -c "from src import window as win; win.remove_session('A', '2026-05-15-收')"
```

`snapshots/a/2026-05-15-收.json` 永久留档**不动**；只从窗口里剔出去。下一次 `gen_prompt` 不再带这一时段。

如果要彻底删（包括归档）：手动删 `data/snapshots/a/2026-05-15-收.json`。

---

## 4. 进阶操作

### 4.1 跳过底层数据补齐

底层切片已经在别处更新过 / 急着出报告：

```bash
python -m src.update_all --markets A --skip-refresh
```

### 4.2 回看更远的报告缺口

默认回看 7 天，想看 14 天：

```bash
python -m src.update_all --lookback 14
```

### 4.3 重新渲染老报告（修了模板想看效果）

直接跑 render，会读 `data/window/` 或 `data/snapshots/` 里已有数据：

```bash
python -m src.render_html --market A --label 2026-05-19-收
```

不会重跑 LLM。

### 4.4 强制重跑某时段 snapshot（数据有问题）

```bash
python -m src.build_snapshot --market A --label 2026-05-20-收 --session close
```

会覆盖同 label 的 snapshot + 窗口位置（同 label 原地覆盖，不重复添加）。

注意：narrative 会被重置成 None，要重跑 LLM。

---

## 5. 常见问题速答

**Q：跑 LLM 一次要花多少 token？**
A：prompt 通常 8-15 KB（约 4000-8000 tokens），返回的 narrative JSON 约 3-6 KB。Claude Sonnet 单次约 ¥0.5-1。

**Q：A 股池子里加了一只新 ETF，需要做什么？**
A：改 `config/pool_a.yaml` 加一条 entry；下次 `update_all` 自动新增切片 + 该品种从该时段起进入 panel/factors/classify 计算。**历史时段不补该品种**（因为没数据）。

**Q：B 不会用 File System Access API（旧浏览器）怎么办？**
A：HTML 会自动降级——批注存在浏览器 localStorage，并在右下角持续提示"未保存"。这种情况下 B 要"另存为"成新文件发回。

**Q：报告太大了浏览器卡？**
A：220 KB 左右是正常的（含 30 天 sparkline + 全 panel snapshot 内嵌）。卡的话先关其他 tab。

**Q：can I 把 A 股和美股报告合并成一个？**
A：不行，且故意不做。双市场独立报告是 §一 核心约束 #4（互不影响）。

**Q：旧报告里看 narrative 历史的话，要去哪？**
A：`data/snapshots/a/<label>.json` 是永久归档，含完整 narrative；如果之前没跑 LLM 就 `is_skeleton=true` 的骨架。`data/window/pool_a.json` 只保留滚动窗口里的（≤40 个 A 股 / ≤20 个美股）。
