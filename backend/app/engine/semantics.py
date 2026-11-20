"""业务语义层：指标口径、同义词、示例问答。

把「GMV 怎么算」「季度怎么切」从 prompt 里挪到配置文件，是准确率能稳定提升的
唯一低成本手段；示例（few-shot）则是性价比最高的那一段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import settings


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
    configured = getattr(settings, "semantics_path", None)
    if configured:
        return Path(configured)
    return settings.data_dir / "semantics.yaml"


def load_semantics() -> Semantics:
    path = _semantics_path()
    if not path.exists():
        return Semantics()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
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