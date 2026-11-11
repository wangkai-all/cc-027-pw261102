"""回放输入数据（同一份数据供两种策略各自独立运行）。

- 3 家门店：优先级 + 各自配送天数
- 4 种商品：不同保质期/整箱规格/成本，覆盖长保与短保品
- 14 天逐日需求（工作日/周末规律 + 两天促销尖峰）
- 门店与中央仓初始批次（批次带有效期与单位成本）
- 中央仓到货计划
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from .database import get_conn, init_db

START_DATE = date(2026, 11, 2)       # 周一
HORIZON_DAYS = 14
DATES = [(START_DATE + timedelta(days=i)).isoformat() for i in range(HORIZON_DAYS)]

PRODUCTS = [
    # product_id, 名称, 单位, 整箱, 单位成本, 保质期天数
    ("P1", "鲜牛奶",   "盒", 12, 4.5, 6),
    ("P2", "常温酸奶", "瓶", 24, 6.0, 21),
    ("P3", "短保三明治", "个", 8, 9.0, 3),
    ("P4", "瓶装水",   "瓶", 24, 2.0, 60),
]

STORES = [
    # store_id, 名称, 优先级(小者优先), 默认配送天数
    ("S1", "中山路店",   1, 1),
    ("S2", "人民广场店", 2, 2),
    ("S3", "滨江店",     3, 3),
]

# (store, product): 补货点, 目标量
POLICIES = {
    ("S1", "P1"): (18, 36),  ("S2", "P1"): (24, 48), ("S3", "P1"): (12, 24),
    ("S1", "P2"): (30, 72),  ("S2", "P2"): (36, 84), ("S3", "P2"): (24, 48),
    ("S1", "P3"): (10, 24),  ("S2", "P3"): (14, 32), ("S3", "P3"): (8, 16),
    ("S1", "P4"): (36, 96),  ("S2", "P4"): (48, 120), ("S3", "P4"): (24, 72),
}

# 中央仓初始批次（batch_id, 商品, 数量, 有效期, 单位成本）
CENTRAL_INITIAL = [
    ("CB-P1-A", "P1", 300, "2026-11-07", 4.4),
    ("CB-P1-B", "P1", 300, "2026-11-14", 4.5),
    ("CB-P2-A", "P2", 400, "2026-11-20", 6.0),
    ("CB-P3-A", "P3", 120, "2026-11-05", 8.8),
    ("CB-P3-B", "P3", 150, "2026-11-10", 9.0),
    ("CB-P4-A", "P4", 300, "2027-01-01", 2.0),
]

# 中央仓到货（到货日, 商品, 数量, 有效期, 单位成本）
CENTRAL_ARRIVALS = [
    ("CA-P1-01", "2026-11-05", "P1", 300, "2026-11-20", 4.6),
    ("CA-P2-01", "2026-11-06", "P2", 300, "2026-11-26", 6.1),
    ("CA-P3-01", "2026-11-04", "P3", 150, "2026-11-08", 8.9),
    ("CA-P3-02", "2026-11-09", "P3", 200, "2026-11-13", 9.1),
    ("CA-P4-01", "2026-11-05", "P4", 360, "2027-01-08", 2.0),
    ("CA-P4-02", "2026-11-10", "P4", 360, "2027-01-12", 2.0),
    ("CA-P3-03", "2026-11-12", "P3", 150, "2026-11-16", 9.1),
]

# 门店初始批次（batch_id, 门店, 商品, 数量, 有效期, 单位成本）
STORE_INITIAL = [
    # S1
    ("IB-S1-P1-A", "S1", "P1", 20, "2026-11-04", 4.4),
    ("IB-S1-P1-B", "S1", "P1", 16, "2026-11-10", 4.5),
    ("IB-S1-P2-A", "S1", "P2", 36, "2026-11-18", 6.0),
    ("IB-S1-P2-B", "S1", "P2", 24, "2026-11-22", 6.0),
    ("IB-S1-P3-A", "S1", "P3", 8,  "2026-11-04", 8.8),
    ("IB-S1-P3-B", "S1", "P3", 8,  "2026-11-06", 9.0),
    ("IB-S1-P4-A", "S1", "P4", 48, "2027-01-01", 2.0),
    # S2
    ("IB-S2-P1-A", "S2", "P1", 24, "2026-11-05", 4.4),
    ("IB-S2-P1-B", "S2", "P1", 20, "2026-11-12", 4.5),
    ("IB-S2-P2-A", "S2", "P2", 30, "2026-11-19", 6.0),
    ("IB-S2-P2-B", "S2", "P2", 30, "2026-11-23", 6.0),
    ("IB-S2-P3-A", "S2", "P3", 10, "2026-11-03", 8.8),
    ("IB-S2-P3-B", "S2", "P3", 10, "2026-11-07", 9.0),
    ("IB-S2-P4-A", "S2", "P4", 60, "2027-01-01", 2.0),
    # S3
    ("IB-S3-P1-A", "S3", "P1", 12, "2026-11-06", 4.4),
    ("IB-S3-P1-B", "S3", "P1", 8,  "2026-11-13", 4.5),
    ("IB-S3-P2-A", "S3", "P2", 24, "2026-11-21", 6.0),
    ("IB-S3-P3-A", "S3", "P3", 6,  "2026-11-05", 8.8),
    ("IB-S3-P3-B", "S3", "P3", 6,  "2026-11-08", 9.0),
    ("IB-S3-P4-A", "S3", "P4", 36, "2027-01-01", 2.0),
]

# 基础日需求（常规工作日）
BASE_DEMAND = {
    ("S1", "P1"): 10, ("S2", "P1"): 14, ("S3", "P1"): 7,
    ("S1", "P2"): 16, ("S2", "P2"): 20, ("S3", "P2"): 10,
    ("S1", "P3"): 7,  ("S2", "P3"): 10, ("S3", "P3"): 5,
    ("S1", "P4"): 20, ("S2", "P4"): 26, ("S3", "P4"): 12,
}

# 星期因子：周一..周日
WEEKDAY_FACTOR = {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0, 4: 1.2, 5: 1.5, 6: 1.3}

# 促销/异常尖峰覆盖：(日期, 门店, 商品) -> 需求量
DEMAND_OVERRIDES = {
    ("2026-11-05", "S1", "P3"): 18,   # 周四短保促销，库存跟不上
    ("2026-11-07", "S2", "P1"): 34,   # 周六鲜奶抢购
    ("2026-11-14", "S1", "P4"): 45,   # 次周六用水高峰，中央仓受限
}


def build_demand_rows() -> list[tuple[str, str, str, int]]:
    rows = []
    for i, iso in enumerate(DATES):
        d = date.fromisoformat(iso)
        factor = WEEKDAY_FACTOR[d.weekday()]
        for (store_id, product_id), base in BASE_DEMAND.items():
            override = DEMAND_OVERRIDES.get((iso, store_id, product_id))
            qty = override if override is not None else round(base * factor)
            rows.append((iso, store_id, product_id, qty))
    return rows


def seed(conn: sqlite3.Connection) -> None:
    init_db(conn)
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO products VALUES (?,?,?,?,?,?)", PRODUCTS
    )
    cur.executemany(
        "INSERT OR REPLACE INTO stores VALUES (?,?,?,?)", STORES
    )
    cur.executemany(
        "INSERT OR REPLACE INTO policies VALUES (?,?,?,?,?)",
        [(s, p, rop, tgt, None) for (s, p), (rop, tgt) in POLICIES.items()],
    )
    cur.executemany(
        "INSERT OR REPLACE INTO initial_batches VALUES (?,?,?,?,?,?)",
        [(bid, "central", pid, qty, exp, cost)
         for bid, pid, qty, exp, cost in CENTRAL_INITIAL]
        + [(bid, sid, pid, qty, exp, cost)
           for bid, sid, pid, qty, exp, cost in STORE_INITIAL],
    )
    cur.executemany(
        "INSERT OR REPLACE INTO central_arrivals VALUES (?,?,?,?,?,?)",
        CENTRAL_ARRIVALS,
    )
    cur.execute("DELETE FROM demand")
    cur.executemany(
        "INSERT OR REPLACE INTO demand VALUES (?,?,?,?)", build_demand_rows()
    )
    conn.commit()


if __name__ == "__main__":
    conn = get_conn()
    seed(conn)
    print(f"seeded {len(PRODUCTS)} products, {len(STORES)} stores, "
          f"{HORIZON_DAYS} days -> {conn.execute('SELECT COUNT(*) FROM demand').fetchone()[0]} demand rows")
