import client from './client'
import { i18n } from '../i18n'

export const listCustomers = (params) => client.get('/customers', params)
export const getCustomer = (id) => client.get(`/customers/${encodeURIComponent(id)}`)
export const getCustomerTrend = (id, metric, periods = 18) =>
  client.get(`/customers/${encodeURIComponent(id)}/trend`, { metric, periods })
export const getCustomerReports = (id) => client.get(`/customers/${encodeURIComponent(id)}/reports`)
export const getCustomerThresholds = (id) => client.get(`/customers/${encodeURIComponent(id)}/thresholds`)
export const getQuadrant = (period) => client.get('/quadrant', { period })
export const getSignals = (limit = 3) => client.get('/signals', { limit, lang: lang() })
export const getSignal = (id) => client.get(`/signals/${id}`, { lang: lang() })
export const getReport = (reportId) => client.get(`/reports/${reportId}`)
export const getReportModel = (reportId, model) =>
  client.get(`/reports/${reportId}/model/${encodeURIComponent(model)}`)
export const getModelSales = (id, model) =>
  client.get(`/customers/${encodeURIComponent(id)}/models/${encodeURIComponent(model)}/sales`)

export const getEli5QaOverview = () => client.get('/eli5/qa/overview', { lang: lang() })
export const getEli5GrowthMatrix = () => client.get('/eli5/growth-matrix')
export const getEli5ModelMatrix = () => client.get('/eli5/qa/model-matrix')
export const getEli5QaCustomer = (id) => client.get(`/eli5/qa/customers/${encodeURIComponent(id)}`, { lang: lang() })
export const getCustomerEli5 = (id) => client.get(`/customers/${encodeURIComponent(id)}/eli5`, { lang: lang() })
export const getChainEvidence = (id, chain) => client.get(`/customers/${encodeURIComponent(id)}/eli5/evidence/${encodeURIComponent(chain)}`)
export const getCustomerOdm = (id) => client.get(`/customers/${encodeURIComponent(id)}/odm`)
export const getOdmPipeline = () => client.get('/odm/pipeline')
export const getCustomerYoy3mma = (id, months = 18) =>
  client.get(`/customers/${encodeURIComponent(id)}/yoy-3mma`, { months })
export const getPortfolioYoy3mma = (months = 18) => client.get('/portfolio/yoy-3mma', { months })
export const getCustomerLeadingIndicators = (id) => client.get(`/customers/${encodeURIComponent(id)}/leading-indicators`)

export const getCustomerServiceTicketTrend = (id, months = 6) =>
  client.get(`/customers/${encodeURIComponent(id)}/service-tickets/monthly-by-category`, { months })

const lang = () => (i18n.global.locale.value === 'zh-CN' ? 'zh-TW' : i18n.global.locale.value)

export const getTodayFocusNarrative = (langOverride) =>
  client.get('/narratives/today', { lang: langOverride ?? lang() })
export const getGrowthReading = (langOverride) =>
  client.get('/narratives/growth-reading', { lang: langOverride ?? lang() })
export const getQualityReading = (langOverride) =>
  client.get('/narratives/quality-reading', { lang: langOverride ?? lang() })
export const getHomeCarousel = (langOverride) =>
  client.get('/narratives/home-carousel', { lang: langOverride ?? lang() })
export const getCustomerNarrative = (id, narrativeType, langOverride) =>
  client.get(`/customers/${encodeURIComponent(id)}/narrative`, {
    lang: langOverride ?? lang(),
    ...(narrativeType ? { type: narrativeType } : {}),
  })
export const getCustomerNarratives = (id) =>
  client.get(`/customers/${encodeURIComponent(id)}/narratives`, { lang: lang() })

export const regenerateTodayFocusNarrative = (langOverride) =>
  client.post(`/narratives/today/regenerate?lang=${encodeURIComponent(langOverride ?? lang())}`)
export const regenerateGrowthReading = (langOverride) =>
  client.post(`/narratives/growth-reading/regenerate?lang=${encodeURIComponent(langOverride ?? lang())}`)
export const regenerateQualityReading = (langOverride) =>
  client.post(`/narratives/quality-reading/regenerate?lang=${encodeURIComponent(langOverride ?? lang())}`)
export const regenerateCustomerNarrative = (id, narrativeType, langOverride) =>
  client.post(
    `/customers/${encodeURIComponent(id)}/narrative/regenerate?lang=${encodeURIComponent(langOverride ?? lang())}` +
      (narrativeType ? `&type=${encodeURIComponent(narrativeType)}` : ''),
  )

export const getClueQa = (id, chainKey, questionId) =>
  client.get(
    `/customers/${encodeURIComponent(id)}/clue-qa/${encodeURIComponent(chainKey)}/${encodeURIComponent(questionId)}`,
    { lang: lang() },
  )
export const regenerateClueQa = (id, chainKey, questionId) =>
  client.post(
    `/customers/${encodeURIComponent(id)}/clue-qa/${encodeURIComponent(chainKey)}/${encodeURIComponent(questionId)}/regenerate?lang=${encodeURIComponent(lang())}`,
  )
