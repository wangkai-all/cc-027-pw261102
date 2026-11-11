import { useEffect, useMemo, useState } from 'react'
import Chart, { COLORS, lineAxis } from '../components/Chart.jsx'
import { api } from '../api'

const shortDate = (iso) => iso.slice(5)

function pct(x) { return `${(x * 100).toFixed(2)}%` }
function money(x) { return `${Number(x).toFixed(2)}` }

function Delta({ value, invert = false, suffix = '' }) {
  if (value === 0 || Number.isNaN(value)) return <span className="delta neutral">持平</span>
  const good = invert ? value < 0 : value > 0
  return (
    <span className={`delta ${good ? 'up' : 'down'}`}>
      {value > 0 ? '+' : ''}{value.toFixed(2)}{suffix} {good ? '▲ 更优' : '▼ 更差'}
    </span>
  )
}

export default function ComparePage() {
  const [data, setData] = useState(null)
  useEffect(() => { api.compare().then(setData) }, [])

  const [dim, setDim] = useState('store')

  const rop = data?.runs?.find((r) => r.run_id === 'rop')
  const cyc = data?.runs?.find((r) => r.run_id === 'cycle')

  const dailyOption = useMemo(() => {
    if (!data) return null
    const dates = [...new Set(data.daily.map((d) => d.date))].sort()
    const pick = (rid, key) => dates.map((d) =>
      data.daily.find((x) => x.date === d && x.run_id === rid)?.[key] ?? 0)
    return lineAxis({
      rest: {
        xAxis: { data: dates.map(shortDate) },
        yAxis: { name: '元', nameTextStyle: { color: '#898781' } },
        series: [
          { name: '低于补货点', type: 'line', symbol: 'circle', symbolSize: 7, lineStyle: { width: 2, color: COLORS.rop }, itemStyle: { color: COLORS.rop }, data: pick('rop', 'inventory_value') },
          { name: '每三天', type: 'line', symbol: 'circle', symbolSize: 7, lineStyle: { width: 2, color: COLORS.cycle }, itemStyle: { color: COLORS.cycle }, data: pick('cycle', 'inventory_value') },
        ],
      },
    })
  }, [data])

  const fillOption = useMemo(() => {
    if (!data) return null
    const dates = [...new Set(data.daily.map((d) => d.date))].sort()
    const rate = (rid) => dates.map((d) => {
      const x = data.daily.find((z) => z.date === d && z.run_id === rid)
      return x && x.demand_qty ? Number((x.sold_qty / x.demand_qty * 100).toFixed(2)) : 0
    })
    return lineAxis({
      rest: {
        xAxis: { data: dates.map(shortDate) },
        yAxis: { name: '%', nameTextStyle: { color: '#898781' }, max: 100 },
        series: [
          { name: '低于补货点 满足率', type: 'line', symbol: 'circle', symbolSize: 7, lineStyle: { width: 2, color: COLORS.rop }, itemStyle: { color: COLORS.rop }, data: rate('rop') },
          { name: '每三天 满足率', type: 'line', symbol: 'circle', symbolSize: 7, lineStyle: { width: 2, color: COLORS.cycle }, itemStyle: { color: COLORS.cycle }, data: rate('cycle') },
        ],
      },
    })
  }, [data])

  const lostOption = useMemo(() => {
    if (!data) return null
    const dates = [...new Set(data.daily.map((d) => d.date))].sort()
    const pick = (rid) => dates.map((d) =>
      data.daily.find((x) => x.date === d && x.run_id === rid)?.lost_qty ?? 0)
    return lineAxis({
      rest: {
        xAxis: { data: dates.map(shortDate) },
        yAxis: { name: '件', nameTextStyle: { color: '#898781' } },
        series: [
          { name: '低于补货点 损失', type: 'bar', barMaxWidth: 14, itemStyle: { color: COLORS.rop, borderRadius: [4, 4, 0, 0] }, data: pick('rop') },
          { name: '每三天 损失', type: 'bar', barMaxWidth: 14, itemStyle: { color: COLORS.cycle, borderRadius: [4, 4, 0, 0] }, data: pick('cycle') },
        ],
      },
    })
  }, [data])

  if (!data || !rop || !cyc) return <p className="muted">加载中…（若为空请先在顶部运行回放）</p>

  const dimRows = dim === 'store' ? data.by_store : data.by_product
  const dimName = (r) => dim === 'store' ? (r.store_name || r.store_id) : (r.product_name || r.product_id)

  return (
    <div>
      <div className="grid cols-3">
        <div className="kpi">
          <div className="label">需求满足率</div>
          <div style={{ display: 'flex', gap: 18, marginTop: 6 }}>
            <div><span style={{ color: COLORS.rop, fontWeight: 700 }}>补货点</span>
              <div className="value" style={{ fontSize: 20 }}>{pct(rop.fill_rate)}</div></div>
            <div><span style={{ color: COLORS.cycle, fontWeight: 700 }}>三天</span>
              <div className="value" style={{ fontSize: 20 }}>{pct(cyc.fill_rate)}</div></div>
          </div>
          <Delta value={(cyc.fill_rate - rop.fill_rate) * 100} suffix="pp" />
        </div>
        <div className="kpi">
          <div className="label">平均库存金额（元，14 天均值）</div>
          <div style={{ display: 'flex', gap: 18, marginTop: 6 }}>
            <div><span style={{ color: COLORS.rop, fontWeight: 700 }}>补货点</span>
              <div className="value" style={{ fontSize: 20 }}>{money(rop.avg_inventory_value)}</div></div>
            <div><span style={{ color: COLORS.cycle, fontWeight: 700 }}>三天</span>
              <div className="value" style={{ fontSize: 20 }}>{money(cyc.avg_inventory_value)}</div></div>
          </div>
          <Delta value={cyc.avg_inventory_value - rop.avg_inventory_value} invert suffix=" 元" />
        </div>
        <div className="kpi">
          <div className="label">门店临期报废成本（元）</div>
          <div style={{ display: 'flex', gap: 18, marginTop: 6 }}>
            <div><span style={{ color: COLORS.rop, fontWeight: 700 }}>补货点</span>
              <div className="value" style={{ fontSize: 20 }}>{money(rop.scrap_cost)}</div></div>
            <div><span style={{ color: COLORS.cycle, fontWeight: 700 }}>三天</span>
              <div className="value" style={{ fontSize: 20 }}>{money(cyc.scrap_cost)}</div></div>
          </div>
          <Delta value={cyc.scrap_cost - rop.scrap_cost} invert suffix=" 元" />
        </div>
      </div>

      <div className="grid cols-3" style={{ marginTop: 16 }}>
        <div className="kpi"><div className="label">总需求 / 总损失（补货点）</div>
          <div className="value" style={{ fontSize: 20 }}>{rop.total_demand} / <span className="negative">{rop.total_lost}</span></div></div>
        <div className="kpi"><div className="label">总需求 / 总损失（三天）</div>
          <div className="value" style={{ fontSize: 20 }}>{cyc.total_demand} / <span className="negative">{cyc.total_lost}</span></div></div>
        <div className="kpi"><div className="label">中央仓报废成本（另计）</div>
          <div className="value" style={{ fontSize: 20 }}>
            <span style={{ color: COLORS.rop }}>{money(rop.central_scrap_cost)}</span>
            {' / '}
            <span style={{ color: COLORS.cycle }}>{money(cyc.central_scrap_cost)}</span>
          </div>
          <div className="delta neutral">补货点 / 三天</div></div>
      </div>

      <div className="grid cols-2" style={{ marginTop: 16 }}>
        <div className="card"><h2>逐日门店库存金额</h2><Chart option={dailyOption} /></div>
        <div className="card"><h2>逐日需求满足率</h2><Chart option={fillOption} /></div>
      </div>
      <div className="card"><h2>逐日损失需求对比</h2><Chart option={lostOption} /></div>

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0 }}>分维度明细</h2>
          <div className="filters" style={{ margin: 0 }}>
            <button className={`btn ${dim === 'store' ? '' : 'ghost'}`} onClick={() => setDim('store')}>按门店</button>
            <button className={`btn ${dim === 'product' ? '' : 'ghost'}`} onClick={() => setDim('product')}>按商品</button>
          </div>
        </div>
        <table style={{ marginTop: 10 }}>
          <thead>
            <tr>
              <th>策略</th><th>{dim === 'store' ? '门店' : '商品'}</th>
              <th className="num">需求</th><th className="num">销量</th><th className="num">损失</th>
              <th className="num">满足率</th><th className="num">报废件</th><th className="num">报废成本</th>
              <th className="num">日均库存金额</th>
            </tr>
          </thead>
          <tbody>
            {dimRows.map((r) => (
              <tr key={`${r.run_id}-${r.store_id || r.product_id}`}>
                <td><span className={`pill ${r.run_id}`}>{r.run_id === 'rop' ? '补货点' : '三天'}</span></td>
                <td>{dimName(r)}<span className="muted" style={{ marginLeft: 6 }}>{r.store_id || r.product_id}</span></td>
                <td className="num">{r.demand_qty}</td>
                <td className="num">{r.sold_qty}</td>
                <td className={`num ${r.lost_qty ? 'negative' : ''}`}>{r.lost_qty}</td>
                <td className="num">{pct(r.fill_rate)}</td>
                <td className={`num ${r.scrap_qty ? 'warning-text' : ''}`}>{r.scrap_qty}</td>
                <td className="num">{money(r.scrap_cost)}</td>
                <td className="num">{money(r.avg_inventory_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
