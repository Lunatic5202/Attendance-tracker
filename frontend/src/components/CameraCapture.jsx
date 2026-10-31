import React, { useEffect, useRef, useState } from 'react'

export function captureDataURL(video) {
  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth || 640
  canvas.height = video.videoHeight || 480
  const ctx = canvas.getContext('2d')
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', 0.9)
}

const CAMERA_ERROR_MESSAGES = {
  AbortError: 'Camera startup was interrupted. Try starting it again.',
  NotAllowedError: 'Camera permission was denied. Allow camera access in your browser.',
  NotFoundError: 'No camera was found on this device.',
  NotReadableError: 'The camera is already in use or could not be accessed.',
  OverconstrainedError: 'The camera cannot satisfy the requested video settings.',
  SecurityError: 'Camera access is blocked. Open this site over HTTPS.',
  VideoPlaybackError: 'The camera connected, but the video feed did not start.',
  CameraApiUnavailable: 'This browser does not provide camera access. Use a supported browser over HTTPS.',
  CameraTrackEnded: 'The camera stream stopped. Try starting it again.',
}

function cameraError(name) {
  const error = new Error(name)
  error.name = name
  return error
}

function waitForVideoFrame(video, isCancelled) {
  if (video.readyState >= 2 && video.videoWidth > 0) return Promise.resolve()

  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (error) => {
      if (settled) return
      settled = true
      clearTimeout(timeout)
      video.removeEventListener('loadeddata', checkReady)
      video.removeEventListener('playing', checkReady)
      video.removeEventListener('error', onError)
      if (error) reject(error)
      else resolve()
    }
    const checkReady = () => {
      if (isCancelled()) return finish(new DOMException('Camera startup cancelled', 'AbortError'))
      if (video.readyState >= 2 && video.videoWidth > 0) finish()
    }
    const onError = () => finish(cameraError('VideoPlaybackError'))
    const timeout = setTimeout(() => finish(new Error('VideoPlaybackError')), 10000)

    video.addEventListener('loadeddata', checkReady)
    video.addEventListener('playing', checkReady)
    video.addEventListener('error', onError)
    checkReady()
  })
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
  const [retryKey, setRetryKey] = useState(0)

  useEffect(() => {
    if (!active) {
      setReady(false)
      return undefined
    }

    let stream = null
    let cancelled = false
    let videoTrack = null
    let handleTrackEnded = null
    const video = videoRef.current

    setReady(false)
    setError(null)
    if (onError) onError(null)

    const startCamera = async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          const unavailable = new Error('CameraApiUnavailable')
          unavailable.name = 'CameraApiUnavailable'
          throw unavailable
        }

        const cameraStream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 640 },
            height: { ideal: 480 },
            facingMode: 'user',
          },
          audio: false,
        })

        if (cancelled) {
          cameraStream.getTracks().forEach((track) => track.stop())
          return
        }

        stream = cameraStream
        videoTrack = cameraStream.getVideoTracks()[0]
        if (videoTrack) {
          handleTrackEnded = () => {
            if (cancelled) return
            setReady(false)
            setError('CameraTrackEnded')
            if (onError) onError('CameraTrackEnded')
          }
          videoTrack.addEventListener('ended', handleTrackEnded)
        }

        if (!video) throw new Error('VideoPlaybackError')

        video.muted = true
        video.playsInline = true
        video.srcObject = cameraStream

        // Do not report LIVE until the browser confirms playback and a real
        // frame is available. An interrupted play() is surfaced to the user.
        await video.play()
        await waitForVideoFrame(video, () => cancelled)

        if (cancelled) return
        setError(null)
        setReady(true)
        if (onError) onError(null)
      } catch (cause) {
        if (cancelled) return
        const errorName = cause?.name || cause?.message || 'CameraUnavailable'
        setReady(false)
        setError(errorName)
        if (onError) onError(errorName)
        if (stream) {
          stream.getTracks().forEach((track) => track.stop())
          stream = null
        }
        if (video && video.srcObject) {
          video.pause()
          video.srcObject = null
        }
      }
    }

    startCamera()

    return () => {
      cancelled = true
      if (videoTrack && handleTrackEnded) {
        videoTrack.removeEventListener('ended', handleTrackEnded)
      }
      if (stream) {
        stream.getTracks().forEach((track) => track.stop())
      }
      if (video && video.srcObject === stream) {
        video.pause()
        video.srcObject = null
      }
    }
  }, [active, onError, retryKey])

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
            setTimeout(collect, 140)
          } else if (frames.length) {
            onBurst(frames)
          }
        }
        collect()
      } else {
        const frame = grab()
        if (frame && onFrame) onFrame(frame)
      }
    }, 1500)
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

  const retryCamera = () => {
    setError(null)
    setReady(false)
    if (onError) onError(null)
    setRetryKey((key) => key + 1)
  }

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
              <div>Camera unavailable — {CAMERA_ERROR_MESSAGES[error] || error}</div>
              <button type="button" onClick={retryCamera}>Retry camera</button>
              <div>Or use the simulate controls below.</div>
            </>
          ) : (
            <div>Starting camera…</div>
          )}
        </div>
      )}
    </div>
  )
}
