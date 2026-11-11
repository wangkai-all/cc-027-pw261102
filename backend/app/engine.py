"""补货策略回放引擎。

每个策略从同一份输入数据的深拷贝独立运行，互不串用库存。

每日固定顺序：
  1. 中央仓收货（中央仓到货批次入库）
  2. 中央仓剔除当天已到期批次
  3. 门店收货（在途批次按发出日 + 配送天数到期入库，保留原有效期与单位成本）
  4. 门店剔除当天已到期批次（记临期报废）
  5. 满足当天需求：FEFO 先到期先出，不足记损失需求，不允许负库存
  6. 日终生成补货单：只能看到当日及以前的信息

补货量：raw = 目标量 - 现有库存 - 在途量，>0 时按整箱向上取整。
中央仓有限：同日同商品按 (门店优先级, 门店编号) 分配，未分到部分保留为缺口。
"""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

STRATEGIES = {
    "rop": "低于补货点补到目标量",
    "cycle": "每三天补到目标量",
}
REVIEW_CYCLE_DAYS = 3


@dataclass
class Batch:
    batch_id: str
    product_id: str
    qty: int
    expiry_date: str
    unit_cost: float
    location: str                        # 'central' 或门店 id
    source_batch_id: str | None = None   # 门店批次溯源到中央仓批次
    arrival_date: str | None = None      # 门店/在途批次的到货日


@dataclass
class InTransit:
    """门店在途：由中央仓发出的批次，保留原有效期与单位成本。"""
    batch: Batch
    arrival_date: str


@dataclass
class LedgerRow:
    batch_id: str
    product_id: str
    location: str
    expiry_date: str
    source_batch_id: str | None
    start_qty: int
    sold_qty: int = 0
    scrap_qty: int = 0
    shipped_out_qty: int = 0
    end_qty: int = 0
    arrival_date: str | None = None


@dataclass
class Runtime:
    run_id: str
    strategy: str
    dates: list[str]
    products: dict
    stores: dict
    policies: dict
    central_batches: list[Batch] = field(default_factory=list)
    store_batches: dict[str, list[Batch]] = field(default_factory=lambda: defaultdict(list))
    in_transit: list[InTransit] = field(default_factory=list)
    demand_map: dict = field(default_factory=dict)
    arrivals: dict = field(default_factory=lambda: defaultdict(list))
    events: list[dict] = field(default_factory=list)
    ledger: dict[str, LedgerRow] = field(default_factory=dict)
    totals: dict = field(default_factory=lambda: defaultdict(float))
    day_inventory_values: list[float] = field(default_factory=list)
    _seq: int = 0

    def log(self, day: str, etype: str, *, store_id=None, product_id=None,
            batch_id=None, qty=None, amount=None, detail=None) -> None:
        self._seq += 1
        self.events.append({
            "run_id": self.run_id, "date": day, "seq": self._seq,
            "type": etype, "store_id": store_id, "product_id": product_id,
            "batch_id": batch_id, "qty": qty,
            "amount": round(amount, 2) if amount is not None else None,
            "detail": detail,
        })


# ---------------------------------------------------------------- 输入装载

def load_config(conn: sqlite3.Connection) -> dict:
    rows = lambda sql: [dict(r) for r in conn.execute(sql).fetchall()]
    return {
        "dates": [r["d"] for r in conn.execute(
            "SELECT DISTINCT date d FROM demand ORDER BY date").fetchall()],
        "products": {r["product_id"]: r for r in rows("SELECT * FROM products")},
        "stores": {r["store_id"]: r for r in rows("SELECT * FROM stores")},
        "policies": {(r["store_id"], r["product_id"]): r
                     for r in rows("SELECT * FROM policies")},
        "initial_batches": rows("SELECT * FROM initial_batches"),
        "arrivals": rows("SELECT * FROM central_arrivals ORDER BY arrival_date"),
        "demand": rows("SELECT * FROM demand"),
    }


def build_runtime(config: dict, strategy: str) -> Runtime:
    rt = Runtime(run_id=strategy, strategy=strategy,
                 dates=list(config["dates"]),
                 products={k: dict(v) for k, v in config["products"].items()},
                 stores={k: dict(v) for k, v in config["stores"].items()},
                 policies={k: dict(v) for k, v in config["policies"].items()})
    # 初始批次：中央仓与各门店独立拷贝（两种策略各自 build，天然不串库存）
    for r in config["initial_batches"]:
        b = Batch(r["batch_id"], r["product_id"], r["qty"], r["expiry_date"],
                  r["unit_cost"], r["location"])
        if r["location"] == "central":
            rt.central_batches.append(b)
        else:
            rt.store_batches[r["location"]].append(b)
        rt.ledger[b.batch_id] = LedgerRow(
            b.batch_id, b.product_id, b.location, b.expiry_date, None, b.qty)
    for a in config["arrivals"]:
        rt.arrivals[a["arrival_date"]].append(dict(a))
    for d in config["demand"]:
        rt.demand_map[(d["date"], d["store_id"], d["product_id"])] = d["qty"]
    return rt


