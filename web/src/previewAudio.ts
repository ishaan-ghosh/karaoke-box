export type StemPreviewMedia = {
  currentTime: number
  volume: number
  play: () => Promise<void>
  pause: () => void
}

export type StemPreviewAudioParam = {
  value: number
  cancelScheduledValues: (startTime: number) => void
  setValueAtTime: (value: number, startTime: number) => void
  linearRampToValueAtTime: (value: number, endTime: number) => void
}

export type StemPreviewGain = {
  gain: StemPreviewAudioParam
  connect: (destination: unknown) => unknown
}

export type StemPreviewSource = {
  connect: (destination: unknown) => unknown
}

export type StemPreviewAudioContext = {
  currentTime: number
  state: AudioContextState
  destination: unknown
  createGain: () => StemPreviewGain
  createMediaElementSource: (media: StemPreviewMedia) => StemPreviewSource
  resume: () => Promise<void>
  close: () => Promise<void>
}

export type StemPreviewGraph = {
  context: StemPreviewAudioContext
  instrumentalGain: StemPreviewGain
  vocalGain: StemPreviewGain
  closed: boolean
}

type AudioContextFactory = () => StemPreviewAudioContext

function browserAudioContext(): StemPreviewAudioContext {
  return new AudioContext() as unknown as StemPreviewAudioContext
}

function closeContext(context: StemPreviewAudioContext) {
  if (context.state === 'closed') return
  try {
    void Promise.resolve(context.close()).catch(() => {})
  } catch {
    // A context can reject or throw while the browser is already tearing down.
  }
}

export function createStemPreviewGraph(
  instrumental: StemPreviewMedia,
  vocals: StemPreviewMedia,
  vocalVolume: number,
  createContext: AudioContextFactory = browserAudioContext,
): StemPreviewGraph {
  const context = createContext()
  try {
    const instrumentalGain = context.createGain()
    const vocalGain = context.createGain()
    context.createMediaElementSource(instrumental).connect(instrumentalGain)
    instrumentalGain.connect(context.destination)
    context.createMediaElementSource(vocals).connect(vocalGain)
    vocalGain.connect(context.destination)
    instrumentalGain.gain.value = 1
    vocalGain.gain.value = vocalVolume
    instrumental.volume = 1
    vocals.volume = 1
    return { context, instrumentalGain, vocalGain, closed: false }
  } catch (error) {
    closeContext(context)
    throw error
  }
}

export function updateStemPreviewGain(graph: StemPreviewGraph, value: number) {
  const { context, vocalGain } = graph
  vocalGain.gain.cancelScheduledValues(context.currentTime)
  vocalGain.gain.setValueAtTime(vocalGain.gain.value, context.currentTime)
  vocalGain.gain.linearRampToValueAtTime(value, context.currentTime + 0.015)
}

export async function playStemPreview(graph: StemPreviewGraph, instrumental: StemPreviewMedia, vocals: StemPreviewMedia) {
  await graph.context.resume()
  vocals.currentTime = instrumental.currentTime
  await Promise.all([instrumental.play(), vocals.play()])
}

export function closeStemPreviewGraph(graph: StemPreviewGraph) {
  if (graph.closed) return
  graph.closed = true
  closeContext(graph.context)
}
