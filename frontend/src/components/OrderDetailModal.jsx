import { useEffect, useState } from 'react'
import { api } from '../api'

const STATUS_LABEL = { full: '全额满足', partial: '部分满足', none: '未发货' }
const REASON_LABEL = {
  below_reorder_point: '库存低于补货点',
  scheduled_review: '三日周期评审日',
}

const EVENT_LABEL = {
  order_placed: '生成补货单', allocation: '中央仓发出',
  receive: '门店收货', store_scrap: '门店报废', central_scrap: '中央仓报废',
  sale: 'FEFO 销售扣减', lost_sale: '损失需求',
  order_skipped: '触发但无需下单', central_inbound: '中央仓到货',
}

/** 点击一笔补货：展示当时的完整计算依据与逐批分配。 */
export default function OrderDetailModal({ orderId, onClose }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.orderDetail(orderId).then(setData).catch((e) => setError(String(e)))
  }, [orderId])

  if (error) return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        加载失败：{error}
      </div>
    </div>
  )
  if (!data) return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>加载中…</div>
    </div>
  )

  const { order, allocations, context_events, basis } = data
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>补货单 {order.order_id}</h2>
            <div className="muted" style={{ marginTop: 4 }}>
              {order.date} · {order.store_name} · {order.product_name} ·
              <span className={`pill ${order.run_id}`} style={{ marginLeft: 6 }}>
                {basis.rule}
              </span>
            </div>
          </div>
          <button className="close-x" onClick={onClose}>✕</button>
        </div>

        <h3>触发原因</h3>
        <p>{REASON_LABEL[order.trigger_reason] || order.trigger_reason}，
          订单状态：<span className={`pill ${order.status}`}>{STATUS_LABEL[order.status]}</span>
        </p>

        <h3>计算依据（仅使用 {order.date} 当日及以前可见的信息）</h3>
        <div className="formula-box">{basis.formula}</div>
        <div className="kv-grid">
          <div className="kv"><div className="k">目标量</div><div className="v">{basis.inputs.target_qty}</div></div>
          <div className="kv"><div className="k">决策时现有库存</div><div className="v">{basis.inputs.on_hand_at_decision}</div></div>
          <div className="kv"><div className="k">决策时在途量</div><div className="v">{basis.inputs.in_transit_at_decision}</div></div>
          <div className="kv"><div className="k">裸需求 raw</div><div className="v">{basis.inputs.raw_needed}</div></div>
          <div className="kv"><div className="k">整箱规格</div><div className="v">{basis.inputs.case_size}</div></div>
          <div className="kv"><div className="k">补货点</div><div className="v">{basis.inputs.reorder_point}</div></div>
          <div className="kv"><div className="k">整箱申请量</div><div className="v">{order.requested_qty}</div></div>
          <div className="kv"><div className="k">中央仓实发</div><div className="v">{order.allocated_qty}</div></div>
          <div className="kv"><div className="k">未满足缺口（未发货）</div>
            <div className="v negative">{order.gap_qty}</div></div>
        </div>
        <ol className="steps">
          {basis.steps.map((s, i) => <li key={i}>{s}</li>)}
        </ol>

        <h3>中央仓逐批分配（保留原有效期与单位成本）</h3>
        {allocations.length === 0 ? (
          <p className="negative">中央仓无库存可发，申请量 {order.requested_qty} 全部保留为缺口，不计入在途。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>中央仓源批次</th><th className="num">发出数量</th>
                <th>原有效期</th><th className="num">单位成本</th><th>到货日</th>
              </tr>
            </thead>
            <tbody>
              {allocations.map((a) => (
                <tr key={a.allocation_id}>
                  <td>{a.source_batch_id}</td>
                  <td className="num">{a.qty}</td>
                  <td>{a.expiry_date}</td>
                  <td className="num">{a.unit_cost.toFixed(2)}</td>
                  <td>{a.arrival_date}<span className="muted">（发出日 + {order.lead_days} 天）</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <h3 style={{ marginTop: 16 }}>当日相关事件时间线</h3>
        {context_events.length === 0 ? <p className="muted">无</p> :
          context_events.map((e) => (
            <div key={e.event_id} className={`event-line ${e.type}`}>
              <span className="seq">#{e.seq}</span>
              <strong>{EVENT_LABEL[e.type] || e.type}</strong>
              {e.batch_id ? ` · 批次 ${e.batch_id}` : ''}
              {e.qty != null ? ` · ${e.qty} ${order.unit}` : ''}
              {e.amount != null ? ` · 金额 ${e.amount.toFixed(2)}` : ''}
              <div className="muted" style={{ marginTop: 2 }}>{e.detail}</div>
            </div>
          ))}
      </div>
    </div>
  )
}
