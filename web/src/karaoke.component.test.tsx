import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ChangeLyricsAction, Preview, SearchPanel } from './components/KaraokeStudio'
import { canReplaceLyrics, lyricsView, type KaraokeProject } from './karaoke'
import { closeStemPreviewGraph, createStemPreviewGraph, playStemPreview, updateStemPreviewGain, type StemPreviewAudioContext } from './previewAudio'

const project: KaraokeProject = {
  version: 1,
  revision: 2,
  record: { id: 1, title: 'Song', artist: 'Artist', album: '', duration_seconds: 10, has_word_timing: false },
  fetched_at: 'now',
  lines: [{ text: 'Hello world', start_ms: 0, end_ms: 5000, words: [{ text: 'Hello ', start_ms: 0, end_ms: null }, { text: 'world', start_ms: 2500, end_ms: null }] }],
  offset_ms: 0,
  title: 'Song',
  subtitle: 'Artist',
  visual: { background: 'custom', solid_color: '#11100f', gradient_start: '#24101d', gradient_end: '#0c111d', font: 'sans', inactive_color: '#112233', highlight_color: '#abcdef', position: 'bottom' },
}

describe('Lyric Lab presentational sections', () => {
  it('shows metadata disclosure, no-results and errors', () => {
    const html = renderToStaticMarkup(<SearchPanel title="Song" artist="Artist" album="" setTitle={() => {}} setArtist={() => {}} setAlbum={() => {}} candidates={[]} searched operation={null} error="LRCLIB unavailable" onSearch={() => {}} onChoose={() => {}} loadError={false} onRetry={() => {}} />)
    expect(html).toContain('LRCLIB metadata disclosure')
    expect(html).toContain('LRCLIB unavailable')
    expect(html).toContain('No synchronized LRCLIB results')
  })

  it('exposes reversible lyric replacement controls and guard policy', () => {
    const changeHtml = renderToStaticMarkup(<ChangeLyricsAction disabled={false} onChange={() => {}} />)
    const blockedChangeHtml = renderToStaticMarkup(<ChangeLyricsAction disabled onChange={() => {}} />)
    const searchHtml = renderToStaticMarkup(<SearchPanel title="Song" artist="Artist" album="" setTitle={() => {}} setArtist={() => {}} setAlbum={() => {}} candidates={[]} searched={false} operation={null} error="" onSearch={() => {}} onChoose={() => {}} showCancel onCancel={() => {}} loadError={false} onRetry={() => {}} />)
    const blockedSearchHtml = renderToStaticMarkup(<SearchPanel title="Song" artist="Artist" album="" setTitle={() => {}} setArtist={() => {}} setAlbum={() => {}} candidates={[]} searched={false} operation={null} error="" onSearch={() => {}} onChoose={() => {}} showCancel onCancel={() => {}} blocked loadError={false} onRetry={() => {}} />)
    expect(changeHtml).toContain('Change lyrics')
    expect(blockedChangeHtml).toContain('disabled')
    expect(searchHtml).toContain('Cancel lyric change')
    expect(blockedSearchHtml).toContain('disabled')
    expect(lyricsView(project, false)).toBe('editor')
    expect(lyricsView(project, true)).toBe('search')
    expect(lyricsView(null, false)).toBe('search')
    let confirmations = 0
    const decline = () => { confirmations += 1; return false }
    const accept = () => { confirmations += 1; return true }
    expect(canReplaceLyrics(false, decline)).toBe(true)
    expect(confirmations).toBe(0)
    expect(canReplaceLyrics(true, decline)).toBe(false)
    expect(confirmations).toBe(1)
    expect(canReplaceLyrics(true, accept)).toBe(true)
    expect(confirmations).toBe(2)
  })

  it('keeps Lyric Lab stems synchronized while changing guide gain', async () => {
    const events: string[] = []
    const destination = { kind: 'destination' }
    class FakeGain {
      gain = {
        value: 0,
        cancelScheduledValues: (time: number) => events.push(`cancel:${time}`),
        setValueAtTime: (value: number, time: number) => { events.push(`set:${value}:${time}`); this.gain.value = value },
        linearRampToValueAtTime: (value: number, time: number) => { events.push(`ramp:${value}:${time}`); this.gain.value = value },
      }
      connections: unknown[] = []
      connect(node: unknown) {
        this.connections.push(node)
        return node
      }
    }
    class FakeSource {
      connections: unknown[] = []
      private readonly name: string
      constructor(name: string) {
        this.name = name
      }
      connect(node: unknown) {
        events.push(`connect:${this.name}`)
        this.connections.push(node)
        return node
      }
    }
    class FakeContext implements StemPreviewAudioContext {
      currentTime = 10
      state: AudioContextState = 'running'
      destination = destination
      gains: FakeGain[] = []
      sources: FakeSource[] = []
      closeCalls = 0
      createGain() {
        const gain = new FakeGain()
        this.gains.push(gain)
        return gain
      }
      createMediaElementSource(media: { currentTime: number; volume: number }) {
        const source = new FakeSource(media === main ? 'instrumental' : 'vocals')
        this.sources.push(source)
        return source
      }
      resume() {
        events.push('resume')
        return Promise.resolve()
      }
      close() {
        this.closeCalls += 1
        events.push('close')
        return Promise.resolve()
      }
    }
    const main = { currentTime: 11, volume: 0.3, play: () => Promise.resolve(), pause: () => events.push('main-pause') }
    let guideClock = 7
    let resolveMain!: () => void
    let resolveGuide!: () => void
    const guide = {
      get currentTime() { return guideClock },
      set currentTime(value: number) { guideClock = value; events.push(`guide-time:${value}`) },
      volume: 0.6,
      play: () => { events.push('guide-play'); return new Promise<void>((resolve) => { resolveGuide = resolve }) },
      pause: () => events.push('guide-pause'),
    }
    main.play = () => { events.push('main-play'); return new Promise<void>((resolve) => { resolveMain = resolve }) }
    const context = new FakeContext()
    const graph = createStemPreviewGraph(main, guide, 0.15, () => context)

    expect(context.sources).toHaveLength(2)
    expect(context.sources[0].connections[0]).toBe(context.gains[0])
    expect(context.sources[1].connections[0]).toBe(context.gains[1])
    expect(context.gains[0].connections[0]).toBe(destination)
    expect(context.gains[1].connections[0]).toBe(destination)
    expect(context.gains[0].gain.value).toBe(1)
    expect(context.gains[1].gain.value).toBe(0.15)
    expect(main.volume).toBe(1)
    expect(guide.volume).toBe(1)

    const clocks = [main.currentTime, guide.currentTime]
    updateStemPreviewGain(graph, 0)
    updateStemPreviewGain(graph, 0.4)
    expect(context.gains[1].gain.value).toBe(0.4)
    expect(events.slice(2, 8)).toEqual([
      'cancel:10', 'set:0.15:10', 'ramp:0:10.015',
      'cancel:10', 'set:0:10', 'ramp:0.4:10.015',
    ])
    expect([main.currentTime, guide.currentTime]).toEqual(clocks)
    expect(main.volume).toBe(1)
    expect(guide.volume).toBe(1)

    const playback = playStemPreview(graph, main, guide)
    await Promise.resolve()
    expect(events.slice(-4)).toEqual(['resume', 'guide-time:11', 'main-play', 'guide-play'])
    expect(guide.currentTime).toBe(11)
    resolveMain()
    resolveGuide()
    await playback
    closeStemPreviewGraph(graph)
    closeStemPreviewGraph(graph)
    expect(context.closeCalls).toBe(1)
  })

  it('closes a partially built audio graph when construction fails', () => {
    let closeCalls = 0
    const context = {
      currentTime: 0,
      state: 'running' as AudioContextState,
      destination: {},
      createGain: () => ({
        gain: {
          value: 0,
          cancelScheduledValues: () => {},
          setValueAtTime: () => {},
          linearRampToValueAtTime: () => {},
        },
        connect: () => undefined,
      }),
      createMediaElementSource: () => { throw new Error('source failed') },
      resume: () => Promise.resolve(),
      close: () => { closeCalls += 1; return Promise.resolve() },
    }
    const main = { currentTime: 0, volume: 0, play: () => Promise.resolve(), pause: () => {} }
    const guide = { currentTime: 0, volume: 0, play: () => Promise.resolve(), pause: () => {} }
    expect(() => createStemPreviewGraph(main, guide, 0.15, () => context)).toThrow('source failed')
    expect(closeCalls).toBe(1)
  })

  it('renders selected colors, font, position and custom preview', () => {
    const html = renderToStaticMarkup(<Preview project={project} current={0} currentWord={1} timeMs={2500} customUrl="/api/jobs/1/karaoke/background?revision=2" />)
    expect(html).toContain('#abcdef')
    expect(html).toContain('#112233')
    expect(html).toContain('--karaoke-sans')
    expect(html).toContain('>Song</small>')
    expect(html.match(/font-family:var\(--karaoke-sans\)/g)).toHaveLength(4)
    expect(html.match(/font-size:2.5cqw/g)).toHaveLength(1)
    expect(html.match(/font-size:1.40625cqw/g)).toHaveLength(1)
    expect(html.match(/font-size:3.5416667cqw/g)).toHaveLength(1)
    expect(html.match(/font-size:1.9791667cqw/g)).toHaveLength(1)
    expect(html.match(/max-width:83.3333333%/g)).toHaveLength(4)
    expect(html).toContain('url(/api/jobs/1/karaoke/background?revision=2)')
    expect(html).toContain('rgba(8, 6, 10, .43)')
    const gapHtml = renderToStaticMarkup(<Preview project={project} current={-1} currentWord={-1} timeMs={7500} customUrl="/api/jobs/1/karaoke/background?revision=2" />)
    expect(gapHtml).not.toContain('♪')
  })

})
