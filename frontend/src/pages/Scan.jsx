import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, fmtTime } from '../api'
import { navigate } from '../App'
import CameraCapture from '../components/CameraCapture'
import { toast } from '../components/Toast'

const actions = {
  'CHECK-IN': { label: 'Check-In', cls: 'in', icon: '→' },
  DETECTED: { label: 'Employee Detected', cls: 'warn', icon: '◎' },
  NO_FACE: { label: 'Ready for Next Person', cls: 'idle', icon: '◎' },
  'CHECK-OUT': { label: 'Check-Out', cls: 'out', icon: '→' },
  VISIT: { label: 'Visit Logged', cls: 'in', icon: '→' },
  UNKNOWN: { label: 'Unknown Face', cls: 'idle', icon: '?' },
  LOW_QUALITY: { label: 'Adjust Camera', cls: 'warn', icon: '◎' },
  DUPLICATE_SCAN: { label: 'Duplicate Rejected', cls: 'idle', icon: '!' },
  CHECKOUT_TOO_EARLY: { label: 'Check-Out Held', cls: 'warn', icon: '⏱' },
  WAIT: { label: 'One At A Time', cls: 'warn', icon: '⏱' },
  DEMO_NEEDS_EMPLOYEE: { label: 'Pick Employee', cls: 'idle', icon: '!' },
  ALREADY_CHECKED_IN: { label: 'Already Checked In', cls: 'warn', icon: '!' },
  NOT_CHECKED_IN: { label: 'Check In First', cls: 'warn', icon: '!' },
  FIELD_NO_CHECKOUT: { label: 'No Check-Out Needed', cls: 'idle', icon: '!' },
}

const star = () => new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true })

const IDLE_SLEEP_MS = 30 * 1000
const PROMPT_MS = 20 * 1000
const CONFIRM_MS = 5200

