import React, { useEffect, useState } from 'react'
import { api, today } from '../api'
import { navigate } from '../App'

const FEATURES = [
  {
    idx: 'SR 01',
    title: 'Face-Based Check-In',
    copy: 'Employees step in front of the camera — OpenCV detects and verifies the registered face and records the first scan of the day as check-in.',
  },
  {
    idx: 'SR 02',
    title: 'Automatic Check-Out',
    copy: 'A later scan closes the day automatically. No manual buttons, no forms — the system decides the action from the attendance state.',
  },
  {
    idx: 'SR 03',
    title: 'Working-Hours Engine',
    copy: 'Working duration is computed on check-out and surfaced as hours worked, per employee and per department, onto the dashboard.',
  },
  {
    idx: 'SR 04',
    title: 'Enrollment Pipeline',
    copy: 'Register employee details and capture a face template. Templates are stored as embeddings only — no raw portraits are kept.',
  },
  {
    idx: 'SR 05',
    title: 'Duplicate Protection',
    copy: 'One check-in and one check-out per employee per day. Repeated scans are rejected instead of writing contradictory records.',
  },
  {
    idx: 'SR 06',
    title: 'Records & Export',
    copy: 'Daily attendance tables with late flags, filters by date and employee, plus CSV export for payroll and reporting workflows.',
  },
]

const FLOW = [
  { n: '01', t: 'Camera' },
  { n: '02', t: 'Face Detect' },
  { n: '03', t: 'Verify' },
  { n: '04', t: 'Check-in' },
  { n: '05', t: 'Check-out' },
  { n: '06', t: 'Record' },
]

export default function Home() {
  const [stats, setStats] = useState(null)
  const [date, setDate] = useState(today())

  useEffect(() => {
    api.stats().then(setStats).catch(() => setStats(null))
  }, [])

  return (
    <div className="page">
      <section className="hero" style={{ margin: 'calc(-1 * clamp(1.25rem, 3vw, 2.5rem)) 0 0' }}>
        <div className="route" />
        <div className="hero-inner">
          <span className="kicker on-navy plain">Attendance Infrastructure // BT Projects</span>
          <h1>
            Face-Based<br />
            Employee<br />
            Attendance<b>.</b>
          </h1>
          <p className="lede">
            A smart attendance system for <strong>BT Projects Pvt. Ltd.</strong> — employees simply
            stand in front of a camera. The system <strong>recognises the face</strong>, records
            check-in and check-out, and calculates working hours automatically.
          </p>
          <div className="cta-row">
            <button className="btn light" onClick={() => navigate('scan')}>
              Open Live Scan →
            </button>
            <button className="btn outline-light" onClick={() => navigate('employees')}>
              Register Employee
            </button>
          </div>
        </div>
        <div className="hero-stats">
          <div className="statline">
            <div className="v">{stats ? stats.present_today : '—'}</div>
            <div className="k">Present Today</div>
          </div>
          <div className="statline">
            <div className="v">{stats ? stats.total_employees : '—'}</div>
            <div className="k">Active Employees</div>
          </div>
          <div className="statline">
            <div className="v">{stats ? (stats.avg_hours ? `${stats.avg_hours}h` : '0h') : '—'}</div>
            <div className="k">Avg. Hours Worked</div>
          </div>
        </div>
      </section>

      <div className="sec-head">
        <span className="idx">SERIES 01</span>
        <h2>System Capabilities</h2>
      </div>
      <div className="grid cols-3">
        {FEATURES.map((f) => (
          <article className="feature" key={f.idx}>
            <span className="fidx">{f.idx}</span>
            <h3>{f.title}</h3>
            <p>{f.copy}</p>
          </article>
        ))}
      </div>

      <div className="sec-head">
        <span className="idx">SERIES 02</span>
        <h2>How It Works</h2>
      </div>
      <div className="card" style={{ padding: '1.6rem' }}>
        <div className="row" style={{ justifyContent: 'space-between', gap: '1rem' }}>
          {FLOW.map((s, i) => (
            <React.Fragment key={s.n}>
              <div style={{ textAlign: 'center' }}>
                <div
                  className="mono"
                  style={{ fontSize: '0.62rem', color: 'var(--bolt)', letterSpacing: '0.18em' }}
                >
                  {s.n}
                </div>
                <div style={{ fontWeight: 800, marginTop: '0.3rem', color: 'var(--navy-deep)' }}>
                  {s.t}
                </div>
              </div>
              {i < FLOW.length - 1 && (
                <div style={{ flex: 1, height: 1, background: 'repeating-linear-gradient(90deg, var(--line-strong) 0 6px, transparent 6px 12px)' }} />
              )}
            </React.Fragment>
          ))}
        </div>
        <p className="muted" style={{ marginTop: '1.3rem', fontSize: '0.88rem' }}>
          First scan of the day → check-in. Second scan → check-out and working-hours calculation.
          The dashboard and record sheets reflect the day immediately.
        </p>
        <div className="row" style={{ marginTop: '1rem' }}>
          <button className="btn sm ghost" onClick={() => navigate('dashboard')}>→ Overview</button>
          <button className="btn sm ghost" onClick={() => navigate('attendance')}>→ Records</button>
        </div>
      </div>

      <div className="sec-head" style={{ marginTop: '2.4rem' }}>
        <span className="idx">SERIES 03</span>
        <h2>Daily Snapshot</h2>
      </div>
      <div className="grid cols-4">
        <div className="card stat">
          <span className="kicker plain">Present</span>
          <div className="num">{stats ? stats.present_today : '—'}</div>
          <span className="hint">{date}</span>
        </div>
        <div className="card stat">
          <span className="kicker plain">Checked Out</span>
          <div className="num">{stats ? stats.checked_out_today : '—'}</div>
          <span className="hint">closing scan done</span>
        </div>
        <div className="card stat">
          <span className="kicker plain">Late</span>
          <div className="num">{stats ? stats.late_today : '—'}</div>
          <span className="hint">after 09:30</span>
        </div>
        <div className="card stat">
          <span className="kicker plain">Departments</span>
          <div className="num">{stats ? Object.keys(stats.departments || {}).length : '—'}</div>
          <span className="hint">active units</span>
        </div>
      </div>
    </div>
  )
}