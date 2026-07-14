import { useEffect, useRef, useState, type CSSProperties, type HTMLAttributes, type ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import type { Variants } from 'motion/react'
import {
  DownloadIcon,
  EjectIcon,
  NoteIcon,
  PauseIcon,
  PlayIcon,
} from './components/icons'
import { Eq } from './components/Eq'
import './App.css'

const EASE_OUT: [number, number, number, number] = [0.16, 1, 0.3, 1]

/* Platter rotation: 150°/s ≈ the deck's 2.4s/rev spin. Each clock update
   may only turn the disc by DISC_MAX_STEP_DEG, so a timeline scrub nudges
   the platter in the seek direction instead of whipping whole rotations. */
const DISC_DEG_PER_SEC = 150
const DISC_MAX_STEP_DEG = 10

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
type SeparatorEngine = 'demucs' | 'melband_roformer'

type SourceType = 'upload' | 'youtube'

type JobStatus =
  | 'queued'
  | 'ingesting'
  | 'preparing'
  | 'validating'
  | 'separating'
  | 'finalizing'
  | 'completed'
  | 'failed'

type Job = {
  id: string
  original_filename: string
  source_type: SourceType
  source_url: string | null
  canonical_url: string | null
  video_id: string | null
  title: string | null
  uploader: string | null
  uploader_id: string | null
  channel: string | null
  channel_id: string | null
  extractor: string | null
  fetched_at: string | null
  rights_attestation_version: string
  rights_attestation_text: string
  rights_confirmed_at: string | null
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
  separator_engine: SeparatorEngine
  separator_model: string
  created_at: string
  updated_at: string
  assets: Partial<Record<'instrumental' | 'vocals', string>>
}

const activeStatuses = new Set<JobStatus>([
  'queued',
  'ingesting',
  'preparing',
  'validating',
  'separating',
  'finalizing',
])
const currentJobStorageKey = 'karaoke-box.current-job-id'
const defaultSeparatorEngine: SeparatorEngine = 'demucs'
const melbandModelId = 'kimberley_melband_roformer_v1'
const rightsAttestationVersion = '1'
const rightsAttestationText =
  'I confirm that I own this source recording or am authorized to use it, including downloading it when I provide a URL, and that I am permitted to process and export it.'
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

function jobDisplayName(job: Job) {
  return job.source_type === 'youtube' && job.title ? job.title : job.original_filename
}

function isSeparationQuality(value: unknown): value is SeparationQuality {
  return value === 'preserve' || value === 'best' || value === 'standard'
}

function fallbackModelForQuality(quality: SeparationQuality) {
  return quality === 'best' ? 'htdemucs_ft' : 'htdemucs'
}

function normalizeJob(payload: unknown): Job {
  const record = payload && typeof payload === 'object' ? payload as Record<string, unknown> : {}
  const quality = isSeparationQuality(record.quality) ? record.quality : 'preserve'
  const engine = record.separator_engine === 'melband_roformer'
    ? 'melband_roformer'
    : defaultSeparatorEngine
  const separatorModel = typeof record.separator_model === 'string' && record.separator_model
    ? record.separator_model
    : engine === 'melband_roformer'
      ? melbandModelId
      : fallbackModelForQuality(quality)
  return {
    ...record,
    quality,
    separator_engine: engine,
    separator_model: separatorModel,
  } as Job
}

function jobEngineLabel(job: Job) {
  if (job.separator_engine === 'melband_roformer') {
    return `High quality · MelBand RoFormer (${job.separator_model})`
  }
  const qualityName = qualityOptions.find(({ value }) => value === job.quality)?.name
  return `Demucs · ${qualityName || 'CPU profile'} (${job.separator_model})`
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
        resolve(normalizeJob(request.response))
        return
      }
      const detail = (request.response as { detail?: string } | null)?.detail
      reject(new Error(detail || `Upload failed (${request.status}).`))
    }
    request.send(body)
  })
}

async function createYoutubeJob(
  url: string,
  quality: SeparationQuality,
  separatorEngine: SeparatorEngine,
) {
  const response = await fetch(apiUrl('/api/jobs/youtube'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url,
      rights_confirmed: true,
      attestation_version: rightsAttestationVersion,
      quality: separatorEngine === 'melband_roformer' ? 'preserve' : quality,
      separator_engine: separatorEngine,
    }),
  })
  if (!response.ok) throw new Error(await responseError(response))
  return normalizeJob(await response.json())
}

/* Presentational number roll for the VFD readouts: whenever `value`
   changes the old digits roll out and the new ones roll in. */
