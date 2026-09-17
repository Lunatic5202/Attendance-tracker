import React, { useEffect, useRef, useState } from 'react'

export function captureDataURL(video) {
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth || 640
  canvas.height = video.videoHeight || 480
  const ctx = canvas.getContext('2d')
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', 0.9)
}

export default function CameraCapture({ active = true, onFrame, mirror = true }) {
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
      .catch((e) => setError(e.name || 'camera_unavailable'))

    return () => {
      cancelled = true
      if (stream) {
        stream.getTracks().forEach((t) => t.stop())
      }
    }
  }, [active])

  useEffect(() => {
    if (!ready || !onFrame || !videoRef.current) return
    const timer = setInterval(() => {
      const v = videoRef.current
      if (v && v.readyState >= 2 && v.videoWidth > 0) {
        onFrame(captureDataURL(v))
      }
    }, 2600)
    return () => clearInterval(timer)
  }, [ready, onFrame])

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