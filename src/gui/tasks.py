"""后台任务管理（GUI 长任务异步执行 + 实时日志流）。

模式：
  task_id = run_async(func, *args, **kwargs)
  func 必须接受 log_cb 关键字参数，把每行进度通过 log_cb(str) 推回。
  前端 fetch /api/task/<id>/status 轮询，拿 {status, log:[lines], result, error}。

线程安全：_tasks 操作加锁；log 列表 append 是 GIL 内原子。
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from typing import Any, Callable

_lock = threading.Lock()
_tasks: dict[str, dict] = {}  # task_id → state dict


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _make_state() -> dict:
    return {
        "status": "running",       # running / done / error
        "log": [],                 # list[str]
        "result": None,            # 任务返回值 (Any)
        "error": None,             # 异常字符串
        "started_at": time.time(),
        "ended_at": None,
    }


class _ThreadLogHandler(logging.Handler):
    """把 root logger 的 INFO/WARN/ERROR 路由到指定 task 的 log_cb。

    只捕获**本任务线程**的日志记录（用 thread ident 过滤），避免 GUI Flask
    自身 / 其它任务的 log 混进来。
    """
    def __init__(self, log_cb, owner_thread_ident):
        super().__init__(level=logging.INFO)
        self._cb = log_cb
        self._owner = owner_thread_ident
        self.setFormatter(logging.Formatter("[%(levelname)s %(name)s] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        if record.thread != self._owner:
            return
        try:
            self._cb(self.format(record))
        except Exception:
            pass


def run_async(func: Callable, *args, **kwargs) -> str:
    """启动后台任务；func 通过 log_cb 推日志；同时 hook Python logging（root logger）
    以捕获 auto-prtsc 的 INFO/WARN（如 'yfinance 批量下载…' / 'yfinance 失败，降级 xxx'）。
    """
    task_id = _new_id()
    with _lock:
        _tasks[task_id] = _make_state()

    def _log(msg: str) -> None:
        with _lock:
            _tasks[task_id]["log"].append(str(msg))

    def _wrap():
        # 挂载本线程专属 logging handler
        root = logging.getLogger()
        # 确保 root level 允许 INFO 通过（auto-prtsc 用 basicConfig 已设过，这里兜底）
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
        handler = _ThreadLogHandler(_log, threading.get_ident())
        root.addHandler(handler)
        try:
            kwargs["log_cb"] = _log
            result = func(*args, **kwargs)
            with _lock:
                _tasks[task_id]["status"] = "done"
                _tasks[task_id]["result"] = result
                _tasks[task_id]["ended_at"] = time.time()
        except Exception as e:
            tb = traceback.format_exc()
            with _lock:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = f"{type(e).__name__}: {e}"
                _tasks[task_id]["log"].append(f"[ERROR] {type(e).__name__}: {e}")
                _tasks[task_id]["log"].append(tb)
                _tasks[task_id]["ended_at"] = time.time()
        finally:
            root.removeHandler(handler)

    t = threading.Thread(target=_wrap, daemon=True)
    t.start()
    return task_id


def get_status(task_id: str, since: int = 0) -> dict | None:
    """读任务状态。since=已收到的日志行数，只返回增量。"""
    with _lock:
        st = _tasks.get(task_id)
        if st is None:
            return None
        log_slice = st["log"][since:]
        return {
            "status": st["status"],
            "log": log_slice,
            "log_total": len(st["log"]),
            "result": st["result"] if st["status"] == "done" else None,
            "error": st["error"],
            "started_at": st["started_at"],
            "ended_at": st["ended_at"],
        }


def cleanup(max_age_sec: int = 3600) -> int:
    """清理超过 max_age_sec 的已完成任务。"""
    now = time.time()
    removed = 0
    with _lock:
        for tid in list(_tasks.keys()):
            st = _tasks[tid]
            if st["status"] in ("done", "error") and st["ended_at"]:
                if now - st["ended_at"] > max_age_sec:
                    del _tasks[tid]
                    removed += 1
    return removed
