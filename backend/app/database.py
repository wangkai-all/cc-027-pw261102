"""SQLite 连接与表结构。

配置类表（商品、门店、策略参数、初始批次、中央仓到货、需求）与
回放运行类表（runs/snapshots/orders/events/reconciliation 等）分离，
每次重新回放只清空运行类表，输入数据保持不变。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "replay.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    product_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    unit            TEXT NOT NULL,
    case_size       INTEGER NOT NULL,      -- 整箱数量（订货按此向上取整）
    unit_cost       REAL NOT NULL,         -- 单位成本
    shelf_life_days INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stores (
    store_id           TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    priority           INTEGER NOT NULL,   -- 数字越小优先级越高
    default_lead_days  INTEGER NOT NULL    -- 默认配送天数
);

CREATE TABLE IF NOT EXISTS policies (
    store_id       TEXT NOT NULL,
    product_id     TEXT NOT NULL,
    reorder_point  INTEGER NOT NULL,       -- 补货点
    target_qty     INTEGER NOT NULL,       -- 目标量
    lead_days      INTEGER,                -- 该商品配送天数，NULL 用门店默认
    PRIMARY KEY (store_id, product_id)
);

CREATE TABLE IF NOT EXISTS initial_batches (
    batch_id     TEXT PRIMARY KEY,
    location     TEXT NOT NULL,            -- 'central' 或 store_id
    product_id   TEXT NOT NULL,
    qty          INTEGER NOT NULL,
    expiry_date  TEXT NOT NULL,            -- ISO 日期，当天早上即剔除
    unit_cost    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS central_arrivals (
    arrival_id    TEXT PRIMARY KEY,
    arrival_date  TEXT NOT NULL,
    product_id    TEXT NOT NULL,
    qty           INTEGER NOT NULL,
    expiry_date   TEXT NOT NULL,
    unit_cost     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS demand (
    date        TEXT NOT NULL,
    store_id    TEXT NOT NULL,
    product_id  TEXT NOT NULL,
    qty         INTEGER NOT NULL,
    PRIMARY KEY (date, store_id, product_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id               TEXT PRIMARY KEY,
    strategy             TEXT NOT NULL,    -- rop / cycle
    label                TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    total_demand         INTEGER,
    total_sold           INTEGER,
    total_lost           INTEGER,
    fill_rate            REAL,
    avg_inventory_value  REAL,             -- 门店日终库存金额的逐日平均
    scrap_cost           REAL,             -- 门店临期报废成本
    central_scrap_cost   REAL,             -- 中央仓报废成本（单独披露）
    total_gap            INTEGER
);

CREATE TABLE IF NOT EXISTS snapshots (
    run_id        TEXT NOT NULL,
    date          TEXT NOT NULL,
    store_id      TEXT NOT NULL,
    product_id    TEXT NOT NULL,
    on_hand       INTEGER NOT NULL,
    on_hand_value REAL NOT NULL,
    in_transit    INTEGER NOT NULL,
    demand_qty    INTEGER NOT NULL,
    sold_qty      INTEGER NOT NULL,
    lost_qty      INTEGER NOT NULL,
    scrap_qty     INTEGER NOT NULL,
    scrap_cost    REAL NOT NULL,
    PRIMARY KEY (run_id, date, store_id, product_id)
);

CREATE TABLE IF NOT EXISTS central_snapshots (
    run_id        TEXT NOT NULL,
    date          TEXT NOT NULL,
    product_id    TEXT NOT NULL,
    on_hand       INTEGER NOT NULL,
    on_hand_value REAL NOT NULL,
    inbound_qty   INTEGER NOT NULL,
    scrap_qty     INTEGER NOT NULL,
    scrap_cost    REAL NOT NULL,
    PRIMARY KEY (run_id, date, product_id)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id        TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    date            TEXT NOT NULL,
    store_id        TEXT NOT NULL,
    product_id      TEXT NOT NULL,
    trigger_reason  TEXT NOT NULL,         -- below_reorder_point / scheduled_review
    on_hand         INTEGER NOT NULL,      -- 决策时门店现有量
    in_transit      INTEGER NOT NULL,      -- 决策时在途量
    target_qty      INTEGER NOT NULL,
    reorder_point   INTEGER NOT NULL,
    raw_needed      INTEGER NOT NULL,      -- 目标量 - 现有 - 在途
    case_size       INTEGER NOT NULL,
    requested_qty   INTEGER NOT NULL,      -- 整箱取整后的申请量
    allocated_qty   INTEGER NOT NULL,      -- 中央仓实际分配量
    gap_qty         INTEGER NOT NULL,      -- 未分到的缺口
    lead_days       INTEGER NOT NULL,
    status          TEXT NOT NULL          -- full / partial / none
);

CREATE TABLE IF NOT EXISTS order_allocations (
    allocation_id    TEXT PRIMARY KEY,
    order_id         TEXT NOT NULL,
    source_batch_id  TEXT NOT NULL,        -- 中央仓来源批次（保留有效期/成本溯源）
    qty              INTEGER NOT NULL,
    expiry_date      TEXT NOT NULL,
    unit_cost        REAL NOT NULL,
    arrival_date     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    date       TEXT NOT NULL,
    seq        INTEGER NOT NULL,           -- 当日顺序：收货→剔除→需求→补货
    type       TEXT NOT NULL,
    store_id   TEXT,
    product_id TEXT,
    batch_id   TEXT,
    qty        INTEGER,
    amount     REAL,
    detail     TEXT
);

CREATE TABLE IF NOT EXISTS reconciliation (
    run_id           TEXT NOT NULL,
    batch_id         TEXT NOT NULL,
    product_id       TEXT NOT NULL,
    location         TEXT NOT NULL,        -- central / store_id / in_transit 落地门店
    expiry_date      TEXT NOT NULL,
    source_batch_id  TEXT,
    start_qty        INTEGER NOT NULL,
    sold_qty         INTEGER NOT NULL,
    scrap_qty        INTEGER NOT NULL,
    shipped_out_qty  INTEGER NOT NULL,     -- 仅中央仓批次
    end_qty          INTEGER NOT NULL,
    balanced         INTEGER NOT NULL,
    PRIMARY KEY (run_id, batch_id)
);
"""

# 每次回放需要清空的运行类表
RUN_TABLES = [
    "reconciliation",
    "events",
    "order_allocations",
    "orders",
    "central_snapshots",
    "snapshots",
    "runs",
]


def get_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def reset_run_tables(conn: sqlite3.Connection) -> None:
    for table in RUN_TABLES:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
