<script setup>
import { i18n } from '../i18n'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { hasCitationData, citedFactIdsSet, markCitedValues } from '../utils/aiFacts'
import { prefersReducedMotion } from '../composables/useAiReveal'
import { useSummaryLang } from '../composables/useSummaryLang'
import { useAsyncWatch } from '../composables/useAsync'
import {
  getGrowthReading, regenerateGrowthReading, getQualityReading, regenerateQualityReading,
} from '../api/endpoints'
import RegenerateButton from './RegenerateButton.vue'
import AssistantFace from './AssistantFace.vue'
import Eli5InkText from './Eli5InkText.vue'

const props = defineProps({
  kind: { type: String, default: 'growth', validator: (v) => ['growth', 'quality'].includes(v) },
})
const API = {
  growth: { get: getGrowthReading, regen: regenerateGrowthReading, path: '/api/narratives/growth-reading/regenerate' },
  quality: { get: getQualityReading, regen: regenerateQualityReading, path: '/api/narratives/quality-reading/regenerate' },
}
const api = API[props.kind] || API.growth
const emit = defineEmits(['update:available'])
const { t } = useI18n()
const { effective: summaryLang } = useSummaryLang()

const { data: narrative, loading } = useAsyncWatch(
  () => [summaryLang.value, i18n.global.locale.value],
  ([lang]) => api.get(lang),
  { optional: true },
)
watch([loading, narrative], ([isLoading, n]) => {
  if (!isLoading) emit('update:available', !!n)
}, { immediate: true })

const root = ref(null)
const shown = ref(prefersReducedMotion())
const revealing = ref(false)
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function reveal() {
  shown.value = true
  if (prefersReducedMotion()) return
  revealing.value = true
  await sleep(1900)
  revealing.value = false
}

let io = null
onMounted(() => {
  if (shown.value || typeof IntersectionObserver === 'undefined') {
    shown.value = true
    return
  }
  io = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) {
      io.disconnect()
      io = null
      reveal()
    }
  }, { threshold: 0.4 })
  if (root.value) io.observe(root.value)
})
onBeforeUnmount(() => io?.disconnect())

const faceState = ref('idle')
const facePhase = computed(() => (faceState.value === 'running' ? 'reasoning' : faceState.value === 'error' ? 'error' : 'idle'))

async function doRegenerate() {
  await api.regen(summaryLang.value)
  narrative.value = await api.get(summaryLang.value)
  if (io) {
    io.disconnect()
    io = null
  }
  await reveal()
}

const blocks = computed(() => {
  const n = narrative.value
  if (!n) return []
  const text = (n.content || '').trim()
  if (!text) return []
  const factJson = n.fact_json
  const cited = hasCitationData(factJson)
    ? (factJson.numbered_facts || []).filter((f) => f && citedFactIdsSet(factJson).has(f.id))
    : []
  return [markCitedValues(text, cited, factJson?.literal_terms || [])]
})

const AI_TRANSLATION_NOTE = { ja: 'AI翻訳・参考情報です', ko: 'AI 번역, 참고용입니다' }
const SUMMARY_LANG_NATIVE_LABEL = { ja: '日本語', ko: '한국어' }
const note = computed(() => {
  const n = narrative.value
  if (!n) return ''
  const requested = summaryLang.value
  const actual = n.lang
  if (actual && ['ja', 'ko'].includes(requested) && actual !== requested) {
    return t('eli5.aiCard.summaryLangFallbackNote', {
      requested: SUMMARY_LANG_NATIVE_LABEL[requested],
      actual: t(actual === 'en' ? 'eli5.aiCard.langNameEn' : 'eli5.aiCard.langNameZhTW'),
    })
  }
  return AI_TRANSLATION_NOTE[actual] || ''
})
</script>

<template>
  <aside v-show="blocks.length" ref="root" class="eli5-chart-reading" :aria-label="t('eli5.chartReading.label')">
    <div class="eli5-chart-reading__head">
      <AssistantFace class="eli5-chart-reading__face" :phase="facePhase" :chunk="0" :size="28" />
      <span class="eli5-chart-reading__label">{{ t('eli5.chartReading.label') }}</span>
      <RegenerateButton
        :api-path="api.path"
        :regenerate-fn="doRegenerate"
        @update:state="(v) => (faceState = v)"
      />
    </div>
    <div class="eli5-chart-reading__body" :class="{ 'eli5-chart-reading__body--hidden': !shown }">
      <Eli5InkText :blocks="blocks" :revealing="revealing" tag="p" />
      <p v-if="note" class="eli5-chart-reading__note">{{ note }}</p>
    </div>
  </aside>
</template>

<style scoped>
.eli5-chart-reading {
  background: var(--e-ai-bg);
  border: 1px solid var(--e-ai-line);
  border-radius: 12px;
  padding: 14px 16px 16px;
  align-self: start;
}
.eli5-chart-reading__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.eli5-chart-reading__face {
  flex: none;
}
.eli5-chart-reading__label {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--e-ai-ink);
}
.eli5-chart-reading__head :deep(button) {
  margin-left: auto;
}
.eli5-chart-reading__body--hidden {
  visibility: hidden;
}
:deep(.eli5-ink-text) {
  margin: 0;
  font-family: var(--e-font-text);
  font-size: 14px;
  line-height: 1.75;
  color: var(--e-ink);
  text-wrap: pretty;
}
:deep(.eli5-ink-text b) {
  font-weight: 700;
  color: inherit;
  background-image: linear-gradient(180deg, transparent 62%, var(--e-ai-glow) 62%, var(--e-ai-glow) 88%, transparent 88%);
}
.eli5-chart-reading__note {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--e-faint);
}
</style>
