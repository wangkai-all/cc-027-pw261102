"""HTTP 端到端冒烟测试：启动服务后运行 `python e2e_test.py`。

覆盖：回放触发、两策略独立汇总、逐日快照、订单计算依据、缺口未发货、
逐批对账、全局守恒、前端所需全部接口的结构完整性。
"""
from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method: str, path: str):
    req = urllib.request.Request(BASE + path, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  ✔ {msg}")


def main() -> None:
    print("1) 触发回放")
    res = call("POST", "/api/replay")
    check(res["status"] == "ok", "回放返回 ok")
    for sid in ("rop", "cycle"):
        check(res["strategies"][sid]["conservation_ok"], f"{sid} 全局守恒")
        check(res["strategies"][sid]["shipment_check_ok"], f"{sid} 逐批发出核对")

    print("2) 输入与运行汇总")
    cfg = call("GET", "/api/config")
    check(len(cfg["products"]) == 4, "4 种商品")
    check(len(cfg["stores"]) == 3, "3 家门店")
    check(len(cfg["dates"]) == 14, "14 天日期轴")
    demand = call("GET", "/api/demand")
    check(len(demand) == 14 * 3 * 4, "逐日需求 168 行")
    runs = call("GET", "/api/runs")
    check({r["run_id"] for r in runs} == {"rop", "cycle"}, "两个策略各一条 run")
    check(abs(sum(r["total_demand"] for r in runs) / 2 - 2547) < 1, "总需求两策略一致（同一段历史）")

    for rid in ("rop", "cycle"):
        print(f"3) 策略 {rid} 逐日数据结构")
        snaps = call("GET", f"/api/snapshots?run_id={rid}")
        check(len(snaps) == 14 * 3 * 4, f"{rid} 快照 168 行")
        check(all(s["demand_qty"] == s["sold_qty"] + s["lost_qty"] for s in snaps),
              "需求=销量+损失，无负库存")
        central = call("GET", f"/api/central-snapshots?run_id={rid}")
        check(len(central) == 14 * 4, f"{rid} 中央仓快照 56 行")
        orders = call("GET", f"/api/orders?run_id={rid}")
        check(all(o["allocated_qty"] + o["gap_qty"] == o["requested_qty"] for o in orders),
              "实发+缺口=申请，缺口未被当成发货")

        print(f"4) 策略 {rid} 订单计算依据可追溯")
        for o in orders[:3]:
            detail = call("GET", f"/api/orders/{o['order_id']}")
            check(len(detail["basis"]["steps"]) >= 5, "计算依据步骤完整")
            check(sum(a["qty"] for a in detail["allocations"]) == o["allocated_qty"],
                  "逐批分配合计=订单实发")
            for a in detail["allocations"]:
                check(a["arrival_date"] > o["date"], "到货日晚于发出日")
        none_orders = [o for o in orders if o["status"] == "none"]
        for o in none_orders:
            detail = call("GET", f"/api/orders/{o['order_id']}")
            check(not detail["allocations"], "未发货订单无分配明细，全部保留为缺口")

        print(f"5) 策略 {rid} 对账")
        recon = call("GET", f"/api/reconciliation?run_id={rid}")
        check(recon["conservation_ok"], "按商品数量守恒")
        check(recon["shipment_match_ok"], "中央仓→门店逐批数量对上")
        check(recon["all_balanced"], "全部批次台账平衡")
        check(all(s["shipped_out_qty"] == s["received_qty"]
                  for s in recon["shipment_match"]), "每个中央批次发出=落地")

    print("6) 对比接口")
    compare = call("GET", "/api/compare")
    check(len(compare["by_store"]) == 6 and len(compare["by_product"]) == 8,
          "分门店/分商品指标齐全")
    check(len(compare["daily"]) == 28, "逐日对比 28 行（14 天 × 2 策略）")

    print("\n全部 HTTP 端到端检查通过 ✔")


if __name__ == "__main__":
    main()
