import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Preview, SearchPanel } from './components/KaraokeStudio'
import type { KaraokeProject } from './karaoke'

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
