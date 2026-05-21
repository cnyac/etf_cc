# etf_cc — A 股 + 美股量价分析自动化

> **状态**：2026-05-20 需求封口 → 2026-05-21 阶段 1-5 实现完成 + 用户反馈已修复。剩阶段 6（数据更新汇总细节）+ 阶段 7（端到端联调）。

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

## 当前代码状态（2026-05-21）

| 阶段 | 模块 | 状态 |
|---|---|---|
| 1a/1b/1c | auto-prtsc 侧 ETF 管道 + `etf_data_api.py` 统一入口 | ✅ |
| 2 | `src/factors.py`（7 因子 + 3 个 close_vs_ma 球）/ `src/panel.py` | ✅ |
| 3 | `src/window.py` / `src/build_snapshot.py` / `src/sync_annotations.py` / `src/backfill.py` | ✅ |
| 4 | `src/llm_schema.py` / `src/llm_validate.py` / `src/llm_prompt.py` / `src/gen_prompt.py` / `src/fill_narrative.py` | ✅ |
| 5 | `src/render_html.py` / `src/templates/report.html.j2` / `src/color_palette.py` + 批注 JS | ✅ |
| 6 | "数据更新汇总输出"细节 | ⏸ |
| 7 | 端到端联调 + 旧代码归档 | 进行中 |

**测试覆盖**：113/113 passed（tests/ 11 个文件）

**旧 docx 流水线**仍在 `src/` 下（ingest.py / prepare_*.py / render_docx.py 等），但 `src/classify.py` 已被新架构复用（2026-05-21 用户批准"全局唯一最增/最缩"改动）。其它旧文件待最后归档到 `src/_archived/`。

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

## 仓库布局（重构后目标态）

```
etf_cc/
├── REFACTOR_BRIEF.md       # 需求决策记录（最详细）
├── DESIGN.md               # 设计动机
├── CLAUDE.md               # AI agent 工作指南
├── README.md               # 本文件
│
├── config/
│   ├── pool_a.yaml         # A 股池清单（用户可编辑）
│   └── pool_us.yaml        # 美股池清单（用户可编辑）
│
├── src/                    # （新架构完成态 ✅）
│   ├── schema.py           # session/window 数据契约（注释 + 默认骨架）
│   ├── factors.py          # 7 因子 + close_vs_ma 三球 + 单一入口 compute_factors
│   ├── classify.py         # 四象限归类 + 位置标签（分类内）+ 全局最增/最缩量
│   ├── panel.py            # panel_breadth 跨品种聚合
│   ├── window.py           # 滚动窗口状态机（load/save/append+弹出/remove/archive）
│   ├── build_snapshot.py   # 单时段生产入口 (CLI)
│   ├── sync_annotations.py # 从 HTML 解析批注 → 窗口 / 归档
│   ├── backfill.py         # 历史回填 + 骨架 narrative
│   ├── llm_schema.py       # 双引擎 schema + enum 白名单 + 长度约束
│   ├── llm_prompt.py       # prompt 构造（短键压缩）
│   ├── llm_validate.py     # 校验 + 校验降级 + merge_into_session
│   ├── gen_prompt.py       # CLI：生成 prompt 到 stdout
│   ├── fill_narrative.py   # CLI：校验 LLM JSON + 回填 session
│   ├── color_palette.py    # 色板闭环（12 浅色默认 + merge）
│   ├── render_html.py      # Jinja2 渲染 + sparkline 真数据注入
│   ├── templates/
│   │   └── report.html.j2  # 单文件自包含主模板（CSS/JS 全内联）
│   │
│   ├── ingest.py / prepare_*.py / render_docx.py / ...   # 旧 docx 流水线（待归档）
│   └── _archived/          # 旧代码最终归档处
│
├── data/
│   ├── window/
│   │   ├── pool_a.json     # A 股滚动窗口（max 40 时段）
│   │   └── pool_us.json    # 美股滚动窗口（max 20 时段）
│   ├── snapshots/
│   │   ├── a/<label>.json  # A 股历史归档（永久保留）
│   │   └── us/<label>.json # 美股历史归档
│   ├── reports/
│   │   ├── a/<label>.html  # A 股报告
│   │   └── us/<label>.html # 美股报告
│   └── logs/
│       ├── update_<ts>.log         # 数据更新日志
│       └── errors/<ts>_<ticker>.json # 失败明细（AI 可复查）
│
└── tests/                   # 单元测试 + 端到端测试
```

## 外部依赖

- **auto-prtsc**（`D:\git\auto prtsc`）：数据基础设施。本项目通过 `from auto_prtsc.etf_data_api import ...` 调用，**不要重新造轮子**。
- **Tushare token**：复用 auto-prtsc 的 `config.py` 中 `TUSHARE_TOKEN`，不另开
- **腾讯财经**：无需认证
- **akshare**：仅兜底
- **yfinance**（auto-prtsc 已集成）：美股主源
- **xfinlink**（auto-prtsc 已集成）：美股备源，付费

## 数据源优先级

| 用途 | 主 | 备 | 兜底 |
|---|---|---|---|
| A 股 ETF 历史日线 | Tushare Pro | 腾讯财经 | akshare |
| A 股 ETF 实时快照 | 腾讯财经 | Tushare（盘后） | akshare |
| 美股历史日线 | yfinance | xfinlink | — |
| 美股实时快照 | yfinance | xfinlink | — |

失败转移：主 → 备 → 兜底逐级 fallback。全部失败则 abort 当前时段 + 错误日志归档。

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
# 单时段生产（含 ingest→factors→classify→panel→入窗口+归档）
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

## 实施工作流（7 阶段 ≈ 11 天）

| 阶段 | 工作 | 估时 | 依赖 | 状态 |
|---|---|---|---|---|
| 1a | auto-prtsc 侧 A 股 ETF 管道 | 1 天 | — | ✅ |
| 1b | auto-prtsc 侧补美股 high/low 宽表 | 0.5 天 | — | ✅（用 Detail 长表代替 pivot） |
| 1c | etf_data_api.py 统一 API | 0.5 天 | 1a, 1b | ✅ |
| 2 | etf_cc factors.py / panel.py | 1.5 天 | 1c | ✅ |
| 3 | 滚动窗口状态机（双市场） | 2 天 | 2 | ✅ |
| 4 | LLM prompt 双引擎 + schema 校验 | 1.5 天 | 3 | ✅ |
| 5 | HTML 渲染（双独立报告） | 2.5 天 | 4 | ✅ |
| 6 | backfill + 池配置 + 数据更新汇总 | 1 天 | 3, 5 | ⏸ 部分（数据更新汇总细节待补） |
| 7 | 端到端联调 + 文档 | 0.5 天 | all | 进行中 |

---

# 三、用户阅读版

> _本部分留空，待用户工作流稳定后补充。_
>
> 内容应包括：
>
> - 日常使用流程（早上看美股报告 / 中午跑 A 股 / 收盘跑 A 股 + 更新美股）
> - 如何编辑池子（pool_a.yaml / pool_us.yaml）
> - 如何在浏览器里批注（点击品种 → 选颜色 → 写备注 → 保存）
> - 如何把批注发回（直接发 HTML 文件给 A）
> - 如何看历史批注线索（在新报告里点击品种展开）
> - 如何主动剔除某个时段
> - 数据更新失败时怎么办（看 `data/logs/errors/` 里的明细）
> - 常见问题速答