export default function Scan() {
  const [scanning, setScanning] = useState(true)
  const [asleep, setAsleep] = useState(false)
  const [camError, setCamError] = useState(null)
  const [last, setLast] = useState(null)
  const [confirmation, setConfirmation] = useState(null)
  const [detected, setDetected] = useState(null)
  const [processing, setProcessing] = useState(false)
  const [phoneAllowed, setPhoneAllowed] = useState(true)
  const [log, setLog] = useState([
    { t: 'SYS', s: 'attendance relay online — awaiting camera frames…', tone: '' },
  ])
  const lock = useRef(false)
  const confirmationRef = useRef(null)
  const detectedRef = useRef(null)
  const pendingFramesRef = useRef(null)
  const blockedEmployeeRef = useRef(null)
  const noFaceStreakRef = useRef(0)
  const confirmationTimer = useRef(null)
  const promptTimer = useRef(null)
  const audioContextRef = useRef(null)
  const logBox = useRef(null)
  const asleepRef = useRef(false)
  const lastActivity = useRef(Date.now())
  const camRef = useRef(null)

  useEffect(() => {
    asleepRef.current = asleep
  }, [asleep])

  // Hide the phone fallback when an administrator has switched it off.
  useEffect(() => {
    api.health().then((h) => setPhoneAllowed(h.phone_fallback !== false)).catch(() => {})
  }, [])

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
    clearTimeout(promptTimer.current)
    audioContextRef.current?.close().catch(() => {})
  }, [])

  const pushLog = (t, s, tone = '') =>
    setLog((cur) => [...cur.slice(-29), { t, s, tone }])

  // The recognition prompt waits for a button, but not forever: it expires so a
  // kiosk left alone returns to idle, and the same face is not re-prompted
  // until it has left the frame.
  const clearPrompt = () => {
    clearTimeout(promptTimer.current)
    detectedRef.current = null
    pendingFramesRef.current = null
    setDetected(null)
  }

  const dismissPrompt = (why) => {
    const id = detectedRef.current?.employee?.id
    if (id) blockedEmployeeRef.current = id
    clearPrompt()
    if (why) pushLog('VERIFY', why, 'err-line')
  }

  const showPrompt = (result) => {
    const same = detectedRef.current?.employee?.id === result.employee?.id
    detectedRef.current = result
    setDetected(result)
    if (!same) {
      clearTimeout(promptTimer.current)
      const expire = () => {
        if (lock.current) { promptTimer.current = setTimeout(expire, 1500); return }
        dismissPrompt('prompt timed out — step away and back to retry')
      }
      promptTimer.current = setTimeout(expire, PROMPT_MS)
    }
  }

  // Recognition only: hold the detected employee on screen until they choose an action.
  // A completed employee stays blocked until the camera sees them leave the frame.
  const runScan = useCallback(async (frames) => {
    if (lock.current || asleepRef.current || confirmationRef.current || !frames?.length) return
    lock.current = true
    try {
      const result = await api.scan(frames, undefined, undefined)
      if (result.action === 'DETECTED') {
        noFaceStreakRef.current = 0
        const employeeId = result.employee?.id
        if (employeeId && blockedEmployeeRef.current === employeeId) return
        pendingFramesRef.current = frames
        showPrompt(result)
        setLast({ action: 'DETECTED', employee: result.employee, message: result.message, time: star() })
      } else {
        if (result.action === 'NO_FACE') {
          noFaceStreakRef.current += 1
          if (noFaceStreakRef.current >= 2) blockedEmployeeRef.current = null
          clearPrompt()
        } else if (result.action === 'UNKNOWN' || result.action === 'LOW_QUALITY') {
          noFaceStreakRef.current = 0
          clearPrompt()
        }
        handleResult(result)
      }
    } catch (e) {
      const result = e.data || { action: 'UNKNOWN', message: e.message }
      if (result.action === 'NO_FACE') {
        noFaceStreakRef.current += 1
        if (noFaceStreakRef.current >= 2) blockedEmployeeRef.current = null
      }
      if (result.action === 'UNKNOWN' || result.action === 'LOW_QUALITY' || result.action === 'NO_FACE') {
        if (result.action !== 'NO_FACE') noFaceStreakRef.current = 0
        clearPrompt()
      }
      handleResult(result)
    } finally {
      lock.current = false
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function chooseAction(action) {
    const prompt = detectedRef.current
    const frames = pendingFramesRef.current
    if (lock.current || !prompt?.employee?.id || !frames?.length) return
    lock.current = true
    setProcessing(true)
    try {
      const result = await api.scan(frames, undefined, action)
      blockedEmployeeRef.current = prompt.employee.id
      noFaceStreakRef.current = 0
      clearPrompt()
      handleResult(result)
    } catch (e) {
      const result = e.data || { action: 'UNKNOWN', message: e.message }
      handleResult(result)
      if (result.action === 'ALREADY_CHECKED_IN') {
        detectedRef.current = { ...prompt, suggested_action: 'check-out' }
        setDetected(detectedRef.current)
      } else if (result.action === 'NOT_CHECKED_IN') {
        detectedRef.current = { ...prompt, suggested_action: 'check-in' }
        setDetected(detectedRef.current)
      }
    } finally {
      setProcessing(false)
      lock.current = false
    }
  }

  function closeConfirmation() {
    clearTimeout(confirmationTimer.current)
    confirmationRef.current = null
    setConfirmation(null)
  }

  useEffect(() => {
    if (!confirmation) return undefined
    const onKey = (e) => { if (e.key === 'Escape') closeConfirmation() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [confirmation]) // eslint-disable-line react-hooks/exhaustive-deps

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
    }, CONFIRM_MS)
  }

  // The phone-number fallback now lives on its own tab (#/phone).
  function openPhone() {
    navigate('phone')
  }

  function handleResult(res, opts = {}) {
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
        phone: opts.phone,
      })
      pushLog('SCAN', `${res.employee?.name} — CHECK-IN @${now}`, 'ok-line')
      toast(`${res.employee?.name} checked in · ${now}`, { ok: true })
    } else if (action === 'VISIT') {
      // Face scans keep their toast; the phone fallback gets the welcome dialog too.
      if (opts.phone) openConfirmation({ kind: 'visit', employee: res.employee, time: now, phone: true })
      pushLog('SCAN', `${res.employee?.name} — VISIT @${now}`, 'ok-line')
      toast(`${res.employee?.name} visit logged · ${now}`, { ok: true })
    } else if (action === 'CHECK-OUT') {
      const hrs = res.attendance?.hours_fmt || '—'
      openConfirmation({
        kind: 'check-out',
        employee: res.employee,
        time: now,
        hours: res.session_hours_fmt || hrs,
        total: hrs,
        sessions: res.session_count || 1,
        phone: opts.phone,
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
    } else if (action === 'ALREADY_CHECKED_IN' || action === 'NOT_CHECKED_IN' || action === 'FIELD_NO_CHECKOUT') {
      pushLog('VERIFY', `${res.employee?.name || 'Employee'} — ${res.message}`, 'err-line')
      toast(res.message)
    } else if (action === 'DEMO_NEEDS_EMPLOYEE') {
      pushLog('VERIFY', 'camera/demo mode — use simulate below', 'err-line')
    }
  }

  const meta = actions[last?.action] || actions.UNKNOWN
  const greeting = confirmation
    ? new Date().getHours() < 12 ? 'Good morning' : new Date().getHours() < 17 ? 'Good afternoon' : 'Good evening'
    : ''

  return (
    <div className="page scan-page">
      <div className="page-head">
        <div>
          <span className="kicker plain">Kiosk // Live Attendance</span>
          <h1>Face <b>Scan</b></h1>
          <div className="sub">Stand in front of the camera. Once recognised, choose whether to check in or check out.</div>
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
            ref={camRef}
            active={scanning || asleep}
            watch={scanning || asleep}
            motionThreshold={0.05}
            onMotion={onMotion}
            onError={setCamError}
            onBurst={scanning ? runScan : undefined}
            burst={3}
          />
          <div className="cam-caption">
            <span>{scanning ? 'FACE DETECTION — ACTION REQUIRED' : 'AUTO-SCAN PAUSED'}</span>
            <span className="mono">{scanning ? 'CAM 01 · LIVE' : 'CAM 01 · PAUSED'}</span>
          </div>

          {phoneAllowed && (
            <div className="phone-fallback">
              <button type="button" className="phone-toggle big-action" onClick={openPhone}>
                <span className="pt-icon" aria-hidden="true">☎</span>
                <span className="pt-text">
                  <b>Can’t scan?</b>
                  <span>Press here to use your phone number</span>
                </span>
              </button>
            </div>
          )}
        </div>

        <div className="result-panel">
          <div className={`result-card ${meta.cls}`}>
            <div className="rc-top">
              <span className="rc-flag">{meta.label}</span>
              <span className="rc-time">{last ? last.time : star()}</span>
            </div>

            {detected ? null : last?.employee ? (
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

            {!detected && last?.message && last.action !== 'CHECK-IN' && last.action !== 'CHECK-OUT' && (
              <div className="rc-note">{last.message}</div>
            )}

            {detected && (() => {
              const emp = detected.employee
              const field = emp.category === 'field'
              const suggested = detected.suggested_action
              const since = detected.checked_in_since
              const status = field
                ? 'Field staff — each scan logs one visit'
                : since ? `Checked in since ${fmtTime(since)}` : 'Not currently checked in'
              return (
                <div className="detected-panel" role="status" aria-live="polite">
                  <div className="detected-top">
                    <div className="detected-kicker"><span className="detected-pulse" /> FACE RECOGNISED</div>
                    <button type="button" className="prompt-cancel" disabled={processing} onClick={() => dismissPrompt()}>
                      Not you?
                    </button>
                  </div>
                  <div className="detected-id">
                    <div className="detected-avatar" aria-hidden="true">{emp.name.trim().charAt(0).toUpperCase()}</div>
                    <div className="detected-who">
                      <div className="detected-name">{emp.name}</div>
                      <div className="detected-meta mono">{emp.id} / {emp.department} · {emp.role || 'staff'}</div>
                    </div>
                  </div>
                  <div className={`prompt-status ${since ? 'on' : ''}`}>{status}</div>
                  <div className="intent-row">
                    {field ? (
                      <button type="button" className="intent-btn in suggested" disabled={processing} onClick={() => chooseAction('check-in')}>
                        <span className="ib-label">{processing ? 'PROCESSING…' : 'LOG VISIT'}</span>
                        <span className="ib-hint">Record arrival</span>
                      </button>
                    ) : (
                      <>
                        <button type="button" className={`intent-btn in ${suggested === 'check-in' ? 'suggested' : 'muted'}`} disabled={processing} onClick={() => chooseAction('check-in')}>
                          {suggested === 'check-in' && <span className="ib-badge">Suggested</span>}
                          <span className="ib-label">{processing ? 'PLEASE WAIT…' : 'CHECK IN'}</span>
                          <span className="ib-hint">{suggested === 'check-out' ? 'Already checked in' : 'Start a session'}</span>
                        </button>
                        <button type="button" className={`intent-btn out ${suggested === 'check-out' ? 'suggested' : 'muted'}`} disabled={processing} onClick={() => chooseAction('check-out')}>
                          {suggested === 'check-out' && <span className="ib-badge">Suggested</span>}
                          <span className="ib-label">{processing ? 'PLEASE WAIT…' : 'CHECK OUT'}</span>
                          <span className="ib-hint">{suggested === 'check-in' ? 'Not checked in' : 'End current session'}</span>
                        </button>
                      </>
                    )}
                  </div>
                  <div className="prompt-timer" aria-hidden="true" style={{ '--prompt-ms': `${PROMPT_MS}ms` }}>
                    <span key={emp.id} />
                  </div>
                  <div className="detected-foot">Nothing is recorded until you press a button.</div>
                </div>
              )
            })()}

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

      <div className="card tight kiosk-note" style={{ marginTop: '0.65rem' }}>
        <span className="series-tag">Secure kiosk</span>
        <span className="mono" style={{ fontSize: '0.66rem', color: 'var(--muted)', letterSpacing: '0.1em' }}>
          Only administrator-enrolled faces can create attendance records. Choose Check In or Check Out after recognition. Repeat sessions are supported throughout the day.
        </span>
      </div>

      {confirmation && (
        <div className={`confirmation-backdrop ${confirmation.late ? 'late' : ''}`} role="dialog" aria-modal="true" aria-labelledby="confirmation-title" aria-describedby="confirmation-desc" onMouseDown={(e) => e.target === e.currentTarget && closeConfirmation()}>
          <div className={`confirmation-dialog ${confirmation.kind} ${confirmation.late ? 'is-late' : ''}`}>
            <button className="confirmation-close" onClick={closeConfirmation} aria-label="Close confirmation">×</button>
            <div className="confirmation-icon" aria-hidden="true">
              <svg viewBox="0 0 52 52" focusable="false">
                <circle className="confirmation-circle" cx="26" cy="26" r="23" />
                <path className="confirmation-check" d="M14 27.5 22 35l16-18" />
              </svg>
            </div>
            <div className="confirmation-kicker">{confirmation.late ? 'Late arrival noted' : confirmation.kind === 'check-in' ? 'Attendance recorded' : confirmation.kind === 'visit' ? 'Visit recorded' : 'Checked out'}</div>
            <h2 id="confirmation-title">
              {confirmation.late ? 'Welcome in' : greeting}, <b>{confirmation.employee?.name?.split(' ')[0] || 'there'}</b>
            </h2>
            <p className="confirmation-message" id="confirmation-desc">
              {confirmation.late
                ? 'Your check-in was recorded and marked as a late arrival.'
                : confirmation.kind === 'check-in'
                  ? 'Your check-in was recorded. Have a great day!'
                  : confirmation.kind === 'visit'
                    ? 'Your visit was logged. Thanks for stopping by!'
                    : 'Your check-out was recorded. See you next time!'}
            </p>
            <div className="confirmation-facts">
              <div><span>{confirmation.kind === 'check-out' ? 'Out at' : confirmation.kind === 'visit' ? 'Visit at' : 'In at'}</span><b>{confirmation.time}</b></div>
              {confirmation.kind === 'check-in' && (
                <div><span>Status</span><b className={confirmation.late ? 'bad' : ''}>{confirmation.late ? 'Late' : 'On time'}</b></div>
              )}
              {confirmation.kind === 'check-out' && (
                <div><span>This session</span><b>{confirmation.hours}</b></div>
              )}
              {confirmation.kind === 'check-out' && confirmation.sessions > 1 && (
                <div><span>Today</span><b>{confirmation.total}</b></div>
              )}
            </div>
            {confirmation.phone && <div className="phone-note">Verified with your phone number</div>}
            <button autoFocus className={`btn confirmation-button ${confirmation.late ? 'bolt' : ''}`} onClick={closeConfirmation}>Continue</button>
            <div className="confirmation-timer" aria-hidden="true" style={{ '--confirm-ms': `${CONFIRM_MS}ms` }}><span /></div>
            <div className="confirmation-auto-close">closes automatically · Esc to dismiss</div>
          </div>
        </div>
      )}

      {asleep && (
        <div className="kiosk-standby" onClick={() => { poke(); setAsleep(false) }} role="button" tabIndex={0} onKeyDown={() => { poke(); setAsleep(false) }}>
          <div className="ks-radar">
            <span className="ks-ring r1" />
            <span className="ks-ring r2" />
            <span className="ks-ring r3" />
            <span className="ks-dot" />
          </div>
          <div className="ks-gate">
            <div className="ks-kicker">TOUCHLESS KIOSK · STANDBY</div>
            <h1>Tap or Wave to <b>Wake</b></h1>
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
