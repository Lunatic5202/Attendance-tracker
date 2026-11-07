import React, { useEffect, useState } from 'react'
import { api, fmtTime, today } from '../api'

export default function AttendancePage() {
  const [date, setDate] = useState(today())
  const [empId, setEmpId] = useState('')
  const [employees, setEmployees] = useState([])
  const [rows, setRows] = useState([])
  const [visits, setVisits] = useState([])
  const [snaps, setSnaps] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.employees().then(setEmployees).catch(() => setEmployees([]))
  }, [])

  useEffect(() => {
    setLoading(true)
    api.attendance(date, empId || undefined)
      .then(setRows)
      .catch(() => setRows([]))
    api.visits(date, empId || undefined)
      .then(setVisits)
      .catch(() => setVisits([]))
      .finally(() => setLoading(false))
    // Snapshots are kept only for phone-number check-ins (see backend/phone_checkin.py).
    api.snapshots(date, empId || undefined)
      .then(setSnaps)
      .catch(() => setSnaps([]))
  }, [date, empId])

  // Latest snapshot per employee for the selected day, keyed by employee id.
  const snapFor = (employeeId) => {
    const own = snaps.filter((s) => s.employee_id === employeeId)
    return own.length ? own[own.length - 1] : null
  }

  const sourceCell = (row) => {
    const snap = row.source === 'phone' ? snapFor(row.employee_id) : null
    return (
      <>
        <span className={`badge plain ${row.source === 'manual' || row.source === 'phone' ? 'warn' : ''}`}>{row.source}</span>
        {snap && (
          <a
            className="snap-link"
            href={`/api/attendance/snapshots/${snap.id}/image`}
            target="_blank"
            rel="noreferrer"
            title={snap.face_detected === false ? 'No face was visible in this snapshot' : 'View check-in snapshot'}
          >
            {snap.face_detected === false ? 'photo · no face' : 'photo'}
          </a>
        )}
      </>
    )
  }

  function exportCsv() {
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
    const head = ['Date', 'Employee ID', 'Employee', 'Department', 'Check-In', 'Check-Out', 'Sessions', 'Total Hours', 'Status']
    const lines = rows.map((r) =>
      [r.date, r.employee_id, r.name, r.department, r.check_in, r.check_out, (r.sessions || []).map((x) => `${x.check_in || '—'}-${x.check_out || 'ACTIVE'}`).join(' | '), r.hours_fmt || '', r.status]
        .map(esc)
        .join(',')
    )
    const vHead = ['Date', 'Employee ID', 'Employee', 'Department', 'Visit Time', 'Source']
    const vLines = visits.map((v) =>
      [v.date, v.employee_id, v.name, v.department, v.visited_at, v.source].map(esc).join(',')
    )
    const csv = [
      head.join(','), ...lines,
      '', vHead.join(','), ...vLines,
    ].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
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
          <div className="sub">office staff can record multiple check-in/check-out sessions per day; field staff log one visit per scan</div>
        </div>
        <button className="btn" onClick={exportCsv} disabled={rows.length === 0 && visits.length === 0}>↧ Export CSV</button>
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
          {rows.length} office · {visits.length} visit{visits.length === 1 ? '' : 's'}
        </span>
      </div>

      {loading ? (
        <div className="empty">Loading records…</div>
      ) : (
        <>
          <h2 className="section-title">Office Staff — Check-In / Check-Out</h2>
          {rows.length === 0 ? (
            <div className="empty">No office attendance records for this view.</div>
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
                    <th>Sessions</th>
                    <th>Total Hours</th>
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
                      <td>
                        <div className="session-list">
                          {(r.sessions || []).map((session, index) => (
                            <div className="session-item mono" key={index}>
                              <span>{fmtTime(session.check_in)}</span>
                              <span className="muted-cell">→</span>
                              <span>{session.check_out ? fmtTime(session.check_out) : 'ACTIVE'}</span>
                            </div>
                          ))}
                        </div>
                      </td>
                      <td className="mono strong-cell">{r.hours_fmt || '—'}</td>
                      <td>
                        <span className={`badge ${r.status === 'Late' ? 'warn' : 'ok'}`}>{r.status}</span>
                      </td>
                      <td>
                        {sourceCell(r)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2 className="section-title">Field / Ground Crew — Visits</h2>
          {visits.length === 0 ? (
            <div className="empty">No field visits for this view.</div>
          ) : (
            <div className="tablewrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Employee</th>
                    <th>Department</th>
                    <th>Visit Time</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {visits.map((v) => (
                    <tr key={v.id}>
                      <td><span className="id-cell">{v.date}</span></td>
                      <td>
                        <div className="strong-cell">{v.name}</div>
                        <div className="id-cell" style={{ marginTop: '0.2rem' }}>{v.employee_id}</div>
                      </td>
                      <td className="muted-cell">{v.department}</td>
                      <td className="mono">{fmtTime(v.visited_at)}</td>
                      <td>
                        {sourceCell(v)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}