import { useEffect, useState } from 'react'

const BASE = import.meta.env.VITE_API_BASE || ''

export default function WakeUpGuard({ children }) {
  const [ready, setReady] = useState(false)
  const [attempts, setAttempts] = useState(0)

  useEffect(() => {
    let cancelled = false
    let timer

    async function ping() {
      try {
        const res = await fetch(`${BASE}/api/health`, { cache: 'no-store' })
        if (res.ok) {
          if (!cancelled) setReady(true)
          return true
        }
      } catch {}
      return false
    }

    async function loop() {
      const ok = await ping()
      if (ok || cancelled) return
      setAttempts((a) => a + 1)
      // exponential-ish backoff up to ~15s
      const delay = Math.min(2000 * Math.pow(1.2, attempts), 15000)
      timer = setTimeout(loop, delay)
    }

    ping().then((ok) => {
      if (!ok && !cancelled) loop()
    })

    const onFocus = () => {
      if (!ready) {
        ping().then((ok) => {
          if (ok && !cancelled) setReady(true)
        })
      }
    }
    const onVis = () => {
      if (!ready && document.visibilityState === 'visible') onFocus()
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVis)
    window.addEventListener('online', onFocus)

    return () => {
      cancelled = true
      clearTimeout(timer)
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVis)
      window.removeEventListener('online', onFocus)
    }
  }, [attempts, ready])

  if (ready) return children

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100dvh',
        flexDirection: 'column',
        gap: 8,
        padding: '0 1rem',
        textAlign: 'center',
      }}
    >
      <div>Waking up server...</div>
      <small>Render free dyno is spinning up. This usually takes 10–20s.</small>
    </div>
  )
}