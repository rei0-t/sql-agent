"""生成演示用的中文电商 SQLite 库。

刻意埋了几个"坑"，用来验证语义层与指标口径是否真的生效：

- 约 5% 的客户是测试账号（``customers.is_test = 1``），算 GMV 时必须排除；
- 约 8% 的订单是取消/退款状态，不能计入成交额；
- 退款单独一张表，``orders.pay_amount`` 未扣退款。

用法::

    python scripts/seed_demo.py                    # 默认写到 data/demo/shop.db
    python scripts/seed_demo.py --orders 50000     # 造更大的库压测
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

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
    "家电": (199, 5999, 0.65),
    "服饰": (49, 899, 0.45),
    "美妆": (39, 1299, 0.52),
    "食品": (9, 199, 0.60),
}

SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
GIVEN = "伟芳娜秀英敏静丽强磊洋艳勇军杰娟涛明超秀霞平刚"


def _name(rng: random.Random) -> str:
    return rng.choice(SURNAMES) + "".join(rng.choice(GIVEN) for _ in range(rng.randint(1, 2)))


def build(path: Path, orders: int, seed: int) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="生成演示用中文电商 SQLite 库")
    parser.add_argument("--out", default="data/demo/shop.db", help="输出路径")
    parser.add_argument("--orders", type=int, default=20000, help="订单数量")
    parser.add_argument("--seed", type=int, default=20261118, help="随机种子（可复现）")
    args = parser.parse_args()

    out = Path(args.out)
    build(out, args.orders, args.seed)
    size_kb = out.stat().st_size / 1024
    print(f"已生成 {out}  ({size_kb:.0f} KB, {args.orders} 笔订单)")


if __name__ == "__main__":
    main()