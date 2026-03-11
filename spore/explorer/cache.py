"""Small TTL cache for explorer read models."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .state import all_task_summaries, collect_explorer_state, task_summary


@dataclass
class _Entry:
    value: object
    created_at: float


class ExplorerCache:
    def __init__(self, ttl_sec: float = 5.0):
        self.ttl_sec = ttl_sec
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], _Entry] = {}

    def get_state(self, node, task_id: str):
        return self._get(
            ("state", task_id or ""),
            lambda: collect_explorer_state(node, task_id),
        )

    def get_tasks(self, node):
        return self._get(("tasks", ""), lambda: all_task_summaries(node))

    def get_task_detail(self, node, task_id: str):
        return self._get(
            ("task_detail", task_id),
            lambda: task_summary(node, node.get_task(task_id)),
        )

    def clear(self):
        with self._lock:
            self._entries.clear()

    def _get(self, key: tuple[str, str], factory):
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry and now - entry.created_at <= self.ttl_sec:
                return entry.value
        value = factory()
        with self._lock:
            self._entries[key] = _Entry(value=value, created_at=now)
        return value
