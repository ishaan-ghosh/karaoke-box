import { useEffect, useRef, useState } from 'react'
import './App.css'

type ToolStatus = {
  ffmpeg: boolean
  ffprobe: boolean
  demucs: boolean
}

type Health = {
  ready: boolean
  tools: ToolStatus
}

type SeparationQuality = 'preserve' | 'best' | 'standard'

type JobStatus =
  | 'queued'
  | 'validating'
  | 'separating'
  | 'finalizing'
  | 'completed'
  | 'failed'

type Job = {
  id: string
  original_filename: string
  size_bytes: number
  status: JobStatus
  progress: number
  message: string
  duration_seconds: number | null
  error: string | null
  quality: SeparationQuality
  assets: Partial<Record<'instrumental' | 'vocals', string>>
}

const activeStatuses = new Set<JobStatus>([
  'queued',
  'validating',
  'separating',
  'finalizing',
])

const qualityOptions: Array<{
  value: SeparationQuality
  name: string
  speed: string
  description: string
  recommended?: boolean
}> = [
  {
    value: 'preserve',
    name: 'Natural backing',
    speed: 'Normal speed',
    description: 'Subtracts predicted vocals from the original mix to preserve instrument detail.',
    recommended: true,
  },
  {
    value: 'best',
    name: 'Best quality',
    speed: 'Several times slower',
    description: 'Uses the fine-tuned Demucs model and preserves the original backing texture.',
  },
  {
    value: 'standard',
    name: 'Strong removal',
    speed: 'Normal speed',
    description: 'Sums predicted instrument stems. Less vocal residue, but it may sound processed.',
  },
]

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds)) return '0:00'
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`
}

async function responseError(response: Response) {
  try {
    const body = (await response.json()) as { detail?: string }
    return body.detail || `Request failed (${response.status})`
  } catch {
    return `Request failed (${response.status})`
  }
}

function WaveIcon() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true">
      <path d="M3 17h3l2-8 4 16 4-22 4 26 4-17 2 5h3" />
    </svg>
  )
}

function StemMixer({ job }: { job: Job }) {
  const instrumentalRef = useRef<HTMLAudioElement>(null)
  const vocalsRef = useRef<HTMLAudioElement>(null)
  const frameRef = useRef<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(job.duration_seconds ?? 0)
  const [instrumentalVolume, setInstrumentalVolume] = useState(0.9)
  const [vocalVolume, setVocalVolume] = useState(0)
  const [playbackError, setPlaybackError] = useState('')

  const instrumentalUrl = job.assets.instrumental
  const vocalsUrl = job.assets.vocals

  useEffect(() => {
    if (instrumentalRef.current) {
      instrumentalRef.current.volume = instrumentalVolume
    }
  }, [instrumentalVolume])

  useEffect(() => {
    if (vocalsRef.current) vocalsRef.current.volume = vocalVolume
  }, [vocalVolume])

  useEffect(() => {
    if (!playing) return

    const updateTime = () => {
      const instrumental = instrumentalRef.current
      const vocals = vocalsRef.current
      if (!instrumental || !vocals) return
      if (Math.abs(instrumental.currentTime - vocals.currentTime) > 0.08) {
        vocals.currentTime = instrumental.currentTime
      }
      setCurrentTime(instrumental.currentTime)
      frameRef.current = requestAnimationFrame(updateTime)
    }
    frameRef.current = requestAnimationFrame(updateTime)
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    }
  }, [playing])

  const togglePlayback = async () => {
    const instrumental = instrumentalRef.current
    const vocals = vocalsRef.current
    if (!instrumental || !vocals) return

    if (playing) {
      instrumental.pause()
      vocals.pause()
      setPlaying(false)
      return
    }

    setPlaybackError('')
    vocals.currentTime = instrumental.currentTime
    try {
      await Promise.all([instrumental.play(), vocals.play()])
      setPlaying(true)
    } catch {
      instrumental.pause()
      vocals.pause()
      setPlaybackError('Your browser could not start audio playback.')
    }
  }

  const seek = (value: number) => {
    if (instrumentalRef.current) instrumentalRef.current.currentTime = value
    if (vocalsRef.current) vocalsRef.current.currentTime = value
    setCurrentTime(value)
  }

  return (
    <section className="result-card" aria-labelledby="result-heading">
      <div className="result-heading">
        <div className="success-icon" aria-hidden="true">✓</div>
        <div>
          <p className="eyebrow success">Separation complete</p>
          <h2 id="result-heading">Your karaoke mix</h2>
        </div>
      </div>

      <div className="transport">
        <button className="play-button" type="button" onClick={togglePlayback}>
          <span aria-hidden="true">{playing ? 'Ⅱ' : '▶'}</span>
          <span className="sr-only">{playing ? 'Pause' : 'Play'} stem mix</span>
        </button>
        <span className="time">{formatTime(currentTime)}</span>
        <input
          className="timeline"
          aria-label="Playback position"
          type="range"
          min="0"
          max={duration || 1}
          step="0.01"
          value={Math.min(currentTime, duration || 1)}
          onChange={(event) => seek(Number(event.target.value))}
        />
        <span className="time">{formatTime(duration)}</span>
      </div>

      {playbackError && <p className="inline-error">{playbackError}</p>}

      <div className="mixer-grid">
        <label className="stem-control">
          <span>
            <strong>Instrumental</strong>
            <small>Main karaoke backing</small>
          </span>
          <output>{Math.round(instrumentalVolume * 100)}%</output>
          <input
            aria-label="Instrumental volume"
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={instrumentalVolume}
            onChange={(event) => setInstrumentalVolume(Number(event.target.value))}
          />
        </label>
        <label className="stem-control">
          <span>
            <strong>Original vocals</strong>
            <small>Raise to compare stems</small>
          </span>
          <output>{Math.round(vocalVolume * 100)}%</output>
          <input
            aria-label="Original vocal volume"
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={vocalVolume}
            onChange={(event) => setVocalVolume(Number(event.target.value))}
          />
        </label>
      </div>

      <audio
        ref={instrumentalRef}
        src={instrumentalUrl}
        preload="metadata"
        onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
        onEnded={(event) => {
          event.currentTarget.currentTime = 0
          if (vocalsRef.current) {
            vocalsRef.current.pause()
            vocalsRef.current.currentTime = 0
          }
          setPlaying(false)
          setCurrentTime(0)
        }}
      />
      <audio ref={vocalsRef} src={vocalsUrl} preload="metadata" />

      <a className="primary-button download" href={`${instrumentalUrl}?download=true`}>
        <span aria-hidden="true">↓</span>
        Download instrumental WAV
      </a>
    </section>
  )
}

function ProgressCard({ job }: { job: Job }) {
  const stages: Array<{ status: JobStatus; label: string }> = [
    { status: 'queued', label: 'Upload received' },
    { status: 'validating', label: 'Validate audio' },
    { status: 'separating', label: 'Separate stems' },
    { status: 'finalizing', label: 'Prepare WAV files' },
    { status: 'completed', label: 'Ready' },
  ]
  const currentIndex = stages.findIndex(({ status }) => status === job.status)
  const qualityName = qualityOptions.find(({ value }) => value === job.quality)?.name

  return (
    <section className="progress-card" aria-live="polite">
      <div className="processing-orbit" aria-hidden="true">
        <WaveIcon />
      </div>
      <p className="eyebrow">{qualityName || 'CPU separation'} · CPU</p>
      <h2>{job.message}</h2>
      <p className="muted">
        {job.original_filename} · {formatBytes(job.size_bytes)}
      </p>
      <div className="progress-track" aria-label={`${job.progress}% complete`}>
        <span style={{ width: `${job.progress}%` }} />
      </div>
      <ol className="stage-list">
        {stages.map((stage, index) => (
          <li
            key={stage.status}
            className={index < currentIndex ? 'done' : index === currentIndex ? 'active' : ''}
          >
            <span>{index < currentIndex ? '✓' : index + 1}</span>
            {stage.label}
          </li>
        ))}
      </ol>
      <p className="local-note">Keep both terminal windows open while this runs.</p>
    </section>
  )
}

function App() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [rightsConfirmed, setRightsConfirmed] = useState(false)
  const [quality, setQuality] = useState<SeparationQuality>('preserve')
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/health')
      .then(async (response) => {
        if (!response.ok) throw new Error(await responseError(response))
        return response.json() as Promise<Health>
      })
      .then(setHealth)
      .catch(() => setHealthError(true))
  }, [])

  useEffect(() => {
    if (!job || !activeStatuses.has(job.status)) return

    const timeout = window.setTimeout(async () => {
      try {
        const response = await fetch(`/api/jobs/${job.id}`)
        if (!response.ok) throw new Error(await responseError(response))
        setJob((await response.json()) as Job)
      } catch (pollError) {
        setError(pollError instanceof Error ? pollError.message : 'Could not read job status.')
      }
    }, 1500)
    return () => window.clearTimeout(timeout)
  }, [job])

  const chooseFile = (nextFile?: File) => {
    if (!nextFile) return
    setFile(nextFile)
    setError('')
  }

  const submit = async () => {
    if (!file || !rightsConfirmed) return
    setUploading(true)
    setError('')
    const body = new FormData()
    body.append('file', file)
    body.append('rights_confirmed', 'true')
    body.append('quality', quality)

    try {
      const response = await fetch('/api/jobs', { method: 'POST', body })
      if (!response.ok) throw new Error(await responseError(response))
      setJob((await response.json()) as Job)
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  const startOver = async () => {
    if (job && !activeStatuses.has(job.status)) {
      await fetch(`/api/jobs/${job.id}`, { method: 'DELETE' }).catch(() => undefined)
    }
    setJob(null)
    setFile(null)
    setRightsConfirmed(false)
    setQuality('preserve')
    setError('')
    if (inputRef.current) inputRef.current.value = ''
  }

  const missingTools = health
    ? Object.entries(health.tools)
        .filter(([, available]) => !available)
        .map(([tool]) => tool)
    : []

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="Karaoke Box home">
          <span className="brand-mark"><WaveIcon /></span>
          <span>Karaoke Box</span>
        </a>
        <span className="local-pill"><i /> Local only</span>
      </header>

      <main>
        <section className="hero-copy">
          <p className="eyebrow">Make the room your stage</p>
          <h1>Turn your track into<br /><em>karaoke.</em></h1>
          <p>
            Upload music you’re allowed to adapt. Karaoke Box separates the vocals locally,
            then gives you a full-quality instrumental to sing over.
          </p>
        </section>

        {healthError && (
          <div className="setup-alert" role="alert">
            <strong>The local API is offline.</strong> Start it with <code>npm run api</code>, then refresh.
          </div>
        )}
        {health && !health.ready && (
          <div className="setup-alert" role="alert">
            <strong>Setup is incomplete.</strong> Missing {missingTools.join(', ')}. Run <code>npm run setup</code>
            and check the README.
          </div>
        )}
        {error && <div className="error-alert" role="alert">{error}</div>}

        {!job && (
          <section className="upload-card" aria-labelledby="upload-heading">
            <div className="card-heading">
              <span>01</span>
              <div>
                <p className="eyebrow">Source audio</p>
                <h2 id="upload-heading">Choose your track</h2>
              </div>
            </div>

            <div
              className={`drop-zone ${dragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`}
              onDragEnter={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                chooseFile(event.dataTransfer.files[0])
              }}
            >
              <input
                ref={inputRef}
                type="file"
                accept=".aac,.flac,.m4a,.mp3,.ogg,.opus,.wav,audio/*"
                onChange={(event) => chooseFile(event.target.files?.[0])}
              />
              {file ? (
                <>
                  <div className="file-icon" aria-hidden="true">♫</div>
                  <strong>{file.name}</strong>
                  <span>{formatBytes(file.size)}</span>
                  <button className="text-button" type="button" onClick={() => inputRef.current?.click()}>
                    Choose another
                  </button>
                </>
              ) : (
                <>
                  <div className="upload-icon" aria-hidden="true">↑</div>
                  <strong>Drop an audio file here</strong>
                  <span>MP3, WAV, M4A, FLAC, OGG, AAC or Opus · up to 250 MB</span>
                  <button className="secondary-button" type="button" onClick={() => inputRef.current?.click()}>
                    Browse files
                  </button>
                </>
              )}
            </div>

            <fieldset className="quality-picker">
              <legend>
                Separation profile
                <small>Different mixes benefit from different tradeoffs.</small>
              </legend>
              <div className="quality-options">
                {qualityOptions.map((option) => (
                  <label
                    key={option.value}
                    className={`quality-option ${quality === option.value ? 'selected' : ''}`}
                  >
                    <input
                      type="radio"
                      name="quality"
                      value={option.value}
                      checked={quality === option.value}
                      onChange={() => setQuality(option.value)}
                    />
                    <span className="radio-mark" aria-hidden="true" />
                    <span className="quality-copy">
                      <strong>
                        {option.name}
                        {option.recommended && <em>Recommended</em>}
                      </strong>
                      <small>{option.description}</small>
                    </span>
                    <span className="quality-speed">{option.speed}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="rights-check">
              <input
                type="checkbox"
                checked={rightsConfirmed}
                onChange={(event) => setRightsConfirmed(event.target.checked)}
              />
              <span className="checkmark" aria-hidden="true">✓</span>
              <span>
                <strong>I’m allowed to process this recording</strong>
                <small>I own it, have permission, or its license permits this use.</small>
              </span>
            </label>

            <button
              className="primary-button"
              type="button"
              disabled={!file || !rightsConfirmed || uploading || health?.ready === false}
              onClick={submit}
            >
              {uploading ? 'Uploading…' : 'Separate vocals'}
              <span aria-hidden="true">→</span>
            </button>
          </section>
        )}

        {job && activeStatuses.has(job.status) && <ProgressCard job={job} />}

        {job?.status === 'failed' && (
          <section className="failed-card" role="alert">
            <div className="failed-icon" aria-hidden="true">!</div>
            <p className="eyebrow">Processing stopped</p>
            <h2>We couldn’t separate this track</h2>
            <p>{job.error || 'An unknown processing error occurred.'}</p>
            <button className="secondary-button" type="button" onClick={startOver}>Try another file</button>
          </section>
        )}

        {job?.status === 'completed' && (
          <>
            <StemMixer job={job} />
            <button className="start-over" type="button" onClick={startOver}>Process another track</button>
          </>
        )}

        <section className="privacy-strip">
          <div className="privacy-icon" aria-hidden="true">⌂</div>
          <div>
            <strong>Your audio stays on this computer</strong>
            <p>Uploads and stems are written only to the local <code>data/</code> directory.</p>
          </div>
          <div className="privacy-detail">
            <span>CPU processing</span>
            <span>WAV output</span>
            <span>No cloud storage</span>
          </div>
        </section>
      </main>

      <footer>
        <span>Karaoke Box · Local studio</span>
        <span>Separation does not change a song’s underlying rights.</span>
      </footer>
    </div>
  )
}

export default App
