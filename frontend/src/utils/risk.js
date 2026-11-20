import { i18n } from '../i18n'

const RISK_LABEL_KEY = { G: 'common.riskNormal', Y: 'common.riskAttention', R: 'common.riskCritical' }

export function riskClass(risk) {
  if (risk === 'R') return 'risk-r'
  if (risk === 'Y') return 'risk-y'
  if (risk === 'G') return 'risk-g'
  return 'risk-none'
}

export function riskLabel(risk) {
  const key = RISK_LABEL_KEY[risk]
  return key ? i18n.global.t(key) : i18n.global.t('common.riskUnknown')
}

const RANK = { R: 2, Y: 1, G: 0 }

export function worseRisk(a, b) {
  if (!a) return b || null
  if (!b) return a
  return RANK[a] >= RANK[b] ? a : b
}
