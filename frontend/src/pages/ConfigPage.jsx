import { useMemo, useState } from 'react'
import { api } from '../api'

export default function ConfigPage({ config, demand }) {
  const [tab, setTab] = useState('products')
  const [demandStore, setDemandStore] = useState('ALL')

  const visibleDemand = useMemo(() =>
    demand.filter((d) => demandStore === 'ALL' || d.store_id === demandStore),
    [demand, demandStore])

  const storeName = (id) => config.stores?.find((s) => s.store_id === id)?.name || id
  const productName = (id) => config.products?.find((p) => p.product_id === id)?.name || id

  return (
    <div>
      <div className="tabs">
        <button className={`tab ${tab === 'products' ? 'active' : ''}`} onClick={() => setTab('products')}>商品与策略参数</button>
        <button className={`tab ${tab === 'batches' ? 'active' : ''}`} onClick={() => setTab('batches')}>初始批次</button>
        <button className={`tab ${tab === 'arrivals' ? 'active' : ''}`} onClick={() => setTab('arrivals')}>中央仓到货</button>
        <button className={`tab ${tab === 'demand' ? 'active' : ''}`} onClick={() => setTab('demand')}>逐日真实需求</button>
      </div>

      {tab === 'products' && (
        <div className="card">
          <h2>商品</h2>
          <table>
            <thead><tr><th>编号</th><th>名称</th><th>单位</th><th className="num">整箱规格</th>
              <th className="num">单位成本</th><th className="num">保质期(天)</th></tr></thead>
            <tbody>
              {config.products?.map((p) => (
                <tr key={p.product_id}>
                  <td>{p.product_id}</td><td>{p.name}</td><td>{p.unit}</td>
                  <td className="num">{p.case_size}</td>
                  <td className="num">{p.unit_cost.toFixed(2)}</td>
                  <td className="num">{p.shelf_life_days}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h2 style={{ marginTop: 20 }}>门店与补货策略（同一参数供两种策略回放）</h2>
          <table>
            <thead><tr><th>门店</th><th>优先级(小者优先)</th><th className="num">配送天数</th>
              <th>商品</th><th className="num">补货点</th><th className="num">目标量</th></tr></thead>
            <tbody>
              {config.stores?.flatMap((s) =>
                config.policies?.filter((p) => p.store_id === s.store_id).map((p) => (
                  <tr key={`${p.store_id}-${p.product_id}`}>
                    <td>{s.name}（{s.store_id}）</td>
                    <td>{s.priority}</td>
                    <td className="num">{s.default_lead_days}</td>
                    <td>{productName(p.product_id)}</td>
                    <td className="num">{p.reorder_point}</td>
                    <td className="num">{p.target_qty}</td>
                  </tr>
                )))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'batches' && (
        <div className="card">
          <h2>初始批次库存（带有效期与单位成本）</h2>
          <table>
            <thead><tr><th>批次号</th><th>位置</th><th>商品</th><th className="num">数量</th>
              <th>有效期</th><th className="num">单位成本</th></tr></thead>
            <tbody>
              {config.initial_batches?.map((b) => (
                <tr key={b.batch_id}>
                  <td style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12 }}>{b.batch_id}</td>
                  <td>{b.location === 'central' ? '中央仓' : storeName(b.location)}</td>
                  <td>{productName(b.product_id)}</td>
                  <td className="num">{b.qty}</td>
                  <td>{b.expiry_date}</td>
                  <td className="num">{b.unit_cost.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'arrivals' && (
        <div className="card">
          <h2>中央仓到货计划</h2>
          <table>
            <thead><tr><th>到货日</th><th>到货单号</th><th>商品</th><th className="num">数量</th>
              <th>有效期</th><th className="num">单位成本</th></tr></thead>
            <tbody>
              {config.central_arrivals?.map((a) => (
                <tr key={a.arrival_id}>
                  <td>{a.arrival_date}</td>
                  <td style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12 }}>{a.arrival_id}</td>
                  <td>{productName(a.product_id)}</td>
                  <td className="num">{a.qty}</td>
                  <td>{a.expiry_date}</td>
                  <td className="num">{a.unit_cost.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'demand' && (
        <div className="card">
          <div className="filters">
            <label>门店
              <select value={demandStore} onChange={(e) => setDemandStore(e.target.value)}>
                <option value="ALL">全部门店</option>
                {config.stores?.map((s) => <option key={s.store_id} value={s.store_id}>{s.name}</option>)}
              </select>
            </label>
            <span className="muted">共 {visibleDemand.length} 条门店×商品×日需求</span>
          </div>
          <table>
            <thead><tr><th>日期</th><th>门店</th><th>商品</th><th className="num">真实需求量</th></tr></thead>
            <tbody>
              {visibleDemand.map((d) => (
                <tr key={`${d.date}-${d.store_id}-${d.product_id}`}>
                  <td>{d.date}</td><td>{storeName(d.store_id)}</td>
                  <td>{productName(d.product_id)}</td>
                  <td className="num">{d.qty}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
