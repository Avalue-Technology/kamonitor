import { computed, ref } from 'vue'
import { i18n } from '../i18n'

const override = ref(null)

export function useSummaryLang() {
  const effective = computed(() => {
    const v = override.value ?? i18n.global.locale.value
    return v === 'zh-CN' ? 'zh-TW' : v
  })
  function setOverride(lang) {
    override.value = lang
  }
  function clearOverride() {
    override.value = null
  }
  return { override, effective, setOverride, clearOverride }
}
