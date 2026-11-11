import { useEffect, useState } from 'react'
import { api } from '../api'

function CheckBadge({ ok, label }) {
  return (
    <div className="kpi">
      <div className="label">{label}</div>
      <div className="value" style={{ fontSize: 19 }}>
        <span className={ok ? 'badge-ok' : 'badge-bad'}>{ok ? '✔ 通过' : '✘ 失败'}</span>
      </div>
    </div>
  )
}

export default function ReconciliationPage({ runs }) {
  const [runId, setRunId] = useState('rop')
  const [data, setData] = useState(null)
  const [locFilter, setLocFilter] = useState('ALL')

  useEffect(() => { api.reconciliation(runId).then(setData) }, [runId])
  if (!data) return <p className="muted">加载中…（若为空请先运行回放）</p>

  const locName = (loc) => loc === 'central' ? '中央仓' : loc
  const batches = data.batches.filter((b) => locFilter === 'ALL' || b.location === locFilter)

  return (
    <div>
      <div className="filters">
        <label>策略
          <select value={runId} onChange={(e) => setRunId(e.target.value)}>
            {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.label}</option>)}
          </select>
        </label>
        <label>批次位置
          <select value={locFilter} onChange={(e) => setLocFilter(e.target.value)}>
            <option value="ALL">全部</option>
            <option value="central">中央仓</option>
            <option value="S1">S1</option><option value="S2">S2</option><option value="S3">S3</option>
          </select>
        </label>
      </div>

      <div className="grid cols-3">
        <CheckBadge ok={data.conservation_ok} label="全局数量守恒（供应 = 期末库存 + 售出 + 报废）" />
        <CheckBadge ok={data.shipment_match_ok} label="中央仓→门店逐批数量对上" />
        <CheckBadge ok={data.all_balanced} label="全部批次台账平衡（无负结束量）" />
      </div>

      <div className="card">
        <h2>按商品守恒核对</h2>
        <table>
          <thead>
            <tr><th>商品</th><th className="num">总供应量</th><th className="num">期末库存</th>
              <th className="num">累计售出</th><th className="num">累计报废</th>
              <th className="num">库存+售出+报废</th><th>结果</th></tr>
          </thead>
          <tbody>
            {data.conservation.map((c) => (
              <tr key={c.product_id}>
                <td>{c.product_name}<span className="muted" style={{ marginLeft: 6 }}>{c.product_id}</span></td>
                <td className="num">{c.supply_qty}</td>
                <td className="num">{c.end_qty}</td>
                <td className="num">{c.sold_qty}</td>
                <td className="num">{c.scrap_qty}</td>
                <td className="num">{c.end_qty + c.sold_qty + c.scrap_qty}</td>
                <td>{c.conserved ? <span className="badge-ok">✔ 守恒</span> : <span className="badge-bad">✘ 差异 {c.supply_qty - c.end_qty - c.sold_qty - c.scrap_qty}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>中央仓批次发出量 vs 门店/在途落地量（逐批对上）</h2>
        <table>
          <thead>
            <tr><th>中央仓批次</th><th>商品</th><th className="num">台账发出量</th>
              <th className="num">门店落地量</th><th>流向门店</th><th>结果</th></tr>
          </thead>
          <tbody>
            {data.shipment_match.map((s) => (
              <tr key={s.central_batch}>
                <td>{s.central_batch}</td>
                <td>{s.product_id}</td>
                <td className="num">{s.shipped_out_qty}</td>
                <td className="num">{s.received_qty}</td>
                <td>{s.destinations || <span className="muted">未发出</span>}</td>
                <td>{s.shipped_out_qty === s.received_qty
                  ? <span className="badge-ok">✔ 一致</span>
                  : <span className="badge-bad">✘ 差异 {s.shipped_out_qty - s.received_qty}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>逐批台账（共 {data.batches.length} 个批次，当前显示 {batches.length}）</h2>
        <table>
          <thead>
            <tr><th>批次号</th><th>位置</th><th>商品</th><th>有效期</th>
              <th>溯源源批次</th><th className="num">起始</th><th className="num">售出</th>
              <th className="num">报废</th><th className="num">中央发出</th><th className="num">期末</th><th>平衡</th></tr>
          </thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.batch_id}>
                <td style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12 }}>{b.batch_id}</td>
                <td>{locName(b.location)}</td>
                <td>{b.product_name}</td>
                <td>{b.expiry_date}</td>
                <td className="muted" style={{ fontSize: 12 }}>{b.source_batch_id || '—'}</td>
                <td className="num">{b.start_qty}</td>
                <td className="num">{b.sold_qty}</td>
                <td className={`num ${b.scrap_qty ? 'warning-text' : ''}`}>{b.scrap_qty}</td>
                <td className="num">{b.shipped_out_qty}</td>
                <td className="num">{b.end_qty}</td>
                <td>{b.balanced ? <span className="badge-ok">✔</span> : <span className="badge-bad">✘</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
