"""进程内限流：滑动窗口计数。

为什么是进程内：本项目单进程部署，够用且零依赖。
多副本时每个进程各算一份（限流会变宽），要严格限流就把入口放到
Nginx / 云 WAF 上——这一点在部署文档里写明了。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(slots=True)
class Decision:
    allowed: bool
    retry_after: int = 0


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, max_keys: int = 5000) -> None:
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._last_sweep = time.monotonic()

    def _prune(self, key: str, now: float) -> None:
        hits = self._hits.get(key)
        if hits is None:
            return
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if not hits:
            self._hits.pop(key, None)

    def _sweep(self, now: float) -> None:
        """定期清理过期窗口，避免 key 无限增长。"""
        if now - self._last_sweep < 60:
            return
        self._last_sweep = now
        for key in list(self._hits):
            self._prune(key, now)

    def check(self, key: str) -> Decision:
        now = time.monotonic()
        self._prune(key, now)
        hits = self._hits.get(key)
        if not hits or len(hits) < self.limit:
            return Decision(True)
        retry_after = int(self.window - (now - hits[0])) + 1
        return Decision(False, max(retry_after, 1))

    def hit(self, key: str) -> None:
        now = time.monotonic()
        self._sweep(now)
        if len(self._hits) >= self.max_keys and key not in self._hits:
            # 极端情况：一次性清空，保证内存有上界
            self._hits.clear()
        self._hits[key].append(now)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear(self) -> None:
        self._hits.clear()