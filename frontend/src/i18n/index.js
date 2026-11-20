import { createI18n } from 'vue-i18n'
import zhTW from './locales/zh-TW.json'
import en from './locales/en.json'
import zhCN from './locales/zh-CN.json'

const STORAGE_KEY = 'kam-locale'

function initialLocale() {
  try {
    return localStorage.getItem(STORAGE_KEY) || 'zh-TW'
  } catch (e) {
    return 'zh-TW'
  }
}

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale(),
  fallbackLocale: 'zh-TW',
  missingWarn: import.meta.env.DEV,
  fallbackWarn: import.meta.env.DEV,
  messages: {
    'zh-TW': zhTW,
    'zh-CN': zhCN,
    en,
  },
})

export function setLocale(locale) {
  i18n.global.locale.value = locale
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch (e) {
  }
}

export default i18n