# ---------------------------------------------------------------- 批次工具

def _fefo(batches: list[Batch], product_id: str) -> list[Batch]:
    return sorted((b for b in batches if b.product_id == product_id and b.qty > 0),
                  key=lambda b: (b.expiry_date, b.batch_id))


def in_transit_qty(rt: Runtime, store_id: str, product_id: str, day: str) -> int:
    """决策时点在途量：到货日晚于当天、尚未入库的批次数量之和。"""
    return sum(t.batch.qty for t in rt.in_transit
               if t.batch.location == store_id
               and t.batch.product_id == product_id
               and t.arrival_date > day)


# ---------------------------------------------------------------- 每日动作

def central_receive(rt: Runtime, day: str) -> dict:
    inbound = defaultdict(int)
    for a in rt.arrivals.get(day, []):
        b = Batch(a["arrival_id"], a["product_id"], a["qty"],
                  a["expiry_date"], a["unit_cost"], "central")
        rt.central_batches.append(b)
        rt.ledger[b.batch_id] = LedgerRow(
            b.batch_id, b.product_id, "central", b.expiry_date, None, b.qty,
            arrival_date=day)
        inbound[b.product_id] += b.qty
        rt.log(day, "central_inbound", product_id=b.product_id, batch_id=b.batch_id,
               qty=b.qty, amount=b.qty * b.unit_cost,
               detail=f"中央仓到货 {b.qty} 件，有效期至 {b.expiry_date}")
    return inbound


def central_expire(rt: Runtime, day: str) -> dict:
    scrap: dict = {}
    for b in list(rt.central_batches):
        if b.qty > 0 and b.expiry_date <= day:
            cost = b.qty * b.unit_cost
            scrap[b.product_id] = scrap.get(b.product_id, 0) + b.qty
            scrap[f"{b.product_id}_cost"] = scrap.get(f"{b.product_id}_cost", 0.0) + cost
            rt.ledger[b.batch_id].scrap_qty += b.qty
            rt.totals["central_scrap_cost"] += cost
            rt.log(day, "central_scrap", product_id=b.product_id, batch_id=b.batch_id,
                   qty=b.qty, amount=cost,
                   detail=f"中央仓批次 {b.batch_id} 于 {day} 到期，报废 {b.qty} 件")
            b.qty = 0
    rt.central_batches[:] = [b for b in rt.central_batches if b.qty > 0]
    return scrap


def store_receive(rt: Runtime, day: str) -> None:
    due = [t for t in rt.in_transit if t.arrival_date == day]
    for t in due:
        b = t.batch
        rt.store_batches[b.location].append(b)
        rt.ledger[b.batch_id] = LedgerRow(
            b.batch_id, b.product_id, b.location, b.expiry_date,
            b.source_batch_id, b.qty, arrival_date=day)
        rt.log(day, "receive", store_id=b.location, product_id=b.product_id,
               batch_id=b.batch_id, qty=b.qty, amount=b.qty * b.unit_cost,
               detail=f"门店 {b.location} 收到在途批次 {b.batch_id}（源批次 {b.source_batch_id}），"
                      f"有效期 {b.expiry_date}，单位成本 {b.unit_cost}")
    rt.in_transit = [t for t in rt.in_transit if t.arrival_date != day]


def store_expire(rt: Runtime, day: str) -> dict:
    """返回 {(store, product): (qty, cost)} 当日门店报废。"""
    scrap: dict = {}
    for sid in rt.stores:
        for b in list(rt.store_batches[sid]):
            if b.qty > 0 and b.expiry_date <= day:
                cost = b.qty * b.unit_cost
                key = (sid, b.product_id)
                q, c = scrap.get(key, (0, 0.0))
                scrap[key] = (q + b.qty, c + cost)
                rt.ledger[b.batch_id].scrap_qty += b.qty
                rt.totals["scrap_cost"] += cost
                rt.log(day, "store_scrap", store_id=sid, product_id=b.product_id,
                       batch_id=b.batch_id, qty=b.qty, amount=cost,
                       detail=f"门店 {sid} 批次 {b.batch_id} 于 {day} 到期，报废 {b.qty} 件")
                b.qty = 0
        rt.store_batches[sid][:] = [b for b in rt.store_batches[sid] if b.qty > 0]
    return scrap


