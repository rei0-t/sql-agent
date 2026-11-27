"""业务语义层：指标口径、同义词、示例问答。

把「GMV 怎么算」「季度怎么切」从 prompt 里挪到配置文件，是准确率能稳定提升的
唯一低成本手段；示例（few-shot）则是性价比最高的那一段。

**按工作空间隔离**（多租户的前提）：
1. ``data/semantics.d/{workspace_id}.yaml`` —— 该空间专属
2. ``SQLAGENT_SEMANTICS_PATH`` 或 ``data/semantics.yaml`` —— 全部署共享的兜底

规则：专属文件存在就用它（写坏了也不会悄悄退回全局，避免"到底哪份生效"说不清）；
不存在才用全局。工作空间编号来自数据库里的数据源记录，不接受请求参数，所以不存在路径穿越。

读取按 (mtime, size) 缓存：改完文件立刻生效，又不会每个请求都重新解析。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import settings

logger = logging.getLogger(__name__)

# 缓存上限：工作空间再多也不会无限占内存
_MAX_CACHED_FILES = 256


@dataclass
class Semantics:
    metrics: dict[str, dict] = field(default_factory=dict)
    synonyms: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    examples: list[dict] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.metrics or self.synonyms or self.notes or self.examples)

    def render(self) -> str:
        if self.empty:
            return ""
        parts: list[str] = ["## 业务口径"]

        if self.metrics:
            parts.append("指标定义（必须使用这里的算式与过滤条件）：")
            for key, item in self.metrics.items():
                name = item.get("name") or key
                expr = item.get("expr") or ""
                filters = item.get("filters") or []
                parts.append(f"- {name}（{key}）= {expr}")
                for flt in filters:
                    parts.append(f"    必须附加：{flt}")
                if item.get("note"):
                    parts.append(f"    说明：{item['note']}")

        if self.synonyms:
            parts.append("术语与同义词（问题里出现这些词时按右边的条件处理）：")
            for key, value in self.synonyms.items():
                parts.append(f"- {key} → {value}")

        if self.notes:
            parts.append("其它约定：")
            parts.extend(f"- {note}" for note in self.notes)

        if self.examples:
            parts.append("参考示例（同库、同口径的真实写法）：")
            for example in self.examples[:4]:
                question = str(example.get("question") or "").strip()
                sql = str(example.get("sql") or "").strip()
                if question and sql:
                    parts.append(f"问题：{question}")
                    parts.append(f"SQL：{sql}")

        return "\n".join(parts)


# ---------------- 路径解析 ----------------


def workspace_semantics_dir() -> Path:
    """每个工作空间一份的目录：data/semantics.d/"""
    return settings.data_dir / "semantics.d"


def workspace_semantics_path(workspace_id: int) -> Path:
    return workspace_semantics_dir() / f"{int(workspace_id)}.yaml"


def _shared_semantics_path() -> Path:
    """全部署共享的语义层。

    ``SQLAGENT_SEMANTICS_PATH`` 可以是绝对路径，也可以是相对 backend/ 的路径
    （相对路径不按进程 CWD 解析，否则从不同目录启动会读到不同的文件）。
    """
    configured = getattr(settings, "semantics_path", None)
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else settings.data_dir.parent / path
    return settings.data_dir / "semantics.yaml"


# ---------------- 读取与缓存 ----------------


# path -> (mtime, size, Semantics)
_cache: dict[str, tuple[float, int, Semantics]] = {}


def load_semantics(workspace_id: int | None = None) -> Semantics:
    """取当前工作空间生效的语义层。

    专属文件缺失时回退到共享文件；专属文件存在但解析失败时返回空语义（并告警），
    不做静默回退——否则运维会以为改的是这份，实际生效的是另一份。
    """
    if workspace_id is not None:
        own = workspace_semantics_path(workspace_id)
        loaded = _load_file(own)
        if loaded is not None:
            return loaded

    shared = _shared_semantics_path()
    loaded = _load_file(shared)
    return loaded if loaded is not None else Semantics()


def reset_semantics_cache() -> None:
    """测试与运维用：强制下次重新读文件。"""
    _cache.clear()


def _load_file(path: Path) -> Semantics | None:
    """读一个文件；不存在返回 None（用于判断是否要回退）。"""
    try:
        stat = path.stat()
    except OSError:
        _cache.pop(str(path), None)
        return None

    key = str(path)
    cached = _cache.get(key)
    if cached is not None and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return cached[2]

    semantics = _parse(path)
    if len(_cache) >= _MAX_CACHED_FILES and key not in _cache:
        _cache.pop(next(iter(_cache)), None)  # 简单 FIFO，够用
    _cache[key] = (stat.st_mtime, stat.st_size, semantics)
    return semantics


def _parse(path: Path) -> Semantics:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        # 静默失败最坑：口径全丢，但界面上看起来一切正常，只是数字算错了
        logger.warning("语义层解析失败，本次按空语义处理（%s）：%s", path, exc)
        return Semantics()
    if not isinstance(raw, dict):
        logger.warning("语义层格式不对（顶层应为 mapping）：%s", path)
        return Semantics()

    metrics = raw.get("metrics") or {}
    synonyms = raw.get("synonyms") or {}
    notes = raw.get("notes") or []
    examples = raw.get("examples") or []
    return Semantics(
        metrics={str(k): (v or {}) for k, v in metrics.items()},
        synonyms={str(k): str(v) for k, v in synonyms.items()},
        notes=[str(note) for note in notes],
        examples=[e for e in examples if isinstance(e, dict)],
    )