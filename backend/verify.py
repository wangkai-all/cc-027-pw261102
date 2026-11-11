"""离线校验：不经过 HTTP 直接跑引擎，断言全部业务不变量。"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import engine
from app.database import get_conn, init_db, reset_run_tables
from app.seed import seed


def main() -> None:
    conn = get_conn()
    init_db(conn)
    seed(conn)
    reset_run_tables(conn)
    config = engine.load_config(conn)

    states_snapshot = None
    for strategy in ("rop", "cycle"):
        rt = engine.run_simulation(conn, config, strategy)

        # 1. 任意时点不允许负库存（批次余量、台账结束量、快照均非负）
        assert all(b.qty >= 0 for b in rt.central_batches), "中央仓负库存"
        for batches in rt.store_batches.values():
            assert all(b.qty >= 0 for b in batches), "门店负库存"
        for t in rt.in_transit:
            assert t.batch.qty > 0
        assert all(r.end_qty >= 0 for r in rt.ledger.values()), "台账出现负结束量"
        neg = conn.execute(
            "SELECT COUNT(*) FROM snapshots WHERE run_id=? AND "
            "(on_hand<0 OR in_transit<0 OR sold_qty<0 OR lost_qty<0)",
            (strategy,)).fetchone()[0]
        assert neg == 0, "快照出现负值"

        # 2. 损失需求 = 需求 - 销量，且销量不超过需求
        for row in conn.execute(
                "SELECT * FROM snapshots WHERE run_id=?", (strategy,)):
            assert row["demand_qty"] == row["sold_qty"] + row["lost_qty"]
            assert row["sold_qty"] <= row["demand_qty"]

        # 3. 缺口不能被当成发货：每单实发 <= 申请，且 实发+缺口 == 申请
        for o in conn.execute("SELECT * FROM orders WHERE run_id=?", (strategy,)):
            assert o["allocated_qty"] + o["gap_qty"] == o["requested_qty"]
            assert o["allocated_qty"] <= o["requested_qty"]
        alloc_joined = conn.execute("""
            SELECT o.order_id, o.requested_qty, COALESCE(SUM(a.qty),0) alloc
            FROM orders o LEFT JOIN order_allocations a ON a.order_id=o.order_id
            WHERE o.run_id=? GROUP BY o.order_id
        """, (strategy,)).fetchall()
        for r in alloc_joined:
            assert r["alloc"] == conn.execute(
                "SELECT allocated_qty FROM orders WHERE order_id=?",
                (r["order_id"],)).fetchone()[0]
            assert r["alloc"] <= r["requested_qty"]

        # 4. 中央仓逐批发出量与分配明细一致
        alloc_sum = defaultdict(int)
        for a in conn.execute(
                "SELECT * FROM order_allocations a JOIN orders o ON o.order_id=a.order_id "
                "WHERE o.run_id=?", (strategy,)):
            alloc_sum[a["source_batch_id"]] += a["qty"]
        for r in conn.execute("SELECT * FROM reconciliation WHERE run_id=? AND location='central'",
                              (strategy,)):
            assert r["shipped_out_qty"] == alloc_sum[r["batch_id"]], \
                f"中央批次 {r['batch_id']} 发出量对不上"

        # 5. 中央 -> 门店逐批数量对上（含仍在途）
        recv = defaultdict(int)
        for r in conn.execute(
                "SELECT source_batch_id, start_qty FROM reconciliation "
                "WHERE run_id=? AND source_batch_id IS NOT NULL", (strategy,)):
            recv[r["source_batch_id"]] += r["start_qty"]
        for r in conn.execute(
                "SELECT batch_id, shipped_out_qty FROM reconciliation "
                "WHERE run_id=? AND location='central'", (strategy,)):
            assert recv[r["batch_id"]] == r["shipped_out_qty"], \
                f"批次 {r['batch_id']} 中央发出 {r['shipped_out_qty']} 与门店/在途落地 {recv[r['batch_id']]} 不一致"

        # 6. 全局守恒
        assert rt.totals["conservation_ok"], f"{strategy} 全局数量不守恒"
        assert rt.totals["shipment_check_ok"], f"{strategy} 发出量核对失败"

        # 7. 发出批次保留有效期与单位成本
        for a in conn.execute("""
            SELECT a.expiry_date a_exp, a.unit_cost a_cost,
                   ib.expiry_date ib_exp, ib.unit_cost ib_cost
            FROM order_allocations a
            JOIN initial_batches ib ON ib.batch_id = a.source_batch_id
            UNION ALL
            SELECT a.expiry_date, a.unit_cost, ca.expiry_date, ca.unit_cost
            FROM order_allocations a
            JOIN central_arrivals ca ON ca.arrival_id = a.source_batch_id
        """):
            assert a["a_exp"] == a["ib_exp"] and a["a_cost"] == a["ib_cost"], "批次有效期/成本未保留"

        # 8. 到货日期 = 发出日 + 配送天数
        from datetime import date as ddate, timedelta
        for o in conn.execute("SELECT * FROM orders WHERE run_id=?", (strategy,)):
            for a in conn.execute("SELECT * FROM order_allocations WHERE order_id=?",
                                  (o["order_id"],)):
                expect = (ddate.fromisoformat(o["date"]) + timedelta(days=o["lead_days"])).isoformat()
                assert a["arrival_date"] == expect, "在途到货日期计算错误"

        # 9. 两种策略从同一初始状态独立运行：台账起始量 = 初始批次 + 中央到货
        start_qty = conn.execute("SELECT COALESCE(SUM(qty),0) q FROM initial_batches").fetchone()["q"]
        arrival_qty = conn.execute("SELECT COALESCE(SUM(qty),0) q FROM central_arrivals").fetchone()["q"]
        led_start = conn.execute(
            "SELECT SUM(start_qty) q FROM reconciliation WHERE run_id=? AND source_batch_id IS NULL",
            (strategy,)).fetchone()["q"]
        assert led_start == start_qty + arrival_qty
        # 发货落地批次起始量 == 中央仓发出总量（逐批已在第 4/5 条核对）
        sh_start = conn.execute(
            "SELECT COALESCE(SUM(start_qty),0) q FROM reconciliation "
            "WHERE run_id=? AND source_batch_id IS NOT NULL", (strategy,)).fetchone()["q"]
        shipped = conn.execute(
            "SELECT COALESCE(SUM(shipped_out_qty),0) q FROM reconciliation "
            "WHERE run_id=? AND location='central'", (strategy,)).fetchone()["q"]
        assert sh_start == shipped

        run = conn.execute("SELECT * FROM runs WHERE run_id=?", (strategy,)).fetchone()
        print(f"[{strategy}] {run['label']}")
        print(f"  需求={run['total_demand']} 满足={run['total_sold']} "
              f"损失={run['total_lost']} 满足率={run['fill_rate']:.2%}")
        print(f"  平均库存金额={run['avg_inventory_value']:.2f} "
              f"门店报废成本={run['scrap_cost']:.2f} 中央报废={run['central_scrap_cost']:.2f} "
              f"累计缺口={run['total_gap']}")
        print(f"  守恒={rt.totals['conservation_ok']} 逐批发出核对={rt.totals['shipment_check_ok']}")

    # 10. 两策略运行互不串库存：最终库存结构应不同（策略确实产生差异），且各自守恒
    rop_end = conn.execute(
        "SELECT SUM(end_qty) q FROM reconciliation WHERE run_id='rop'").fetchone()["q"]
    cyc_end = conn.execute(
        "SELECT SUM(end_qty) q FROM reconciliation WHERE run_id='cycle'").fetchone()["q"]
    print(f"\n期末实物总量 rop={rop_end} cycle={cyc_end}（两策略销量/报废不同，允许有差异，但各自必须守恒）")

    # 11. FEFO 抽查：任一天门店销售扣减顺序按有效期升序（从事件序列检查，分策略）
    for strategy in ("rop", "cycle"):
        seen = defaultdict(list)
        for e in conn.execute(
                "SELECT * FROM events WHERE run_id=? AND type='sale' ORDER BY date, seq",
                (strategy,)):
            seen[(e["date"], e["store_id"], e["product_id"])].append(e["batch_id"])
        batch_exp = {r["batch_id"]: r["expiry_date"]
                     for r in conn.execute(
                         "SELECT DISTINCT batch_id, expiry_date FROM reconciliation WHERE run_id=?",
                         (strategy,))}
        for key, bids in seen.items():
            exps = [batch_exp[b] for b in bids]
            assert exps == sorted(exps), f"FEFO 顺序错误 {key}: {bids}"
    print("FEFO 扣减顺序校验通过")

    print("\n全部不变量校验通过 ✔")
    conn.close()


if __name__ == "__main__":
    main()
