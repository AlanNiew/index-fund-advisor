# api/tasks/manager.py
"""内存任务存储（带 TTL 过期 + 容量上限 + 线程锁）。"""

import os
import threading
import time
from datetime import datetime

_TASK_TTL_SECONDS = int(os.environ.get("IFA_TASK_TTL", "3600"))
_TASK_MAX_SIZE = int(os.environ.get("IFA_TASK_MAX_SIZE", "1000"))

_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()
_last_cleanup = time.monotonic()


def _cleanup_tasks() -> None:
    """清理过期任务，保持内存可控。"""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < 60:
        return
    _last_cleanup = now
    cutoff = time.time() - _TASK_TTL_SECONDS
    expired = [
        tid
        for tid, t in _tasks.items()
        if t.get("completed_at") and datetime.fromisoformat(t["completed_at"]).timestamp() < cutoff
    ]
    for tid in expired:
        _tasks.pop(tid, None)
    if len(_tasks) > _TASK_MAX_SIZE:
        sorted_tasks = sorted(_tasks.items(), key=lambda x: x[1].get("created_at", ""))
        for tid, _ in sorted_tasks[: len(sorted_tasks) - _TASK_MAX_SIZE]:
            _tasks.pop(tid, None)


def add_task(task: dict) -> None:
    with _tasks_lock:
        _cleanup_tasks()
        _tasks[task["task_id"]] = task


def get_task(task_id: str) -> dict | None:
    with _tasks_lock:
        return _tasks.get(task_id)


def all_tasks() -> list[dict]:
    with _tasks_lock:
        return list(_tasks.values())
