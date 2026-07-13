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
  eta_seconds: number | null
  current_pass: number | null
  total_passes: number | null
  error: string | null
  quality: SeparationQuality
  created_at: string
  updated_at: string
  assets: Partial<Record<'instrumental' | 'vocals', string>>
}

const activeStatuses = new Set<JobStatus>([
  'queued',
  'validating',
  'separating',
  'finalizing',
])
const currentJobStorageKey = 'karaoke-box.current-job-id'
const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')

function apiUrl(path: string) {
  return `${apiBaseUrl}${path}`
}

function assetUrl(path?: string) {
  if (!path) return undefined
  return /^https?:\/\//.test(path) ? path : apiUrl(path)
}

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

function formatJobDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value))
}

function upsertJob(jobs: Job[], nextJob: Job) {
  return [nextJob, ...jobs.filter(({ id }) => id !== nextJob.id)].sort((left, right) =>
    right.created_at.localeCompare(left.created_at),
  )
}

function formatEta(seconds: number) {
  if (seconds < 60) {
    const rounded = Math.max(5, Math.round(seconds / 5) * 5)
    return `About ${rounded} seconds remaining`
  }
  const minutes = Math.ceil(seconds / 60)
  if (minutes < 60) return `About ${minutes} minute${minutes === 1 ? '' : 's'} remaining`
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return `About ${hours}h${remainder ? ` ${remainder}m` : ''} remaining`
}

async function responseError(response: Response) {
  try {
    const body = (await response.json()) as { detail?: string }
    return body.detail || `Request failed (${response.status})`
  } catch {
    return `Request failed (${response.status})`
  }
}

function uploadJob(body: FormData, onProgress: (percent: number) => void) {
  return new Promise<Job>((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', apiUrl('/api/jobs'))
    request.responseType = 'json'
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)))
      }
    }
    request.onerror = () => reject(new Error('Could not reach the local API.'))
    request.onabort = () => reject(new Error('Upload was cancelled.'))
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress(100)
        resolve(request.response as Job)
        return
      }
      const detail = (request.response as { detail?: string } | null)?.detail
      reject(new Error(detail || `Upload failed (${request.status}).`))
    }
    request.send(body)
  })
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

  const instrumentalUrl = assetUrl(job.assets.instrumental)
  const vocalsUrl = assetUrl(job.assets.vocals)

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
  const passLabel =
    job.status === 'separating' && job.total_passes && job.total_passes > 1
      ? `Model pass ${job.current_pass || 1} of ${job.total_passes}`
      : null
  const progressDetail =
    job.status === 'separating'
      ? job.eta_seconds !== null && job.progress > 0
        ? formatEta(job.eta_seconds)
        : job.progress > 0
          ? 'Calculating time remaining…'
          : 'Preparing model and audio…'
      : job.status === 'finalizing'
        ? 'Separation complete'
        : 'Preparing separation…'

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
      <div className="progress-readout">
        <strong>{job.progress}%</strong>
        <span>{passLabel}</span>
        <small>{progressDetail}</small>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-label="Stem separation progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={job.progress}
      >
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

