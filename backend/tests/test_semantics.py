"""语义层按工作空间隔离。

优先级：data/semantics.d/{workspace_id}.yaml > 全局文件。
专属文件写坏时不回退（否则"哪份生效"说不清），直接按空语义处理并告警。
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.engine import semantics as semantics_module
from app.engine.semantics import (
    load_semantics,
    reset_semantics_cache,
    workspace_semantics_path,
)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "semantics_path", None)
    reset_semantics_cache()
    yield tmp_path
    reset_semantics_cache()


def _write_shared(root, body: str) -> None:
    (root / "semantics.yaml").write_text(body, encoding="utf-8")


def _write_workspace(root, workspace_id: int, body: str) -> None:
    path = workspace_semantics_path(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


GMV = "metrics:\n  gmv:\n    name: GMV\n    expr: SUM(pay_amount)\n"
REFUND = "metrics:\n  refund_rate:\n    name: 退款率\n    expr: SUM(refund)/SUM(pay)\n"


def test_workspace_file_wins_over_shared(data_dir) -> None:
    _write_shared(data_dir, GMV)
    _write_workspace(data_dir, 1, REFUND)

    own = load_semantics(1)
    assert "refund_rate" in own.metrics
    assert "gmv" not in own.metrics, "专属文件应当是独占的，不和全局叠加"


def test_missing_workspace_falls_back_to_shared(data_dir) -> None:
    _write_shared(data_dir, GMV)
    shared = load_semantics(2)
    assert "gmv" in shared.metrics


def test_workspaces_are_isolated(data_dir) -> None:
    _write_workspace(data_dir, 1, GMV)
    _write_workspace(data_dir, 2, REFUND)

    assert "gmv" in load_semantics(1).metrics
    assert "gmv" not in load_semantics(2).metrics
    assert "refund_rate" in load_semantics(2).metrics
    assert "refund_rate" not in load_semantics(1).metrics


def test_no_files_anywhere_is_empty(data_dir) -> None:
    assert load_semantics(3).empty
    assert load_semantics().empty


def test_broken_workspace_file_does_not_fall_back(data_dir, caplog) -> None:
    """写坏了就是写坏了：不能悄悄用全局文件顶上，否则改了半天不知道为什么没生效。"""
    _write_shared(data_dir, GMV)
    _write_workspace(data_dir, 4, "metrics:\n  gmv:\n   name: [unclosed\n")

    with caplog.at_level("WARNING"):
        loaded = load_semantics(4)

    assert loaded.empty
    assert any("语义层解析失败" in record.message for record in caplog.records)


def test_cache_is_per_file(data_dir, monkeypatch) -> None:
    _write_shared(data_dir, GMV)
    _write_workspace(data_dir, 1, REFUND)

    calls: list[str] = []
    original = semantics_module._parse

    def counting(path):
        calls.append(path.name)
        return original(path)

    monkeypatch.setattr(semantics_module, "_parse", counting)

    load_semantics(1)
    load_semantics(1)
    load_semantics(2)  # 走全局文件

    assert calls == ["1.yaml", "semantics.yaml"], "同一个文件只解析一次，不同文件各一次"


def test_edit_takes_effect_immediately(data_dir) -> None:
    _write_workspace(data_dir, 1, GMV)
    assert "gmv" in load_semantics(1).metrics

    _write_workspace(data_dir, 1, REFUND)
    assert "refund_rate" in load_semantics(1).metrics