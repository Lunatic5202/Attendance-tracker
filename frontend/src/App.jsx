import React, { useEffect, useState } from 'react'
import { api, today } from './api'
import Home from './pages/Home'
import Dashboard from './pages/Dashboard'
import Scan from './pages/Scan'
import Employees from './pages/Employees'
import AttendancePage from './pages/AttendancePage'
import { Toasts, toast } from './components/Toast'

const NAV = [
  { to: 'dashboard', num: '01', label: 'Overview' },
  { to: 'scan', num: '02', label: 'Live Scan' },
  { to: 'employees', num: '03', label: 'Employees' },
  { to: 'attendance', num: '04', label: 'Records' },
]

function readRoute() {
  return window.location.hash.replace(/^#\/?/, '') || 'dashboard'
}

export function useRoute() {
  const [route, setRoute] = useState(readRoute())
  useEffect(() => {
    const on = () => setRoute(readRoute())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}

export function navigate(to) {
  window.location.hash = `/${to}`
}

function Clock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  const date = now.toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })
  const time = now.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true })
  return (
    <span className="time-chip">{date} · {time}</span>
  )
}

export default function App() {
  const route = useRoute()
  const [engine, setEngine] = useState(null)

  useEffect(() => {
    api.health().then((h) => setEngine(h.face_engine)).catch(() => setEngine('offline'))
  }, [])

  let page = <Dashboard />
  if (route.startsWith('scan')) page = <Scan />
  else if (route.startsWith('employees')) page = <Employees />
  else if (route.startsWith('attendance')) page = <AttendancePage />
  else if (route === 'home') page = <Home />

  return (
    <div className="app fade-in">
      <header className="topbar">
        <a className="logo" href="#/home" onClick={() => navigate('dashboard')}>
          <span className="logo-mark">AT</span>
          <span className="logo-type">
            <b>BT Projects</b>
            <span>Attendance Tracker</span>
          </span>
        </a>
        <div className="top-actions">
          <Clock />
          <button className="btn sm" onClick={() => navigate('scan')}>Scan Now</button>
          <span className="series-tag">
            Engine <b data-engine>{engine ?? '…'}</b>
          </span>
        </div>
      </header>

      <div className="shell">
        <aside className="sidebar">
          <span className="side-label">Operations</span>
          <nav className="nav">
            {NAV.map((item) => (
              <a
                key={item.to}
                className={`navlink ${route.startsWith(item.to) ? 'active' : ''}`}
                href={`#/${item.to}`}
              >
                <span className="num">{item.num}</span>
                {item.label}
              </a>
            ))}
          </nav>
          <div className="sidebar-foot">
            date <b>·</b> {today()} <br />
            infra <b>·</b> face-attendance
          </div>
        </aside>

        <main className="content">{page}</main>
      </div>

      <footer className="page-foot">
        <div className="foot-inner">
          <div>
            <span className="logo-mark">BT</span>
            <div className="logo-type" style={{ marginTop: '0.6rem', color: '#fff' }}>
              <b style={{ color: '#fff' }}>BT Projects</b>
              <span>Private Limited</span>
            </div>
          </div>
          <div className="mono" style={{ textAlign: 'right', lineHeight: 1.9 }}>
            face-attendance / kiosk-ready <b>·</b> fastapi + opencv<br />
            © {new Date().getFullYear()} BT Projects Pvt. Ltd.
          </div>
        </div>
      </footer>

      <Toasts />
    </div>
  )
}