
import { i18n } from '../i18n'

const DOMAIN_META = {
  sales: 'aiFacts.domain.sales',
  quality: 'aiFacts.domain.quality',
  opportunity: 'aiFacts.domain.opportunity',
  service: 'aiFacts.domain.service',
  odm: 'aiFacts.domain.odm',
  signal: 'aiFacts.domain.signal',
  portfolio: 'aiFacts.domain.portfolio',
  other: 'aiFacts.domain.other',
}

export function domainLabel(domain) {
  if (domain in DOMAIN_META) return i18n.global.t(DOMAIN_META[domain])
  return i18n.global.t('aiFacts.domainUnclassified', {
    domain: domain || i18n.global.t('aiFacts.domainUnclassifiedNone'),
  })
}

export function groupFactsByDomain(numberedFacts, citedIds) {
  const ids = citedIds instanceof Set ? citedIds : new Set()
  const byDomain = new Map()
  for (const f of numberedFacts || []) {
    const domain = f && f.domain ? f.domain : 'other'
    if (!byDomain.has(domain)) byDomain.set(domain, { domain, label: domainLabel(domain), cited: [], uncited: [] })
    const bucket = byDomain.get(domain)
    if (ids.has(f.id)) bucket.cited.push(f)
    else bucket.uncited.push(f)
  }
  return [...byDomain.values()].sort((a, b) => b.cited.length - a.cited.length || a.label.localeCompare(b.label, 'zh-Hant'))
}

export function hasCitationData(factJson) {
  return Array.isArray(factJson && factJson.cited_fact_ids)
}

export function citedFactIdsSet(factJson) {
  const arr = (factJson && factJson.cited_fact_ids) || []
  return new Set(arr)
}

function classifyValueType(value) {
  if (value.includes('美元') || value.includes('$')) return 'amount'
  if (value.includes('%') || value.includes('個百分點') || value.includes('个百分点')) return 'percent'
  return null
}

const MAX_LITERAL_TERM_LENGTH = 20

export function isModelCodeLike(term) {
  if (typeof term !== 'string') return false
  if (term.length < 2 || term.length > MAX_LITERAL_TERM_LENGTH) return false
  if (!/^[\x20-\x7e]+$/.test(term)) return false
  if (/\s/.test(term)) return false
  return /[0-9-]/.test(term)
}

export function markCitedValues(text, citedFacts, literalTerms) {
  if (!text) return [{ text: text || '', type: null }]

  const MAX_VALUE_LENGTH = 20
  const valueCandidates = (citedFacts || [])
    .filter(
      (f) =>
        f &&
        typeof f.value === 'string' &&
        f.value.length >= 2 &&
        f.value.length <= MAX_VALUE_LENGTH &&
        /\d/.test(f.value),
    )
    .map((f) => ({ value: f.value, type: classifyValueType(f.value), label: f.label }))
    .filter((c) => c.type !== null)

  const codeCandidates = (literalTerms || [])
    .filter((t) => isModelCodeLike(t))
    .map((t) => ({ value: t, type: 'model', label: undefined }))

  const candidates = [...valueCandidates, ...codeCandidates].sort((a, b) => b.value.length - a.value.length)

  const covered = new Array(text.length).fill(false)
  const matches = []
  for (const c of candidates) {
    const v = c.value
    let from = 0
    while (from <= text.length - v.length) {
      const idx = text.indexOf(v, from)
      if (idx === -1) break
      const end = idx + v.length
      let overlap = false
      for (let i = idx; i < end; i++) {
        if (covered[i]) {
          overlap = true
          break
        }
      }
      if (!overlap) {
        for (let i = idx; i < end; i++) covered[i] = true
        matches.push({ start: idx, end, label: c.label, value: v, type: c.type })
      }
      from = idx + 1
    }
  }
  matches.sort((a, b) => a.start - b.start)

  const segments = []
  let pos = 0
  for (const m of matches) {
    if (m.start > pos) segments.push({ text: text.slice(pos, m.start), type: null })
    segments.push({ text: m.value, type: m.type, label: m.label })
    pos = m.end
  }
  if (pos < text.length) segments.push({ text: text.slice(pos), type: null })
  if (segments.length === 0) segments.push({ text, type: null })
  return segments
}