def satisfy_demand(rt: Runtime, day: str, store_id: str, product_id: str,
                   demand: int) -> tuple[int, int]:
    """FEFO 扣减，返回 (销量, 损失需求)。绝不出现负库存。"""
    remaining = demand
    for b in _fefo(rt.store_batches[store_id], product_id):
        if remaining <= 0:
            break
        take = min(remaining, b.qty)
        b.qty -= take
        remaining -= take
        rt.ledger[b.batch_id].sold_qty += take
        rt.log(day, "sale", store_id=store_id, product_id=product_id,
               batch_id=b.batch_id, qty=take, amount=take * b.unit_cost,
               detail=f"FEFO 扣减批次 {b.batch_id}（有效期 {b.expiry_date}）{take} 件")
    sold, lost = demand - remaining, remaining
    if lost:
        rt.log(day, "lost_sale", store_id=store_id, product_id=product_id,
               qty=lost, detail=f"库存不足，损失需求 {lost} 件")
    rt.store_batches[store_id][:] = [b for b in rt.store_batches[store_id] if b.qty > 0]
    return sold, lost


# ---------------------------------------------------------------- 补货分配

def _should_order(strategy: str, day_idx: int, on_hand: int,
                  rop: int) -> tuple[bool, str]:
    if strategy == "rop":
        return (True, "below_reorder_point") if on_hand < rop else (False, "")
    if strategy == "cycle":
        return (True, "scheduled_review") if day_idx % REVIEW_CYCLE_DAYS == 0 else (False, "")
    raise ValueError(f"unknown strategy {strategy}")


def generate_and_allocate(rt: Runtime, day: str, day_idx: int) -> tuple[list[dict], list[dict]]:
    """日终补货：多门店同日同商品按 (优先级, 门店编号) 抢中央仓库存。"""
    order_rows, alloc_rows, alloc_seq = [], [], 0
    for store in sorted(rt.stores.values(), key=lambda s: (s["priority"], s["store_id"])):
        sid = store["store_id"]
        for pid in sorted(rt.products):
            prod, policy = rt.products[pid], rt.policies[(sid, pid)]
            rop, target = policy["reorder_point"], policy["target_qty"]
            lead = policy["lead_days"] or store["default_lead_days"]
            case_size = prod["case_size"]
            on_hand = sum(b.qty for b in rt.store_batches[sid] if b.product_id == pid)
            transit = in_transit_qty(rt, sid, pid, day)

            fire, reason = _should_order(rt.strategy, day_idx, on_hand, rop)
            if not fire:
                continue
            raw_needed = target - on_hand - transit
            if raw_needed <= 0:
                rt.log(day, "order_skipped", store_id=sid, product_id=pid,
                       detail=f"触发补货但现有({on_hand})+在途({transit})已覆盖目标量({target})，raw={raw_needed}，不下单")
                continue
            requested = math.ceil(raw_needed / case_size) * case_size

            # 中央仓 FEFO 分配；不足保留为缺口，不能当成已发货
            allocated, lines = 0, []
            for cb in _fefo(rt.central_batches, pid):
                if allocated >= requested:
                    break
                give = min(cb.qty, requested - allocated)
                cb.qty -= give
                allocated += give
                rt.central_batches[:] = [x for x in rt.central_batches if x.qty > 0]
                alloc_seq += 1
                alloc_id = f"AL-{rt.run_id}-{day}-{sid}-{pid}-{alloc_seq}"
                arrival = (date.fromisoformat(day) + timedelta(days=lead)).isoformat()
                # 发出的批次保留原有效期与单位成本，成为门店在途新批次
                ship = Batch(f"SH-{alloc_id}", pid, give, cb.expiry_date,
                             cb.unit_cost, sid, cb.batch_id, arrival)
                rt.in_transit.append(InTransit(ship, arrival))
                rt.ledger[cb.batch_id].shipped_out_qty += give
                lines.append({
                    "allocation_id": alloc_id, "order_id": None,
                    "source_batch_id": cb.batch_id, "qty": give,
                    "expiry_date": cb.expiry_date, "unit_cost": cb.unit_cost,
                    "arrival_date": arrival,
                })
                rt.log(day, "allocation", store_id=sid, product_id=pid,
                       batch_id=cb.batch_id, qty=give, amount=give * cb.unit_cost,
                       detail=f"中央仓批次 {cb.batch_id} 发出 {give} 件至 {sid}，{arrival} 到货，"
                              f"保留有效期 {cb.expiry_date} 与单位成本 {cb.unit_cost}")

            gap = requested - allocated
            status = "full" if gap == 0 else ("partial" if allocated else "none")
            order_id = f"OR-{rt.run_id}-{day}-{sid}-{pid}"
            order_rows.append({
                "order_id": order_id, "run_id": rt.run_id, "date": day,
                "store_id": sid, "product_id": pid, "trigger_reason": reason,
                "on_hand": on_hand, "in_transit": transit, "target_qty": target,
                "reorder_point": rop, "raw_needed": raw_needed,
                "case_size": case_size, "requested_qty": requested,
                "allocated_qty": allocated, "gap_qty": gap,
                "lead_days": lead, "status": status,
            })
            for ln in lines:
                ln["order_id"] = order_id
                alloc_rows.append(ln)
            rt.totals["gap"] += gap
            rt.log(day, "order_placed", store_id=sid, product_id=pid, qty=requested,
                   detail=(f"{STRATEGIES[rt.strategy]}｜触发={reason}，现有={on_hand}，在途={transit}，"
                           f"目标={target}，raw需求={raw_needed}，整箱({case_size})申请={requested}，"
                           f"实发={allocated}，缺口={gap}，状态={status}，配送天数={lead}"))
    return order_rows, alloc_rows


