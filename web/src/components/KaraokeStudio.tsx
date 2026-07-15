import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { activeLine, activeWord, canReplaceLyrics, editLineText, lineIntervals, lyricsView, shiftLine, sortLines, type KaraokeProject, type KaraokeState, type LyricLine, type LyricsCandidate } from '../karaoke'
import { closeStemPreviewGraph, createStemPreviewGraph, playStemPreview, updateStemPreviewGain, type StemPreviewGraph } from '../previewAudio'
import './KaraokeStudio.css'

type Job = {
  id: string
  original_filename: string
  title: string | null
  uploader: string | null
  duration_seconds?: number | null
  assets?: Partial<Record<'instrumental' | 'vocals' | 'karaoke', string>>
  karaoke_status?: KaraokeState['status']
  karaoke_progress?: number
  karaoke_message?: string
  karaoke_error?: string | null
  karaoke_project_revision?: number | null
  karaoke_rendered_revision?: number | null
}
type Props = { job: Job; apiUrl: (path: string) => string; onClose: () => void; onUpdated: (job: Partial<Job>) => void; onDirtyChange: (dirty: boolean) => void }

const emptyState: KaraokeState = { status: 'empty', progress: 0, message: '', error: null, project_revision: null, rendered_revision: null, updated_at: '' }

async function responseError(response: Response) {
  try {
    const detail = (await response.json()) as { detail?: string | Array<{ msg?: string }> }
    if (typeof detail.detail === 'string') return detail.detail
    if (Array.isArray(detail.detail)) return detail.detail.map((item) => item.msg || 'Invalid value').join('; ')
    return `Request failed (${response.status})`
  } catch { return `Request failed (${response.status})` }
}

function editable(project: KaraokeProject) {
  return { lines: project.lines.map(({ editor_id: _editorId, ...line }) => line), offset_ms: project.offset_ms, title: project.title, subtitle: project.subtitle, visual: project.visual }
}

function withEditorIds(project: KaraokeProject): KaraokeProject {
  return { ...project, lines: project.lines.map((line, index) => ({ ...line, editor_id: line.editor_id || `line-${project.revision}-${index}-${Math.random().toString(36).slice(2)}` })) }
}

export function Preview({ project, current, currentWord, timeMs, customUrl }: { project: KaraokeProject; current: number; currentWord: number; timeMs: number; customUrl: string }) {
  const visual = project.visual
  const family = `var(--karaoke-${visual.font})`
  const background = visual.background === 'custom' && customUrl
    ? `linear-gradient(rgba(8, 6, 10, .43), rgba(8, 6, 10, .43)), url(${customUrl}) center/cover`
    : visual.background === 'solid'
      ? `linear-gradient(rgba(8, 6, 10, .43), rgba(8, 6, 10, .43)), ${visual.solid_color}`
      : `linear-gradient(rgba(8, 6, 10, .43), rgba(8, 6, 10, .43)), linear-gradient(180deg, ${visual.gradient_start}, ${visual.gradient_end})`
  const lyricWidth = { left: '8.3333333%', right: '8.3333333%', maxWidth: '83.3333333%' }
  const lyricTop = { ...lyricWidth, top: `${(visual.position === 'top' ? 260 : visual.position === 'bottom' ? 790 : 540) / 10.8}%` }
  const nextTop = { ...lyricWidth, top: `${(visual.position === 'top' ? 365 : visual.position === 'bottom' ? 895 : 645) / 10.8}%` }
  const line = current >= 0 ? project.lines[current] : null
  return (
    <div className="lyric-preview" style={{ background, color: visual.inactive_color }}>
      <div className="lyric-preview__heading">
        <small style={{ ...lyricWidth, color: visual.highlight_color, fontFamily: family, fontSize: '2.5cqw', fontWeight: 700 }}>{project.title}</small>
        <p className="lyric-preview__subtitle" style={{ ...lyricWidth, color: visual.inactive_color, fontFamily: family, fontSize: '1.40625cqw' }}>{project.subtitle}</p>
      </div>
      <div className="lyric-preview__lyrics">
        <h2 style={{ ...lyricTop, color: visual.highlight_color, fontFamily: family, fontSize: '3.5416667cqw' }}>
          {line
            ? line.words.length
              ? line.words.map((word, index) => (
                  <span key={`${index}-${word.text}`} style={{ color: index === currentWord ? visual.highlight_color : visual.inactive_color }}>
                    {word.text}
                  </span>
                ))
              : line.text
            : ''}
        </h2>
        <p style={{ ...nextTop, color: visual.inactive_color, fontFamily: family, fontSize: '1.9791667cqw' }}>{line && project.lines[current + 1]?.text}</p>
      </div>
      <output aria-label="Preview position">{Math.floor(timeMs / 60000)}:{String(Math.floor(timeMs / 1000) % 60).padStart(2, '0')}</output>
    </div>
  )
}

