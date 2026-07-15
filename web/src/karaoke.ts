export type LyricWord = { text: string; start_ms: number; end_ms: number | null }
export type LyricLine = { text: string; start_ms: number; end_ms: number | null; words: LyricWord[]; editor_id?: string }
export type KaraokeProject = {
  version: 1
  revision: number
  record: { id: number; title: string; artist: string; album: string; duration_seconds: number; has_word_timing: boolean }
  fetched_at: string
  lines: LyricLine[]
  offset_ms: number
  title: string
  subtitle: string
  visual: {
    background: 'neon' | 'solid' | 'gradient' | 'custom'
    solid_color: string
    gradient_start: string
    gradient_end: string
    font: 'sans' | 'display' | 'mono'
    inactive_color: string
    highlight_color: string
    position: 'top' | 'center' | 'bottom'
  }
}
export type KaraokeState = {
  status: 'empty' | 'draft' | 'queued' | 'rendering' | 'completed' | 'failed'
  progress: number
  message: string
  error: string | null
  project_revision: number | null
  rendered_revision: number | null
  updated_at: string
}
export type LyricsCandidate = {
  id: number
  title: string
  artist: string
  album: string
  duration_seconds: number
  has_word_timing: boolean
  instrumental: boolean
}

export type LyricsStudioView = 'search' | 'editor'

export function lyricsView(project: KaraokeProject | null, changingLyrics: boolean): LyricsStudioView {
  return project && !changingLyrics ? 'editor' : 'search'
}

export function canReplaceLyrics(dirty: boolean, confirmReplacement: () => boolean): boolean {
  return !dirty || confirmReplacement()
}

export function lineIntervals(lines: LyricLine[], durationMs: number, offsetMs = 0) {
  const bounded = Math.max(0, Number.isFinite(durationMs) ? durationMs : 0)
  return lines.map((line, index) => {
    const start = Math.max(0, Math.min(bounded, line.start_ms + offsetMs))
    const next = lines[index + 1]?.start_ms ?? bounded
    const end = Math.max(start, Math.min(bounded, line.end_ms !== null ? line.end_ms + offsetMs : index + 1 < lines.length ? next + offsetMs : next))
    return { start, end, index }
  }).filter(({ end, start }) => end > start)
}

export function wordIntervals(line: LyricLine, lineEndMs: number, durationMs: number, offsetMs = 0) {
  const bounded = Math.max(0, Number.isFinite(durationMs) ? durationMs : 0)
  return line.words.map((word, index) => {
    const start = Math.max(0, Math.min(bounded, word.start_ms + offsetMs))
    const next = line.words[index + 1]?.start_ms ?? lineEndMs
    const end = Math.max(start, Math.min(bounded, word.end_ms !== null ? word.end_ms + offsetMs : index + 1 < line.words.length ? next + offsetMs : next))
    return { start, end, index }
  }).filter(({ end, start }) => end > start)
}

export function activeLine(lines: LyricLine[], timeMs: number, offsetMs = 0, durationMs = Number.MAX_SAFE_INTEGER) {
  return lineIntervals(lines, durationMs, offsetMs).find(({ start, end }) => start <= timeMs && timeMs < end)?.index ?? -1
}

export function activeWord(line: LyricLine, lineEndMs: number, timeMs: number, durationMs: number, offsetMs = 0) {
  return wordIntervals(line, lineEndMs, durationMs, offsetMs).find(({ start, end }) => start <= timeMs && timeMs < end)?.index ?? -1
}

export function sortLines(lines: LyricLine[]) {
  return [...lines].sort((left, right) => left.start_ms - right.start_ms || left.text.localeCompare(right.text))
}

export function shiftLine(line: LyricLine, deltaMs: number): LyricLine {
  return { ...line, start_ms: Math.max(0, line.start_ms + deltaMs), end_ms: line.end_ms === null ? null : Math.max(0, line.end_ms + deltaMs), words: line.words.map((word) => ({ ...word, start_ms: Math.max(0, word.start_ms + deltaMs), end_ms: word.end_ms === null ? null : Math.max(0, word.end_ms + deltaMs) })) }
}

export function editLineText(line: LyricLine, text: string): LyricLine {
  return { ...line, text, words: [] }
}
