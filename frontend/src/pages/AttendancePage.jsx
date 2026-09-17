import React, { useEffect, useState } from 'react'
import { api, fmtTime, today } from '../api'

export default function AttendancePage() {
  const [date, setDate] = useState(today())
  const [empId, setEmpId] = useState('')
  const [employees, setEmployees] = useState([])
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.employees().then(setEmployees).catch(() => setEmployees([]))
  }, [])

  useEffect(() => {
    setLoading(true)
    api.attendance(date, empId || undefined)
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [date, empId])

  function exportCsv() {
    const head = ['Date', 'Employee ID', 'Employee', 'Department', 'Check-In', 'Check-Out', 'Hours', 'Status']
    const lines = rows.map((r) =>
      [r.date, r.employee_id, r.name, r.department, r.check_in, r.check_out, r.hours_fmt || '', r.status]
        .map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`)
        .join(',')
    )
    const blob = new Blob([[head.join(','), ...lines].join('\n')], { type: 'text/csv' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `attendance-${date}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="kicker plain">Daily / Historical</span>
          <h1>Attendance <b>Records</b></h1>
          <div className="sub">one check-in and one check-out per employee per day</div>
        </div>
        <button className="btn" onClick={exportCsv} disabled={rows.length === 0}>↧ Export CSV</button>
      </div>

      <div className="toolbar">
        <input type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} />
        <select className="input" value={empId} onChange={(e) => setEmpId(e.target.value)}>
          <option value="">All employees</option>
          {employees.map((e) => (
            <option key={e.id} value={e.id}>{e.id} — {e.name}</option>
          ))}
        </select>
        <span className="mono muted" style={{ fontSize: '0.7rem', letterSpacing: '0.12em' }}>
          {rows.length} record{rows.length === 1 ? '' : 's'}
        </span>
      </div>

      {loading ? (
        <div className="empty">Loading records…</div>
      ) : rows.length === 0 ? (
        <div className="empty">No attendance records for this view.</div>
      ) : (
        <div className="tablewrap">
          <table className="data">
            <thead>
              <tr>
                <th>Date</th>
                <th>Employee</th>
                <th>Department</th>
                <th>Check-In</th>
                <th>Check-Out</th>
                <th>Hours</th>
                <th>Status</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td><span className="id-cell">{r.date}</span></td>
                  <td>
                    <div className="strong-cell">{r.name}</div>
                    <div className="id-cell" style={{ marginTop: '0.2rem' }}>{r.employee_id}</div>
                  </td>
                  <td className="muted-cell">{r.department}</td>
                  <td className="mono">{fmtTime(r.check_in)}</td>
                  <td className="mono">{fmtTime(r.check_out)}</td>
                  <td className="mono strong-cell">{r.hours_fmt || '—'}</td>
                  <td>
                    <span className={`badge ${r.status === 'Late' ? 'warn' : 'ok'}`}>{r.status}</span>
                  </td>
                  <td>
                    <span className={`badge plain ${r.source === 'manual' ? 'warn' : ''}`}>{r.source}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}