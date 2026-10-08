import React, { useEffect, useRef, useState } from 'react'

export function captureDataURL(video) {
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth || 640
  canvas.height = video.videoHeight || 480
  const ctx = canvas.getContext('2d')
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', 0.9)
}

export default function CameraCapture({
  active = true,
  onFrame,
  mirror = true,
  watch = false,
  motionThreshold = 0.05,
  onMotion,
  onError,
  burst = 1,
  onBurst,
}) {
  const videoRef = useRef(null)
  const [error, setError] = useState(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!active) return
    let stream = null
    let cancelled = false
    navigator.mediaDevices
      .getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false })
      .then((s) => {
        if (cancelled) {
          s.getTracks().forEach((t) => t.stop())
          return
        }
        stream = s
        if (videoRef.current) {
          videoRef.current.srcObject = s
          videoRef.current.play().catch(() => {})
        }
        setReady(true)
        setError(null)
      })
      .catch((e) => {
        setError(e.name || 'camera_unavailable')
        if (onError) onError(e.name || 'camera_unavailable')
      })

    return () => {
      cancelled = true
      if (stream) {
        stream.getTracks().forEach((t) => t.stop())
      }
    }
  }, [active, onError])

  useEffect(() => {
    if (!ready || (!onFrame && !onBurst) || !videoRef.current) return
    const grab = () => {
      const v = videoRef.current
      if (v && v.readyState >= 2 && v.videoWidth > 0) return captureDataURL(v)
      return null
    }
    const timer = setInterval(() => {
      if (onBurst && burst > 1) {
        // Short burst: the backend votes across frames, so one smeared or
        // badly lit frame no longer fails the whole scan.
        const frames = []
        let taken = 0
        const collect = () => {
          const frame = grab()
          if (frame) frames.push(frame)
          taken += 1
          if (taken < burst) {
            setTimeout(collect, 250)
          } else if (frames.length) {
            onBurst(frames)
          }
        }
        collect()
      } else {
        const frame = grab()
        if (frame && onFrame) onFrame(frame)
      }
    }, 2600)
    return () => clearInterval(timer)
  }, [ready, onFrame, onBurst, burst])

  useEffect(() => {
    if (!watch || !ready || !videoRef.current) return
    const canvas = document.createElement('canvas')
    canvas.width = 48
    canvas.height = 36
    const ctx = canvas.getContext('2d')
    let prev = null
    const timer = setInterval(() => {
      const v = videoRef.current
      if (!v || v.readyState < 2 || v.videoWidth === 0) return
      ctx.drawImage(v, 0, 0, canvas.width, canvas.height)
      let data
      try {
        data = ctx.getImageData(0, 0, canvas.width, canvas.height).data
      } catch {
        return
      }
      const cur = new Float32Array(canvas.width * canvas.height)
      for (let i = 0, j = 0; i < data.length; i += 4, j++) {
        cur[j] = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]
      }
      if (prev) {
        let sum = 0
        for (let i = 0; i < cur.length; i++) {
          const d = cur[i] - prev[i]
          sum += d > 0 ? d : -d
        }
        if (sum / cur.length / 255 > motionThreshold && onMotion) onMotion()
      }
      prev = cur
    }, 400)
    return () => {
      clearInterval(timer)
      prev = null
    }
  }, [watch, ready, motionThreshold, onMotion])

  return (
    <div className="camera">
      <span className="cam-kicker">CAM 01 / {ready ? 'LIVE' : 'OFFLINE'}</span>
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        style={mirror ? { transform: 'scaleX(-1)' } : undefined}
      />
      {ready && <div className="scanline" />}
      <div className="frame-guide" style={{ opacity: ready ? 0.4 : 0 }} />
      {!ready && (
        <div className="camera-off">
          {error ? (
            <>
              <div>Camera unavailable — {error}</div>
              <div>use the simulate controls below</div>
            </>
          ) : (
            <div>starting camera…</div>
          )}
        </div>
      )}
    </div>
  )
}