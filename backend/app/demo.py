"""示例库：给每个工作空间自动发一个只读的演示数据源。

为什么放在应用里而不是只留在 ``scripts/``：应用启动时要自己造这个库、注册时要用它。
脚本只是同一段逻辑的 CLI 外壳。

设计要点：
- **一个文件，多行引用**：所有工作空间的 ``database`` 都指向同一个 ``data/demo/shop.db``，
  连接串带 ``mode=ro``，互不影响，也不占额外磁盘
- 用户删掉自己那份只是删了一行记录，文件还在（``uploads.remove_upload`` 只删受管目录里的文件）
- ``SQLAGENT_DEMO_DATASOURCE=false`` 可以整体关掉
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Datasource, Workspace, utcnow

DEFAULT_ORDERS = 20000
DEFAULT_SEED = 20261118
DEMO_NAME = "示例库（只读）"

SCHEMA = """
DROP TABLE IF EXISTS refunds;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    city       TEXT    NOT NULL,
    region     TEXT    NOT NULL,
    is_test    INTEGER NOT NULL DEFAULT 0,   -- 1 = 测试账号，统计时需排除
    created_at TEXT    NOT NULL
);

CREATE TABLE products (
    id       INTEGER PRIMARY KEY,
    title    TEXT    NOT NULL,
    category TEXT    NOT NULL,
    price    REAL    NOT NULL,
    cost     REAL    NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1     -- 0 = 已下架
);

CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    status      TEXT    NOT NULL,            -- paid | shipped | done | cancelled | refunded
    pay_amount  REAL    NOT NULL,            -- 未扣退款的支付金额
    created_at  TEXT    NOT NULL
);

CREATE TABLE order_items (
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL,
    unit_price REAL    NOT NULL
);

CREATE TABLE refunds (
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    amount     REAL    NOT NULL,
    reason     TEXT,
    created_at TEXT    NOT NULL
);

