"""业务语义层：指标口径、同义词、示例问答。

把「GMV 怎么算」「季度怎么切」从 prompt 里挪到配置文件，是准确率能稳定提升的
唯一低成本手段；示例（few-shot）则是性价比最高的那一段。

读取按 (mtime, size) 缓存：改完文件立刻生效，又不会每个请求都重新解析。
解析失败会记 warning 而不是静默吞掉——口径没生效时，用户至少有个线索。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import settings

logger = logging.getLogger(__name__)


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


def _semantics_path() -> Path:
    """语义层文件位置。

    ``SQLAGENT_SEMANTICS_PATH`` 可以是绝对路径，也可以是相对 backend/ 的路径
    （相对路径不按进程 CWD 解析，否则从不同目录启动会读到不同的文件）。
    """
    configured = getattr(settings, "semantics_path", None)
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else settings.data_dir.parent / path
    return settings.data_dir / "semantics.yaml"


# (mtime, size) -> 解析结果；文件一改就失效
_cache: tuple[float, int, Semantics] | None = None


def load_semantics() -> Semantics:
    global _cache

    path = _semantics_path()
    try:
        stat = path.stat()
    except OSError:
        _cache = None
        return Semantics()

    if _cache is not None and _cache[0] == stat.st_mtime and _cache[1] == stat.st_size:
        return _cache[2]

    semantics = _parse(path)
    _cache = (stat.st_mtime, stat.st_size, semantics)
    return semantics


def reset_semantics_cache() -> None:
    """测试与运维用：强制下次重新读文件。"""
    global _cache
    _cache = None


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