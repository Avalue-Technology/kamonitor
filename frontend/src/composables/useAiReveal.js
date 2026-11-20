import { ref } from 'vue'

export function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export function useAiReveal() {
  const facePhase = ref('idle')
  const faceChunk = ref(0)

  async function flourish({ ticks = 4, tickMs = 140 } = {}) {
    facePhase.value = 'speaking'
    for (let i = 0; i < ticks; i++) {
      faceChunk.value++
      await sleep(tickMs)
    }
    facePhase.value = 'idle'
  }

  async function typewriter(fullText, { onUpdate, step = 3, stepMs = 28 } = {}) {
    if (prefersReducedMotion()) {
      onUpdate(fullText)
      faceChunk.value++
      facePhase.value = 'idle'
      return
    }
    facePhase.value = 'speaking'
    let i = 0
    while (i < fullText.length) {
      i = Math.min(fullText.length, i + step)
      onUpdate(fullText.slice(0, i))
      faceChunk.value++
      await sleep(stepMs)
    }
    facePhase.value = 'idle'
  }

  return { facePhase, faceChunk, flourish, typewriter }
}
