"""一个有上限的 TTL 缓存。

为什么不用裸 dict：模块级 dict 只增不减，数据源一多就是内存泄漏；
多进程部署时也无法共享，必须让"每个进程各存一份、且有界"这件事显式化。

线程/协程安全性：本项目是单事件循环，读写都在协程里，不需要锁。
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, maxsize: int = 64, ttl: float = 60.0) -> None:
        self.maxsize = maxsize
        self.ttl = ttl
        self._data: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def get(self, key: str) -> T | None:
        item = self._data.get(key)
        if item is None:
            return None
        stored_at, value = item
        if time.time() - stored_at > self.ttl:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: T) -> None:
        self._data[key] = (time.time(), value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def clear(self, prefix: str | None = None) -> None:
        if prefix is None:
            self._data.clear()
            return
        for key in [key for key in self._data if key.startswith(prefix)]:
            self._data.pop(key, None)

    def __len__(self) -> int:
        return len(self._data)