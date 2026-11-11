"""FastAPI 路由：输入数据、回放控制、逐日数据、订单计算依据、对账。"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import engine
from .database import get_conn, init_db, reset_run_tables
from .seed import seed

app = FastAPI(title="补货策略回放", version="1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


@app.on_event("startup")
def _startup() -> None:
    conn = get_conn()
    init_db(conn)
    # 首次启动若没有配置数据则播种（同一份历史数据）
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        seed(conn)
    conn.close()


@app.post("/api/replay")
def replay():
    """用同一份初始状态分别跑两种策略，清空旧运行结果后重算。"""
    conn = get_conn()
    reset_run_tables(conn)
    config = engine.load_config(conn)
    results = {}
    for strategy in ("rop", "cycle"):
        rt = engine.run_simulation(conn, config, strategy)
        results[strategy] = {
            "label": engine.STRATEGIES[strategy],
            "conservation_ok": bool(rt.totals["conservation_ok"]),
            "shipment_check_ok": bool(rt.totals["shipment_check_ok"]),
        }
    conn.close()
    return {"status": "ok", "strategies": results}


@app.get("/api/config")
def get_config():
    conn = get_conn()
    out = {
        "products": _rows(conn, "SELECT * FROM products ORDER BY product_id"),
        "stores": _rows(conn, "SELECT * FROM stores ORDER BY priority, store_id"),
        "policies": _rows(conn, "SELECT * FROM policies ORDER BY store_id, product_id"),
        "central_arrivals": _rows(conn,
            "SELECT * FROM central_arrivals ORDER BY arrival_date, product_id"),
        "initial_batches": _rows(conn,
            "SELECT * FROM initial_batches ORDER BY location, product_id, expiry_date"),
        "dates": [r["d"] for r in conn.execute(
            "SELECT DISTINCT date d FROM demand ORDER BY date").fetchall()],
    }
    conn.close()
    return out


@app.get("/api/demand")
def get_demand():
    conn = get_conn()
    out = _rows(conn, "SELECT * FROM demand ORDER BY date, store_id, product_id")
    conn.close()
    return out


@app.get("/api/runs")
def get_runs():
    conn = get_conn()
    out = _rows(conn, "SELECT * FROM runs ORDER BY run_id")
    conn.close()
    return out


@app.get("/api/snapshots")
def get_snapshots(run_id: str):
    conn = get_conn()
    out = _rows(conn, """
        SELECT s.*, p.name product_name, st.name store_name
        FROM snapshots s
        JOIN products p ON p.product_id = s.product_id
        JOIN stores st ON st.store_id = s.store_id
        WHERE run_id = ? ORDER BY date, s.store_id, s.product_id
    """, (run_id,))
    conn.close()
    return out


@app.get("/api/central-snapshots")
def get_central_snapshots(run_id: str):
    conn = get_conn()
    out = _rows(conn, """
        SELECT c.*, p.name product_name
        FROM central_snapshots c JOIN products p ON p.product_id = c.product_id
        WHERE run_id = ? ORDER BY date, c.product_id
    """, (run_id,))
    conn.close()
    return out


@app.get("/api/orders")
def get_orders(run_id: str, date: str | None = None):
    conn = get_conn()
    sql = """SELECT o.*, p.name product_name, p.unit, st.name store_name
             FROM orders o
             JOIN products p ON p.product_id = o.product_id
             JOIN stores st ON st.store_id = o.store_id
             WHERE run_id = ?"""
    params: list = [run_id]
    if date:
        sql += " AND o.date = ?"
        params.append(date)
    sql += " ORDER BY o.date, st.priority, st.store_id, o.product_id"
    out = _rows(conn, sql, tuple(params))
    conn.close()
    return out


@app.get("/api/orders/{order_id}")
def get_order_detail(order_id: str):
    """一笔补货的完整计算依据：申请量推导、中央仓逐批分配、当日相关事件。"""
    conn = get_conn()
    order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not order:
        conn.close()
        raise HTTPException(404, f"订单 {order_id} 不存在")
    order = dict(order)
    allocs = _rows(conn, """
        SELECT * FROM order_allocations
        WHERE order_id = ? ORDER BY allocation_id
    """, (order_id,))
    # 当天同门店同商品的决策上下文事件（order_placed / allocation / order_skipped）
    context = _rows(conn, """
        SELECT * FROM events
        WHERE run_id = ? AND date = ? AND store_id = ? AND product_id = ?
          AND type IN ('order_placed', 'allocation', 'order_skipped',
                       'lost_sale', 'receive', 'store_scrap')
        ORDER BY seq
    """, (order["run_id"], order["date"], order["store_id"], order["product_id"]))
    conn.close()

    # 结构化计算依据，前端直接展示
    basis = {
        "rule": engine.STRATEGIES[order["run_id"]],
        "trigger_reason": order["trigger_reason"],
        "formula": "requested = ceil((目标量 - 现有库存 - 在途量) / 整箱) × 整箱",
        "inputs": {
            "target_qty": order["target_qty"],
            "on_hand_at_decision": order["on_hand"],
            "in_transit_at_decision": order["in_transit"],
            "raw_needed": order["raw_needed"],
            "case_size": order["case_size"],
            "reorder_point": order["reorder_point"],
            "lead_days": order["lead_days"],
        },
        "steps": [
            f"决策时点只可见 {order['date']} 及以前的信息",
            f"现有库存 {order['on_hand']}，在途（未到货）{order['in_transit']}",
            f"目标量 {order['target_qty']}，裸需求 = {order['target_qty']} - "
            f"{order['on_hand']} - {order['in_transit']} = {order['raw_needed']}",
            f"整箱规格 {order['case_size']}，向上取整："
            f"ceil({order['raw_needed']}/{order['case_size']}) × {order['case_size']} "
            f"= {order['requested_qty']}",
            f"中央仓按门店优先级 FEFO 实发 {order['allocated_qty']}，"
            f"未满足缺口 {order['gap_qty']}（保留为缺口，未发货）",
            f"配送天数 {order['lead_days']} 天，发出批次保留原有效期与单位成本",
        ],
    }
    return {"order": order, "allocations": allocs, "context_events": context, "basis": basis}


@app.get("/api/events")
def get_events(run_id: str, date: str | None = None):
    conn = get_conn()
    sql = "SELECT * FROM events WHERE run_id = ?"
    params: list = [run_id]
    if date:
        sql += " AND date = ?"
        params.append(date)
    sql += " ORDER BY date, seq"
    out = _rows(conn, sql, tuple(params))
    conn.close()
    return out


@app.get("/api/reconciliation")
def get_reconciliation(run_id: str):
    """逐批对账 + 守恒/发出量核对结论。"""
    conn = get_conn()
    rows = _rows(conn, """
        SELECT r.*, p.name product_name
        FROM reconciliation r JOIN products p ON p.product_id = r.product_id
        WHERE run_id = ? ORDER BY r.location, r.product_id, r.expiry_date, r.batch_id
    """, (run_id,))

    # 中央仓 -> 门店：每个中央仓批次发出量 == 各门店收货批次（source_batch_id）起始量之和
    shipment_rows = _rows(conn, """
        SELECT src.batch_id central_batch, src.product_id,
               src.shipped_out_qty,
               COALESCE(SUM(dst.start_qty), 0) received_qty,
               GROUP_CONCAT(DISTINCT dst.location) destinations
        FROM reconciliation src
        LEFT JOIN reconciliation dst
          ON dst.source_batch_id = src.batch_id AND dst.run_id = src.run_id
        WHERE src.run_id = ? AND src.location = 'central'
        GROUP BY src.batch_id
        ORDER BY src.product_id, src.batch_id
    """, (run_id,))
    shipment_ok = all(r["shipped_out_qty"] == r["received_qty"] for r in shipment_rows)
    balanced_ok = all(r["balanced"] for r in rows)

    conservation = _rows(conn, """
        WITH supply AS (
            SELECT product_id, SUM(qty) q FROM initial_batches GROUP BY product_id
            UNION ALL
            SELECT product_id, SUM(qty) FROM central_arrivals GROUP BY product_id
        )
        SELECT s.product_id, p.name product_name, SUM(s.q) supply_qty,
               (SELECT COALESCE(SUM(end_qty),0) FROM reconciliation
                 WHERE run_id = ? AND product_id = s.product_id) end_qty,
               (SELECT COALESCE(SUM(sold_qty),0) FROM reconciliation
                 WHERE run_id = ? AND product_id = s.product_id) sold_qty,
               (SELECT COALESCE(SUM(scrap_qty),0) FROM reconciliation
                 WHERE run_id = ? AND product_id = s.product_id) scrap_qty
        FROM supply s JOIN products p ON p.product_id = s.product_id
        GROUP BY s.product_id
    """, (run_id, run_id, run_id))
    for r in conservation:
        r["conserved"] = r["supply_qty"] == r["end_qty"] + r["sold_qty"] + r["scrap_qty"]

    conn.close()
    return {
        "batches": rows,
        "shipment_match": shipment_rows,
        "shipment_match_ok": shipment_ok,
        "all_balanced": balanced_ok,
        "conservation": conservation,
        "conservation_ok": all(r["conserved"] for r in conservation),
    }


@app.get("/api/compare")
def compare():
    """两策略汇总对比 + 按门店指标。"""
    conn = get_conn()
    runs = _rows(conn, "SELECT * FROM runs ORDER BY run_id")
    by_store = _rows(conn, """
        SELECT s.run_id, s.store_id, st.name store_name,
               SUM(s.demand_qty) demand_qty, SUM(s.sold_qty) sold_qty,
               SUM(s.lost_qty) lost_qty, SUM(s.scrap_qty) scrap_qty,
               ROUND(SUM(s.scrap_cost),2) scrap_cost,
               ROUND(AVG(s.on_hand_value),2) avg_inventory_value,
               ROUND(1.0 * SUM(s.sold_qty) / NULLIF(SUM(s.demand_qty),0), 4) fill_rate
        FROM snapshots s JOIN stores st ON st.store_id = s.store_id
        GROUP BY s.run_id, s.store_id ORDER BY s.run_id, s.store_id
    """)
    by_product = _rows(conn, """
        SELECT s.run_id, s.product_id, p.name product_name,
               SUM(s.demand_qty) demand_qty, SUM(s.sold_qty) sold_qty,
               SUM(s.lost_qty) lost_qty, SUM(s.scrap_qty) scrap_qty,
               ROUND(SUM(s.scrap_cost),2) scrap_cost,
               ROUND(AVG(s.on_hand_value),2) avg_inventory_value,
               ROUND(1.0 * SUM(s.sold_qty) / NULLIF(SUM(s.demand_qty),0), 4) fill_rate
        FROM snapshots s JOIN products p ON p.product_id = s.product_id
        GROUP BY s.run_id, s.product_id ORDER BY s.run_id, s.product_id
    """)
    daily = _rows(conn, """
        SELECT run_id, date,
               SUM(demand_qty) demand_qty, SUM(sold_qty) sold_qty,
               SUM(lost_qty) lost_qty,
               ROUND(SUM(on_hand_value),2) inventory_value,
               ROUND(SUM(scrap_cost),2) scrap_cost
        FROM snapshots GROUP BY run_id, date ORDER BY date, run_id
    """)
    conn.close()
    return {"runs": runs, "by_store": by_store,
            "by_product": by_product, "daily": daily}
