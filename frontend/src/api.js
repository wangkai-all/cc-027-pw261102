const BASE = ''

async function get(path) {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`${res.status} ${path}`)
  return res.json()
}

async function post(path) {
  const res = await fetch(BASE + path, { method: 'POST' })
  if (!res.ok) throw new Error(`${res.status} ${path}`)
  return res.json()
}

export const api = {
  replay: () => post('/api/replay'),
  config: () => get('/api/config'),
  demand: () => get('/api/demand'),
  runs: () => get('/api/runs'),
  compare: () => get('/api/compare'),
  snapshots: (runId) => get(`/api/snapshots?run_id=${runId}`),
  centralSnapshots: (runId) => get(`/api/central-snapshots?run_id=${runId}`),
  orders: (runId, date) =>
    get(`/api/orders?run_id=${runId}${date ? `&date=${date}` : ''}`),
  orderDetail: (orderId) => get(`/api/orders/${orderId}`),
  events: (runId, date) =>
    get(`/api/events?run_id=${runId}${date ? `&date=${date}` : ''}`),
  reconciliation: (runId) => get(`/api/reconciliation?run_id=${runId}`),
}
