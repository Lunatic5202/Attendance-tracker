import React, { useEffect, useState } from 'react'

const listeners = new Set()

export function toast(message, opts = {}) {
  listeners.forEach((fn) => fn({ id: Date.now() + Math.random(), message, ok: Boolean(opts.ok) }))
}

export function Toasts() {
  const [items, setItems] = useState([])

  useEffect(() => {
    const add = (item) => {
      setItems((cur) => [...cur, item])
      setTimeout(() => setItems((cur) => cur.filter((i) => i.id !== item.id)), 3200)
    }
    listeners.add(add)
    return () => listeners.delete(add)
  }, [])

  return (
    <div>
      {items.map((item) => (
        <div key={item.id} className={`toast ${item.ok ? 'ok' : ''}`}>
          {item.message}
        </div>
      ))}
    </div>
  )
}