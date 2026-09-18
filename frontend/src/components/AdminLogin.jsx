import React, { useState } from 'react'
import { api } from '../api'

export default function AdminLogin({ onLogin }) {
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.adminLogin(password)
      onLogin()
    } catch (err) {
      setError(err.message || 'Administrator sign-in failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="admin-gate">
      <div className="admin-gate-mark">BT<span>ACCESS</span></div>
      <span className="kicker plain">Restricted / Company Administration</span>
      <h1>Admin <b>Console</b></h1>
      <p>Employee face scanning stays open at the kiosk. This area is restricted to authorized BT Projects administrators.</p>
      <form onSubmit={submit} className="admin-form">
        <label className="field">
          <span>Administrator password</span>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus autoComplete="current-password" />
        </label>
        {error && <div className="admin-error">{error}</div>}
        <button className="btn" type="submit" disabled={busy || !password}>{busy ? 'Checking…' : 'Open Admin Console →'}</button>
      </form>
      <a className="admin-back" href="#/scan">← Return to face scan kiosk</a>
    </div>
  )
}
