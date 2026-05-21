# 接力棒：etf_cc 前端 GUI 实施

> 新对话窗口的 AI，你的任务是给 `etf_cc` 项目做一个 Flask + Tailwind 前端，整合所有 CLI 命令为按钮操作。
>
> 这份文档是冷启动指南——读完就能动手。

---

## 1. 5 分钟项目认知（必读）

### 1.1 这个项目在做什么

`etf_cc` 是 A 股 + 美股板块联动量价分析自动化项目。完整工作流文档在 `README.md`，特别是 **§三 用户阅读版** 详细列了所有日常操作步骤。

核心原则（CLAUDE.md "绝对禁区"）：

- **Python 算确定性，LLM 说人话**
- HTML 视觉规范固化（红/深蓝/灰，**严禁绿色**——用户色盲）
- 字体规范：华文中宋一级 / 黑体二级 / 楷体_GB2312 三级 / 仿宋_GB2312 正文
- 不动 `classify.py` 边界规则
- 不修改 `src/templates/report.html.j2`（那是产出报告的模板，不是 GUI 模板）

### 1.2 必读的 4 个文档（按顺序）

1. **`README.md`** — §一 项目核心约束 + §二 模块分类目录树 + **§三 用户日常工作流**（你要做的就是把 §三 的命令做成按钮）
2. **`CLAUDE.md`** — 工作时的禁区 + 模块分层 + 常用命令列表
3. **`DESIGN.md`** — 设计动机，不要做什么
4. **`REFACTOR_BRIEF.md §7.10`** — **本任务的完整需求规格**（5 个 tab / 日志面板 / 状态栏 / 技术选型）

不要跳过这 4 个，否则你不会知道用户的术语（龙1/最增量/独特等）和铁律。

### 1.3 验证你读懂了

回答这两个问题不需要看代码：

1. 用户敲一次完整日常流程是哪 5 步命令？
2. `update_all` 内部做了哪 4 件事？

如果答不出，先回头读 `README.md` §三。

---

## 2. 开工前的 3 个检查命令

```bash
# 1. 测试全过（基线 170/170）
python -m pytest tests/

# 2. 看最近 git 历史
git log --oneline -8

# 3. 看现有目录结构
ls src/        # 你将新增 src/gui/ 这个子目录
ls tests/      # 你也要在这里加 GUI 测试
```

如果测试不全过，**停下来报告用户**，不要在不稳定的基线上加新代码。

---

## 3. 复用 auto-prtsc 前端（关键）

`D:\git\auto prtsc\` 里有一个成熟的 Flask + Tailwind 形态匹配引擎前端，你**整体复用它的设计模式**，但不直接 import（两个项目独立部署）。

### 3.1 必看的源文件

```
D:\git\auto prtsc\
├── app_base.py                   # Flask app factory + AppConfig 注入模式
├── templates/index.html          # 1189 行 Tailwind 单页（tab + fetch API）
├── static/
│   ├── fonts/STZHONGS.TTF        # 华文中宋字体
│   └── lib/                      # 第三方库
└── cross_market/app.py           # 另一个独立端口的 Flask app 范例
```

### 3.2 复用方式

**抄结构**：

- Flask 路由设计（`@app.route("/api/...")`）
- 异步任务模式：长任务（如 update_all）→ 后台线程 → `/api/task/<id>/status` 轮询进度
- Tailwind CDN（`<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries">`）
- tab 切换 + `display:none` 切面板的纯 JS 写法
- 按钮 / 输入 / 卡片的 CSS 变量（已定义好色板：`--primary` / `--surface` 等）

**直接复制**：

```bash
# 你要 cp 这两个目录到 etf_cc/src/gui/static/
cp -r "D:/git/auto prtsc/static/fonts"  src/gui/static/
cp -r "D:/git/auto prtsc/static/lib"    src/gui/static/
```

**不要复用的**：

- `auto-prtsc` 的 `engine.py` / `etf_extractor.py` 业务逻辑（那是形态匹配，跟 etf_cc 无关）
- `app_base.py` 里所有 `/api/etf/*` / `/api/pool/*` 路由（业务不同）

### 3.3 颜色 + 字体强约束（不要复制 auto-prtsc 的暖红色调）