function TickNumber({ value, reduce }: { value: number; reduce: boolean | null }) {
  return (
    <span className="tick-number">
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={value}
          className="tick-number__val"
          initial={reduce ? { opacity: 0 } : { opacity: 0, y: '60%' }}
          animate={reduce ? { opacity: 1 } : { opacity: 1, y: '0%' }}
          exit={reduce ? { opacity: 0 } : { opacity: 0, y: '-60%' }}
          transition={reduce ? { duration: 0.12 } : { type: 'spring', stiffness: 360, damping: 26 }}
        >
          {value}
        </motion.span>
      </AnimatePresence>
    </span>
  )
}

/* The turntable. Purely presentational: the disc, the progress/seek ring,
   the marching-ants drop ring, the tonearm, and a center label (children).
   Extra props (drag handlers, progressbar roles) spread onto the zone.
   `spinning` runs the free CSS spin (processing); `discAngle` pins the
   disc to an exact rotation instead (playback-position-driven). */
type PlatterProps = {
  spinning?: boolean
  engaged?: boolean
  ring?: number | null
  ringTone?: 'vfd' | 'amber' | 'red'
  dragging?: boolean
  discAngle?: number | null
  children?: ReactNode
} & HTMLAttributes<HTMLDivElement>

function Platter({
  spinning = false,
  engaged = false,
  ring = null,
  ringTone = 'vfd',
  dragging = false,
  discAngle = null,
  children,
  ...zoneProps
}: PlatterProps) {
  const zoneClass = [
    'platter-zone',
    spinning ? 'platter--spinning' : '',
    dragging ? 'dragging' : '',
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <div className={zoneClass} {...zoneProps}>
      <div
        className="platter-disc"
        aria-hidden="true"
        style={discAngle === null ? undefined : { transform: `rotate(${discAngle}deg)` }}
      />
      <svg className="platter-ring" viewBox="0 0 100 100" aria-hidden="true">
        <circle className="ring-track" cx="50" cy="50" r="48.6" />
        {ring !== null && (
          <circle
            className={`ring-fill${ringTone !== 'vfd' ? ` ring-fill--${ringTone}` : ''}`}
            cx="50"
            cy="50"
            r="48.6"
            pathLength={100}
            style={{ strokeDashoffset: 100 - Math.min(100, Math.max(0, ring)) }}
          />
        )}
      </svg>
      <svg className="drop-ring" viewBox="0 0 100 100" aria-hidden="true">
        <circle cx="50" cy="50" r="49.2" pathLength={120} />
      </svg>
      <div className={`tonearm${engaged ? ' tonearm--engaged' : ''}`} aria-hidden="true">
        <span className="tonearm-arm" />
        <span className="tonearm-pivot" />
      </div>
      <div className="platter-label">{children}</div>
    </div>
  )
}

