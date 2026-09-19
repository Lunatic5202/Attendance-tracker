import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, fmtTime } from '../api'
import CameraCapture from '../components/CameraCapture'
import { toast } from '../components/Toast'

const actions = {
  'CHECK-IN': { label: 'Check-In', cls: 'in', icon: '→' },
  'CHECK-OUT': { label: 'Check-Out', cls: 'out', icon: '→' },
  UNKNOWN: { label: 'Unknown Face', cls: 'idle', icon: '?' },
  DUPLICATE_SCAN: { label: 'Duplicate Rejected', cls: 'idle', icon: '!' },
  CHECKOUT_TOO_EARLY: { label: 'Check-Out Held', cls: 'warn', icon: '⏱' },
  DEMO_NEEDS_EMPLOYEE: { label: 'Pick Employee', cls: 'idle', icon: '!' },
}

const star = () => new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true })

const IDLE_SLEEP_MS = 30 * 1000

export default function Scan() {
  const [scanning, setScanning] = useState(true)
  const [asleep, setAsleep] = useState(false)
  const [camError, setCamError] = useState(null)
  const [last, setLast] = useState(null)
  const [log, setLog] = useState([
    { t: 'SYS', s: 'attendance relay online — awaiting camera frames…', tone: '' },
  ])
  const lock = useRef(false)
  const logBox = useRef(null)
  const asleepRef = useRef(false)
  const lastActivity = useRef(Date.now())

  useEffect(() => {
    asleepRef.current = asleep
  }, [asleep])

  const poke = useCallback(() => {
    lastActivity.current = Date.now()
  }, [])

  const onMotion = useCallback(() => {
    poke()
    if (asleepRef.current) setAsleep(false)
  }, [poke])

  useEffect(() => {
    const t = setInterval(() => {
      if (asleepRef.current) return
      if (Date.now() - lastActivity.current >= IDLE_SLEEP_MS) setAsleep(true)
    }, 3000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    if (logBox.current) logBox.current.scrollTop = logBox.current.scrollHeight
  }, [log])

  const pushLog = (t, s, tone = '') =>
    setLog((cur) => [...cur.slice(-29), { t, s, tone }])

  const runScan = useCallback(async (image) => {
    if (lock.current || asleepRef.current) return
    lock.current = true
    try {
      handleResult(await api.scan(image, undefined))
    } catch (e) {
      handleResult(e.data || {})
    } finally {
      lock.current = false
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function handleResult(res) {
    const action = res.action || 'UNKNOWN'
    const now = star()
    setLast({ action, employee: res.employee, attendance: res.attendance, message: res.message, time: now })
    if (res.employee) poke()

    if (action === 'CHECK-IN') {
      pushLog('SCAN', `${res.employee?.name} — CHECK-IN @${now}`, 'ok-line')
      toast(`${res.employee?.name} checked in · ${now}`, { ok: true })
    } else if (action === 'CHECK-OUT') {
      const hrs = res.attendance?.hours_fmt || '—'
      pushLog('SCAN', `${res.employee?.name} — CHECK-OUT @${now} (${hrs})`, 'ok-line')
      toast(`${res.employee?.name} checked out · ${hrs}`, { ok: true })
    } else if (action === 'DUPLICATE_SCAN') {
      pushLog('SCAN', 'duplicate rejected — day already closed', 'err-line')
    } else if (action === 'CHECKOUT_TOO_EARLY') {
      const unlocks = res.unlocks_at ? ` unlocks at ${fmtTime(res.unlocks_at)}` : ''
      pushLog('VERIFY', `${res.employee?.name || 'Employee'} held — check-out${unlocks}`, 'err-line')
      toast(`Check-out held${unlocks}`)
    } else if (action === 'UNKNOWN') {
      pushLog('VERIFY', res.message || 'face did not match any template', 'err-line')
    } else if (action === 'DEMO_NEEDS_EMPLOYEE') {
      pushLog('VERIFY', 'camera/demo mode — use simulate below', 'err-line')
    }
  }

  const meta = actions[last?.action] || actions.UNKNOWN

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="kicker plain">Kiosk // Live Attendance</span>
          <h1>Face <b>Scan</b></h1>
          <div className="sub">first scan → CHECK-IN · a later scan after the work buffer → CHECK-OUT</div>
        </div>
        <label className="row" style={{ gap: '0.5rem', cursor: 'pointer' }}>
          <input type="checkbox" checked={scanning} onChange={(e) => setScanning(e.target.checked)} />
          <span className="mono" style={{ fontSize: '0.7rem', letterSpacing: '0.14em', color: 'var(--muted)' }}>
            AUTO-SCAN
          </span>
        </label>
      </div>

      <div className="scan-grid">
        <div className="cam-col">
          <CameraCapture
            active={scanning || asleep}
            watch={scanning || asleep}
            motionThreshold={0.05}
            onMotion={onMotion}
            onError={setCamError}
            onFrame={runScan}
          />
          <div className="cam-caption">
            <span>TARGET FRAME — HOLD STILL</span>
            <span className="mono">{scanning ? 'CAM 01 · LIVE' : 'CAM 01 · PAUSED'}</span>
          </div>
        </div>

        <div className="result-panel">
          <div className={`result-card ${meta.cls}`}>
            <div className="rc-top">
              <span className="rc-flag">{meta.label}</span>
              <span className="rc-time">{last ? last.time : star()}</span>
            </div>

            {last?.employee ? (
              <div className="rc-body">
                <div className="rc-avatar">{last.employee.name.trim().charAt(0).toUpperCase()}</div>
                <div className="rc-main">
                  <div className="rc-name">{last.employee.name}</div>
                  <div className="rc-meta mono">
                    {last.employee.id} / {last.employee.department} · {last.employee.role || 'staff'}
                  </div>
                </div>
                <div className="rc-status">
                  <span className={`flag ${meta.cls}`}><span className="dot" /></span>
                </div>
              </div>
            ) : (
              <div className="rc-body">
                <div className="rc-avatar ghost">{meta.icon}</div>
                <div className="rc-main">
                  <div className="rc-name dim">{last ? last.message || meta.label : 'No scan yet'}</div>
                  <div className="rc-meta mono">look into the camera to record</div>
                </div>
              </div>
            )}

            {last?.message && last.action !== 'CHECK-IN' && last.action !== 'CHECK-OUT' && (
              <div className="rc-note">{last.message}</div>
            )}

            {last?.attendance && (
              <div className="rc-strip">
                <div>
                  <span className="st-label">Check-In</span>
                  <span className="st-val mono">{fmtTime(last.attendance.check_in)}</span>
                </div>
                <div>
                  <span className="st-label">Check-Out</span>
                  <span className="st-val mono">{fmtTime(last.attendance.check_out)}</span>
                </div>
                <div>
                  <span className="st-label">Worked</span>
                  <span className="st-val mono hot">{last.attendance.hours_fmt || '—'}</span>
                </div>
              </div>
            )}
          </div>

          <div className="result-log" ref={logBox}>
            {log.map((l, i) => (
              <div key={i} className={l.tone}>
                <span className="lg-t">{l.t}</span>
                <span className="lg-s">{l.s}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card tight kiosk-note" style={{ marginTop: '1.4rem' }}>
        <span className="series-tag">Secure kiosk</span>
        <span className="mono" style={{ fontSize: '0.66rem', color: 'var(--muted)', letterSpacing: '0.1em' }}>
          Only administrator-enrolled faces can create attendance records. Check-out unlocks after the configured work buffer.
        </span>
      </div>

      {asleep && (
        <div className="kiosk-standby">
          <div className="ks-radar">
            <span className="ks-ring r1" />
            <span className="ks-ring r2" />
            <span className="ks-ring r3" />
            <span className="ks-dot" />
          </div>
          <div className="ks-gate">
            <div className="ks-kicker">TOUCHLESS KIOSK · STANDBY</div>
            <h1>Wave to <b>Wake</b></h1>
            <p className="ks-sub mono">
              motion near the camera reopens live scan
              {camError ? <span style={{ color: 'var(--bolt)' }}> · camera unavailable ({camError})</span> : null}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
