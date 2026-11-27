"""上下文装配：把数据库结构压成模型看得懂的几段文本。

准确率的大头在这里，不在 prompt 措辞：
- 只给相关表（bm25 选表），不是把整个库倒给模型
- 列名后面跟中文注释、主键标记
- 每张表给 2~3 行采样，让模型知道值的真实形态（'paid' 还是 1）
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field

from app.cache import TTLCache
from app.config import settings
from app.engine.execute import run_select
from app.introspect import introspect
from app.models import Datasource

_WORD_RE = None


@dataclass
class TableContext:
    name: str
    row_count: int | None = None
    columns: list[dict] = field(default_factory=list)
    sample: list[list] = field(default_factory=list)


@dataclass
class SchemaContext:
    text: str
    tables: list[str] = field(default_factory=list)
    candidate_tables: list[str] = field(default_factory=list)

    def describe(self) -> str:
        return "、".join(self.tables)


# ---------------- 选表（BM25，纯标准库）----------------


def _tokenize(text: str) -> list[str]:
    """英文按词、中文按二元组，够用且不用分词库。"""
    lowered = text.lower()
    tokens: list[str] = []
    buffer = ""
    cjk_run = ""
    for char in lowered:
        if char.isascii() and (char.isalnum() or char == "_"):
            buffer += char
            if cjk_run:
                tokens.extend(_cjk_bigrams(cjk_run))
                cjk_run = ""
        elif "\u4e00" <= char <= "\u9fff":
            if buffer:
                tokens.append(buffer)
                buffer = ""
            cjk_run += char
        else:
            if buffer:
                tokens.append(buffer)
                buffer = ""
            if cjk_run:
                tokens.extend(_cjk_bigrams(cjk_run))
                cjk_run = ""
    if buffer:
        tokens.append(buffer)
    if cjk_run:
        tokens.extend(_cjk_bigrams(cjk_run))
    return [token for token in tokens if len(token) >= 2]


def _cjk_bigrams(run: str) -> list[str]:
    if len(run) == 1:
        return [run]
    return [run[i : i + 2] for i in range(len(run) - 1)]


def _document(table: TableContext) -> list[str]:
    pieces = [table.name, table.name.replace("_", " ")]
    for column in table.columns:
        pieces.append(str(column.get("name", "")))
        if column.get("comment"):
            pieces.append(str(column["comment"]))
    return _tokenize(" ".join(pieces))


def rank_tables(question: str, tables: list[TableContext], top_k: int) -> list[TableContext]:
    if len(tables) <= top_k:
        return tables

    docs = [_document(table) for table in tables]
    query = _tokenize(question)
    if not query:
        return tables[:top_k]

    total = len(docs)
    avg_len = sum(len(doc) for doc in docs) / max(total, 1)
    df: dict[str, int] = {}
    for doc in docs:
        for token in set(doc):
            df[token] = df.get(token, 0) + 1

    k1, b = 1.4, 0.75
    scored: list[tuple[float, TableContext]] = []
    for doc, table in zip(docs, tables, strict=False):
        length = len(doc) or 1
        score = 0.0
        for token in query:
            freq = doc.count(token)
            if not freq:
                continue
            idf = math.log(1 + (total - df.get(token, 0) + 0.5) / (df.get(token, 0) + 0.5))
            score += idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * length / avg_len))
        scored.append((score, table))

    scored.sort(key=lambda item: item[0], reverse=True)
    picked = [table for _, table in scored[:top_k]]
    # 同名的关联表（外键命名习惯 xxx_id）一并带上，join 才不会缺表
    picked_names = {table.name for table in picked}
    for table in tables:
        if table.name in picked_names:
            continue
        for column in table.columns:
            cname = str(column.get("name", "")).lower()
            for name in list(picked_names):
                if cname == f"{name.lower()}_id" or cname == f"{name.lower()}id":
                    picked.append(table)
                    picked_names.add(table.name)
                    break
            if table.name in picked_names:
                break
    return picked[: top_k + 2]


# ---------------- 缓存 ----------------


# 有上限的 TTL 缓存：数据源多了不会无限涨；换进程各存一份，靠 ttl 收敛
_CACHE: TTLCache[list[TableContext]] = TTLCache(
    maxsize=settings.schema_cache_max_entries, ttl=settings.schema_cache_ttl
)


def _cache_key(ds: Datasource) -> str:
    return f"{ds.id}:{ds.type}:{ds.database}:{ds.host}:{ds.port}"


async def _load_tables(ds: Datasource, password: str) -> list[TableContext]:
    key = _cache_key(ds)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    schema = await introspect(ds, password)
    tables = [
        TableContext(
            name=table.name,
            row_count=table.row_count_estimate,
            columns=[
                {
                    "name": column.name,
                    "type": column.data_type,
                    "nullable": column.nullable,
                    "primary_key": column.primary_key,
                    "comment": column.comment,
                }
                for column in table.columns
            ],
        )
        for table in schema.tables
    ]
    _CACHE.set(key, tables)
    return tables


def invalidate_cache(ds_id: int | None = None) -> None:
    if ds_id is None:
        _CACHE.clear()
        return
    _CACHE.clear(f"{ds_id}:")


# ---------------- 渲染 ----------------


def _short(value: object, limit: int = 40) -> str:
    text = repr(value)
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_table(table: TableContext) -> str:
    header = f"表 {table.name}"
    if table.row_count is not None:
        header += f"（约 {table.row_count:,} 行）"
    lines = [header]
    for column in table.columns:
        flags = []
        if column.get("primary_key"):
            flags.append("PK")
        if column.get("nullable") is False:
            flags.append("NOT NULL")
        if column.get("comment"):
            flags.append(str(column["comment"]))
        suffix = f"   {' · '.join(flags)}" if flags else ""
        lines.append(f"  {column['name']} {column['type']}{suffix}")
    if table.sample:
        sample = ", ".join(f"({', '.join(_short(cell) for cell in row)})" for row in table.sample)
        lines.append(f"  采样: {sample}")
    return "\n".join(lines)


async def build_context(
    ds: Datasource,
    password: str,
    question: str,
    *,
    semantics_text: str = "",
) -> SchemaContext:
    tables = await _load_tables(ds, password)
    picked = rank_tables(question, tables, settings.schema_max_tables)

    async def sample(table: TableContext) -> None:
        """采样失败不影响主流程：模型看不到真实值形态，但至少还能生成 SQL。"""
        if table.sample:
            return
        try:
            result = await run_select(
                ds,
                password,
                f'SELECT * FROM "{table.name}"',
                max_rows=settings.schema_sample_rows,
                timeout=settings.query_timeout,
            )
            table.sample = result.rows
        except Exception:  # noqa: BLE001
            table.sample = []

    # 并发采样：最多 8 次查询，串行时最坏要 8×timeout
    await asyncio.gather(*(sample(table) for table in picked[: settings.schema_max_tables]))

    body = "\n\n".join(render_table(table) for table in picked)
    parts = [f"## 可用的表（共 {len(picked)} 张，已按问题相关性筛选）", body]
    if semantics_text:
        parts.append(semantics_text)
    return SchemaContext(
        text="\n\n".join(parts),
        tables=[table.name for table in picked],
        candidate_tables=[table.name for table in tables],
    )