auto-prtsc 用棕红色调（`--primary:#8f482f`），etf_cc 不能跟它一样。`etf_cc` 的视觉规范见 `CLAUDE.md`：

- 文字主色：黑（标题）+ 红 `#FF0000` 涨 + 深蓝 `#00008B` 跌
- 用户色盲：**严禁绿色**任何地方
- 字体：华文中宋（一级标题） / 黑体（二级） / 楷体_GB2312（三级粗体） / 仿宋_GB2312（正文）

GUI 主色建议：黑白灰为底 + 红/深蓝点缀（与报告视觉一致）。

---

## 4. 实施要点速查（必读 REFACTOR_BRIEF §7.10 后再回来对照）

### 4.1 目标结构

```
src/gui/
├── __init__.py
├── app.py                   # Flask app + 所有 /api 路由（~300-500 行）
├── tasks.py                 # 后台线程管理（运行 update_all 等长任务）
├── templates/
│   └── index.html           # 单页 Tailwind UI（tab 切换 5+ 个面板）
└── static/
    ├── fonts/               # 抄 auto-prtsc
    └── lib/                 # 抄 auto-prtsc

启动:  python -m src.gui.app   # 默认端口 5010
```

### 4.2 5 个 tab 要做的事（详见 REFACTOR_BRIEF §7.10）

| Tab | 调用 | UI 元素 |
|---|---|---|
| 1. 数据更新 | `src.update_all.run(...)` | 市场单选 + lookback 数字框 + skip-refresh 复选 + "开跑"按钮 + 实时滚动日志 |
| 2. 生成 Prompt | `src.gen_prompt` 或直接 `src.llm_prompt.build_prompt` | market/label 下拉 + "生成"按钮 + textarea 显示 + 一键复制 |
| 3. 填回 Narrative | `src.fill_narrative` 或直接 `src.llm_validate.validate_narrative + merge_into_session` | textarea 粘 JSON + "校验+回填"按钮 + 错误列表展示 |
| 4. 渲染报告 | `src.render_html.render` | market/label 下拉 + "渲染"按钮 + iframe 预览 |
| 5. 同步批注 | `src.sync_annotations` | 上传/拖拽 HTML + "同步"按钮 |

### 4.3 日志面板（关键，用户专门要求）

用户的原话：

> 也要方便查看日志以便提交给你修 bug

所以日志面板必须包含：

1. **实时执行日志**：当前操作的 stdout/stderr 滚动显示（subprocess + 流式）
2. **历史汇总列表**：`data/logs/update_*.log` 文件列表，点击查看
3. **错误明细**：`data/logs/errors/*.json` 列表，**一键复制 JSON 内容到剪贴板**（方便用户贴给 AI 修 bug——这就是用户原话）

### 4.4 状态栏（顶部常驻）

显示：

- A 股窗口：N 个 session，最新 label = `2026-05-20-收`
- 美股窗口：M 个 session，最新 label = `2026-05-20`
- 报告缺口：调 `src.report_gap.detect_report_gaps`，缺 X 个
- 上次更新：`data/logs/update_<ts>.log` 最新 mtime

### 4.5 池配置编辑器（"池子" tab）

不是必须，但建议做。表格行：code / name / role 三列 + 增删按钮 + 保存按钮 → 写回 `config/pool_a.yaml` 或 `pool_us.yaml`。

注意：`role` 字段是 enum（`treasury_10y/treasury_30y/gold/oil/dollar/vix/btc/eth` 或空），下拉框限定，**禁止自由输入**——否则 panel.cross_asset_state 会算错。

---

## 5. 关键技术细节

### 5.1 长任务的异步模式（必须）

`update_all` 跑全市场 + 全缺口可能 1-2 分钟。前端不能阻塞，必须：

```python
# src/gui/tasks.py
import threading
import uuid

_tasks: dict[str, dict] = {}  # task_id → {status, log, result}

def run_async(func, *args, **kwargs) -> str:
    task_id = uuid.uuid4().hex[:8]
    _tasks[task_id] = {"status": "running", "log": [], "result": None}

    def _wrap():
        try:
            result = func(*args, _log_cb=lambda s: _tasks[task_id]["log"].append(s), **kwargs)
            _tasks[task_id]["status"] = "done"
            _tasks[task_id]["result"] = result
        except Exception as e:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["log"].append(f"ERROR: {e}")
    threading.Thread(target=_wrap, daemon=True).start()
    return task_id
```

