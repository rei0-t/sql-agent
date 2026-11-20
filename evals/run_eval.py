"""读评测：在演示库上跑一遍 golden 集，算执行准确率（EX）。

用法（在 backend 目录下）：

    python ../evals/run_eval.py
    python ../evals/run_eval.py --limit 5 --tag time
    python ../evals/run_eval.py --save

比较方式是「比结果集，不比 SQL 文本」：列数、行数、行内容（数值容差 1e-6）。
排序不影响结果，聚合别名不影响结果——用户只关心数字对不对。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.engine.execute import run_select  # noqa: E402
from app.engine.llm import get_default_model  # noqa: E402
from app.engine.pipeline import answer_question  # noqa: E402
from app.models import Datasource  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "demo" / "shop.db"


@dataclass
class CaseResult:
    id: str
    question: str
    tags: list[str] = field(default_factory=list)
    ok: bool = False
    reason: str = ""
    attempts: int = 0
    sql: str = ""
    elapsed_ms: int = 0
    tokens: int = 0
    gold_rows: int = 0
    got_rows: int = 0


def _normalize_cell(value):
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return None if value is None else str(value).strip()


def _rows_equal(left: list[list], right: list[list]) -> bool:
    if len(left) != len(right):
        return False
    if not left:
        return True

    def sort_key(row):
        return tuple("" if cell is None else str(cell) for cell in row)

    try:
        left_sorted = sorted(left, key=sort_key)
        right_sorted = sorted(right, key=sort_key)
    except TypeError:
        left_sorted, right_sorted = left, right

    for row_a, row_b in zip(left_sorted, right_sorted, strict=False):
        if len(row_a) != len(row_b):
            return False
        for a, b in zip(row_a, row_b, strict=False):
            na, nb = _normalize_cell(a), _normalize_cell(b)
            if na is None and nb is None:
                continue
            if isinstance(na, float) and isinstance(nb, float):
                if abs(na - nb) > 1e-6 * max(1.0, abs(na), abs(nb)):
                    return False
            elif na != nb:
                return False
    return True


async def ensure_datasource() -> Datasource:
    if not DB_PATH.exists():
        raise SystemExit(f"演示库不存在：{DB_PATH}\n先运行 python scripts/seed_demo.py")
    async with SessionLocal() as session:
        ds = await session.scalar(select(Datasource).where(Datasource.name == "eval:shop"))
        if ds is None:
            ds = Datasource(
                workspace_id=1,
                name="eval:shop",
                type="sqlite",
                database=str(DB_PATH),
                safety_level="L0",
                is_prod=False,
                username="",
                password_enc="",
            )
            session.add(ds)
            await session.commit()
            await session.refresh(ds)
        return ds


async def run_case(case: dict, ds: Datasource, model) -> CaseResult:
    result = CaseResult(
        id=case["id"], question=case["question"], tags=case.get("tags", [])
    )

    gold = await run_select(ds, "", case["gold"], max_rows=500, timeout=settings.query_timeout)
    result.gold_rows = len(gold.rows)

    started = time.perf_counter()
    answer = await answer_question(ds, "", case["question"], model)
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    result.attempts = answer.attempts
    result.tokens = answer.usage.total
    result.sql = answer.sql or ""

    if answer.clarification:
        result.reason = f"反问：{answer.clarification[:60]}"
        return result
    if answer.error:
        result.reason = f"错误：{answer.error[:80]}"
        return result

    candidate = await run_select(
        ds, "", answer.sql or "", max_rows=settings.read_max_rows, timeout=settings.query_timeout
    )
    result.got_rows = len(candidate.rows)

    if answer.truncated:
        result.reason = f"结果被截断（{settings.read_max_rows} 行上限）"
        return result
    if len(candidate.columns) != len(gold.columns):
        result.reason = f"列数不同：{len(candidate.columns)} vs {len(gold.columns)}"
        return result
    if not _rows_equal(gold.rows, candidate.rows):
        result.reason = f"结果不同：{len(candidate.rows)} 行 vs 标准 {len(gold.rows)} 行"
        return result

    result.ok = True
    return result


def load_cases(limit: int | None, tag: str | None) -> list[dict]:
    cases = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    if tag:
        cases = [case for case in cases if tag in case.get("tags", [])]
    if limit:
        cases = cases[:limit]
    return cases


async def main() -> None:
    parser = argparse.ArgumentParser(description="只读问答评测")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--tag", type=str, default=None)
    parser.add_argument("--save", action="store_true", help="把结果写入 evals/results/")
    args = parser.parse_args()

    await init_db()
    ds = await ensure_datasource()
    cases = load_cases(args.limit, args.tag)
    model = get_default_model()

    print(f"模型 {model.name} · {len(cases)} 题 · 库 {DB_PATH.name}\n")
    results: list[CaseResult] = []
    for index, case in enumerate(cases, start=1):
        result = await run_case(case, ds, model)
        results.append(result)
        flag = "PASS" if result.ok else "FAIL"
        print(
            f"[{index:02d}/{len(cases)}] {flag} {result.id} {result.elapsed_ms/1000:5.1f}s "
            f"attempts={result.attempts} {case['question']}"
        )
        if not result.ok:
            print(f"       ↳ {result.reason}")
            if result.sql:
                print(f"       ↳ SQL {result.sql[:180]}")

    passed = sum(1 for item in results if item.ok)
    ex = passed / max(len(results), 1)
    elapsed = [item.elapsed_ms for item in results]
    tokens = sum(item.tokens for item in results)
    print("\n" + "=" * 64)
    print(f"EX（执行准确率）: {ex:.1%}  ({passed}/{len(results)})")
    print(f"平均尝试次数    : {sum(item.attempts for item in results)/max(len(results),1):.2f}")
    print(f"平均耗时        : {sum(elapsed)/max(len(elapsed),1)/1000:.1f}s   最长 {max(elapsed)/1000:.1f}s")
    print(f"总 token        : {tokens}")
    print("=" * 64)

    if args.save:
        RESULTS.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = RESULTS / f"{stamp}.json"
        out.write_text(
            json.dumps(
                {
                    "model": model.name,
                    "cases": len(results),
                    "ex": ex,
                    "tokens": tokens,
                    "results": [asdict(item) for item in results],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"结果已写入 {out}")


if __name__ == "__main__":
    asyncio.run(main())