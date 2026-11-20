const MAX_PROTECTED_LEN = 10
const PUNCTUATION_RE = /[。，、；：]/

export function splitNoteSegments(text) {
  if (!text) return []
  const segments = []
  const parts = text.split(/( )/)
  let precededBySpace = false
  for (const part of parts) {
    if (part === '') continue
    if (part === ' ') {
      segments.push({ text: ' ', nowrap: false })
      precededBySpace = true
      continue
    }
    if (!precededBySpace) {
      segments.push({ text: part, nowrap: false })
      precededBySpace = false
      continue
    }
    const m = PUNCTUATION_RE.exec(part)
    const cut = m ? m.index : part.length
    const head = part.slice(0, cut)
    const rest = part.slice(cut)
    if (head) {
      segments.push({ text: head, nowrap: head.length <= MAX_PROTECTED_LEN })
    }
    if (rest) {
      segments.push({ text: rest, nowrap: false })
    }
    precededBySpace = false
  }
  return segments
}
