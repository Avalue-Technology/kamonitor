
export function formatUSDCompact(value, { approx = false } = {}) {
  if (value === null || value === undefined) return '—'
  const prefix = approx ? '≈' : ''
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${prefix}$${(value / 1_000_000).toFixed(2)}M`
  if (abs >= 1_000) return `${prefix}$${(value / 1_000).toFixed(1)}K`
  return `${prefix}$${value.toFixed(0)}`
}

export function formatUSDFull(value, { approx = false } = {}) {
  if (value === null || value === undefined) return '—'
  const prefix = approx ? '≈' : ''
  return `${prefix}$${Math.round(value).toLocaleString('en-US')}`
}

export function formatPct(value, decimals = 1) {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(decimals)}%`
}

export function formatFraction(value, decimals = 2) {
  if (value === null || value === undefined) return '—'
  return `${(value * 100).toFixed(decimals)}%`
}

export function formatInt(value) {
  if (value === null || value === undefined) return '—'
  return Math.round(value).toLocaleString('en-US')
}

export function formatDate(value) {
  if (!value) return '—'
  return String(value).slice(0, 10)
}

export function formatPeriod(period) {
  if (!period) return '—'
  const s = String(period)
  return `${s.slice(0, 4)}/${s.slice(4, 6)}`
}

export function signedPct(value, decimals = 1) {
  if (value === null || value === undefined) return { text: '—', direction: 'flat' }
  const direction = value > 0 ? 'up' : value < 0 ? 'down' : 'flat'
  const sign = value > 0 ? '+' : ''
  return { text: `${sign}${value.toFixed(decimals)}%`, direction }
}

export function daysAgo(dateStr, today) {
  if (!dateStr) return null
  const d = new Date(dateStr)
  const t = today ? new Date(today) : new Date()
  return Math.round((t - d) / 86400000)
}
