import { describe, expect, it } from 'vitest'
import { activeLine, activeWord, editLineText, lineIntervals, shiftLine, sortLines, wordIntervals, type LyricLine } from './karaoke'

const line: LyricLine = {
  text: 'One two', start_ms: 1000, end_ms: 3000,
  words: [{ text: 'One ', start_ms: 1000, end_ms: 1800 }, { text: 'two', start_ms: 1800, end_ms: 3000 }],
}

describe('karaoke timing helpers', () => {
  it('selects the active line with an offset', () => {
    expect(activeLine([line, { ...line, start_ms: 4000 }], 900, 200)).toBe(-1)
    expect(activeLine([line, { ...line, start_ms: 4000 }], 1300, 200)).toBe(0)
  })
  it('shifts line and provider word timings together', () => {
    const shifted = shiftLine(line, 100)
    expect(shifted.start_ms).toBe(1100)
    expect(shifted.words[1].start_ms).toBe(1900)
  })
  it('advances through implicit word ends and respects line gaps', () => {
    expect(wordIntervals(line, 3000, 4000)[0].end).toBe(1800)
    expect(activeWord(line, 3000, 2200, 4000)).toBe(1)
    expect(lineIntervals([{ ...line, end_ms: 1200 }, { ...line, start_ms: 3000, end_ms: 4000 }], 4000)).toHaveLength(2)
  })
  it('does not offset terminal implicit line and word endpoints twice', () => {
    const finalLine = { ...line, end_ms: null, words: [{ text: 'One ', start_ms: 1000, end_ms: null }, { text: 'two', start_ms: 1800, end_ms: null }] }
    expect(lineIntervals([finalLine], 5000, 500)).toEqual([{ start: 1500, end: 5000, index: 0 }])
    expect(wordIntervals(finalLine, 5000, 5000, 500).at(-1)?.end).toBe(5000)
    expect(lineIntervals([finalLine], 5000, -500)).toEqual([{ start: 500, end: 5000, index: 0 }])
    expect(wordIntervals(finalLine, 5000, 5000, -500).at(-1)?.end).toBe(5000)
  })
  it('sorts edited lines immediately', () => {
    expect(sortLines([{ ...line, start_ms: 3000 }, line ])[0].start_ms).toBe(1000)
  })
  it('invalidates provider word timings when text changes', () => {
    expect(editLineText(line, 'Changed').words).toEqual([])
  })
})
