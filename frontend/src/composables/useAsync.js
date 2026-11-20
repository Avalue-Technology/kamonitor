import { ref, shallowRef, watch, watchEffect } from 'vue'
import { i18n } from '../i18n'

export function useAsync(fn, { optional = false, localized = false } = {}) {
  const data = shallowRef(null)
  const loading = ref(true)
  const error = ref(null)
  const notFound = ref(false)

  async function run() {
    loading.value = true
    error.value = null
    notFound.value = false
    try {
      data.value = await fn()
    } catch (e) {
      if (optional && (e.status === 404 || e.status === 400 || e.status === 0)) {
        notFound.value = true
      } else {
        error.value = e
      }
      data.value = null
    } finally {
      loading.value = false
    }
  }

  run()

  if (localized) watch(i18n.global.locale, () => run())

  return { data, loading, error, notFound, reload: run }
}

export function useAsyncWatch(source, fn, { optional = false } = {}) {
  const data = shallowRef(null)
  const loading = ref(true)
  const error = ref(null)
  const notFound = ref(false)

  watchEffect(async () => {
    const key = typeof source === 'function' ? source() : source.value
    loading.value = true
    error.value = null
    notFound.value = false
    data.value = null
    try {
      const result = await fn(key)
      data.value = result
    } catch (e) {
      if (optional && (e.status === 404 || e.status === 400 || e.status === 0)) {
        notFound.value = true
      } else {
        error.value = e
      }
    } finally {
      loading.value = false
    }
  })

  return { data, loading, error, notFound }
}
