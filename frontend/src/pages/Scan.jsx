import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, fmtTime } from '../api'
import CameraCapture from '../components/CameraCapture'
import { toast } from '../components/Toast'

const actions = {
  'CHECK-IN': { label: 'Check-In', cls: 'in', icon: '→' },
  'CHECK-OUT': { label: 'Check-Out', cls: 'out', icon: '→' },
  VISIT: { label: 'Visit Logged', cls: 'in', icon: '→' },
  UNKNOWN: { label: 'Unknown Face', cls: 'idle', icon: '?' },
  LOW_QUALITY: { label: 'Adjust Camera', cls: 'warn', icon: '◎' },
  DUPLICATE_SCAN: { label: 'Duplicate Rejected', cls: 'idle', icon: '!' },
  CHECKOUT_TOO_EARLY: { label: 'Check-Out Held', cls: 'warn', icon: '⏱' },
  WAIT: { label: 'One At A Time', cls: 'warn', icon: '⏱' },
  DEMO_NEEDS_EMPLOYEE: { label: 'Pick Employee', cls: 'idle', icon: '!' },
}

const star = () => new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true })

const IDLE_SLEEP_MS = 30 * 1000

export default function Scan() {
  const [scanning, setScanning] = useState(true)
  const [asleep, setAsleep] = useState(false)
  const [camError, setCamError] = useState(null)
  const [last, setLast] = useState(null)
  const [confirmation, setConfirmation] = useState(null)
  const [log, setLog] = useState([
    { t: 'SYS', s: 'attendance relay online — awaiting camera frames…', tone: '' },
  ])
  const lock = useRef(false)
  const confirmationRef = useRef(null)
  const confirmationTimer = useRef(null)
  const audioContextRef = useRef(null)
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

  useEffect(() => () => {
    clearTimeout(confirmationTimer.current)
    audioContextRef.current?.close().catch(() => {})
  }, [])

  const pushLog = (t, s, tone = '') =>
    setLog((cur) => [...cur.slice(-29), { t, s, tone }])

  const runScan = useCallback(async (frames) => {
    if (lock.current || asleepRef.current || confirmationRef.current) return
    lock.current = true
    try {
      handleResult(await api.scan(frames, undefined))
    } catch (e) {
      handleResult(e.data || {})
    } finally {
      lock.current = false
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function closeConfirmation() {
    clearTimeout(confirmationTimer.current)
    confirmationRef.current = null
    setConfirmation(null)
  }

  function playConfirmationTone(kind, late = false) {
    if (typeof window === 'undefined') return
    const AudioContext = window.AudioContext || window.webkitAudioContext
    if (!AudioContext) return

    try {
      const context = audioContextRef.current || new AudioContext()
      audioContextRef.current = context
      const start = context.currentTime + 0.02
      const notes = late
        ? [{ frequency: 392, at: 0, length: .14 }, { frequency: 330, at: .12, length: .2 }]
        : kind === 'check-out'
          ? [{ frequency: 440, at: 0, length: .14 }, { frequency: 659.25, at: .11, length: .22 }]
          : [{ frequency: 523.25, at: 0, length: .14 }, { frequency: 659.25, at: .1, length: .14 }, { frequency: 783.99, at: .2, length: .25 }]

      notes.forEach(({ frequency, at, length }) => {
        const oscillator = context.createOscillator()
        const gain = context.createGain()
        oscillator.type = late ? 'sine' : 'triangle'
        oscillator.frequency.setValueAtTime(frequency, start + at)
        gain.gain.setValueAtTime(0.0001, start + at)
        gain.gain.exponentialRampToValueAtTime(late ? 0.035 : 0.045, start + at + 0.012)
        gain.gain.exponentialRampToValueAtTime(0.0001, start + at + length)
        oscillator.connect(gain)
        gain.connect(context.destination)
        oscillator.start(start + at)
        oscillator.stop(start + at + length + 0.03)
      })
      if (context.state === 'suspended') context.resume().catch(() => {})
    } catch {
      // Audio is an enhancement; a browser policy should never interrupt scanning.
    }
  }

  function openConfirmation(data) {
    clearTimeout(confirmationTimer.current)
    confirmationRef.current = data
    setConfirmation(data)
    playConfirmationTone(data.kind, data.late)
    confirmationTimer.current = setTimeout(() => {
      confirmationRef.current = null
      setConfirmation(null)
    }, 5200)
  }

  function handleResult(res) {
    const action = res.action || 'UNKNOWN'
    const now = star()
    setLast({ action, employee: res.employee, attendance: res.attendance, message: res.message, time: now })
    if (res.employee) poke()

    if (action === 'CHECK-IN') {
      openConfirmation({
        kind: 'check-in',
        employee: res.employee,
        time: now,
        late: res.attendance?.status === 'Late',
      })
      pushLog('SCAN', `${res.employee?.name} — CHECK-IN @${now}`, 'ok-line')
      toast(`${res.employee?.name} checked in · ${now}`, { ok: true })
    } else if (action === 'VISIT') {
      pushLog('SCAN', `${res.employee?.name} — VISIT @${now}`, 'ok-line')
      toast(`${res.employee?.name} visit logged · ${now}`, { ok: true })
    } else if (action === 'CHECK-OUT') {
      const hrs = res.attendance?.hours_fmt || '—'
      openConfirmation({
        kind: 'check-out',
        employee: res.employee,
        time: now,
        hours: hrs,
      })
      pushLog('SCAN', `${res.employee?.name} — CHECK-OUT @${now} (${hrs})`, 'ok-line')
      toast(`${res.employee?.name} checked out · ${hrs}`, { ok: true })
    } else if (action === 'WAIT') {
      pushLog('VERIFY', `check-in buffer — wait ${res.retry_after ?? '?'}s`, 'err-line')
      toast(`One at a time — wait ${res.retry_after ?? '?'}s`)
    } else if (action === 'DUPLICATE_SCAN') {
      pushLog('SCAN', 'duplicate rejected — day already closed', 'err-line')
    } else if (action === 'CHECKOUT_TOO_EARLY') {
      const unlocks = res.unlocks_at ? ` unlocks at ${fmtTime(res.unlocks_at)}` : ''
      pushLog('VERIFY', `${res.employee?.name || 'Employee'} held — check-out${unlocks}`, 'err-line')
      toast(`Check-out held${unlocks}`)
    } else if (action === 'UNKNOWN') {
      pushLog('VERIFY', res.message || 'face did not match any template', 'err-line')
    } else if (action === 'LOW_QUALITY') {
      pushLog('VERIFY', res.message || 'image quality too low', 'err-line')
      toast(res.message || 'Poor image quality — try again')
    } else if (action === 'DEMO_NEEDS_EMPLOYEE') {
      pushLog('VERIFY', 'camera/demo mode — use simulate below', 'err-line')
    }
  }

  const meta = actions[last?.action] || actions.UNKNOWN
  const greeting = confirmation
    ? new Date().getHours() < 12 ? 'Good morning' : new Date().getHours() < 17 ? 'Good afternoon' : 'Good evening'
    : ''

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="kicker plain">Kiosk // Live Attendance</span>
          <h1>Face <b>Scan</b></h1>
          <div className="sub">first scan → CHECK-IN · later scan after 4h → CHECK-OUT · field crew → VISIT · one check-in at a time</div>
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
            onBurst={runScan}
            burst={3}
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
              <span className="rc-time">{last ? fmtTime(last.time) : star()}</span>
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

      {confirmation && (
        <div className={`confirmation-backdrop ${confirmation.late ? 'late' : ''}`} role="dialog" aria-modal="true" aria-labelledby="confirmation-title" onMouseDown={(e) => e.target === e.currentTarget && closeConfirmation()}>
          <div className={`confirmation-dialog ${confirmation.kind} ${confirmation.late ? 'is-late' : ''}`}>
            <button className="confirmation-close" onClick={closeConfirmation} aria-label="Close confirmation">×</button>
            <div className="confirmation-icon" aria-hidden="true">
              <svg viewBox="0 0 52 52" focusable="false">
                <circle className="confirmation-circle" cx="26" cy="26" r="23" />
                <path className="confirmation-check" d="M14 27.5 22 35l16-18" />
              </svg>
            </div>
            <div className="confirmation-kicker">{confirmation.late ? 'Late arrival noted' : confirmation.kind === 'check-in' ? 'Attendance recorded' : 'Day complete'}</div>
            <h2 id="confirmation-title">
              {confirmation.late ? 'You made it.' : greeting}, <b>{confirmation.employee?.name?.split(' ')[0] || 'there'}</b>
            </h2>
            <p className="confirmation-message">
              {confirmation.late
                ? `Your check-in was recorded at ${confirmation.time}. We marked this arrival as late.`
                : confirmation.kind === 'check-in'
                  ? `You’re checked in for today at ${confirmation.time}. Have a great day!`
                  : `You’re checked out at ${confirmation.time}. You worked ${confirmation.hours}. See you next time!`}
            </p>
            {confirmation.late && <div className="late-note"><span className="late-spark">✦</span> Late arrival recorded — no further action needed.</div>}
            <button className={`btn confirmation-button ${confirmation.late ? 'bolt' : ''}`} onClick={closeConfirmation}>Continue</button>
            <div className="confirmation-auto-close">closing automatically</div>
          </div>
        </div>
      )}

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