# ---------------------------------------------------------------- 主流程

def run_simulation(conn: sqlite3.Connection, config: dict, strategy: str) -> Runtime:
    rt = build_runtime(config, strategy)
    all_orders, all_allocs, all_events = [], [], []
    snap_rows, central_snap_rows = [], []

    for day_idx, day in enumerate(rt.dates):
        rt._seq = 0
        inbound = central_receive(rt, day)                       # 1.中央收货
        c_scrap = central_expire(rt, day)                        # 2.中央剔除
        store_receive(rt, day)                                   # 3.门店收货
        s_scrap = store_expire(rt, day)                          # 4.门店剔除

        day_demand, day_sold, day_lost = {}, defaultdict(int), defaultdict(int)
        for sid in sorted(rt.stores):                            # 5.满足需求
            for pid in sorted(rt.products):
                demand = rt.demand_map.get((day, sid, pid), 0)
                day_demand[(sid, pid)] = demand
                if demand:
                    sold, lost = satisfy_demand(rt, day, sid, pid, demand)
                    day_sold[(sid, pid)], day_lost[(sid, pid)] = sold, lost
                    rt.totals["demand"] += demand
                    rt.totals["sold"] += sold
                    rt.totals["lost"] += lost

        orders, allocs = generate_and_allocate(rt, day, day_idx)  # 6.日终补货
        all_orders.extend(orders)
        all_allocs.extend(allocs)

        day_value = 0.0                                          # 7.日终快照
        for sid in sorted(rt.stores):
            for pid in sorted(rt.products):
                batches = [b for b in rt.store_batches[sid] if b.product_id == pid]
                on_hand = sum(b.qty for b in batches)
                value = round(sum(b.qty * b.unit_cost for b in batches), 2)
                day_value += value
                sq, sc = s_scrap.get((sid, pid), (0, 0.0))
                snap_rows.append((
                    rt.run_id, day, sid, pid, on_hand, value,
                    in_transit_qty(rt, sid, pid, day),
                    day_demand[(sid, pid)], day_sold[(sid, pid)],
                    day_lost[(sid, pid)], sq, round(sc, 2)))
        for pid in sorted(rt.products):
            batches = [b for b in rt.central_batches if b.product_id == pid]
            central_snap_rows.append((
                rt.run_id, day, pid, sum(b.qty for b in batches),
                round(sum(b.qty * b.unit_cost for b in batches), 2),
                inbound.get(pid, 0), c_scrap.get(pid, 0),
                round(c_scrap.get(f"{pid}_cost", 0.0), 2)))
        rt.day_inventory_values.append(round(day_value, 2))
        all_events.extend(rt.events)
        rt.events = []

    _persist(conn, rt, all_orders, all_allocs, all_events,
             snap_rows, central_snap_rows)
    return rt


# ---------------------------------------------------------------- 持久化与对账

