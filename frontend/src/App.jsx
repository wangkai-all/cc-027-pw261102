import { useEffect, useState } from 'react'
import { api } from './api'
import ReplayPage from './pages/ReplayPage.jsx'
import ComparePage from './pages/ComparePage.jsx'
import ReconciliationPage from './pages/ReconciliationPage.jsx'
import ConfigPage from './pages/ConfigPage.jsx'

const TABS = [
  { key: 'replay', label: '逐日回放' },
  { key: 'compare', label: '策略对比' },
  { key: 'recon', label: '批次对账' },
  { key: 'config', label: '输入数据' },
]

export default function App() {
  const [tab, setTab] = useState('replay')
  const [config, setConfig] = useState(null)
  const [demand, setDemand] = useState([])
  const [runs, setRuns] = useState([])
  const [replaying, setReplaying] = useState(false)
  const [toast, setToast] = useState('')

  const refreshMeta = async () => {
    const [cfg, dmd, rn] = await Promise.all([api.config(), api.demand(), api.runs()])
    setConfig(cfg); setDemand(dmd); setRuns(rn)
  }

  useEffect(() => { refreshMeta() }, [])

  const runReplay = async () => {
    setReplaying(true)
    try {
      const res = await api.replay()
      const checks = Object.entries(res.strategies).map(([k, v]) =>
        `${k}: 守恒${v.conservation_ok ? '✔' : '✘'} 逐批${v.shipment_check_ok ? '✔' : '✘'}`)
      setToast(`回放完成：${checks.join('；')}`)
      await refreshMeta()
    } catch (e) {
      setToast(`回放失败：${e}`)
    } finally {
      setReplaying(false)
      setTimeout(() => setToast(''), 6000)
    }
  }

  return (
    <div className="app">
      <div className="app-header">
        <div>
          <h1>补货规则回放：低于补货点 vs 每三天补到目标量</h1>
          <div className="sub">
            同一段历史需求 · 同一初始状态独立运行 · FEFO 销售 · 中央仓有限按优先级分配 ·
            14 天 / {config?.stores?.length || 3} 家门店 / {config?.products?.length || 4} 种商品
          </div>
        </div>
        <button className="btn" onClick={runReplay} disabled={replaying}>
          {replaying ? '回放计算中…' : '重新运行回放'}
        </button>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={`tab ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {!config ? <p className="muted">加载中…</p> : (
        <>
          {tab === 'replay' && <ReplayPage config={config} runs={runs.length ? runs : [
            { run_id: 'rop', label: '低于补货点补到目标量' },
            { run_id: 'cycle', label: '每三天补到目标量' },
          ]} />}
          {tab === 'compare' && <ComparePage />}
          {tab === 'recon' && <ReconciliationPage runs={runs.length ? runs : [
            { run_id: 'rop', label: '低于补货点补到目标量' },
            { run_id: 'cycle', label: '每三天补到目标量' },
          ]} />}
          {tab === 'config' && <ConfigPage config={config} demand={demand} />}
        </>
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
