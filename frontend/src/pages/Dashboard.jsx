import React, { useEffect, useState } from 'react'
import { api, fmtTime, today } from '../api'
import { navigate } from '../App'
import { toast } from '../components/Toast'

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [rows, setRows] = useState([])
  const [date, setDate] = useState(today())
  const [loading, setLoading] = useState(true)
  const [msync, setMsync] = useState(null)
  const [syncing, setSyncing] = useState(false)

  function load(nextDate) {
    setLoading(true)
    api.stats(nextDate).then(setStats).catch(() => setStats(null))
    api.attendance(nextDate).then(setRows).catch(() => setRows([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => load(date), [date]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api.excelStatus().then(setMsync).catch(() => setMsync(null)) }, [])

  function runSync(kind) {
    setSyncing(true)
    const call = kind === 'excel' ? api.excelSync() : api.backupNow()
    call
      .then((res) => {
        const msg = kind === 'excel'
          ? `Excel updated — ${res.attendance_rows ?? 0} attendance rows`
          : `Encrypted backup saved — ${res.filename}`
        toast(msg, { ok: true })
        api.excelStatus().then(setMsync).catch(() => setMsync(null))
      })
      .catch((err) => toast(err.message || 'Sync failed'))
      .finally(() => setSyncing(false))
  }

  const maxDept = stats ? Math.max(1, ...Object.values(stats.departments || {})) : 1

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="kicker plain">Operations Overview / {today()}</span>
          <h1>Attendance <b>Dashboard</b></h1>
        </div>
        <div className="row">
          <input
            type="date"
            className="input"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
          <button className="btn ghost sm" onClick={() => navigate('scan')}>Live Scan →</button>
        </div>
      </div>

      {loading && !stats ? (
        <div className="empty">Loading snapshot…</div>
      ) : (
        <>
          <div className="grid cols-5">
            <div className="card stat">
              <span className="kicker plain">Present</span>
              <div className="num">{stats?.present_today ?? 0}</div>
              <span className="hint">office checked in · {date}</span>
            </div>
            <div className="card stat">
              <span className="kicker plain">Checked Out</span>
              <div className="num">{stats?.checked_out_today ?? 0}</div>
              <span className="hint">complete attendance</span>
            </div>
            <div className="card stat">
              <span className="kicker plain">Late Arrivals</span>
              <div className="num">{stats?.late_today ?? 0}</div>
              <span className="hint">after 09:30</span>
            </div>
            <div className="card stat">
              <span className="kicker plain">Avg. Hours</span>
              <div className="num">{stats?.avg_hours ? <>{stats.avg_hours}<small>h</small></> : '0'}</div>
              <span className="hint">per present employee</span>
            </div>
            <div className="card stat">
              <span className="kicker plain">Field Visits</span>
              <div className="num">{stats?.field_visits_today ?? 0}</div>
              <span className="hint">{stats?.field_staff_seen_today ?? 0} crew seen today</span>
            </div>
          </div>

          <div className="sec-head" style={{ marginTop: '1.8rem' }}>
            <span className="idx">VIEW 01</span>
            <h2>Department Strength</h2>
          </div>
          <div className="card">
            {Object.keys(stats?.departments || {}).length === 0 ? (
              <div className="empty">No departments yet — register an employee.</div>
            ) : (
              Object.entries(stats.departments).map(([dep, count]) => (
                <div key={dep} style={{ marginBottom: '0.9rem' }}>
                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: '0.3rem' }}>
                    <div style={{ fontSize: '0.92rem', fontWeight: 700 }}>{dep}</div>
                    <div className="mono" style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>{count}</div>
                  </div>
                  <div className="bar-track">
                    <div
                      className={`bar-fill ${dep === 'Operations' ? 'hot' : ''}`}
                      style={{ width: `${Math.max(6, (count / maxDept) * 100)}%` }}
                    />
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="sec-head" style={{ marginTop: '2rem' }}>
            <span className="idx">VIEW 02</span>
            <h2>Today's Activity</h2>
          </div>
          {rows.length === 0 ? (
            <div className="empty">No scans recorded for {date}.</div>
          ) : (
            <div className="tablewrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Employee</th>
                    <th>Dept</th>
                    <th>Check-In</th>
                    <th>Check-Out</th>
                    <th>Hours</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id}>
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
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="sec-head" style={{ marginTop: '2rem' }}>
            <span className="idx">VIEW 03</span>
            <h2>Excel & Backup Sync</h2>
          </div>
          <div className="card">
            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
              <div>
                {msync?.configured ? (
                  <>
                    <div className="strong-cell">Microsoft OneDrive connected</div>
                    <div className="muted-cell" style={{ marginTop: '0.2rem' }}>
                      daily sync {msync.sync_time?.slice(0, 5)} · {msync.folder}/{msync.filename}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="strong-cell">Microsoft sync not configured</div>
                    <div className="muted-cell" style={{ marginTop: '0.2rem' }}>
                      Set MS_CLIENT_ID / MS_CLIENT_SECRET / MS_TENANT_ID / MS_DRIVE_UPN to push the
                      attendance workbook to Excel and encrypted backups to OneDrive.
                    </div>
                  </>
                )}
              </div>
              <div className="row">
                <button className="btn sm" disabled={syncing} onClick={() => runSync('excel')}>
                  Sync to Excel
                </button>
                <button className="btn sm ghost" disabled={syncing} onClick={() => runSync('backup')}>
                  Encrypted Backup
                </button>
              </div>
            </div>
          </div>

          <div className="row" style={{ marginTop: '1.6rem' }}>
            <button className="btn" onClick={() => navigate('scan')}>Open Live Scan →</button>
            <button className="btn ghost" onClick={() => navigate('employees')}>Manage Employees</button>
          </div>
        </>
      )}
    </div>
  )
}