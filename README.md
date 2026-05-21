# etf_cc — A 股 + 美股量价分析自动化

> **状态**：2026-05-21 阶段 1-6 + A + B 实现完成；旧 docx 流水线归档；剩阶段 7（端到端真实 LLM 联调）。
>
> Git: https://github.com/cnyac/etf_cc · main · 170/170 测试通过

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

## 当前代码状态（2026-05-21）

| 阶段 | 模块 | 状态 |
|---|---|---|
| 1a/1b/1c | auto-prtsc 侧 ETF 管道 + `etf_data_api.py` 统一入口 | ✅ |
| 2 | `src/factors.py` / `src/panel.py`（含 breadth_alert） | ✅ |
| 3 | `src/window.py` / `src/build_snapshot.py` / `src/sync_annotations.py` / `src/backfill.py` | ✅ |
| 4 | `src/llm_schema.py` / `src/llm_validate.py` / `src/llm_prompt.py` / `src/gen_prompt.py` / `src/fill_narrative.py` | ✅ |
| 5 | `src/render_html.py` / `src/templates/report.html.j2` / `src/color_palette.py` + 批注 JS | ✅ |
| 6 | 数据更新汇总：`update_all` / `data_refresh` / `report_gap` / `log_util` | ✅ |
| A | 极值预警 + §3 三行滚动渲染（不动 LLM） | ✅ |
| B | 人格扩职 + 预期审计（`audit.py` + schema 扩字段 + §3.5/§6/§7） | ✅ |
| 7 | 端到端联调（待真实 LLM narrative） | ⏸ |

**测试覆盖**：170/170 passed（tests/ 16 个文件）

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
│   ├── pool_a.yaml         # A 股池清单（用户可编辑）
│   └── pool_us.yaml        # 美股池清单（用户可编辑）
│
├── src/                    # 22 个新代码文件，按下方 6 层划分
│   │
│   │   ── A. 数据流水线 ─────────────────────────
│   ├── update_all.py       # 一键入口：补底层切片 + 检测报告缺口 + 跑缺的 label
│   ├── data_refresh.py     # 调 auto-prtsc 池粒度 API（只更新 90 只池子）
│   ├── report_gap.py       # 报告层缺口检测 + 行为矩阵（A/US × 时刻）
│   ├── build_snapshot.py   # 单时段生产（含 noon 实时 + quant audit 注入）
│   ├── backfill.py         # 历史回填 + 骨架 narrative (is_skeleton=true)
│   │
│   │   ── B. 计算核心 ───────────────────────────
│   ├── factors.py          # 7 因子 + close_vs_ma 三球 + 单一入口 compute_factors
│   ├── classify.py         # 四象限归类 + 位置标签（分类内）+ 全局最增/最缩量
│   ├── panel.py            # panel_breadth 聚合 + breadth_alert（±70% 共振）
│   ├── audit.py            # per-ticker 量化代审（D1 归类跃迁 + D2 量能配合）
│   │
│   │   ── C. 状态管理 ───────────────────────────
│   ├── schema.py           # session/window 数据契约
│   ├── window.py           # 滚动窗口（load/save/append+弹出/remove/archive）
│   ├── sync_annotations.py # 从 HTML 解析 <script id="annotations"> 回写窗口
│   │
│   │   ── D. LLM 协作 ───────────────────────────
│   ├── llm_schema.py       # 双引擎 schema + enum 白名单 + 长度约束 + 人格扩职
│   ├── llm_prompt.py       # prompt 构造（短键压缩 + 审计上下文 + 周末标志）
│   ├── llm_validate.py     # 校验 + 校验降级 + merge_into_session 覆盖 audit
│   ├── gen_prompt.py       # CLI：生成 prompt → stdout
│   ├── fill_narrative.py   # CLI：校验 LLM JSON + 回填 session
│   │
│   │   ── E. 渲染层 ─────────────────────────────
│   ├── render_html.py      # Jinja2 渲染 + 三行滚动 + sparkline 真数据注入
│   ├── color_palette.py    # 色板闭环（12 浅色默认 + merge）
│   ├── templates/
│   │   ├── report.html.j2  # 单文件自包含主模板（CSS/JS 全内联）
│   │   └── _archived/      # 旧版 html.j2 模板
│   │
│   │   ── F. 工具 ───────────────────────────────
│   ├── log_util.py         # 数据更新汇总 + 错误明细 JSON
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
└── tests/                  # 16 个 test_ 文件，170 个 case
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
# 一键数据更新（推荐：补底层切片 + 跑报告缺口）
python -m src.update_all                    # A + US 全跑，lookback 7 天
python -m src.update_all --markets A        # 只 A 股
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

# 跑所有测试
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