export function ChangeLyricsAction({ disabled, onChange, buttonRef }: { disabled: boolean; onChange: () => void; buttonRef?: RefObject<HTMLButtonElement | null> }) {
  return <button ref={buttonRef} className="label-button" type="button" disabled={disabled} onClick={onChange}>Change lyrics</button>
}

type SearchPanelProps = {
  title: string
  artist: string
  album: string
  setTitle: (value: string) => void
  setArtist: (value: string) => void
  setAlbum: (value: string) => void
  candidates: LyricsCandidate[]
  searched: boolean
  operation: 'loading' | 'searching' | 'selecting' | null
  error: string
  onSearch: () => void
  onChoose: (candidate: LyricsCandidate) => void
  titleRef?: RefObject<HTMLInputElement | null>
  showCancel?: boolean
  onCancel?: () => void
  blocked?: boolean
  loadError: boolean
  onRetry: () => void
}

export function SearchPanel({ title, artist, album, setTitle, setArtist, setAlbum, candidates, searched, operation, error, onSearch, onChoose, titleRef, showCancel = false, onCancel, blocked = false, loadError, onRetry }: SearchPanelProps) {
  const busy = operation !== null || blocked
  return (
    <div className="lyric-lab__search">
      <div className="lyric-disclosure" role="note">
        <strong>LRCLIB metadata disclosure</strong>
        <span>Track title, artist, album, and search text are sent only to https://lrclib.net. Review and explicitly select a synchronized result; Karaoke Box does not claim returned lyrics are licensed.</span>
      </div>
      {loadError ? (
        <div className="lyric-status" role="alert">Could not load the saved lyric project. <button className="label-button" type="button" onClick={onRetry}>Retry load</button></div>
      ) : <>
        <label>Track title<input ref={titleRef} value={title} disabled={busy} onChange={(event) => setTitle(event.target.value)} /></label>
        <label>Artist<input value={artist} disabled={busy} onChange={(event) => setArtist(event.target.value)} /></label>
        <label>Album (optional)<input value={album} disabled={busy} onChange={(event) => setAlbum(event.target.value)} /></label>
        <button className="start-button" type="button" disabled={busy || !title.trim() || !artist.trim()} onClick={onSearch}>
          {busy ? 'Searching…' : 'Search LRCLIB'}
        </button>
        {showCancel && <button className="label-button" type="button" disabled={busy} onClick={onCancel}>Cancel lyric change</button>}
      </>}
      {operation === 'loading' && <p className="lyric-status" role="status">Loading saved lyric project…</p>}
      {operation === 'searching' && <p className="lyric-status" role="status">Searching LRCLIB…</p>}
      {operation === 'selecting' && <p className="lyric-status" role="status">Loading selected synchronized lyrics…</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}
      {!busy && searched && candidates.length === 0 && <p className="lyric-status" role="status">No synchronized LRCLIB results. Try different metadata.</p>}
      {!busy && searched && candidates.length > 0 && <p className="lyric-status" role="status">{candidates.length} synchronized result{candidates.length === 1 ? '' : 's'} found.</p>}
      {candidates.length > 0 && (
        <div className="lyric-candidates" aria-label="Synchronized lyric results">
          {candidates.map((candidate) => (
            <button className="lyric-candidate" type="button" disabled={busy} key={candidate.id} onClick={() => onChoose(candidate)}>
              <strong>{candidate.title}</strong>
              <span>{candidate.artist} · {candidate.album || 'Unknown album'} · {Math.round(candidate.duration_seconds)}s</span>
              <small>{candidate.has_word_timing ? 'Word timing available' : 'Line timing'}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function PreviewSection({ project, current, currentWord, customUrl, duration, timeMs, instrumental, vocals, instrumentalUrl, vocalsUrl, onSeek, onDuration, onTime, onError, onPause, onEnded, onUnmount }: {
  project: KaraokeProject
  current: number
  currentWord: number
  customUrl: string
  duration: number
  timeMs: number
  instrumental: RefObject<HTMLAudioElement | null>
  vocals: RefObject<HTMLAudioElement | null>
  onSeek: (value: number) => void
  onDuration: (value: number) => void
  onTime: (value: number) => void
  onError: (message: string) => void
  onPause: () => void
  onEnded: () => void
  onUnmount: () => void
  instrumentalUrl: string
  vocalsUrl: string
}) {
  useLayoutEffect(() => onUnmount, [onUnmount])
  return (
    <div className="lyric-lab__preview">
      <Preview project={project} current={current} currentWord={currentWord} timeMs={timeMs} customUrl={customUrl} />
      <input className="lyric-seek" aria-label="Preview position" type="range" min="0" max={Math.max(1, duration)} step="10" value={Math.min(timeMs, duration || 1)} onChange={(event) => onSeek(Number(event.target.value))} />
      <audio ref={instrumental} src={instrumentalUrl} preload="auto" onLoadedMetadata={(event) => onDuration(event.currentTarget.duration * 1000)} onTimeUpdate={(event) => onTime(event.currentTarget.currentTime * 1000)} onPause={onPause} onError={() => onError('The instrumental preview could not be loaded.')} onEnded={onEnded} />
      <audio ref={vocals} src={vocalsUrl} preload="auto" onError={() => onError('The vocal guide preview could not be loaded.')} />
    </div>
  )
}

export function KaraokeStudio({ job, apiUrl, onClose, onUpdated, onDirtyChange }: Props) {
  const [project, setProject] = useState<KaraokeProject | null>(null)
  const [changingLyrics, setChangingLyrics] = useState(false)
  const [state, setState] = useState<KaraokeState>(emptyState)
  const [title, setTitle] = useState(job.title || job.original_filename.replace(/\.[^.]+$/, ''))
  const [artist, setArtist] = useState(job.uploader || '')
  const [album, setAlbum] = useState('')
  const [candidates, setCandidates] = useState<LyricsCandidate[]>([])
  const [searched, setSearched] = useState(false)
  const [operation, setOperation] = useState<'loading' | 'searching' | 'selecting' | 'saving' | 'uploading' | 'rendering' | null>(null)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [timeMs, setTimeMs] = useState(0)
  const [duration, setDuration] = useState((job.duration_seconds || 0) * 1000)
  const [vocalVolume, setVocalVolume] = useState(0.15)
  const instrumental = useRef<HTMLAudioElement>(null)
  const vocals = useRef<HTMLAudioElement>(null)
  const previewGraph = useRef<StemPreviewGraph | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const searchTitle = useRef<HTMLInputElement>(null)
  const changeLyricsButton = useRef<HTMLButtonElement>(null)
  const wasChangingLyrics = useRef(false)
  const returnFocus = useRef<HTMLElement | null>(null)
  const assetsRef = useRef(job.assets)
  const setDirtyState = useCallback((next: boolean) => {
    setDirty(next)
    onDirtyChange(next)
  }, [onDirtyChange])
  const closePreviewGraph = useCallback(() => {
    if (previewGraph.current) {
      closeStemPreviewGraph(previewGraph.current)
      previewGraph.current = null
    }
  }, [])
  const stopPlayback = useCallback((reset = false) => {
    instrumental.current?.pause()
    vocals.current?.pause()
    if (reset) {
      if (instrumental.current) instrumental.current.currentTime = 0
      if (vocals.current) vocals.current.currentTime = 0
      setTimeMs(0)
    }
    setPlaying(false)
  }, [])

  const load = useCallback(async () => {
    const response = await fetch(apiUrl(`/api/jobs/${job.id}/karaoke`))
    if (!response.ok) throw new Error(await responseError(response))
    const payload = await response.json() as { project: KaraokeProject | null; state: KaraokeState }
    setProject(payload.project ? withEditorIds(payload.project) : null); setState(payload.state); setDirtyState(false); setLoadError(false); setError('')
    const persistedAssets = assetsRef.current
    const assets = payload.state.status === 'completed' && payload.state.rendered_revision !== null
      ? { ...persistedAssets, karaoke: `/api/jobs/${job.id}/assets/karaoke` }
      : persistedAssets
    onUpdated({ karaoke_status: payload.state.status, karaoke_progress: payload.state.progress, karaoke_message: payload.state.message, karaoke_error: payload.state.error, karaoke_project_revision: payload.state.project_revision, karaoke_rendered_revision: payload.state.rendered_revision, assets })
  }, [apiUrl, job.id, onUpdated, setDirtyState])

  useEffect(() => {
    assetsRef.current = {
      instrumental: job.assets?.instrumental,
      vocals: job.assets?.vocals,
      karaoke: job.assets?.karaoke,
    }
  }, [job.assets?.instrumental, job.assets?.vocals, job.assets?.karaoke])
  useEffect(() => {
    returnFocus.current = document.activeElement as HTMLElement | null
  }, [])
  useEffect(() => {
    if (changingLyrics) searchTitle.current?.focus()
    else if (wasChangingLyrics.current) changeLyricsButton.current?.focus()
    wasChangingLyrics.current = changingLyrics
  }, [changingLyrics])
  useEffect(() => {
    const graph = previewGraph.current
    if (graph) updateStemPreviewGain(graph, vocalVolume)
  }, [vocalVolume])
  useLayoutEffect(() => () => {
    instrumental.current?.pause()
    vocals.current?.pause()
    if (instrumental.current) instrumental.current.currentTime = 0
    if (vocals.current) vocals.current.currentTime = 0
    closePreviewGraph()
  }, [closePreviewGraph])
  useEffect(() => {
    if (!dirty) return
    const preventDirtyLoss = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', preventDirtyLoss)
    return () => window.removeEventListener('beforeunload', preventDirtyLoss)
  }, [dirty])
  useEffect(() => {
    if (!job.karaoke_status) return
    setState((old) => {
      const next = {
        ...old,
        status: job.karaoke_status!,
        progress: job.karaoke_progress ?? old.progress,
        message: job.karaoke_message ?? old.message,
        error: job.karaoke_error ?? null,
        project_revision: job.karaoke_project_revision ?? old.project_revision,
        rendered_revision: job.karaoke_rendered_revision ?? old.rendered_revision,
      }
      return old.status === next.status && old.progress === next.progress && old.message === next.message && old.error === next.error && old.project_revision === next.project_revision && old.rendered_revision === next.rendered_revision ? old : next
    })
  }, [job.karaoke_status, job.karaoke_progress, job.karaoke_message, job.karaoke_error, job.karaoke_project_revision, job.karaoke_rendered_revision])
  useEffect(() => {
    const previousFocus = returnFocus.current
    setOperation('loading')
    void load().catch((reason: unknown) => { setLoadError(true); setError(reason instanceof Error ? reason.message : 'Could not load karaoke project.') }).finally(() => setOperation(null))
    heading.current?.focus()
    return () => previousFocus?.focus()
  }, [load])
  useEffect(() => {
    if (!['queued', 'rendering'].includes(state.status)) return
    let timer = 0
    let cancelled = false
    const refresh = () => {
      void load()
        .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : 'Could not refresh karaoke render status.'))
        .finally(() => { if (!cancelled) timer = window.setTimeout(refresh, 1000) })
    }
    timer = window.setTimeout(refresh, 1000)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [load, project, state.status, state.progress])
  useEffect(() => {
    if (!playing) return
    let frame = 0
    const tick = () => {
      const media = instrumental.current
      if (media) setTimeMs(media.currentTime * 1000)
      frame = window.requestAnimationFrame(tick)
    }
    frame = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(frame)
  }, [playing])

  const current = useMemo(
    () => project ? activeLine(project.lines, timeMs, project.offset_ms, duration || Number.MAX_SAFE_INTEGER) : -1,
    [project, timeMs, duration],
  )
  const currentWord = useMemo(() => {
    if (!project || current < 0) return -1
    const end = lineIntervals(project.lines, duration || Number.MAX_SAFE_INTEGER, project.offset_ms).find((entry) => entry.index === current)?.end || duration
    return activeWord(project.lines[current], end, timeMs, duration || Number.MAX_SAFE_INTEGER, project.offset_ms)
  }, [current, duration, project, timeMs])
  const customUrl = `${apiUrl(`/api/jobs/${job.id}/karaoke/background`)}?revision=${project?.revision ?? state.project_revision ?? 0}`
  const mutating = operation !== null || state.status === 'queued' || state.status === 'rendering'
  const mark = (next: KaraokeProject) => {
    if (state.status === 'queued' || state.status === 'rendering' || operation !== null) return
    setProject({ ...next, lines: sortLines(next.lines) })
    setDirtyState(true)
    setState((old) => old.status === 'queued' || old.status === 'rendering' ? old : ({ ...old, status: 'draft', error: null }))
  }

  const save = async (next: KaraokeProject): Promise<KaraokeProject | null> => {
    setOperation('saving')
    setError('')
    try {
      const response = await fetch(apiUrl(`/api/jobs/${job.id}/karaoke`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editable({ ...next, lines: sortLines(next.lines) })),
      })
      if (!response.ok) throw new Error(await responseError(response))
      const payload = await response.json() as { project: KaraokeProject; state: KaraokeState }
      setProject(withEditorIds(payload.project))
      setState(payload.state)
      setDirtyState(false)
      onUpdated({ karaoke_status: payload.state.status, karaoke_project_revision: payload.state.project_revision, karaoke_rendered_revision: payload.state.rendered_revision, karaoke_error: payload.state.error })
      return payload.project
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save karaoke project.')
      return null
    } finally {
      setOperation(null)
    }
  }

  const search = async () => {
    setOperation('searching')
    setError('')
    setCandidates([])
    setSearched(false)
    try {
      const response = await fetch(apiUrl(`/api/jobs/${job.id}/lyrics/search`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), artist: artist.trim(), album: album.trim() }),
      })
      if (!response.ok) throw new Error(await responseError(response))
      setCandidates(await response.json() as LyricsCandidate[])
      setSearched(true)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not search LRCLIB.')
      setSearched(true)
    } finally {
      setOperation(null)
    }
  }

  const changeLyrics = () => {
    if (!project || mutating) return
    stopPlayback(true)
    setTitle(project.record.title)
    setArtist(project.record.artist)
    setAlbum(project.record.album)
    setCandidates([])
    setSearched(false)
    setError('')
    setChangingLyrics(true)
  }

  const cancelLyricsChange = () => {
    if (mutating) return
    setCandidates([])
    setSearched(false)
    setError('')
    setChangingLyrics(false)
  }

  const choose = async (candidate: LyricsCandidate) => {
    if (!canReplaceLyrics(dirty, () => window.confirm('Discard unsaved lyric edits and replace the selected lyrics?'))) return
    setOperation('selecting')
    setError('')
    try {
      const response = await fetch(apiUrl(`/api/jobs/${job.id}/lyrics/select`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ record_id: candidate.id }),
      })
      if (!response.ok) throw new Error(await responseError(response))
      const payload = await response.json() as { project: KaraokeProject; state: KaraokeState }
      setProject(withEditorIds(payload.project))
      setState(payload.state)
      setCandidates([])
      setDirtyState(false)
      setChangingLyrics(false)
      heading.current?.focus()
      onUpdated({ karaoke_status: payload.state.status, karaoke_progress: payload.state.progress, karaoke_message: payload.state.message, karaoke_error: payload.state.error, karaoke_project_revision: payload.state.project_revision, karaoke_rendered_revision: payload.state.rendered_revision })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not select lyrics.')
    } finally {
      setOperation(null)
    }
  }

  const uploadBackground = async (file: File) => {
    if (!project) return
    const saved = dirty ? await save(project) : project
    if (!saved) return
    setOperation('uploading')
    setError('')
    try {
      const body = new FormData()
      body.append('file', file)
      const response = await fetch(apiUrl(`/api/jobs/${job.id}/karaoke/background`), { method: 'POST', body })
      if (!response.ok) throw new Error(await responseError(response))
      const payload = await response.json() as { project: KaraokeProject; state: KaraokeState }
      setProject(withEditorIds(payload.project))
      setState(payload.state)
      setDirtyState(false)
      onUpdated({ karaoke_status: payload.state.status, karaoke_project_revision: payload.state.project_revision, karaoke_rendered_revision: payload.state.rendered_revision })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not save background.')
    } finally {
      setOperation(null)
    }
  }

  const render = async () => {
    if (!project) return
    const saved = dirty ? await save(project) : project
    if (!saved) return
    setOperation('rendering')
    setError('')
    try {
      const response = await fetch(apiUrl(`/api/jobs/${job.id}/karaoke/render`), { method: 'POST' })
      if (!response.ok) throw new Error(await responseError(response))
      onUpdated(await response.json() as Partial<Job>)
      await load()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not start rendering.')
    } finally {
      setOperation(null)
    }
  }

  const seek = (value: number) => {
    if (instrumental.current) instrumental.current.currentTime = value / 1000
    if (vocals.current) vocals.current.currentTime = value / 1000
    setTimeMs(value)
  }

  const ensurePreviewGraph = () => {
    if (previewGraph.current) return previewGraph.current
    const main = instrumental.current
    const guide = vocals.current
    if (!main || !guide) return null
    const graph = createStemPreviewGraph(main, guide, vocalVolume)
    previewGraph.current = graph
    return graph
  }

  const togglePlayback = async () => {
    const main = instrumental.current
    const guide = vocals.current
    if (!main || !guide) return
    if (playing) {
      main.pause()
      guide.pause()
      setPlaying(false)
      return
    }
    setError('')
    try {
      const graph = ensurePreviewGraph()
      if (!graph) return
      await playStemPreview(graph, main, guide)
      setPlaying(true)
    } catch {
      main.pause()
      guide.pause()
      setPlaying(false)
      setError('Your browser could not start audio playback.')
    }
  }

  const mutateLine = (index: number, line: LyricLine) => {
    if (!project) return
    mark({ ...project, lines: project.lines.map((entry, candidate) => candidate === index ? line : entry) })
  }

  const view = lyricsView(project, changingLyrics)
  return (
    <section className="lyric-lab" aria-labelledby="lyric-lab-title">
      <header className="lyric-lab__header">
        <div>
          <span className="module-label">LYRIC LAB · VIDEO STUDIO</span>
          <h1 id="lyric-lab-title" tabIndex={-1} ref={heading}>Build the sing-along.</h1>
          <p>Preview your instrumental, tune the lines, then render a 1080p karaoke video.</p>
        </div>
        <button className="eject-button" type="button" disabled={operation !== null} onClick={() => { if (dirty && !window.confirm('Discard unsaved lyric edits?')) return; onClose() }}>Back to deck</button>
      </header>
      {view === 'search' || project === null ? (
        <SearchPanel title={title} artist={artist} album={album} setTitle={(value) => { setTitle(value); setCandidates([]); setSearched(false) }} setArtist={(value) => { setArtist(value); setCandidates([]); setSearched(false) }} setAlbum={(value) => { setAlbum(value); setCandidates([]); setSearched(false) }} candidates={candidates} searched={searched} operation={operation === 'loading' || operation === 'searching' || operation === 'selecting' ? operation : null} error={error} onSearch={() => void search()} onChoose={(candidate) => void choose(candidate)} titleRef={searchTitle} showCancel={Boolean(project)} onCancel={cancelLyricsChange} blocked={mutating} loadError={loadError} onRetry={() => { setLoadError(false); setOperation('loading'); void load().catch((reason: unknown) => { setLoadError(true); setError(reason instanceof Error ? reason.message : 'Could not load karaoke project.') }).finally(() => setOperation(null)) }} />
      ) : (
        <>
          <div className="lyric-lab__toolbar">
            <button type="button" className="play-button" onClick={() => void togglePlayback()}>{playing ? 'Pause' : 'Play'}</button>
            <span>{Math.floor(timeMs / 60000)}:{String(Math.floor(timeMs / 1000) % 60).padStart(2, '0')} · {project.record.title} · Lyrics via LRCLIB</span>
            <ChangeLyricsAction disabled={mutating} onChange={changeLyrics} buttonRef={changeLyricsButton} />
            <label>Offset <input type="number" min={-120000} max={120000} value={project.offset_ms} disabled={mutating} onChange={(event) => mark({ ...project, offset_ms: Math.max(-120000, Math.min(120000, Number(event.target.value) || 0)) })} /> ms</label>
          </div>
          <PreviewSection
            project={project}
            current={current}
            currentWord={currentWord}
            customUrl={customUrl}
            duration={duration}
            timeMs={timeMs}
            instrumental={instrumental}
            vocals={vocals}
            instrumentalUrl={apiUrl(`/api/jobs/${job.id}/assets/instrumental`)}
            vocalsUrl={apiUrl(`/api/jobs/${job.id}/assets/vocals`)}
            onSeek={seek}
            onDuration={setDuration}
            onTime={setTimeMs}
            onError={(message) => { stopPlayback(true); setError(message) }}
            onPause={() => setPlaying(false)}
            onEnded={() => stopPlayback(true)}
            onUnmount={closePreviewGraph}
          />
          <div className="lyric-lab__controls">
            <label>Video title<input maxLength={300} value={project.title} disabled={mutating} onChange={(event) => mark({ ...project, title: event.target.value })} /></label>
            <label>Subtitle<input maxLength={300} value={project.subtitle} disabled={mutating} onChange={(event) => mark({ ...project, subtitle: event.target.value })} /></label>
            <label>Position<select value={project.visual.position} disabled={mutating} onChange={(event) => mark({ ...project, visual: { ...project.visual, position: event.target.value as KaraokeProject['visual']['position'] } })}><option value="top">Top</option><option value="center">Center</option><option value="bottom">Bottom</option></select></label>
            <label>Background<select value={project.visual.background} disabled={mutating} onChange={(event) => mark({ ...project, visual: { ...project.visual, background: event.target.value as KaraokeProject['visual']['background'] } })}><option value="neon">Neon gradient</option><option value="solid">Solid color</option><option value="gradient">Custom gradient</option><option value="custom" disabled>Uploaded image (upload below)</option></select></label>
            <label>Solid color<input type="color" disabled={mutating} value={project.visual.solid_color} onChange={(event) => mark({ ...project, visual: { ...project.visual, solid_color: event.target.value } })} /></label>
            <label>Gradient start<input type="color" disabled={mutating} value={project.visual.gradient_start} onChange={(event) => mark({ ...project, visual: { ...project.visual, gradient_start: event.target.value } })} /></label>
            <label>Gradient end<input type="color" disabled={mutating} value={project.visual.gradient_end} onChange={(event) => mark({ ...project, visual: { ...project.visual, gradient_end: event.target.value } })} /></label>
            <label>Inactive color<input type="color" disabled={mutating} value={project.visual.inactive_color} onChange={(event) => mark({ ...project, visual: { ...project.visual, inactive_color: event.target.value } })} /></label>
            <label>Highlight color<input type="color" disabled={mutating} value={project.visual.highlight_color} onChange={(event) => mark({ ...project, visual: { ...project.visual, highlight_color: event.target.value } })} /></label>
            <label>Font<select value={project.visual.font} disabled={mutating} onChange={(event) => mark({ ...project, visual: { ...project.visual, font: event.target.value as KaraokeProject['visual']['font'] } })}><option value="sans">Archivo sans</option><option value="display">Doto display</option><option value="mono">Spline Sans Mono</option></select></label>
            <label>Vocal guide<input type="range" min="0" max="1" step="0.01" value={vocalVolume} onChange={(event) => setVocalVolume(Number(event.target.value))} /></label>
            <label>Custom background<input type="file" accept=".png,.jpg,.jpeg,.webp" disabled={mutating} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadBackground(file) }} /></label>
            <button className="label-button" type="button" disabled={mutating || !dirty} onClick={() => void save(project)}>Save timing &amp; style</button>
          </div>
          <div className="lyric-lab__lines">
            <div className="lyric-lab__lines-head">
              <strong>Timing rack</strong>
              <span>{project.lines.length} lines · {project.record.has_word_timing ? 'provider word timing available; line editor active' : 'line timing'}</span>
              <button className="label-button" type="button" disabled={mutating} onClick={() => mark({ ...project, lines: [...project.lines, { editor_id: `line-${Date.now()}`, text: 'New lyric line', start_ms: Math.min(86400000, Math.round(timeMs)), end_ms: null, words: [] }] })}>Add line at playhead</button>
            </div>
            {project.lines.map((line, index) => (
              <div className={`lyric-line ${index === current ? 'lyric-line--active' : ''}`} role="group" aria-label={`Lyric line ${index + 1}: ${line.text}`} key={line.editor_id || `line-${index}`}>
                <input maxLength={500} required value={line.text} disabled={mutating} aria-label={`Lyric line ${index + 1}`} onChange={(event) => mutateLine(index, editLineText(line, event.target.value))} />
                <input type="number" min={0} max={86400000} value={line.start_ms} disabled={mutating} aria-label={`Start time for line ${index + 1}`} onChange={(event) => mutateLine(index, shiftLine(line, Number(event.target.value) - line.start_ms))} />
                <button type="button" disabled={mutating} className="label-button" onClick={() => mutateLine(index, shiftLine(line, Math.round(timeMs) - line.start_ms))}>Set playhead</button>
                <button type="button" disabled={mutating} className="label-button" onClick={() => mutateLine(index, shiftLine(line, -100))}>−100ms</button>
                <button type="button" disabled={mutating} className="label-button" onClick={() => mutateLine(index, shiftLine(line, 100))}>+100ms</button>
                <button type="button" disabled={mutating || project.lines.length <= 1} className="label-button" onClick={() => mark({ ...project, lines: project.lines.filter((_, candidate) => candidate !== index) })}>Delete</button>
              </div>
            ))}
          </div>
          <footer className="lyric-lab__footer">
            <p>Search metadata is sent to LRCLIB. Review lyrics and timing before export.</p>
            {(error || state.error) && <p className="inline-error" role="alert">{error || state.error}</p>}
            {dirty && <p className="lyric-status">Unsaved changes · previous MP4 is stale.</p>}
            {state.status === 'rendering' || state.status === 'queued' ? (
              <div role="status">Rendering {state.progress}% · {state.message}</div>
            ) : state.status === 'completed' && state.rendered_revision === project.revision && !dirty ? (
              <a className="hw-download" href={`${apiUrl(`/api/jobs/${job.id}/assets/karaoke`)}?download=true`}>Download karaoke MP4</a>
            ) : (
              <>
                {job.assets?.karaoke && <a className="hw-download" href={`${apiUrl(`/api/jobs/${job.id}/assets/karaoke`)}?download=true`}>Download previous MP4 (stale)</a>}
                <button className="start-button" type="button" disabled={mutating} onClick={() => void render()}>{state.status === 'failed' ? 'Retry render' : 'Render karaoke video'}</button>
              </>
            )}
          </footer>
        </>
      )}
    </section>
  )
}
