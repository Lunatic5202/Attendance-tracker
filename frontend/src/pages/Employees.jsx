import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import CameraCapture from '../components/CameraCapture'
import { toast } from '../components/Toast'

function EnrollModal({ employee, onClose, onDone }) {
  const [busy, setBusy] = useState(false)
  const [lastShot, setLastShot] = useState(null)

  const capture = useCallback(async (dataUrl) => setLastShot(dataUrl), [])

  async function submit() {
    if (!lastShot) return toast('Hold still and capture a frame first')
    setBusy(true)
    try {
      await api.enrollFace(employee.id, lastShot)
      toast(`Face enrolled for ${employee.name}`, { ok: true })
      onDone()
      onClose()
    } catch (e) {
      toast(e.message || 'Enrollment failed — no face detected?')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="mhead">
          <h3>Enroll Face · {employee.id}</h3>
          <button className="x-btn" onClick={onClose}>✕</button>
        </div>
        <div className="mbody">
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: '0.9rem' }}>
            <span className="mono" style={{ fontWeight: 700, color: 'var(--navy-deep)' }}>{employee.name}</span>
            <span className="badge plain">{employee.department}</span>
          </div>
          <CameraCapture active={!busy} onFrame={capture} />
          <p className="muted" style={{ fontSize: '0.82rem', marginTop: '0.8rem' }}>
            Look straight at the camera. The latest captured frame appears below and is enrolled
            on submit. Only a compact embedding is stored.
          </p>
          {lastShot && <img src={lastShot} alt="face" style={{ width: '100%', maxHeight: 220, objectFit: 'cover', borderRadius: 'var(--radius)', border: '1px solid var(--line)' }} />}
        </div>
        <div className="mfoot">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn" onClick={submit} disabled={busy || !lastShot}>
            {busy ? 'Enrolling…' : 'Capture & Enroll Face'}
          </button>
        </div>
      </div>
    </div>
  )
}

function AddModal({ onClose, onCreated }) {
  const [form, setForm] = useState({ name: '', department: 'General', role: '', email: '', phone: '' })
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const [busy, setBusy] = useState(false)

  async function submit() {
    if (!form.name.trim()) return toast('Name is required')
    setBusy(true)
    try {
      const emp = await api.createEmployee(form)
      toast(`Registered ${emp.id}`, { ok: true })
      onCreated(emp)
      onClose()
    } catch (e) {
      toast(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="mhead">
          <h3>Register Employee</h3>
          <button className="x-btn" onClick={onClose}>✕</button>
        </div>
        <div className="mbody">
          <div className="field">
            <label>Full Name *</label>
            <input className="input" value={form.name} onChange={set('name')} placeholder="e.g. John Doe" />
          </div>
          <div className="row">
            <div className="field" style={{ flex: 1 }}>
              <label>Department</label>
              <select className="input" value={form.department} onChange={set('department')}>
                {['General', 'Development', 'Operations', 'Field Works', 'Administration', 'Finance'].map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label>Role</label>
              <input className="input" value={form.role} onChange={set('role')} placeholder="Engineer / Analyst" />
            </div>
          </div>
          <div className="field">
            <label>Email</label>
            <input className="input" type="email" value={form.email} onChange={set('email')} />
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Phone</label>
            <input className="input" value={form.phone} onChange={set('phone')} />
          </div>
        </div>
        <div className="mfoot">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn" onClick={submit} disabled={busy}>{busy ? 'Saving…' : 'Register Employee'}</button>
        </div>
      </div>
    </div>
  )
}

export default function Employees() {
  const [list, setList] = useState([])
  const [q, setQ] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [enrolling, setEnrolling] = useState(null)
  const [confirmDel, setConfirmDel] = useState(null)

  const load = () => api.employees().then(setList).catch(() => setList([]))
  useEffect(() => { load() }, [])

  const filtered = list.filter((e) => {
    const needle = q.toLowerCase()
    return !needle || e.name.toLowerCase().includes(needle) || e.id.toLowerCase().includes(needle)
  })

  async function toggleActive(e, id) {
    const next = !e.is_active
    try {
      await api.updateEmployee(id, { is_active: next })
      toast(next ? `${e.name} re-activated` : `${e.name} deactivated`, { ok: true })
      load()
    } catch (err) {
      toast(err.message)
    }
  }

  async function doDelete(id) {
    await api.deleteEmployee(id).catch(() => {})
    toast('Employee removed')
    setConfirmDel(null)
    load()
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="kicker plain">Register / Manage</span>
          <h1>Employee <b>Registry</b></h1>
          <div className="sub">{list.length} registered · faces kept as embeddings only</div>
        </div>
        <button className="btn" onClick={() => setShowAdd(true)}>+ Register Employee</button>
      </div>

      <div className="toolbar">
        <input
          className="input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search by name or id…"
          style={{ width: 'min(320px, 100%)' }}
        />
        <div className="spacer" />
        <button className="btn ghost sm" onClick={load}>Refresh</button>
      </div>

      {filtered.length === 0 ? (
        <div className="empty">{q ? 'No employees match the search.' : 'No employees yet — register the first one.'}</div>
      ) : (
        <div className="tablewrap">
          <table className="data">
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Department</th>
                <th>Role</th>
                <th>Face</th>
                <th>Status</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => (
                <tr key={e.id} style={{ opacity: e.is_active ? 1 : 0.5 }}>
                  <td><span className="id-cell">{e.id}</span></td>
                  <td>
                    <div className="strong-cell">{e.name}</div>
                    <div className="muted-cell">{e.email}</div>
                  </td>
                  <td className="muted-cell">{e.department}</td>
                  <td className="muted-cell">{e.role || '—'}</td>
                  <td>
                    <span className={`badge ${e.face_enrolled ? 'ok' : 'danger'}`}>
                      {e.face_enrolled ? 'Enrolled' : 'No Face'}
                    </span>
                  </td>
                  <td>
                    <span className={`badge ${e.is_active ? 'ok' : 'plain'}`}>
                      {e.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </td>
                  <td>
                    <div className="row" style={{ justifyContent: 'flex-end', gap: '0.4rem' }}>
                      <button className="btn sm ghost" onClick={() => setEnrolling(e)}>
                        {e.face_enrolled ? 'Re-enroll' : 'Enroll'}
                      </button>
                      <button className="btn sm ghost" onClick={() => toggleActive(e, e.id)}>
                        {e.is_active ? 'Disable' : 'Enable'}
                      </button>
                      <button className="btn sm bolt" onClick={() => setConfirmDel(e)}>✕</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAdd && <AddModal onClose={() => setShowAdd(false)} onCreated={load} />}
      {enrolling && <EnrollModal employee={enrolling} onClose={() => setEnrolling(null)} onDone={load} />}
      {confirmDel && (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setConfirmDel(null)}>
          <div className="modal">
            <div className="mhead"><h3>Remove {confirmDel.id}?</h3></div>
            <div className="mbody">
              <p style={{ margin: 0, color: 'var(--muted)' }}>
                <strong>{confirmDel.name}</strong> and their attendance history will be permanently
                deleted. Face templates are also removed.
              </p>
            </div>
            <div className="mfoot">
              <button className="btn ghost" onClick={() => setConfirmDel(null)}>Cancel</button>
              <button className="btn bolt" onClick={() => doDelete(confirmDel.id)}>Delete Employee</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}