function JobHistory({
  jobs,
  currentJobId,
  onOpen,
  onDelete,
}: {
  jobs: Job[]
  currentJobId?: string
  onOpen: (job: Job) => void
  onDelete: (job: Job) => void
}) {
  if (jobs.length === 0) return null

  return (
    <section className="history-card" aria-labelledby="history-heading">
      <div className="history-heading">
        <div>
          <p className="eyebrow">Stored locally</p>
          <h2 id="history-heading">Recent tracks</h2>
        </div>
        <span>{jobs.length} saved</span>
      </div>
      <div className="history-list">
        {jobs.map((historyJob) => {
          const active = activeStatuses.has(historyJob.status)
          const selected = historyJob.id === currentJobId
          const qualityName = qualityOptions.find(({ value }) => value === historyJob.quality)?.name
          return (
            <article className={`history-row ${selected ? 'selected' : ''}`} key={historyJob.id}>
              <div className="history-file-icon" aria-hidden="true">♫</div>
              <div className="history-copy">
                <strong>{historyJob.original_filename}</strong>
                <small>{qualityName} · {formatJobDate(historyJob.created_at)}</small>
              </div>
              <div className={`history-status ${active ? 'active' : historyJob.status}`}>
                <i />
                {active ? `${historyJob.progress}% processing` : historyJob.status}
              </div>
              <div className="history-actions">
                {historyJob.status === 'completed' && historyJob.assets.instrumental && (
                  <a href={`${assetUrl(historyJob.assets.instrumental)}?download=true`}>Download</a>
                )}
                <button type="button" onClick={() => onOpen(historyJob)}>
                  {active ? 'Resume' : 'Open'}
                </button>
                {!active && (
                  <button className="danger" type="button" onClick={() => onDelete(historyJob)}>
                    Delete
                  </button>
                )}
              </div>
            </article>
          )
        })}
      </div>
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
  const [uploadProgress, setUploadProgress] = useState(0)
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [history, setHistory] = useState<Job[]>([])
  const [restoringJobs, setRestoringJobs] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch(apiUrl('/api/health'))
      .then(async (response) => {
        if (!response.ok) throw new Error(await responseError(response))
        return response.json() as Promise<Health>
      })
      .then(setHealth)
      .catch(() => setHealthError(true))
  }, [])

  useEffect(() => {
    let cancelled = false
    const restoreJobs = async () => {
      try {
        const response = await fetch(apiUrl('/api/jobs?limit=100'))
        if (!response.ok) throw new Error(await responseError(response))
        const savedJobs = (await response.json()) as Job[]
        if (cancelled) return
        setHistory(savedJobs)

        const savedId = localStorage.getItem(currentJobStorageKey)
        const resumable = savedId
          ? savedJobs.find(({ id }) => id === savedId)
          : savedJobs.find(({ status }) => activeStatuses.has(status))
        if (resumable) {
          setJob(resumable)
        } else if (savedId) {
          localStorage.removeItem(currentJobStorageKey)
        }
      } catch {
        // The health banner handles an unavailable API; do not hide the upload UI.
      } finally {
        if (!cancelled) setRestoringJobs(false)
      }
    }
    void restoreJobs()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (job) localStorage.setItem(currentJobStorageKey, job.id)
  }, [job])

  useEffect(() => {
    if (!job || !activeStatuses.has(job.status)) return

    const timeout = window.setTimeout(async () => {
      try {
        const response = await fetch(apiUrl(`/api/jobs/${job.id}`))
        if (!response.ok) throw new Error(await responseError(response))
        const updatedJob = (await response.json()) as Job
        setJob(updatedJob)
        setHistory((savedJobs) => upsertJob(savedJobs, updatedJob))
      } catch (pollError) {
        setError(pollError instanceof Error ? pollError.message : 'Could not read job status.')
      }
    }, 1000)
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
    setUploadProgress(0)
    setError('')
    const body = new FormData()
    body.append('file', file)
    body.append('rights_confirmed', 'true')
    body.append('quality', quality)

    try {
      const createdJob = await uploadJob(body, setUploadProgress)
      setJob(createdJob)
      setHistory((savedJobs) => upsertJob(savedJobs, createdJob))
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : 'Upload failed.')
    } finally {
      setUploading(false)
    }
  }

  const startOver = () => {
    localStorage.removeItem(currentJobStorageKey)
    setJob(null)
    setFile(null)
    setRightsConfirmed(false)
    setQuality('preserve')
    setError('')
    if (inputRef.current) inputRef.current.value = ''
  }

  const openStoredJob = (storedJob: Job) => {
    setJob(storedJob)
    localStorage.setItem(currentJobStorageKey, storedJob.id)
    setError('')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const deleteStoredJob = async (storedJob: Job) => {
    try {
      const response = await fetch(apiUrl(`/api/jobs/${storedJob.id}`), { method: 'DELETE' })
      if (!response.ok) throw new Error(await responseError(response))
      setHistory((savedJobs) => savedJobs.filter(({ id }) => id !== storedJob.id))
      if (job?.id === storedJob.id) startOver()
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : 'Could not delete the job.')
    }
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

        {restoringJobs && (
          <div className="restore-status" aria-live="polite">
            <span /> Loading saved jobs…
          </div>
        )}

        {!restoringJobs && !job && (
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
              {uploading ? `Uploading ${uploadProgress}%` : 'Separate vocals'}
              <span aria-hidden="true">→</span>
            </button>
            {uploading && (
              <div className="upload-progress" aria-live="polite">
                <div
                  role="progressbar"
                  aria-label="File upload progress"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={uploadProgress}
                >
                  <span style={{ width: `${uploadProgress}%` }} />
                </div>
                <small>{uploadProgress}% of the file sent to the local API</small>
              </div>
            )}
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

        {!restoringJobs && (
          <JobHistory
            jobs={history}
            currentJobId={job?.id}
            onOpen={openStoredJob}
            onDelete={(storedJob) => void deleteStoredJob(storedJob)}
          />
        )}

        <section className="privacy-strip">
          <div className="privacy-icon" aria-hidden="true">⌂</div>
          <div>
            <strong>Your audio stays on this computer</strong>
            <p>Sources and stems are stored only in Karaoke Box’s local application data.</p>
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
