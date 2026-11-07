import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, fmtTime } from '../api'
import { navigate } from '../App'
import CameraCapture from '../components/CameraCapture'
import { toast } from '../components/Toast'

// A deliberately large, touch-first page for people whose face will not scan.
// Same rules as the face kiosk server-side: the number is matched to an
// enrolled employee, a camera snapshot is stored for admin review, and the
// normal check-in / check-out buffers apply.

const MAX_DIGITS = 12
const IDLE_RETURN_MS = 90 * 1000
const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9']

const time12 = () =>
  new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true })

// "9830012345" -> "98300 12345" so a long number is easy to read back.
function pretty(digits) {
  if (digits.length <= 5) return digits
  return `${digits.slice(0, 5)} ${digits.slice(5)}`
}

export default function PhoneCheckin() {
  const [allowed, setAllowed] = useState(true)
  const [digits, setDigits] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [camError, setCamError] = useState(null)
  const [done, setDone] = useState(null)
  const camRef = useRef(null)
  const lastActivity = useRef(Date.now())
  const doneTimer = useRef(null)

  const poke = useCallback(() => {
    lastActivity.current = Date.now()
  }, [])

  useEffect(() => {
    api.health().then((h) => setAllowed(h.phone_fallback !== false)).catch(() => {})
  }, [])

  // Nobody should be left on this page: drift back to the face kiosk when idle.
  useEffect(() => {
    const t = setInterval(() => {
      if (Date.now() - lastActivity.current >= IDLE_RETURN_MS) navigate('scan')
    }, 5000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => () => clearTimeout(doneTimer.current), [])

  function press(key) {
    poke()
    if (busy) return
    setError(null)
    setDigits((cur) => (cur.length >= MAX_DIGITS ? cur : cur + key))
  }

  function backspace() {
    poke()
    if (busy) return
    setError(null)
    setDigits((cur) => cur.slice(0, -1))
  }

  function clearAll() {
    poke()
    if (busy) return
    setError(null)
    setDigits('')
  }

  function finish() {
    clearTimeout(doneTimer.current)
    setDone(null)
    navigate('scan')
  }

  // Nothing is recorded until one of the two big buttons is pressed.
  async function submit(action) {
    if (busy || done) return
    if (digits.length < 6) {
      setError('Please type your full phone number.')
      return
    }
    poke()
    setBusy(true)
    setError(null)
    // The snapshot is taken at the moment of submit, from the live camera.
    const image = camRef.current?.capture() || null
    let res
    try {
      res = await api.phoneCheckin(digits, image, action)
    } catch (err) {
      res = err.data && err.data.action ? err.data : { action: 'UNKNOWN', message: err.message }
    } finally {
      setBusy(false)
    }

    const now = time12()
    const name = res.employee?.name
    if (res.action === 'CHECK-IN' || res.action === 'CHECK-OUT' || res.action === 'VISIT') {
      const kind = res.action === 'CHECK-IN' ? 'check-in' : res.action === 'CHECK-OUT' ? 'check-out' : 'visit'
      setDone({
        kind,
        name,
        time: now,
        late: res.attendance?.status === 'Late',
        hours: res.attendance?.hours_fmt || '—',
      })
      toast(`${name} ${kind === 'check-out' ? 'checked out' : kind === 'visit' ? 'visit logged' : 'checked in'} · ${now}`, { ok: true })
      clearTimeout(doneTimer.current)
      doneTimer.current = setTimeout(finish, 6000)
      return
    }

    if (res.action === 'CHECKOUT_TOO_EARLY') {
      const unlocks = res.unlocks_at ? ` Check-out opens at ${fmtTime(res.unlocks_at)}.` : ''
      setError(`${name ? `${name}, ` : ''}it is too early to check out.${unlocks}`)
    } else if (res.action === 'WAIT') {
      setError(`Someone else just checked in. Please wait ${res.retry_after ?? 'a few'} seconds and press the green button again.`)
    } else if (res.action === 'DUPLICATE_SCAN') {
      setError('You are already checked out for today.')
    } else if (res.action === 'ALREADY_CHECKED_IN') {
      setError(`${name ? `${name}, ` : ''}you are already checked in today. Press the red Check Out button when you leave.`)
    } else if (res.action === 'NOT_CHECKED_IN') {
      setError(`${name ? `${name}, ` : ''}you have not checked in today. Press the green Check In button first.`)
    } else if (res.action === 'FIELD_NO_CHECKOUT') {
      setError('Field staff do not check out. Press the green Check In button to log a visit.')
    } else {
      setError(res.message || 'Could not check you in. Please try again or ask an administrator.')
    }
  }

  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'

  return (
    <div className="page" onPointerDown={poke}>
      <div className="page-head">
        <div>
          <span className="kicker plain">Kiosk // Phone Check-In</span>
          <h1>Phone <b>Check-In</b></h1>
          <div className="sub">Type the phone number saved on your profile, then press Check In when you arrive or Check Out when you leave.</div>
        </div>
        <button type="button" className="btn ghost big-back" onClick={() => navigate('scan')}>
          ← Back to face scan
        </button>
      </div>

      {!allowed ? (
        <div className="card phone-off">
          <div className="phone-off-title">Phone check-in is turned off</div>
          <p>Please use the face scan, or ask an administrator to check you in.</p>
          <button type="button" className="btn big-action" onClick={() => navigate('scan')}>Go to face scan</button>
        </div>
      ) : (
        <div className="scan-grid">
          <div className="cam-col">
            <CameraCapture ref={camRef} active onError={setCamError} />
            <div className="cam-caption">
              <span>LOOK AT THE CAMERA — A PHOTO IS TAKEN WHEN YOU PRESS A BUTTON</span>
              <span className="mono">{camError ? 'CAM 01 · OFFLINE' : 'CAM 01 · LIVE'}</span>
            </div>
          </div>

          <form className="card phone-pad" onSubmit={(e) => e.preventDefault()}>
            <label className="phone-pad-label" htmlFor="phone-display">Your phone number</label>
            <input
              id="phone-display"
              className="phone-display"
              type="tel"
              inputMode="numeric"
              autoComplete="off"
              maxLength={MAX_DIGITS + 1}
              placeholder="98300 12345"
              value={pretty(digits)}
              disabled={busy}
              aria-describedby={error ? 'phone-error' : undefined}
              onChange={(e) => {
                poke()
                setError(null)
                setDigits(e.target.value.replace(/\D/g, '').slice(0, MAX_DIGITS))
              }}
            />

            {error && <div id="phone-error" className="phone-error-big" role="alert">{error}</div>}

            <div className="keypad" role="group" aria-label="Number keypad">
              {KEYS.map((k) => (
                <button key={k} type="button" className="key" onClick={() => press(k)} disabled={busy}>{k}</button>
              ))}
              <button type="button" className="key key-clear" onClick={clearAll} disabled={busy || !digits}>Clear</button>
              <button type="button" className="key" onClick={() => press('0')} disabled={busy}>0</button>
              <button type="button" className="key key-back" onClick={backspace} disabled={busy || !digits} aria-label="Delete last digit">⌫</button>
            </div>

            <div className="intent-row" role="group" aria-label="Choose what you are doing">
              <button type="button" className="intent-btn in" onClick={() => submit('check-in')} disabled={busy || digits.length < 6}>
                <span className="ib-icon" aria-hidden="true">→</span>
                <span className="ib-label">{busy ? 'Checking…' : 'Check In'}</span>
                <span className="ib-hint">I am arriving</span>
              </button>
              <button type="button" className="intent-btn out" onClick={() => submit('check-out')} disabled={busy || digits.length < 6}>
                <span className="ib-icon" aria-hidden="true">←</span>
                <span className="ib-label">{busy ? 'Checking…' : 'Check Out'}</span>
                <span className="ib-hint">I am leaving</span>
              </button>
            </div>
            <div className="phone-help mono">Type your number, then press the button for what you are doing. Nothing is recorded until you press it.</div>
          </form>
        </div>
      )}

      {done && (
        <div className={`confirmation-backdrop ${done.late ? 'late' : ''}`} role="dialog" aria-modal="true" aria-labelledby="phone-done-title" onMouseDown={(e) => e.target === e.currentTarget && finish()}>
          <div className={`confirmation-dialog ${done.kind} ${done.late ? 'is-late' : ''}`}>
            <div className="confirmation-icon" aria-hidden="true">
              <svg viewBox="0 0 52 52" focusable="false">
                <circle className="confirmation-circle" cx="26" cy="26" r="23" />
                <path className="confirmation-check" d="M14 27.5 22 35l16-18" />
              </svg>
            </div>
            <div className="confirmation-kicker">
              {done.late ? 'Late arrival noted' : done.kind === 'check-in' ? 'Attendance recorded' : done.kind === 'visit' ? 'Visit recorded' : 'Day complete'}
            </div>
            <h2 id="phone-done-title">
              {greeting}, <b>{done.name?.split(' ')[0] || 'there'}</b>
            </h2>
            <p className="confirmation-message">
              {done.kind === 'check-in'
                ? `You are checked in at ${done.time}.${done.late ? ' This arrival was marked late.' : ' Have a great day!'}`
                : done.kind === 'visit'
                  ? `Your visit was logged at ${done.time}. Thank you!`
                  : `You are checked out at ${done.time}. You worked ${done.hours}. See you next time!`}
            </p>
            <div className="phone-note">Verified with your phone number</div>
            <button className="btn confirmation-button big-action" onClick={finish}>OK</button>
            <div className="confirmation-auto-close">closing automatically</div>
          </div>
        </div>
      )}
    </div>
  )
}