前端 fetch `/api/task/<id>/status` 每 500ms 轮询。

但是！现有 `update_all.py` 内部用 `print()`，要 stream 到 UI 你得：

- 选项 A（简单）：subprocess + `iter()` stdout（推荐，无需改 update_all）
- 选项 B（清爽）：改 update_all 接受 `log_callback` 参数，所有 print 走它

我倾向**选项 A**：用 `subprocess.Popen(["python", "-m", "src.update_all", ...], stdout=PIPE)`，逐行读 stdout 推到 task log，这样不动现有 CLI。

### 5.2 别绕过校验

`fill_narrative` 已经有完整 schema 校验（enum / 长度 / what_kills_this_view 必填等）。GUI 不要自己写一遍校验，**直接调** `src.llm_validate.validate_narrative()`。

错误展示：把 errors list 在 UI 里红色列出，每条对应字段 + 期望值，让用户能直接复制贴给 LLM 让它修。

### 5.3 路由约定建议

```
GET  /                                # 主页（index.html）
GET  /api/status                      # 窗口/缺口/上次更新概览
POST /api/update_all                  # 跑 update_all → 返回 task_id
POST /api/gen_prompt                  # 同步返回 prompt 字符串
POST /api/fill_narrative              # 同步返回 (ok, errors)
POST /api/render_html                 # 同步，返回 report 路径
POST /api/sync_annotations            # 跑 → 返回结果
GET  /api/task/<task_id>/status       # 轮询任务进度
GET  /api/logs                        # 列 update_*.log
GET  /api/logs/<filename>             # 看具体内容
GET  /api/errors                      # 列 errors/*.json
GET  /api/errors/<filename>           # 看具体内容
GET  /api/pool/<market>               # 读 pool yaml
POST /api/pool/<market>               # 写 pool yaml
GET  /reports/<path>                  # 静态服务 data/reports/
```

---

## 6. 验收标准

完工时必须满足：

1. **`python -m src.gui.app` 启动** → 浏览器开 `http://127.0.0.1:5010` 看到主页
2. **5 个 tab 都能跑通**：从数据更新到批注同步全部按钮化
3. **日志面板能展示** stdout 实时滚动 + 历史 log 列表 + 错误一键复制
4. **不破坏现有 170 个测试**（`python -m pytest tests/` 仍 170 passed）
5. **加 GUI 单测**（至少覆盖路由 200/400 响应）：`tests/test_gui.py`
6. **不引入 React/Vue/Webpack**（保持原生 JS + Tailwind CDN）
7. **commit + push** 到 `origin/main`

---

## 7. 如果中途遇到难题

用户的偏好（CLAUDE.md 末尾）：

- **不要默认开工**：拍板前先讨论
- **写代码前告诉用户你打算做什么**，等他拍板
- **用户喜欢"先讨论清楚再写代码"**

所以遇到歧义（比如"日志显示要不要带时间戳染色"），**问用户**，别凭感觉做。

技术问题（比如"subprocess 流式输出有缓冲问题"）你可以自己解决。

---

## 8. 第一句话建议

进新对话窗口后，把这份 `HANDOFF_FRONTEND.md` 整文件贴给 AI 当作上下文（用 `@HANDOFF_FRONTEND.md` 或者整段复制），然后说：

> 按 HANDOFF_FRONTEND.md 给 etf_cc 做前端 GUI。先读 §1 必读文档、跑 §2 检查命令、看 §3 auto-prtsc 复用资产，然后跟我对一下 §4 的 5 个 tab 设计有没有要调整，对完再开工。

AI 应该花前 30 分钟读项目，然后给你一个简短的"准备开工方案"，**不应该立刻动手写代码**。如果它直接开始 import flask 写路由，提醒它先汇报理解。

---

**祝顺利**。完工后记得更新 `REFACTOR_BRIEF.md §7.10` 标记完成，并在 `README.md` §三 加一段"GUI 用法"。