CREATE INDEX idx_orders_created ON orders(created_at);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_items_order ON order_items(order_id);
"""

CITIES = [
    ("上海", "华东"), ("杭州", "华东"), ("南京", "华东"), ("苏州", "华东"),
    ("北京", "华北"), ("天津", "华北"), ("石家庄", "华北"),
    ("广州", "华南"), ("深圳", "华南"), ("厦门", "华南"),
    ("成都", "西南"), ("重庆", "西南"), ("昆明", "西南"),
    ("武汉", "华中"), ("长沙", "华中"),
    ("西安", "西北"), ("沈阳", "东北"), ("哈尔滨", "东北"),
]

CATEGORIES = {
    "手机": (1499, 8999, 0.72),
    "电脑": (3299, 15999, 0.78),
    "家电": (899, 6999, 0.68),
    "服饰": (49, 899, 0.45),
    "美妆": (39, 1299, 0.52),
    "食品": (9, 199, 0.60),
}

SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
GIVEN = "伟芳娜秀英敏静丽强磊洋艳勇军杰娟涛明超秀霞平刚"


def _name(rng: random.Random) -> str:
    return rng.choice(SURNAMES) + "".join(rng.choice(GIVEN) for _ in range(rng.randint(1, 2)))


def build_demo_database(path: Path, orders: int = DEFAULT_ORDERS, seed: int = DEFAULT_SEED) -> None:
    """生成演示库（覆盖写）。刻意埋了几个语义陷阱，见模块注释。"""
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)

        start = date(2026, 1, 1)
        span = (date(2026, 11, 30) - start).days

        customers = []
        for cid in range(1, 2001):
            city, region = rng.choice(CITIES)
            created = datetime.combine(start + timedelta(days=rng.randint(0, span)), datetime.min.time())
            customers.append((cid, _name(rng), city, region, int(rng.random() < 0.05), created.isoformat()))
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)

        products = []
        pid = 1
        for category, (low, high, cost_ratio) in CATEGORIES.items():
            for _ in range(35):
                price = round(rng.uniform(low, high), 2)
                products.append(
                    (pid, f"{category}{rng.randint(100, 999)}", category, price,
                     round(price * cost_ratio, 2), int(rng.random() > 0.1))
                )
                pid += 1
        conn.executemany("INSERT INTO products VALUES (?,?,?,?,?,?)", products)

        order_rows, item_rows, refund_rows = [], [], []
        item_id = 1
        for oid in range(1, orders + 1):
            customer_id = rng.randint(1, 2000)
            created = datetime.combine(start + timedelta(days=rng.randint(0, span)), datetime.min.time())
            created = created + timedelta(hours=rng.randint(8, 23), minutes=rng.randint(0, 59))

            roll = rng.random()
            status = "cancelled" if roll < 0.08 else "refunded" if roll < 0.11 else rng.choice(
                ["paid", "shipped", "done", "done", "done"]
            )

            items = []
            amount = 0.0
            for _ in range(rng.randint(1, 4)):
                product = products[rng.randrange(len(products))]
                quantity = rng.randint(1, 3)
                unit_price = round(product[3] * rng.uniform(0.85, 1.0), 2)
                amount += unit_price * quantity
                items.append((item_id, oid, product[0], quantity, unit_price))
                item_id += 1

            pay_amount = round(amount, 2)
            order_rows.append((oid, customer_id, status, pay_amount, created.isoformat(sep=" ")))
            item_rows.extend(items)

            if status in {"refunded", "cancelled"}:
                refund_amount = pay_amount if status == "refunded" else round(pay_amount * 0.3, 2)
                refund_rows.append(
                    (len(refund_rows) + 1, oid, refund_amount, rng.choice(["不想要了", "质量问题", "发货超时"]),
                     (created + timedelta(days=rng.randint(1, 10))).isoformat(sep=" "))
                )

        conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", order_rows)
        conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", item_rows)
        conn.executemany("INSERT INTO refunds VALUES (?,?,?,?,?)", refund_rows)
        conn.commit()
    finally:
        conn.close()


def demo_db_path() -> Path:
    return settings.data_dir / "demo" / "shop.db"


def ensure_demo_file() -> Path | None:
    """确保示例库文件存在（没有就造）。关闭时返回 None。"""
    if not settings.demo_datasource:
        return None
    path = demo_db_path()
    if not path.exists():
        build_demo_database(path)
    return path


async def ensure_demo_datasource(session: AsyncSession, workspace_id: int) -> Datasource | None:
    """给某个工作空间发一份示例库（已有就复用）。"""
    path = ensure_demo_file()
    if path is None:
        return None

    existing = await session.scalar(
        select(Datasource).where(
            Datasource.workspace_id == workspace_id,
            Datasource.database == str(path),
        )
    )
    if existing is not None:
        return existing

    ds = Datasource(
        workspace_id=workspace_id,
        name=DEMO_NAME,
        type="sqlite",
        database=str(path),
        safety_level="L0",
        is_prod=False,
        last_check_ok=True,
        last_checked_at=utcnow(),
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)
    return ds


async def ensure_demo_for_all(session: AsyncSession) -> int:
    """启动时补齐：给还沒有示例库的工作空间各发一份。返回新建的数量。"""
    path = ensure_demo_file()
    if path is None:
        return 0

    workspace_ids = list(await session.scalars(select(Workspace.id)))
    have = set(
        await session.scalars(
            select(Datasource.workspace_id).where(Datasource.database == str(path))
        )
    )

    created = 0
    for workspace_id in workspace_ids:
        if workspace_id in have:
            continue
        session.add(
            Datasource(
                workspace_id=workspace_id,
                name=DEMO_NAME,
                type="sqlite",
                database=str(path),
                safety_level="L0",
                is_prod=False,
                last_check_ok=True,
                last_checked_at=utcnow(),
            )
        )
        created += 1
    if created:
        await session.commit()
    return created