"""缓存与语义层加载的单元测试。

覆盖这次修的几处"静默出问题"的地方：
- 结构缓存有上界、会过期
- 语义层文件改了要能重载，写错要留 warning（而不是悄悄变成空口径）
"""

from __future__ import annotations

import time

import pytest

from app.cache import TTLCache
from app.config import settings
from app.engine import semantics as semantics_module
from app.engine.semantics import load_semantics, reset_semantics_cache

# ---------------- TTLCache ----------------


def test_cache_returns_value_and_evicts_lru() -> None:
    cache: TTLCache[str] = TTLCache(maxsize=2, ttl=60)
    cache.set("a", "1")
    cache.set("b", "2")
    assert cache.get("a") == "1"

    cache.set("c", "3")  # 撞上限，淘汰最久未用的 b
    assert cache.get("b") is None
    assert cache.get("a") == "1"
    assert cache.get("c") == "3"
    assert len(cache) == 2


def test_cache_expires() -> None:
    cache: TTLCache[str] = TTLCache(maxsize=4, ttl=0.05)
    cache.set("k", "v")
    assert cache.get("k") == "v"
    time.sleep(0.06)
    assert cache.get("k") is None
    assert len(cache) == 0


def test_cache_clear_by_prefix() -> None:
    cache: TTLCache[int] = TTLCache(maxsize=8, ttl=60)
    cache.set("1:sqlite:a", 1)
    cache.set("1:mysql:b", 2)
    cache.set("2:sqlite:c", 3)
    cache.clear("1:")
    assert cache.get("1:sqlite:a") is None
    assert cache.get("1:mysql:b") is None
    assert cache.get("2:sqlite:c") == 3


# ---------------- 语义层 ----------------


@pytest.fixture()
def semantics_file(tmp_path, monkeypatch):
    path = tmp_path / "semantics.yaml"
    path.write_text(
        "metrics:\n  gmv:\n    name: GMV\n    expr: SUM(orders.pay_amount)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "semantics_path", str(path))
    reset_semantics_cache()
    yield path
    reset_semantics_cache()


def test_semantics_path_is_respected(semantics_file) -> None:
    """回归：SQLAGENT_SEMANTICS_PATH 之前没有对应字段，配了等于没配。"""
    loaded = load_semantics()
    assert "gmv" in loaded.metrics
    assert loaded.metrics["gmv"]["name"] == "GMV"


def test_semantics_reload_after_edit(semantics_file) -> None:
    assert "gmv" in load_semantics().metrics

    semantics_file.write_text(
        "metrics:\n  gmv:\n    name: GMV\n  refund_rate:\n    name: 退款率\n", encoding="utf-8"
    )
    reloaded = load_semantics()
    assert "refund_rate" in reloaded.metrics


def test_semantics_is_cached_between_calls(semantics_file, monkeypatch) -> None:
    calls = {"n": 0}
    original = semantics_module._parse

    def counting(path):
        calls["n"] += 1
        return original(path)

    monkeypatch.setattr(semantics_module, "_parse", counting)

    load_semantics()
    load_semantics()
    assert calls["n"] == 1


def test_broken_yaml_is_loud(semantics_file, caplog) -> None:
    """写错缩进不能再静默：留一条 warning，口径为空但服务不崩。"""
    semantics_file.write_text("metrics:\n  gmv:\n   name: [unclosed\n", encoding="utf-8")

    with caplog.at_level("WARNING"):
        loaded = load_semantics()

    assert loaded.empty
    assert any("语义层解析失败" in record.message for record in caplog.records)


def test_missing_file_is_not_an_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "semantics_path", str(tmp_path / "nope.yaml"))
    reset_semantics_cache()
    assert load_semantics().empty