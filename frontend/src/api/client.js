import { i18n } from '../i18n'

function localeHeader() {
  return { 'X-Locale': i18n.global.locale.value }
}

const BASE = '/api'

class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function extractDetail(res) {
  try {
    const data = await res.clone().json()
    if (data && typeof data.detail === 'string' && data.detail) return data.detail
  } catch (e) {
  }
  return null
}

async function get(path, params) {
  let url = BASE + path
  if (params && Object.keys(params).length) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null),
    ).toString()
    if (qs) url += '?' + qs
  }
  let res
  try {
    res = await fetch(url, { headers: localeHeader() })
  } catch (e) {
    throw new ApiError(i18n.global.t('api.networkError', { path }), 0)
  }
  if (!res.ok) {
    const detail = await extractDetail(res)
    throw new ApiError(detail || i18n.global.t('api.responseError', { path, status: res.status }), res.status)
  }
  return res.json()
}

async function post(path, body) {
  const url = BASE + path
  let res
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: body !== undefined ? { 'Content-Type': 'application/json', ...localeHeader() } : localeHeader(),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (e) {
    throw new ApiError(i18n.global.t('api.networkError', { path }), 0)
  }
  if (!res.ok) {
    const detail = await extractDetail(res)
    throw new ApiError(detail || i18n.global.t('api.responseError', { path, status: res.status }), res.status)
  }
  return res.json()
}

export { ApiError }
export default { get, post }
