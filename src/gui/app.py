"""etf_cc 前端 GUI — Flask 单文件 app（端口 5010）。

启动：  python -m src.gui.app
访问：  http://127.0.0.1:5010

设计：
  - 路由约定见 REFACTOR_BRIEF.md §7.10 / §7.11
  - 长任务（update_all / sync）走 gui.tasks 后台线程 + /api/task/<id> 轮询
  - 同步小任务（gen_prompt / fill_narrative / render_html / pool 编辑）直接返回
  - 静态资源：static/{fonts,lib}/，报告：/reports/<m>/<file>
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from typing import Literal

from flask import (
    Flask, render_template, jsonify, request, send_from_directory, abort
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.gui import tasks as bg
from src import window as win
from src import report_gap

REPORTS_DIR = os.path.join(ROOT, "data", "reports")
LOGS_DIR = os.path.join(ROOT, "data", "logs")
ERRORS_DIR = os.path.join(LOGS_DIR, "errors")
CONFIG_DIR = os.path.join(ROOT, "config")
WINDOW_DIR = os.path.join(ROOT, "data", "window")


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
        static_url_path="/static",
    )

    # ───────────────────────────── 主页 ─────────────────────────────
    @app.route("/")
    def index():
        return render_template("index.html")

    # ─────────────────────────── 状态栏 ─────────────────────────────
    @app.route("/api/status")
    def api_status():
        def _market_status(m: str) -> dict:
            data = win.load(m)
            sessions = data.get("sessions", [])
            latest = sessions[-1]["label"] if sessions else None
            # 缺口
            try:
                end_date, a_until = report_gap.default_end(m)
                start_date = (datetime.date.fromisoformat(end_date)
                              - datetime.timedelta(days=7)).isoformat()
                gaps = report_gap.detect_report_gaps(m, start_date, end_date, a_until)
            except Exception as e:
                gaps = []
                latest = latest or f"(gap check 失败: {e})"
            return {
                "market": m,
                "session_count": len(sessions),
                "max_sessions": data.get("max_sessions", 0),
                "latest_label": latest,
                "gap_count": len(gaps),
                "gap_labels": gaps,
            }

        # 上次 update_all 时间
        last_update = None
        if os.path.isdir(LOGS_DIR):
            logs = sorted(
                [f for f in os.listdir(LOGS_DIR) if f.startswith("update_") and f.endswith(".log")],
                reverse=True,
            )
            if logs:
                fp = os.path.join(LOGS_DIR, logs[0])
                last_update = {
                    "filename": logs[0],
                    "mtime": datetime.datetime.fromtimestamp(os.path.getmtime(fp)).isoformat(timespec="seconds"),
                }

        return jsonify({
            "A": _market_status("A"),
            "US": _market_status("US"),
            "last_update": last_update,
            "now": datetime.datetime.now().isoformat(timespec="seconds"),
        })

    # ─────────────────────── label 下拉数据源 ───────────────────────
    @app.route("/api/labels/<market>")
    def api_labels(market):
        if market not in ("A", "US"):
            abort(400)
        data = win.load(market)
        labels = [s["label"] for s in data.get("sessions", [])]
        # 升序，最新在最后
        return jsonify({"market": market, "labels": labels})

    # ─────────────────────── Tab 1 数据更新 ─────────────────────────
    @app.route("/api/update_all", methods=["POST"])
    def api_update_all():
        body = request.get_json(silent=True) or {}
        markets = body.get("markets") or ["A", "US"]
        lookback = int(body.get("lookback", 7))
        skip_refresh = bool(body.get("skip_refresh", False))

        # 校验
        markets = [m for m in markets if m in ("A", "US")]
        if not markets:
            return jsonify({"error": "markets 不能为空"}), 400

        from src import update_all as ua
        task_id = bg.run_async(
            ua.run,
            markets=markets,
            lookback_days=lookback,
            skip_refresh=skip_refresh,
        )
        return jsonify({"task_id": task_id})

    @app.route("/api/task/<task_id>")
    def api_task(task_id):
        since = int(request.args.get("since", 0))
        st = bg.get_status(task_id, since)
        if st is None:
            return jsonify({"error": "task not found"}), 404
        return jsonify(st)

    # ─────────────────────── Tab 2 生成 Prompt ──────────────────────
    @app.route("/api/gen_prompt", methods=["POST"])
    def api_gen_prompt():
        body = request.get_json(silent=True) or {}
        market = body.get("market")
        label = body.get("label")
        segmented = bool(body.get("segmented", False))
        if market not in ("A", "US") or not label:
            return jsonify({"error": "需 market(A/US) + label"}), 400

        from src.llm_prompt import build_prompt, build_segmented_prompts
        data = win.load(market)
        target = next((s for s in data["sessions"] if s["label"] == label), None)
        if target is None:
            return jsonify({"error": f"窗口里找不到 {market}/{label}"}), 404
        history = [s for s in data["sessions"] if s["label"] != label]
        try:
            if segmented:
                parts = build_segmented_prompts(market, target, history)
                # 向后兼容：未传 segmented=true 时仍是旧返回结构
                return jsonify({
                    "prompts": parts,
                    "lengths": [len(p) for p in parts],
                    "segmented": True,
                })
            prompt = build_prompt(market, target, history)
        except Exception as e:
            return jsonify({"error": f"build_prompt 失败: {type(e).__name__}: {e}"}), 500
        return jsonify({"prompt": prompt, "length": len(prompt)})

    # ─────────────────────── Tab 3 填回 Narrative ───────────────────
    @app.route("/api/fill_narrative", methods=["POST"])
    def api_fill_narrative():
        body = request.get_json(silent=True) or {}
        market = body.get("market")
        label = body.get("label")
        narrative_text = body.get("narrative")
        if market not in ("A", "US") or not label or narrative_text is None:
            return jsonify({"error": "需 market(A/US) + label + narrative(JSON string or object)"}), 400

        # narrative 可能是 string 或已经是 object
        try:
            narrative = (json.loads(narrative_text) if isinstance(narrative_text, str)
                         else narrative_text)
        except json.JSONDecodeError as e:
            return jsonify({"ok": False, "errors": [f"JSON 解析失败: {e}"]}), 422

        data = win.load(market)
        target = next((s for s in data["sessions"] if s["label"] == label), None)
        if target is None:
            return jsonify({"ok": False, "errors": [f"窗口里找不到 {market}/{label}"]}), 404

        from src.llm_validate import validate_narrative, merge_into_session
        ok, errors = validate_narrative(
            narrative, market, target.get("panel"),
            is_weekend_close=target.get("is_weekend_close", False),
        )
        if not ok:
            return jsonify({"ok": False, "errors": errors}), 422

        merge_into_session(target, narrative)
        win.save(market, data)
        win.archive_to_snapshot(market, target)
        return jsonify({"ok": True, "label": label})

    # ─────────────────────── Tab 4 渲染报告 ─────────────────────────
    @app.route("/api/render_html", methods=["POST"])
    def api_render():
        body = request.get_json(silent=True) or {}
        market = body.get("market")
        label = body.get("label")
        if market not in ("A", "US") or not label:
            return jsonify({"error": "需 market + label"}), 400
        from src.render_html import render
        try:
            fp = render(market, label)
        except Exception as e:
            return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
        rel = os.path.relpath(fp, REPORTS_DIR).replace("\\", "/")
        return jsonify({
            "report_path": fp,
            "report_url": f"/reports/{rel}",
        })

    @app.route("/reports/<path:subpath>")
    def serve_report(subpath):
        return send_from_directory(REPORTS_DIR, subpath)

    # ─────────────────────── Tab 5 同步批注 ─────────────────────────
    @app.route("/api/sync_annotations", methods=["POST"])
    def api_sync():
        body = request.get_json(silent=True) or {}
        market = body.get("market")
        if market not in ("A", "US"):
            return jsonify({"error": "需 market(A/US)"}), 400
        from src.sync_annotations import sync
        try:
            result = sync(market)
        except Exception as e:
            return jsonify({"error": f"{type(e).__name__}: {e}"}), 500
        return jsonify(result)

    @app.route("/api/upload_report", methods=["POST"])
    def api_upload_report():
        """拖拽上传：表单字段 market + file。文件名作 label.html 覆盖。
        覆盖后立即调 sync_annotations。"""
        market = request.form.get("market")
        if market not in ("A", "US"):
            return jsonify({"error": "需 market(A/US)"}), 400
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "未上传文件"}), 400
        if not f.filename.lower().endswith(".html"):
            return jsonify({"error": "只支持 .html"}), 400
        # 防目录穿越
        safe_name = os.path.basename(f.filename)
        target_dir = os.path.join(REPORTS_DIR, market.lower())
        os.makedirs(target_dir, exist_ok=True)
        target_fp = os.path.join(target_dir, safe_name)
        f.save(target_fp)
        # 立即触发同步
        from src.sync_annotations import sync
        try:
            result = sync(market)
        except Exception as e:
            return jsonify({"saved": target_fp, "sync_error": str(e)}), 200
        return jsonify({"saved": target_fp, "sync": result})

    # ─────────────────────── Tab 6 批注收件 ─────────────────────────
    @app.route("/api/inbox/<market>")
    def api_inbox(market):
        if market not in ("A", "US"):
            abort(400)
        market_dir = os.path.join(REPORTS_DIR, market.lower())
        last_synced_fp = os.path.join(WINDOW_DIR, "last_synced.json")
        last = {}
        if os.path.exists(last_synced_fp):
            with open(last_synced_fp, "r", encoding="utf-8") as fp:
                last = json.load(fp).get(market, {})
        items = []
        if os.path.isdir(market_dir):
            for fn in sorted(os.listdir(market_dir)):
                if not fn.endswith(".html"):
                    continue
                fp = os.path.join(market_dir, fn)
                mtime = os.path.getmtime(fp)
                label = fn[:-5]
                synced_at = last.get(label)
                pending = (synced_at is None) or (mtime > synced_at)
                items.append({
                    "filename": fn,
                    "label": label,
                    "mtime": datetime.datetime.fromtimestamp(mtime).isoformat(timespec="seconds"),
                    "synced_at": (datetime.datetime.fromtimestamp(synced_at).isoformat(timespec="seconds")
                                  if synced_at else None),
                    "pending": pending,
                    "url": f"/reports/{market.lower()}/{fn}",
                })
        return jsonify({"market": market, "items": items})

    # ─────────────────────── Tab 7 池配置 ──────────────────────────
    @app.route("/api/pool/<market>")
    def api_get_pool(market):
        if market not in ("A", "US"):
            abort(400)
        import yaml
        fp = os.path.join(CONFIG_DIR, f"pool_{market.lower()}.yaml")
        if not os.path.exists(fp):
            return jsonify({"etfs": []})
        with open(fp, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return jsonify(data)

    @app.route("/api/pool/<market>", methods=["POST"])
    def api_set_pool(market):
        if market not in ("A", "US"):
            abort(400)
        body = request.get_json(silent=True) or {}
        etfs = body.get("etfs")
        if not isinstance(etfs, list):
            return jsonify({"error": "需 etfs:list"}), 400
        # role 白名单校验（防 GUI 绕过）
        from src.gui.config_schema import VALID_ROLES
        for i, e in enumerate(etfs):
            if not isinstance(e, dict) or "code" not in e:
                return jsonify({"error": f"etfs[{i}] 缺 code"}), 400
            role = e.get("role", "")
            if role and role not in VALID_ROLES:
                return jsonify({"error": f"etfs[{i}].role={role!r} 不在白名单 {VALID_ROLES}"}), 400
        import yaml
        fp = os.path.join(CONFIG_DIR, f"pool_{market.lower()}.yaml")
        with open(fp, "w", encoding="utf-8") as f:
            yaml.safe_dump({"etfs": etfs}, f, allow_unicode=True, sort_keys=False)
        return jsonify({"ok": True, "count": len(etfs)})

    # ─────────────────── Tab 8 系统调参（占位，后续填实现） ─────────
    @app.route("/api/personas")
    def api_get_personas():
        from src.gui import config_io
        return jsonify(config_io.load_personas())

    @app.route("/api/personas", methods=["POST"])
    def api_set_personas():
        from src.gui import config_io
        body = request.get_json(silent=True) or {}
        config_io.save_personas(body)
        return jsonify({"ok": True})

    @app.route("/api/thresholds")
    def api_get_thresholds():
        from src.gui import config_io
        return jsonify(config_io.load_thresholds())

    @app.route("/api/thresholds", methods=["POST"])
    def api_set_thresholds():
        from src.gui import config_io
        body = request.get_json(silent=True) or {}
        try:
            config_io.save_thresholds(body)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({"ok": True, "warning":
                        "阈值已更新。注意：新阈值仅影响下次 build_snapshot 产出的 session；"
                        "已存在的窗口数据不会重算，跨日比较可能失去可比性。"})

    @app.route("/api/prompt_templates")
    def api_list_prompt_templates():
        from src.gui import config_io
        return jsonify(config_io.list_prompt_templates())

    @app.route("/api/prompt_template/<key>")
    def api_get_prompt_template(key):
        from src.gui import config_io
        try:
            text, is_default = config_io.read_prompt_template(key)
        except FileNotFoundError:
            abort(404)
        return jsonify({"key": key, "content": text, "is_default": is_default})

    @app.route("/api/prompt_template/<key>", methods=["POST"])
    def api_set_prompt_template(key):
        from src.gui import config_io
        body = request.get_json(silent=True) or {}
        content = body.get("content")
        if content is None:
            return jsonify({"error": "需 content"}), 400
        try:
            config_io.write_prompt_template(key, content)
        except KeyError:
            abort(404)
        return jsonify({"ok": True})

    @app.route("/api/prompt_template/<key>/reset", methods=["POST"])
    def api_reset_prompt_template(key):
        from src.gui import config_io
        try:
            config_io.reset_prompt_template(key)
        except KeyError:
            abort(404)
        return jsonify({"ok": True})

    # ─────────────────────── 日志 / 错误 ──────────────────────────
    @app.route("/api/logs")
    def api_logs():
        if not os.path.isdir(LOGS_DIR):
            return jsonify({"items": []})
        items = []
        for fn in sorted(os.listdir(LOGS_DIR), reverse=True):
            if fn.startswith("update_") and fn.endswith(".log"):
                fp = os.path.join(LOGS_DIR, fn)
                items.append({
                    "filename": fn,
                    "mtime": datetime.datetime.fromtimestamp(os.path.getmtime(fp)).isoformat(timespec="seconds"),
                    "size": os.path.getsize(fp),
                })
        return jsonify({"items": items[:50]})

    @app.route("/api/logs/<filename>")
    def api_log_content(filename):
        if "/" in filename or "\\" in filename or ".." in filename:
            abort(400)
        fp = os.path.join(LOGS_DIR, filename)
        if not os.path.exists(fp):
            abort(404)
        with open(fp, "r", encoding="utf-8") as f:
            return jsonify({"filename": filename, "content": f.read()})

    @app.route("/api/errors")
    def api_errors():
        if not os.path.isdir(ERRORS_DIR):
            return jsonify({"items": []})
        items = []
        for fn in sorted(os.listdir(ERRORS_DIR), reverse=True):
            if fn.endswith(".json"):
                fp = os.path.join(ERRORS_DIR, fn)
                items.append({
                    "filename": fn,
                    "mtime": datetime.datetime.fromtimestamp(os.path.getmtime(fp)).isoformat(timespec="seconds"),
                    "size": os.path.getsize(fp),
                })
        return jsonify({"items": items[:100]})

    @app.route("/api/errors/<filename>")
    def api_error_content(filename):
        if "/" in filename or "\\" in filename or ".." in filename:
            abort(400)
        fp = os.path.join(ERRORS_DIR, filename)
        if not os.path.exists(fp):
            abort(404)
        with open(fp, "r", encoding="utf-8") as f:
            return jsonify({"filename": filename, "content": f.read()})

    return app


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=5010)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    app = create_app()
    print(f"\n  etf_cc GUI 启动\n  → http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)


if __name__ == "__main__":
    main()
