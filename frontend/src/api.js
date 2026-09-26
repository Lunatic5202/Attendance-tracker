const BASE = '/api'

async function req(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(data.message || data.detail || 'Request failed')
    err.status = res.status
    err.data = data
    throw err
  }
  return data
}

export const api = {
  health: () => req('/health'),
  adminSession: () => req('/admin/session'),
  adminLogin: (password) => req('/admin/login', { method: 'POST', body: JSON.stringify({ password }) }),
  adminLogout: () => req('/admin/logout', { method: 'POST' }),

  employees: () => req('/employees'),
  employee: (id) => req(`/employees/${id}`),
  createEmployee: (body) => req('/employees', { method: 'POST', body: JSON.stringify(body) }),
  updateEmployee: (id, body) => req(`/employees/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteEmployee: (id) => req(`/employees/${id}`, { method: 'DELETE' }),
  enrollFace: async (id, base64Image) => {
    const form = new FormData()
    const blob = await (await fetch(base64Image)).blob()
    form.append('file', blob, 'face.jpg')
    const res = await fetch(`${BASE}/employees/${id}/face`, { method: 'POST', body: form })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || 'Face enrollment failed')
    }
    return res.json()
  },
  enrollFaces: async (id, files) => {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    const res = await fetch(`${BASE}/employees/${id}/face/upload`, { method: 'POST', body: form })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || 'Picture upload failed')
    }
    return res.json()
  },

  scan: (image, employeeId) =>
    req('/attendance/scan', { method: 'POST', body: JSON.stringify({ image, employee_id: employeeId }) }),
  manual: (employeeId, action) =>
    req('/attendance/manual', { method: 'POST', body: JSON.stringify({ employee_id: employeeId, action }) }),

  attendance: (date, employeeId) => {
    const q = new URLSearchParams()
    if (date) q.set('date', date)
    if (employeeId) q.set('employee_id', employeeId)
    return req(`/attendance?${q.toString()}`)
  },
  // Field / ground crew visits, reported separately from office attendance.
  visits: (date, employeeId) => {
    const q = new URLSearchParams()
    if (date) q.set('date', date)
    if (employeeId) q.set('employee_id', employeeId)
    return req(`/attendance/visits?${q.toString()}`)
  },
  stats: (date) => req(`/stats${date ? `?date=${date}` : ''}`),
  departments: () => req('/departments'),

  excelStatus: () => req('/excel/status'),
  excelSync: () => req('/excel/sync', { method: 'POST' }),
  backupNow: () => req('/backup/now', { method: 'POST' }),
}

export function fmtTime(hhmmss) {
  if (!hhmmss) return '—'
  const [h, m] = hhmmss.split(':').map(Number)
  // Backend stores times in UTC ("HH:MM" / "HH:MM:SS"). Anchor at a fixed
  // UTC instant, then let the runtime render it in the viewer's local zone.
  // (Handles +5:30, +5:45, DST — any offset a browser can produce.)
  const t = new Date(Date.UTC(2000, 0, 1, h, m))
  return t.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
}

export function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