function StemMixer({ job, reduce }: { job: Job; reduce: boolean | null }) {
  const instrumentalRef = useRef<HTMLAudioElement>(null)
  const vocalsRef = useRef<HTMLAudioElement>(null)
  const frameRef = useRef<number | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const instrumentalGainRef = useRef<GainNode | null>(null)
  const vocalGainRef = useRef<GainNode | null>(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(job.duration_seconds ?? 0)
  const [instrumentalVolume, setInstrumentalVolume] = useState(0.9)
  const [vocalVolume, setVocalVolume] = useState(0)
  const [playbackError, setPlaybackError] = useState('')

  const instrumentalUrl = assetUrl(job.assets.instrumental)
  const vocalsUrl = assetUrl(job.assets.vocals)

  const ensureAudioGraph = () => {
    const instrumental = instrumentalRef.current
    const vocals = vocalsRef.current
    if (!instrumental || !vocals) return null
    if (audioContextRef.current) return audioContextRef.current

    const context = new AudioContext()
    const instrumentalGain = context.createGain()
    const vocalGain = context.createGain()
    context.createMediaElementSource(instrumental).connect(instrumentalGain).connect(context.destination)
    context.createMediaElementSource(vocals).connect(vocalGain).connect(context.destination)
    instrumentalGain.gain.value = instrumentalVolume
    vocalGain.gain.value = vocalVolume
    instrumental.volume = 1
    vocals.volume = 1
    audioContextRef.current = context
    instrumentalGainRef.current = instrumentalGain
    vocalGainRef.current = vocalGain
    return context
  }

  useEffect(() => {
    const context = audioContextRef.current
    const gain = instrumentalGainRef.current
    if (!context || !gain) return
    gain.gain.cancelScheduledValues(context.currentTime)
    gain.gain.setValueAtTime(gain.gain.value, context.currentTime)
    gain.gain.linearRampToValueAtTime(instrumentalVolume, context.currentTime + 0.015)
  }, [instrumentalVolume])

  useEffect(() => {
    const context = audioContextRef.current
    const gain = vocalGainRef.current
    if (!context || !gain) return
    gain.gain.cancelScheduledValues(context.currentTime)
    gain.gain.setValueAtTime(gain.gain.value, context.currentTime)
    gain.gain.linearRampToValueAtTime(vocalVolume, context.currentTime + 0.015)
  }, [vocalVolume])

  useEffect(() => {
    const instrumental = instrumentalRef.current
    const vocals = vocalsRef.current
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
      instrumental?.pause()
      vocals?.pause()
      const context = audioContextRef.current
      if (context && context.state !== 'closed') void context.close()
    }
  }, [])

  useEffect(() => {
    if (!playing) return

    const updateTime = () => {
      const instrumental = instrumentalRef.current
      if (!instrumental) return
      // Both stems continue playing at normal speed. This loop only paints the
      // transport; it must never seek or change either media clock.
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
    try {
      const context = ensureAudioGraph()
      if (!context) return
      await context.resume()
      // Align once while paused. The player then leaves both local WAV streams
      // running continuously, even when a gain slider is at zero.
      vocals.currentTime = instrumental.currentTime
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

  // Presentational fill % for the seek ring / range gradients (derived state).
  const seekPercent = duration ? (Math.min(currentTime, duration) / duration) * 100 : 0

  // Disc angle integrates media-clock deltas (capped per update). Ref writes
  // are guarded by lastClockRef, so re-renders at the same clock are no-ops.
  const discAngleRef = useRef(0)
  const lastClockRef = useRef(0)
  if (currentTime === 0) {
    discAngleRef.current = 0
    lastClockRef.current = 0
  } else if (currentTime !== lastClockRef.current) {
    const step = (currentTime - lastClockRef.current) * DISC_DEG_PER_SEC
    const clamped = Math.max(-DISC_MAX_STEP_DEG, Math.min(DISC_MAX_STEP_DEG, step))
    discAngleRef.current = (discAngleRef.current + clamped + 360) % 360
    lastClockRef.current = currentTime
  }

  return (
    <>
      <div className="stage-readout">
        <p className="readout-main readout-main--title">{jobDisplayName(job)}</p>
        <p className="readout-sub">Separation complete · {jobEngineLabel(job)} · CPU</p>
      </div>

      <Platter
        engaged
        ring={seekPercent}
        ringTone="amber"
        /* Pinned to the media clock: freezes on pause, nudges with the seek
           slider (capped per step), returns to top only when the track
           restarts at 0:00. */
        discAngle={reduce ? null : discAngleRef.current}
      >
        <button
          className="play-button"
          type="button"
          data-state={playing ? 'pause' : 'play'}
          onClick={togglePlayback}
        >
          {playing ? <PauseIcon size={22} /> : <PlayIcon size={22} />}
          <span className="sr-only">{playing ? 'Pause' : 'Play'} stem mix</span>
        </button>
      </Platter>

      <div className="stage-under">
        {playbackError && <p className="inline-error">{playbackError}</p>}

        <div className="transport">
          <span className="transport-time">
            {formatTime(currentTime)}
            <Eq size="sm" className={playing ? '' : 'eq--paused'} />
          </span>
          <input
            className="transport-range"
            style={{ '--seek': `${seekPercent}%` } as CSSProperties}
            aria-label="Playback position"
            type="range"
            min="0"
            max={duration || 1}
            step="0.01"
            value={Math.min(currentTime, duration || 1)}
            onChange={(event) => seek(Number(event.target.value))}
          />
          <span className="transport-time">{formatTime(duration)}</span>
        </div>

        <div className="mix-console">
          <label className="fader fader--amber">
            <span className="fader-head">
              <strong>Instrumental</strong>
              <output><TickNumber value={Math.round(instrumentalVolume * 100)} reduce={reduce} />%</output>
            </span>
            <input
              className="fader-range"
              style={{ '--seek': `${instrumentalVolume * 100}%` } as CSSProperties}
              aria-label="Instrumental volume"
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={instrumentalVolume}
              onChange={(event) => setInstrumentalVolume(Number(event.target.value))}
            />
          </label>
          <label className="fader fader--vox">
            <span className="fader-head">
              <strong>Original vocals</strong>
              <output><TickNumber value={Math.round(vocalVolume * 100)} reduce={reduce} />%</output>
            </span>
            <input
              className="fader-range"
              style={{ '--seek': `${vocalVolume * 100}%` } as CSSProperties}
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
          preload="auto"
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
        <audio ref={vocalsRef} src={vocalsUrl} preload="auto" />

        <a className="hw-download" href={`${instrumentalUrl}?download=true`}>
          <DownloadIcon size={16} />
          Download instrumental WAV
        </a>
      </div>
    </>
  )
}

function ProcessDisplay({ job, reduce }: { job: Job; reduce: boolean | null }) {
  const melbandSelected = job.separator_engine === 'melband_roformer'
  const stages: Array<{ status: JobStatus; label: string }> = job.source_type === 'youtube'
    ? [
        { status: 'queued', label: 'Source received' },
        { status: 'ingesting', label: 'Fetch source' },
        { status: 'validating', label: 'Validate audio' },
        ...(melbandSelected ? [{ status: 'preparing' as const, label: 'Prepare model' }] : []),
        { status: 'separating', label: 'Separate stems' },
        { status: 'finalizing', label: 'Prepare WAV files' },
        { status: 'completed', label: 'Ready' },
      ]
    : [
        { status: 'queued', label: 'Upload received' },
        { status: 'validating', label: 'Validate audio' },
        ...(melbandSelected ? [{ status: 'preparing' as const, label: 'Prepare model' }] : []),
        { status: 'separating', label: 'Separate stems' },
        { status: 'finalizing', label: 'Prepare WAV files' },
        { status: 'completed', label: 'Ready' },
      ]
  const currentIndex = stages.findIndex(({ status }) => status === job.status)
  const passLabel =
    job.status === 'separating' && job.total_passes && job.total_passes > 1
      ? `Model pass ${job.current_pass || 1} of ${job.total_passes}`
      : null
  const progressDetail =
    job.status === 'ingesting'
      ? 'Fetching the best available audio source…'
      : job.status === 'preparing'
        ? job.progress > 0
          ? 'Verifying or downloading the selected model…'
          : 'Preparing the selected model…'
        : job.status === 'separating'
          ? job.eta_seconds !== null && job.progress > 0
            ? formatEta(job.eta_seconds)
            : job.progress > 0
              ? 'Calculating time remaining…'
              : 'Starting CPU inference…'
          : job.status === 'finalizing'
            ? 'Separation complete'
            : 'Preparing separation…'

  return (
    <>
      <div className="stage-readout">
        <p className="readout-main"><TickNumber value={job.progress} reduce={reduce} />%</p>
        <p className="readout-sub readout-sub--amber">
          {passLabel ? `${passLabel} · ` : ''}{progressDetail}
        </p>
      </div>

      <Platter
        spinning={!reduce}
        engaged
        ring={job.progress}
        role="progressbar"
        aria-label="Stem separation progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={job.progress}
      >
        <p className="label-kicker label-kicker--amber">
          <span className="led led--amber led--pulse" aria-hidden="true" /> On air
        </p>
        <p className="label-title">{jobDisplayName(job)}</p>
        <p className="label-sub">{job.message}</p>
      </Platter>

      <div className="stage-under">
        <ol className="stage-leds">
          {stages.map((stage, index) => {
            const done = index < currentIndex
            const active = index === currentIndex
            return (
              <li key={stage.status} className={done ? 'done' : active ? 'active' : ''}>
                <span className="led" aria-hidden="true" />
                {stage.label}
              </li>
            )
          })}
        </ol>
        <p className="local-note">Keep both terminal windows open while this runs.</p>
      </div>
    </>
  )
}

function SetList({
  jobs,
  currentJobId,
  restoring,
  reduce,
  onOpen,
  onDelete,
}: {
  jobs: Job[]
  currentJobId?: string
  restoring: boolean
  reduce: boolean | null
  onOpen: (job: Job) => void
  onDelete: (job: Job) => void
}) {
  return (
    <aside className="rail" aria-labelledby="setlist-heading">
      <div className="rail-head">
        <h2 className="rail-title" id="setlist-heading">Set list</h2>
        <span className="rail-count">{jobs.length > 0 ? String(jobs.length).padStart(2, '0') : '——'}</span>
      </div>
      <div className="slot-list">
        {restoring ? (
          <div className="rail-empty">
            <p>Reading local library…</p>
          </div>
        ) : jobs.length === 0 ? (
          <div className="rail-empty">
            <NoteIcon size={18} />
            <p>No tracks on file<br />Drop one on the platter</p>
          </div>
        ) : (
          <AnimatePresence>
            {jobs.map((historyJob, index) => {
              const active = activeStatuses.has(historyJob.status)
              const selected = historyJob.id === currentJobId
              const engineLabel = jobEngineLabel(historyJob)
              const ticket = String(index + 1).padStart(2, '0')
              return (
                <motion.article
                  layout
                  key={historyJob.id}
                  className={`slot ${selected ? 'slot--selected' : ''}`}
                  initial={reduce ? { opacity: 0 } : { opacity: 0, x: -12 }}
                  animate={{
                    opacity: 1,
                    x: 0,
                    transition: reduce
                      ? { duration: 0.2 }
                      : { type: 'spring', stiffness: 280, damping: 30, delay: index * 0.04 },
                  }}
                  exit={reduce ? { opacity: 0 } : { opacity: 0, x: -14, transition: { duration: 0.18 } }}
                >
                  <span className="slot-index" aria-hidden="true">{ticket}</span>
                  <strong className="slot-name">{historyJob.original_filename}</strong>
                  <span className="slot-meta">{engineLabel} · {formatJobDate(historyJob.created_at)}</span>
                  <span className={`slot-status ${active ? 'active' : historyJob.status}`}>
                    {active ? <Eq size="sm" /> : <i aria-hidden="true" />}
                    {active ? `${historyJob.progress}% processing` : historyJob.status}
                  </span>
                  <div className="slot-actions">
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
                </motion.article>
              )
            })}
          </AnimatePresence>
        )}
      </div>
    </aside>
  )
}

function App() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [sourceType, setSourceType] = useState<SourceType>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [rightsConfirmed, setRightsConfirmed] = useState(false)
  const [separatorEngine, setSeparatorEngine] = useState<SeparatorEngine>(defaultSeparatorEngine)
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
        const savedJobs = (await response.json() as unknown[]).map(normalizeJob)
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
        // The VFD strip reports an unavailable API; do not hide the panel UI.
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
        const updatedJob = normalizeJob(await response.json())
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
    setSourceType('upload')
    setFile(nextFile)
    setError('')
  }

  const submit = async () => {
    if (!rightsConfirmed || (sourceType === 'upload' ? !file : !youtubeUrl.trim())) return
    setUploading(true)
    setUploadProgress(0)
    setError('')

    try {
      let createdJob: Job
      if (sourceType === 'upload') {
        if (!file) return
        const body = new FormData()
        body.append('file', file)
        body.append('rights_confirmed', 'true')
        body.append('attestation_version', rightsAttestationVersion)
        body.append('quality', separatorEngine === 'melband_roformer' ? 'preserve' : quality)
        body.append('separator_engine', separatorEngine)
        createdJob = await uploadJob(body, setUploadProgress)
      } else {
        createdJob = await createYoutubeJob(youtubeUrl.trim(), quality, separatorEngine)
      }
      setJob(createdJob)
      setHistory((savedJobs) => upsertJob(savedJobs, createdJob))
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Could not start source ingest.')
    } finally {
      setUploading(false)
    }
  }

  const startOver = () => {
    localStorage.removeItem(currentJobStorageKey)
    setJob(null)
    setSourceType('upload')
    setFile(null)
    setYoutubeUrl('')
    setRightsConfirmed(false)
    setSeparatorEngine(defaultSeparatorEngine)
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

  const reduce = useReducedMotion()
  const isProcessing = !!job && activeStatuses.has(job.status)
  const startDisabled =
    (sourceType === 'upload' ? !file : !youtubeUrl.trim()) || !rightsConfirmed || uploading || health?.ready === false

  /* One line of phosphor: the VFD strip reports whatever matters most. */
  const vfd: { text: ReactNode; tone?: 'amber' | 'red'; alert?: boolean } = healthError
    ? { text: <>The local API is offline. Start it with <code>npm run api</code>, then refresh.</>, tone: 'red', alert: true }
    : health && !health.ready
      ? { text: <>Setup is incomplete. Missing {missingTools.join(', ')}. Run <code>npm run setup</code> and check the README.</>, tone: 'amber', alert: true }
      : error
        ? { text: error, tone: 'red', alert: true }
        : restoringJobs
          ? { text: 'Reading local library…' }
          : isProcessing && job
            ? { text: `${job.message} · ${job.progress}%` }
            : job?.status === 'failed'
              ? { text: 'Processing stopped · see stage readout', tone: 'red' }
              : job?.status === 'completed'
                ? { text: `Ready · ${jobDisplayName(job)}` }
                : { text: 'Ready · Load a track to begin' }

  /* Shared stage-view swap (the machine morphs; it never navigates). */
  const stageVariants: Variants = reduce
    ? {
        initial: { opacity: 0 },
        animate: { opacity: 1, transition: { duration: 0.2 } },
        exit: { opacity: 0, transition: { duration: 0.15 } },
      }
    : {
        initial: { opacity: 0, scale: 0.985 },
        animate: {
          opacity: 1,
          scale: 1,
          transition: { type: 'spring', stiffness: 240, damping: 28 },
        },
        exit: {
          opacity: 0,
          scale: 0.985,
          transition: { duration: 0.18, ease: EASE_OUT },
        },
      }

  const regionFade = (delay: number) => ({
    initial: reduce ? { opacity: 0 } : { opacity: 0, y: 10 },
    animate: { opacity: 1, y: 0 },
    transition: { delay, duration: 0.5, ease: EASE_OUT },
  })

  return (
    <div className="deck-room">
      <div className="deck brushed screws">
        <motion.header className="deck-top" {...regionFade(0)}>
          <a className="plate" href="/" aria-label="Karaoke Box home">
            <span className="plate-name">Karaoke Box</span>
            <span className="plate-model">Deck·01</span>
          </a>
          <div
            className="vfd-strip"
            data-tone={vfd.tone}
            role={vfd.alert ? 'alert' : undefined}
            aria-live={vfd.alert ? undefined : 'polite'}
          >
            {vfd.text}
          </div>
          <div className="status-cluster">
            <span
              className={`led ${healthError ? 'led--red' : health && !health.ready ? 'led--amber' : 'led--green'}`}
              aria-hidden="true"
            />
            <span className="status-label">Local only</span>
          </div>
        </motion.header>

        <div className="deck-body">
          <motion.div className="rail-shell" {...regionFade(0.15)}>
            <SetList
              jobs={history}
              currentJobId={job?.id}
              restoring={restoringJobs}
              reduce={reduce}
              onOpen={openStoredJob}
              onDelete={(storedJob) => void deleteStoredJob(storedJob)}
            />
          </motion.div>

          <main className="stage">
            <AnimatePresence mode="wait">
              {restoringJobs && (
                <motion.div
                  className="stage-view"
                  key="boot"
                  variants={stageVariants}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                >
                  <div className="stage-readout">
                    <p className="readout-main">··</p>
                    <p className="readout-sub">Power on</p>
                  </div>
                  <Platter ring={null}>
                    <p className="label-kicker">Boot</p>
                    <p className="label-title">Reading local library…</p>
                  </Platter>
                </motion.div>
              )}

              {!restoringJobs && !job && (
                <motion.div
                  className="stage-view"
                  key="load"
                  variants={stageVariants}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                >
                  <div className="stage-readout">
                    <p className="readout-main">{file ? 'Loaded' : 'Ready'}</p>
                    <p className="readout-sub">
                      {file
                        ? `${file.name} · ${formatBytes(file.size)}`
                        : 'Load a track · Set the panel · Press start'}
                    </p>
                  </div>
                  <Platter
                    dragging={dragging}
                    ring={null}
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
                      aria-label="Choose an audio file"
                      accept=".aac,.flac,.m4a,.mp3,.ogg,.opus,.wav,audio/*"
                      onChange={(event) => chooseFile(event.target.files?.[0])}
                    />
                    {file ? (
                      <>
                        <p className="label-kicker">Track loaded</p>
                        <p className="label-title">{file.name}</p>
                        <p className="label-sub">{formatBytes(file.size)}</p>
                        <button className="label-button" type="button" onClick={() => inputRef.current?.click()}>
                          Change track
                        </button>
                      </>
                    ) : sourceType === 'youtube' ? (
                      <>
                        <p className="label-kicker">Link mode</p>
                        <p className="label-title">Paste a YouTube URL</p>
                        <p className="label-sub">Use the source panel →</p>
                      </>
                    ) : (
                      <>
                        <p className="label-kicker">No disc</p>
                        <p className="label-title">Drop a track here</p>
                        <button className="label-button" type="button" onClick={() => inputRef.current?.click()}>
                          Browse files
                        </button>
                      </>
                    )}
                  </Platter>
                  <p className="local-note">MP3 · WAV · M4A · FLAC · OGG · AAC · Opus — up to 250 MB, on this computer</p>
                </motion.div>
              )}

              {job && activeStatuses.has(job.status) && (
                <motion.div
                  className="stage-view"
                  key="busy"
                  aria-live="polite"
                  variants={stageVariants}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                >
                  <ProcessDisplay job={job} reduce={reduce} />
                </motion.div>
              )}

              {job?.status === 'failed' && (
                <motion.div
                  className="stage-view"
                  key="failed"
                  variants={stageVariants}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                >
                  <div className="stage-readout">
                    <p className="readout-main readout-main--red">Fault</p>
                    <p className="readout-sub readout-sub--red">
                      {job.source_type === 'youtube'
                        ? 'We couldn’t fetch this YouTube source'
                        : 'We couldn’t separate this track'}
                    </p>
                  </div>
                  <Platter ring={100} ringTone="red">
                    <p className="label-kicker label-kicker--red">
                      <span className="led led--red" aria-hidden="true" /> Fault
                    </p>
                    <p className="label-title">{jobDisplayName(job)}</p>
                    <p className="label-sub">{jobEngineLabel(job)}</p>
                  </Platter>
                  <div className="stage-under" role="alert">
                    <p className="fail-msg">{job.error || 'An unknown processing error occurred.'}</p>
                    <button className="eject-button eject-button--inline" type="button" onClick={startOver}>
                      <EjectIcon size={12} /> Eject · Try another source
                    </button>
                  </div>
                </motion.div>
              )}

              {job?.status === 'completed' && (
                <motion.div
                  className="stage-view"
                  key="result"
                  variants={stageVariants}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                >
                  <StemMixer job={job} reduce={reduce} />
                </motion.div>
              )}
            </AnimatePresence>
          </main>

          <motion.aside className="console" aria-label="Control panel" {...regionFade(0.22)}>
            {!job ? (
              <>
                <section className="module">
                  <span className="module-label">01 · Source</span>
                  <div className="selector" role="tablist" aria-label="Audio source">
                    <button
                      className={sourceType === 'upload' ? 'selected' : ''}
                      type="button"
                      role="tab"
                      aria-selected={sourceType === 'upload'}
                      onClick={() => {
                        setSourceType('upload')
                        setError('')
                      }}
                    >
                      {sourceType === 'upload' && (
                        <motion.span
                          className="tab-indicator"
                          layoutId="tab-indicator"
                          aria-hidden="true"
                          transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 420, damping: 38 }}
                        />
                      )}
                      <span className="tab-label">File</span>
                    </button>
                    <button
                      className={sourceType === 'youtube' ? 'selected' : ''}
                      type="button"
                      role="tab"
                      aria-selected={sourceType === 'youtube'}
                      onClick={() => {
                        setSourceType('youtube')
                        setError('')
                      }}
                    >
                      {sourceType === 'youtube' && (
                        <motion.span
                          className="tab-indicator"
                          layoutId="tab-indicator"
                          aria-hidden="true"
                          transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 420, damping: 38 }}
                        />
                      )}
                      <span className="tab-label">YouTube</span>
                    </button>
                  </div>

                  {sourceType === 'upload' ? (
                    <div className={`file-line ${file ? 'file-line--loaded' : ''}`}>
                      <NoteIcon size={16} />
                      <span className="file-line-copy">
                        <strong>{file ? file.name : 'No track loaded'}</strong>
                        <small>{file ? formatBytes(file.size) : 'Drop on the platter or browse'}</small>
                      </span>
                      <button className="label-button" type="button" onClick={() => inputRef.current?.click()}>
                        Browse
                      </button>
                    </div>
                  ) : (
                    <>
                      <label className="url-field" htmlFor="youtube-url">
                        <span>Individual YouTube video URL</span>
                        <input
                          id="youtube-url"
                          type="url"
                          inputMode="url"
                          placeholder="https://www.youtube.com/watch?v=…"
                          value={youtubeUrl}
                          onChange={(event) => setYoutubeUrl(event.target.value)}
                          disabled={uploading}
                        />
                      </label>
                      <p className="url-note">
                        Individual HTTPS videos are supported. Playlist/channel URLs without a specific video are
                        not accepted; queue parameters are ignored when a video ID is present.
                      </p>
                    </>
                  )}
                </section>

                <fieldset className="module">
                  <legend className="module-label">02 · Engine</legend>
                  <div className="opt-stack">
                    <label className={`opt ${separatorEngine === 'demucs' ? 'opt--selected' : ''}`}>
                      <input
                        type="radio"
                        name="separator-engine"
                        value="demucs"
                        checked={separatorEngine === 'demucs'}
                        onChange={() => setSeparatorEngine('demucs')}
                      />
                      <span className="opt-led" aria-hidden="true" />
                      <span className="opt-copy">
                        <strong>Demucs <em>Current · faster</em></strong>
                        <small>CPU separation with Natural backing, Best quality, and Strong removal profiles.</small>
                      </span>
                    </label>
                    <label className={`opt ${separatorEngine === 'melband_roformer' ? 'opt--selected' : ''}`}>
                      <input
                        type="radio"
                        name="separator-engine"
                        value="melband_roformer"
                        checked={separatorEngine === 'melband_roformer'}
                        onChange={() => {
                          setSeparatorEngine('melband_roformer')
                          setQuality('preserve')
                        }}
                      />
                      <span className="opt-led" aria-hidden="true" />
                      <span className="opt-copy">
                        <strong>MelBand RoFormer <em>Experimental</em></strong>
                        <small>CPU-only model with an ~871 MB first download. Runtime varies by track and computer.</small>
                      </span>
                    </label>
                  </div>
                </fieldset>

                {separatorEngine === 'demucs' && (
                  <fieldset className="module">
                    <legend className="module-label">03 · Profile</legend>
                    <div className="opt-stack">
                      {qualityOptions.map((option) => (
                        <label
                          key={option.value}
                          className={`opt ${quality === option.value ? 'opt--selected' : ''}`}
                        >
                          <input
                            type="radio"
                            name="quality"
                            value={option.value}
                            checked={quality === option.value}
                            onChange={() => setQuality(option.value)}
                          />
                          <span className="opt-led" aria-hidden="true" />
                          <span className="opt-copy">
                            <strong>
                              {option.name}
                              {option.recommended && <em>Recommended</em>}
                            </strong>
                            <small>{option.description}</small>
                          </span>
                          <span className="opt-speed">{option.speed}</span>
                        </label>
                      ))}
                    </div>
                  </fieldset>
                )}

                <section className="module">
                  <span className="module-label">04 · Rights</span>
                  <label className="arm">
                    <input
                      type="checkbox"
                      checked={rightsConfirmed}
                      onChange={(event) => setRightsConfirmed(event.target.checked)}
                    />
                    <span className="arm-switch" aria-hidden="true" />
                    <span className="arm-copy">
                      <strong>I confirm I’m allowed to use this source</strong>
                      <small>{rightsAttestationText}</small>
                    </span>
                  </label>
                </section>

                <section className="module module--start">
                  <span className="module-label">05 · Start</span>
                  <motion.button
                    className="start-button"
                    type="button"
                    disabled={startDisabled}
                    onClick={submit}
                    whileTap={reduce || startDisabled ? undefined : { scale: 0.98 }}
                    transition={{ type: 'spring', stiffness: 480, damping: 32 }}
                  >
                    {uploading ? (
                      <>
                        <span className="button-spinner" aria-hidden="true" />
                        {sourceType === 'upload' ? `Sending ${uploadProgress}%` : 'Starting fetch…'}
                      </>
                    ) : (
                      'Start'
                    )}
                  </motion.button>
                  {uploading && sourceType === 'upload' && (
                    <div className="upload-meter" aria-live="polite">
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
                  {!uploading && (
                    <p className="start-hint">
                      {startDisabled ? 'Load a source · arm rights to enable' : 'Separates stems on this computer'}
                    </p>
                  )}
                </section>
              </>
            ) : (
              <section className="module">
                <span className="module-label">Loaded job</span>
                <div className="job-lines">
                  <div className="job-line">
                    <span>Track</span>
                    <strong>{jobDisplayName(job)}</strong>
                  </div>
                  <div className="job-line">
                    <span>Engine</span>
                    <strong>{jobEngineLabel(job)}</strong>
                  </div>
                  <div className="job-line">
                    <span>Status</span>
                    <strong>{job.status}</strong>
                  </div>
                  <div className="job-line">
                    <span>Started</span>
                    <strong>{formatJobDate(job.created_at)}</strong>
                  </div>
                </div>
                {isProcessing ? (
                  <p className="lock-note">
                    <span className="led led--amber led--pulse" aria-hidden="true" /> Processing · panel unlocks when done
                  </p>
                ) : (
                  <button className="eject-button" type="button" onClick={startOver}>
                    <EjectIcon size={12} /> Eject · New source
                  </button>
                )}
              </section>
            )}
          </motion.aside>
        </div>

        <motion.footer className="deck-bottom" {...regionFade(0.3)}>
          <ul className="rules-line">
            <li>Sources &amp; stems stay on this computer</li>
            <li>Stored only in local app data</li>
            <li>CPU processing</li>
            <li>WAV output</li>
            <li>No cloud storage</li>
            <li>Separation does not change a song’s underlying rights</li>
          </ul>
          <div className="tool-leds">
            {(['ffmpeg', 'ffprobe', 'demucs'] as const).map((tool) => (
              <span key={tool}>
                <span
                  className={`led ${health ? (health.tools[tool] ? 'led--green' : 'led--red') : ''}`}
                  aria-hidden="true"
                />
                {tool}
              </span>
            ))}
          </div>
        </motion.footer>
      </div>
    </div>
  )
}

export default App
