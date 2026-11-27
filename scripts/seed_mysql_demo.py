"""建一个 MySQL 演示库 + 只读账号，用于验证 MySQL 方言的完整链路。

会 **DROP 并重建** `sqlagent_demo` 库（只动这个名字），不碰已有数据。
需要管理员账号建库和授权。

用法：
    python scripts/seed_mysql_demo.py --user root --password root
    python scripts/seed_mysql_demo.py --user root --password root --host 127.0.0.1

跑完会打印标准答案，可以直接拿去和 SQL-agent 的回答对比：
    2026 Q3 华东区 GMV / 退款率 / 品类 GMV Top3
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta
from decimal import Decimal

import pymysql

DB = "sqlagent_demo"
RO_USER = "sqlagent_ro"
RO_PASSWORD = "sqlagent_ro_2026"

REGIONS = ["华东", "华北", "华南", "西南", "华中"]
CITIES = {
    "华东": ["上海", "杭州", "南京", "苏州"],
    "华北": ["北京", "天津", "石家庄"],
    "华南": ["广州", "深圳", "厦门"],
    "西南": ["成都", "重庆", "昆明"],
    "华中": ["武汉", "长沙", "郑州"],
}
CATEGORIES = ["手机", "电脑", "家电", "服饰", "食品"]


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 MySQL 演示库")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    parser.add_argument("--customers", type=int, default=500)
    parser.add_argument("--orders", type=int, default=8000)
    args = parser.parse_args()

    rng = random.Random(20261127)
    conn = pymysql.connect(
        host=args.host, port=args.port, user=args.user, password=args.password, charset="utf8mb4"
    )
    conn.autocommit(True)
    cur = conn.cursor()

    cur.execute(f"DROP DATABASE IF EXISTS {DB}")
    cur.execute(f"CREATE DATABASE {DB} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cur.execute(f"USE {DB}")

    cur.execute(
        """
        CREATE TABLE customers (
            id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(64) NOT NULL,
            city VARCHAR(32) NOT NULL,
            region VARCHAR(16) NOT NULL,
            is_test TINYINT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cur.execute(
        """
        CREATE TABLE orders (
            id INT PRIMARY KEY AUTO_INCREMENT,
            customer_id INT NOT NULL,
            status VARCHAR(16) NOT NULL,
            pay_amount DECIMAL(12,2) NOT NULL,
            created_at DATETIME NOT NULL,
            KEY idx_created (created_at),
            CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cur.execute(
        """
        CREATE TABLE products (
            id INT PRIMARY KEY AUTO_INCREMENT,
            title VARCHAR(64) NOT NULL,
            category VARCHAR(16) NOT NULL,
            price DECIMAL(10,2) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cur.execute(
        """
        CREATE TABLE order_items (
            id INT PRIMARY KEY AUTO_INCREMENT,
            order_id INT NOT NULL,
            product_id INT NOT NULL,
            quantity INT NOT NULL,
            unit_price DECIMAL(10,2) NOT NULL,
            KEY idx_order (order_id),
            CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES orders(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )
    cur.execute(
        """
        CREATE TABLE refunds (
            id INT PRIMARY KEY AUTO_INCREMENT,
            order_id INT NOT NULL,
            amount DECIMAL(12,2) NOT NULL,
            created_at DATETIME NOT NULL,
            KEY idx_refund_order (order_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    base = datetime(2026, 1, 1)
    customers = []
    for i in range(1, args.customers + 1):
        region = rng.choice(REGIONS)
        customers.append(
            (
                f"客户{i:04d}",
                rng.choice(CITIES[region]),
                region,
                1 if rng.random() < 0.05 else 0,
                base + timedelta(days=rng.randint(0, 300)),
            )
        )
    cur.executemany(
        "INSERT INTO customers (name, city, region, is_test, created_at) VALUES (%s,%s,%s,%s,%s)",
        customers,
    )

    products = []
    for i in range(1, 121):
        category = rng.choice(CATEGORIES)
        products.append((f"{category}商品{i:03d}", category, Decimal(rng.randint(50, 9000)) + Decimal("0.99")))
    cur.executemany("INSERT INTO products (title, category, price) VALUES (%s,%s,%s)", products)

    orders, refunds = [], []
    for i in range(1, args.orders + 1):
        customer_id = rng.randint(1, args.customers)
        if rng.random() < 0.08:
            status = "cancelled" if rng.random() < 0.5 else "refunded"
        else:
            status = rng.choice(["paid", "shipped", "done"])
        created = base + timedelta(
            days=rng.randint(0, 364), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        amount = Decimal(rng.randint(100, 60000)) + Decimal("0.50")
        orders.append((customer_id, status, amount, created))
        if status == "refunded":
            refunds.append((i, amount, created + timedelta(days=rng.randint(1, 10))))
    cur.executemany(
        "INSERT INTO orders (customer_id, status, pay_amount, created_at) VALUES (%s,%s,%s,%s)",
        orders,
    )
    if refunds:
        cur.executemany("INSERT INTO refunds (order_id, amount, created_at) VALUES (%s,%s,%s)", refunds)

    items = []
    for order_id in range(1, args.orders + 1):
        for _ in range(rng.randint(1, 3)):
            product_id = rng.randint(1, 120)
            items.append((order_id, product_id, rng.randint(1, 4), products[product_id - 1][2]))
    cur.executemany(
        "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (%s,%s,%s,%s)",
        items,
    )

    # 只读账号：只有 SELECT，写操作会被 MySQL 直接拒绝
    for host in ("127.0.0.1", "localhost"):
        cur.execute(f"DROP USER IF EXISTS '{RO_USER}'@'{host}'")
        cur.execute(f"CREATE USER '{RO_USER}'@'{host}' IDENTIFIED BY '{RO_PASSWORD}'")
        cur.execute(f"GRANT SELECT ON {DB}.* TO '{RO_USER}'@'{host}'")
    cur.execute("FLUSH PRIVILEGES")

    cur.execute(
        """
        SELECT ROUND(SUM(o.pay_amount), 2)
        FROM orders o JOIN customers c ON c.id = o.customer_id
        WHERE o.status IN ('paid','shipped','done') AND c.is_test = 0 AND c.region = '华东'
          AND o.created_at >= '2026-07-01' AND o.created_at < '2026-10-01'
        """
    )
    gmv = cur.fetchone()[0]

    cur.execute(
        """
        SELECT p.category, ROUND(SUM(i.quantity * i.unit_price), 2) AS gmv
        FROM order_items i
        JOIN products p ON p.id = i.product_id
        JOIN orders o ON o.id = i.order_id
        JOIN customers c ON c.id = o.customer_id
        WHERE o.status IN ('paid','shipped','done') AND c.is_test = 0
        GROUP BY p.category ORDER BY gmv DESC LIMIT 3
        """
    )
    top = cur.fetchall()

    print(f"库 {DB} 就绪。只读账号 {RO_USER} / {RO_PASSWORD}")
    print("--- 标准答案（拿去和 SQL-agent 对比）---")
    print(f"2026 Q3 华东区 GMV = {gmv}")
    print("品类 GMV Top3 =", [(c, str(v)) for c, v in top])
    print()
    print("在「数据源」页新建：MySQL / 127.0.0.1 / 3306 /", DB, "/", RO_USER)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()