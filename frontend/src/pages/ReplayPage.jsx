import { useEffect, useMemo, useState } from 'react'
import Chart, { COLORS, lineAxis } from '../components/Chart.jsx'
import OrderDetailModal from '../components/OrderDetailModal.jsx'
import { api } from '../api'

const STATUS_LABEL = { full: '全额满足', partial: '部分满足', none: '未发货' }
const REASON_LABEL = {
  below_reorder_point: '低于补货点',
  scheduled_review: '周期评审',
}
const EVENT_LABEL = {
  central_inbound: '中央仓到货', central_scrap: '中央仓报废',
  receive: '门店收货', store_scrap: '门店报废',
  sale: 'FEFO 销售', lost_sale: '损失需求',
  allocation: '中央仓发出', order_placed: '生成补货单', order_skipped: '跳过下单',
}
const shortDate = (iso) => iso.slice(5)

export default function ReplayPage({ config, runs }) {
  const [runId, setRunId] = useState('rop')
  const [dayIdx, setDayIdx] = useState(0)
  const [storeId, setStoreId] = useState('ALL')
  const [productId, setProductId] = useState('ALL')
  const [snapshots, setSnapshots] = useState([])
  const [central, setCentral] = useState([])
  const [orders, setOrders] = useState([])
  const [events, setEvents] = useState([])
  const [loadedRun, setLoadedRun] = useState('')
  const [modalOrder, setModalOrder] = useState(null)
  const [loading, setLoading] = useState(false)

  const dates = config.dates || []
  const day = dates[dayIdx]

  // 切换策略时一次性拉取该策略全部数据
  const ensureRun = async (rid) => {
    if (loadedRun === rid) return
    setLoading(true)
    try {
      const [sn, cs, os, ev] = await Promise.all([
        api.snapshots(rid), api.centralSnapshots(rid),
        api.orders(rid), api.events(rid),
      ])
      setSnapshots(sn); setCentral(cs); setOrders(os); setEvents(ev)
      setLoadedRun(rid)
    } finally { setLoading(false) }
  }

  useEffect(() => { ensureRun(runId) }, [runId])

  const daySnaps = snapshots.filter((s) => s.date === day)
  const visibleSnaps = daySnaps.filter((s) =>
    (storeId === 'ALL' || s.store_id === storeId) &&
    (productId === 'ALL' || s.product_id === productId))
  const dayOrders = orders.filter((o) => o.date === day &&
    (storeId === 'ALL' || o.store_id === storeId) &&
    (productId === 'ALL' || o.product_id === productId))
  const dayEvents = events.filter((e) => e.date === day &&
    (storeId === 'ALL' || !e.store_id || e.store_id === storeId) &&
    (productId === 'ALL' || !e.product_id || e.product_id === productId))
  const dayCentral = central.filter((c) => c.date === day &&
    (productId === 'ALL' || c.product_id === productId))

  // 截至当天的逐日序列（库存金额、损失、报废、在途）
  const seriesUpToDay = useMemo(() => {
    const byDate = new Map()
    for (const s of snapshots) {
      if (!byDate.has(s.date)) byDate.set(s.date, { value: 0, lost: 0, scrap: 0, transit: 0, sold: 0, demand: 0 })
      const r = byDate.get(s.date)
      if (storeId === 'ALL' || s.store_id === storeId) {
        r.value += s.on_hand_value; r.lost += s.lost_qty
        r.scrap += s.scrap_cost; r.transit += s.in_transit
        r.sold += s.sold_qty; r.demand += s.demand_qty
      }
    }
    return [...byDate.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [snapshots, storeId])

  const upto = seriesUpToDay.slice(0, dayIdx + 1)
  const invOption = lineAxis({
    rest: {
      tooltip: { ...lineAxis().tooltip, valueFormatter: (v) => v?.toFixed?.(2) ?? v },
      xAxis: { data: upto.map(([d]) => shortDate(d)) },
      yAxis: { name: '元', nameTextStyle: { color: '#898781' } },
      series: [{
        name: '门店库存金额', type: 'line', smooth: false, symbol: 'circle', symbolSize: 8,
        lineStyle: { width: 2, color: COLORS.rop }, itemStyle: { color: COLORS.rop },
        areaStyle: { color: 'rgba(42,120,214,0.10)' },
        data: upto.map(([, r]) => r.value),
        markLine: { silent: true, symbol: 'none', lineStyle: { color: COLORS.cycle, type: 'dashed' },
          label: { formatter: '当天', color: COLORS.cycle },
          data: [{ xAxis: dayIdx }] },
      }],
    },
  })

  const lostOption = lineAxis({
    rest: {
      xAxis: { data: upto.map(([d]) => shortDate(d)) },
      yAxis: { name: '件', nameTextStyle: { color: '#898781' } },
      series: [
        { name: '损失需求(件)', type: 'bar', barMaxWidth: 18, itemStyle: { color: COLORS.lost, borderRadius: [4, 4, 0, 0] }, data: upto.map(([, r]) => r.lost) },
      ],
    },
  })

  const scrapOption = lineAxis({
    rest: {
      xAxis: { data: upto.map(([d]) => shortDate(d)) },
      yAxis: { name: '元', nameTextStyle: { color: '#898781' } },
      series: [
        { name: '报废成本(元)', type: 'line', symbol: 'circle', symbolSize: 8, lineStyle: { width: 2, color: COLORS.scrap }, itemStyle: { color: COLORS.scrap }, areaStyle: { color: 'rgba(236,131,90,0.10)' }, data: upto.map(([, r]) => r.scrap) },
      ],
    },
  })

  const dayTotals = visibleSnaps.reduce((acc, s) => {
    acc.onHand += s.on_hand; acc.transit += s.in_transit
    acc.demand += s.demand_qty; acc.sold += s.sold_qty
    acc.lost += s.lost_qty; acc.scrapQty += s.scrap_qty; acc.scrapCost += s.scrap_cost
    return acc
  }, { onHand: 0, transit: 0, demand: 0, sold: 0, lost: 0, scrapQty: 0, scrapCost: 0 })

  return (
    <div>
      <div className="filters">
        <label>策略
          <select value={runId} onChange={(e) => setRunId(e.target.value)}>
            {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.label}</option>)}
          </select>
        </label>
        <label>门店
          <select value={storeId} onChange={(e) => setStoreId(e.target.value)}>
            <option value="ALL">全部门店</option>
            {config.stores?.map((s) => <option key={s.store_id} value={s.store_id}>{s.name}</option>)}
          </select>
        </label>
        <label>商品
          <select value={productId} onChange={(e) => setProductId(e.target.value)}>
            <option value="ALL">全部商品</option>
            {config.products?.map((p) => <option key={p.product_id} value={p.product_id}>{p.name}</option>)}
          </select>
        </label>
        <button className="btn ghost" disabled={dayIdx === 0} onClick={() => setDayIdx(dayIdx - 1)}>← 前一天</button>
        <button className="btn ghost" disabled={dayIdx >= dates.length - 1} onClick={() => setDayIdx(dayIdx + 1)}>后一天 →</button>
        {loading && <span className="muted">加载中…</span>}
      </div>

      <div className="day-strip">
        {dates.map((d, i) => (
          <button key={d} className={`day-btn ${i === dayIdx ? 'active' : ''}`} onClick={() => setDayIdx(i)}>
            {shortDate(d)}
          </button>
        ))}
      </div>

      <div className="grid cols-4">
        <div className="kpi"><div className="label">当日现有库存（件）</div><div className="value">{dayTotals.onHand}</div></div>
        <div className="kpi"><div className="label">在途量（件）</div><div className="value" style={{ color: COLORS.violet }}>{dayTotals.transit}</div></div>
        <div className="kpi"><div className="label">损失需求（件）</div>
          <div className="value negative">{dayTotals.lost}</div>
          <div className="delta neutral">需求 {dayTotals.demand} / 满足 {dayTotals.sold}</div></div>
        <div className="kpi"><div className="label">当日报废</div>
          <div className="value" style={{ color: COLORS.scrap }}>{dayTotals.scrapQty} 件</div>
          <div className="delta neutral">{dayTotals.scrapCost.toFixed(2)} 元</div></div>
      </div>

      <div className="grid cols-2">
        <div className="card"><h2>门店库存金额走势（截至当天）</h2><Chart option={invOption} /></div>
        <div className="card"><h2>损失需求走势（截至当天）</h2><Chart option={lostOption} /></div>
      </div>
      <div className="card"><h2>临期报废成本走势（截至当天）</h2><Chart option={scrapOption} /></div>

      <div className="card">
        <h2>{day} 门店 × 商品 库存明细</h2>
        <table>
          <thead>
            <tr>
              <th>门店</th><th>商品</th><th className="num">现有</th><th className="num">在途</th>
              <th className="num">需求</th><th className="num">销量</th><th className="num">损失</th>
              <th className="num">报废件数</th><th className="num">库存金额</th>
            </tr>
          </thead>
          <tbody>
            {visibleSnaps.map((s) => (
              <tr key={`${s.store_id}-${s.product_id}`}>
                <td>{s.store_name}</td><td>{s.product_name}</td>
                <td className="num">{s.on_hand}</td>
                <td className="num" style={{ color: COLORS.violet }}>{s.in_transit}</td>
                <td className="num">{s.demand_qty}</td>
                <td className="num">{s.sold_qty}</td>
                <td className={`num ${s.lost_qty ? 'negative' : ''}`}>{s.lost_qty}</td>
                <td className={`num ${s.scrap_qty ? 'warning-text' : ''}`}>{s.scrap_qty}</td>
                <td className="num">{s.on_hand_value.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>{day} 日终补货单（点击查看计算依据）</h2>
          {dayOrders.length === 0 ? <p className="muted">当日无补货单</p> : (
            <table>
              <thead>
                <tr><th>门店</th><th>商品</th><th>触发</th><th className="num">申请</th>
                  <th className="num">实发</th><th className="num">缺口</th><th>状态</th></tr>
              </thead>
              <tbody>
                {dayOrders.map((o) => (
                  <tr key={o.order_id} className="clickable" onClick={() => setModalOrder(o.order_id)}>
                    <td>{o.store_name}</td><td>{o.product_name}</td>
                    <td>{REASON_LABEL[o.trigger_reason]}</td>
                    <td className="num">{o.requested_qty}</td>
                    <td className="num">{o.allocated_qty}</td>
                    <td className={`num ${o.gap_qty ? 'negative' : ''}`}>{o.gap_qty}</td>
                    <td><span className={`pill ${o.status}`}>{STATUS_LABEL[o.status]}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h2>{day} 中央仓库存</h2>
          <table>
            <thead><tr><th>商品</th><th className="num">现有</th><th className="num">当日到货</th>
              <th className="num">当日报废</th><th className="num">库存金额</th></tr></thead>
            <tbody>
              {dayCentral.map((c) => (
                <tr key={c.product_id}>
                  <td>{c.product_name}</td>
                  <td className="num">{c.on_hand}</td>
                  <td className="num">{c.inbound_qty}</td>
                  <td className={`num ${c.scrap_qty ? 'warning-text' : ''}`}>{c.scrap_qty}</td>
                  <td className="num">{c.on_hand_value.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>{day} 事件时间线（顺序：收货 → 剔除 → 需求 → 补货）</h2>
        {dayEvents.length === 0 ? <p className="muted">无事件</p> :
          dayEvents.map((e) => (
            <div key={e.event_id} className={`event-line ${e.type}`}>
              <span className="seq">#{e.seq}</span>
              <strong>{EVENT_LABEL[e.type] || e.type}</strong>
              {e.store_id ? ` · ${e.store_id}` : ''}
              {e.product_id ? ` · ${e.product_id}` : ''}
              {e.batch_id ? ` · ${e.batch_id}` : ''}
              {e.qty != null ? ` · ${e.qty} 件` : ''}
              {e.amount != null ? ` · ${e.amount.toFixed(2)} 元` : ''}
              <div className="muted" style={{ marginTop: 2 }}>{e.detail}</div>
            </div>
          ))}
      </div>

      {modalOrder && <OrderDetailModal orderId={modalOrder} onClose={() => setModalOrder(null)} />}
    </div>
  )
}