def _persist(conn: sqlite3.Connection, rt: Runtime, orders, allocs, events,
             snap_rows, central_snap_rows) -> None:
    cur = conn.cursor()
    cur.executemany("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", snap_rows)
    cur.executemany("INSERT INTO central_snapshots VALUES (?,?,?,?,?,?,?,?)", central_snap_rows)
    cur.executemany(
        "INSERT INTO events (run_id,date,seq,type,store_id,product_id,batch_id,qty,amount,detail)"
        " VALUES (:run_id,:date,:seq,:type,:store_id,:product_id,:batch_id,:qty,:amount,:detail)",
        events)
    cur.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [tuple(o[k] for k in ("order_id", "run_id", "date", "store_id",
                              "product_id", "trigger_reason", "on_hand",
                              "in_transit", "target_qty", "reorder_point",
                              "raw_needed", "case_size", "requested_qty",
                              "allocated_qty", "gap_qty", "lead_days", "status"))
         for o in orders])
    cur.executemany(
        "INSERT INTO order_allocations VALUES (?,?,?,?,?,?,?)",
        [(a["allocation_id"], a["order_id"], a["source_batch_id"], a["qty"],
          a["expiry_date"], a["unit_cost"], a["arrival_date"]) for a in allocs])

    n = len(rt.dates)
    total_demand, total_sold, total_lost = (int(rt.totals[k])
                                            for k in ("demand", "sold", "lost"))
    fill_rate = round(total_sold / total_demand, 4) if total_demand else 0.0
    avg_inv = round(sum(rt.day_inventory_values) / n, 2)
    scrap_cost = round(rt.totals["scrap_cost"], 2)
    central_scrap = round(rt.totals["central_scrap_cost"], 2)

    # 逐批对账：仍在途的发货批次也要入账（位置记目的门店，源批次可溯源）
    for t in rt.in_transit:
        b = t.batch
        rt.ledger.setdefault(b.batch_id, LedgerRow(
            b.batch_id, b.product_id, b.location, b.expiry_date,
            b.source_batch_id, b.qty, arrival_date=t.arrival_date))
    recon_rows = []
    for bid, row in rt.ledger.items():
        if row.location == "central":
            end = row.start_qty - row.shipped_out_qty - row.scrap_qty
        else:
            end = row.start_qty - row.sold_qty - row.scrap_qty
        row.end_qty = end
        recon_rows.append((
            rt.run_id, bid, row.product_id, row.location, row.expiry_date,
            row.source_batch_id, row.start_qty, row.sold_qty, row.scrap_qty,
            row.shipped_out_qty, end, 1 if end >= 0 else 0))
    cur.executemany("INSERT INTO reconciliation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", recon_rows)

    # 全局守恒（按商品）：初始+到货 = 期末(中央+门店+在途) + 售出 + 报废
    supply = defaultdict(int)
    for r in conn.execute("SELECT product_id, SUM(qty) q FROM initial_batches GROUP BY product_id"):
        supply[r["product_id"]] += r["q"]
    for r in conn.execute("SELECT product_id, SUM(qty) q FROM central_arrivals GROUP BY product_id"):
        supply[r["product_id"]] += r["q"]
    remaining = defaultdict(int)
    for b in rt.central_batches:
        remaining[b.product_id] += b.qty
    for batches in rt.store_batches.values():
        for b in batches:
            remaining[b.product_id] += b.qty
    for t in rt.in_transit:
        remaining[t.batch.product_id] += t.batch.qty
    sold_p, scrap_p = defaultdict(int), defaultdict(int)
    for row in rt.ledger.values():
        sold_p[row.product_id] += row.sold_qty
        scrap_p[row.product_id] += row.scrap_qty
    conservation = {pid: supply[pid] == remaining[pid] + sold_p[pid] + scrap_p[pid]
                    for pid in rt.products}
    rt.totals["conservation_ok"] = all(conservation.values())

    # 中央仓发出量逐批对上：台账 shipped_out == 分配明细按源批次汇总
    alloc_sum = defaultdict(int)
    for a in allocs:
        alloc_sum[a["source_batch_id"]] += a["qty"]
    rt.totals["shipment_check_ok"] = all(
        row.shipped_out_qty == alloc_sum.get(bid, 0)
        for bid, row in rt.ledger.items() if row.location == "central")

    cur.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (rt.run_id, rt.strategy, STRATEGIES[rt.strategy],
                 datetime.now().isoformat(timespec="seconds"),
                 total_demand, total_sold, total_lost, fill_rate,
                 avg_inv, scrap_cost, central_scrap, int(rt.totals["gap"])))
    conn.commit()
