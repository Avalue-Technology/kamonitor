<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { hasCitationData, citedFactIdsSet, markCitedValues } from '../utils/aiFacts'
import { useAiReveal } from '../composables/useAiReveal'
import { useSummaryLang } from '../composables/useSummaryLang'
import GenerationStamp from './GenerationStamp.vue'
import RegenerateButton from './RegenerateButton.vue'
import AssistantFace from './AssistantFace.vue'

const props = defineProps({
  narrative: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: Object, default: null },
  regenerateFn: { type: Function, default: null },
  regenerateApiPath: { type: String, default: '/api/customers/{erp_customer_id}/narrative/regenerate' },
  eyebrow: { type: String, default: null },
  emptyMessage: { type: String, default: null },
  emptyHint: { type: String, default: null },
})

const { t } = useI18n()
const eyebrowText = computed(() => props.eyebrow ?? t('eli5.aiCard.eyebrowDefault'))
const emptyMessageText = computed(() => props.emptyMessage ?? t('eli5.aiCard.emptyMessageDefault'))
const emptyHintText = computed(() => props.emptyHint ?? t('eli5.aiCard.emptyHintDefault'))

const { effective: summaryLang, setOverride: setSummaryLangOverride } = useSummaryLang()
const SUMMARY_LANG_OPTIONS = [
  { value: 'zh-TW', label: '中文' },
  { value: 'en', label: 'EN' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
]
function onSummaryLangChange(event) {
  setSummaryLangOverride(event.target.value)
}

const AI_TRANSLATION_NOTE = { ja: 'AI翻訳・参考情報です', ko: 'AI 번역, 참고용입니다' }
const aiTranslationNoteText = computed(() => AI_TRANSLATION_NOTE[props.narrative?.lang] || '')

const SUMMARY_LANG_NATIVE_LABEL = { ja: '日本語', ko: '한국어' }
const fallbackNoteText = computed(() => {
  const requested = summaryLang.value
  const actual = props.narrative?.lang
  if (!actual || !['ja', 'ko'].includes(requested) || actual === requested) return ''
  const actualLabel = t(actual === 'en' ? 'eli5.aiCard.langNameEn' : 'eli5.aiCard.langNameZhTW')
  return t('eli5.aiCard.summaryLangFallbackNote', {
    requested: SUMMARY_LANG_NATIVE_LABEL[requested],
    actual: actualLabel,
  })
})

const numberedFacts = computed(() => props.narrative?.fact_json?.numbered_facts || [])
const contentParagraphs = computed(() => {
  const raw = props.narrative?.content || ''
  return raw
    .split(/\n\s*\n/)
    .map((para) => para.trim())
    .filter(Boolean)
})
const citedFactsForMark = computed(() => {
  const factJson = props.narrative?.fact_json
  if (!hasCitationData(factJson)) return []
  const ids = citedFactIdsSet(factJson)
  return numberedFacts.value.filter((f) => f && ids.has(f.id))
})
const literalTermsForMark = computed(() => props.narrative?.fact_json?.literal_terms || [])
const contentSegments = computed(() =>
  contentParagraphs.value.map((para) => markCitedValues(para, citedFactsForMark.value, literalTermsForMark.value)),
)

const faceState = ref('idle')
function onFaceState(value) {
  faceState.value = value
}
const { facePhase: revealPhase, faceChunk, typewriter } = useAiReveal()
const facePhase = computed(() => {
  if (revealPhase.value === 'speaking') return 'speaking'
  if (props.loading) return 'reasoning'
  if (props.error) return 'error'
  if (faceState.value === 'running') return 'reasoning'
  if (faceState.value === 'error') return 'error'
  return 'idle'
})

const typingText = ref('')
const isTyping = ref(false)
const justRegenerated = ref(false)
watch(
  () => props.narrative,
  async (next) => {
    if (!justRegenerated.value || !next) return
    justRegenerated.value = false
    isTyping.value = true
    typingText.value = ''
    await typewriter(next.content || '', {
      onUpdate: (text) => { typingText.value = text },
    })
    isTyping.value = false
  },
)

const regenErrorMsg = ref('')
const regenErrorKind = ref('error')
function classifyRegenerateError(status) {
  if (status === 409) return 'info'
  if (status === 501) return 'notwired'
  return 'error'
}
async function doRegenerate() {
  regenErrorMsg.value = ''
  if (!props.regenerateFn) return
  justRegenerated.value = true
  try {
    await props.regenerateFn()
  } catch (e) {
    justRegenerated.value = false
    regenErrorMsg.value = e.message || t('eli5.aiCard.regenErrorDefault')
    regenErrorKind.value = classifyRegenerateError(e.status)
    throw e
  }
}
</script>

<template>
  <section class="eli5-ai-card" :aria-label="t('eli5.aiCard.ariaLabel')">
    <div class="eli5-ai-card__body">
      <AssistantFace class="eli5-ai-card__face" :phase="facePhase" :chunk="faceChunk" :size="40" />
      <div class="eli5-ai-card__main">
        <div class="eli5-ai-card__head">
          <div class="eli5-ai-card__head-left">
            <span class="eli5-ai-card__eyebrow">{{ eyebrowText }}</span>
            <select
              class="eli5-ai-card__lang-select"
              :value="summaryLang"
              :aria-label="t('eli5.aiCard.langMenuLabel')"
              @change="onSummaryLangChange"
            >
              <option v-for="opt in SUMMARY_LANG_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
            <RegenerateButton :api-path="regenerateApiPath" :regenerate-fn="doRegenerate" @update:state="onFaceState" />
          </div>
        </div>
        <p v-if="regenErrorMsg" class="eli5-ai-card__regen-msg" :class="'eli5-ai-card__regen-msg--' + regenErrorKind">{{ regenErrorMsg }}</p>

        <div v-if="loading" class="eli5-ai-card__empty">
          <p class="eli5-ai-card__empty-msg">{{ t('eli5.aiCard.loading') }}</p>
        </div>

        <div v-else-if="error" class="eli5-ai-card__empty">
          <p class="eli5-ai-card__empty-msg">{{ t('eli5.aiCard.errorMessage') }}</p>
          <p class="eli5-ai-card__empty-hint">{{ error.message }}</p>
        </div>

        <template v-else-if="narrative">
          <p v-if="isTyping" class="eli5-ai-card__text eli5-ai-card__text--typing">{{ typingText }}</p>
          <template v-else>
            <p v-for="(segments, i) in contentSegments" :key="i" class="eli5-ai-card__text"><template
              v-for="(seg, j) in segments"
              :key="j"
            ><b v-if="seg.type">{{ seg.text }}</b><template v-else>{{ seg.text }}</template></template></p>
          </template>

          <p v-if="fallbackNoteText" class="eli5-ai-card__lang-note">{{ fallbackNoteText }}</p>
          <p v-else-if="aiTranslationNoteText" class="eli5-ai-card__lang-note">{{ aiTranslationNoteText }}</p>

          <div class="eli5-ai-card__footer">
            <GenerationStamp
              :model-name="narrative.model_name"
              :generated-at="narrative.generated_at"
              :elapsed-ms="narrative.elapsed_ms"
              :fact-count="numberedFacts.length"
              :expandable="false"
            />
          </div>
        </template>

        <div v-else class="eli5-ai-card__empty">
          <p class="eli5-ai-card__empty-msg">{{ emptyMessageText }}</p>
          <p class="eli5-ai-card__empty-hint">{{ emptyHintText }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.eli5-ai-card {
  position: relative;
  padding: 22px 26px;
  border-radius: var(--e-radius);
  background: var(--e-ai-bg);
}
.eli5-ai-card__body {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}
.eli5-ai-card__face {
  flex: none;
  margin-top: 2px;
}
.eli5-ai-card__main {
  display: grid;
  gap: 10px;
  min-width: 0;
  flex: 1 1 auto;
}
.eli5-ai-card::before {
  content: '';
  position: absolute;
  inset: -1px;
  padding: 1.5px;
  border-radius: inherit;
  pointer-events: none;
  background: conic-gradient(
    from var(--e-ai-angle),
    var(--e-ai-line) 0deg 300deg,
    var(--e-ai-glow) 322deg,
    #ffffff 334deg,
    var(--e-ai-glow) 346deg,
    var(--e-ai-line) 360deg
  );
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  animation: eli5-ai-orbit 5.5s linear infinite;
}
.eli5-ai-card::after {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  pointer-events: none;
  box-shadow: 0 0 0 4px rgba(124, 99, 235, 0.06), 0 10px 30px rgba(91, 69, 201, 0.1);
}
@keyframes eli5-ai-orbit {
  to {
    --e-ai-angle: 360deg;
  }
}
@media (prefers-reduced-motion: reduce) {
  .eli5-ai-card::before {
    animation: none;
  }
}
.eli5-ai-card__head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.eli5-ai-card__head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.eli5-ai-card__eyebrow {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--e-ai-ink);
}
.eli5-ai-card__lang-select {
  font-family: inherit;
  font-size: 12px;
  color: var(--e-ai-ink);
  background: var(--e-surface);
  border: 1px solid var(--e-ai-line);
  border-radius: var(--radius-sm);
  padding: 2px 6px;
  cursor: pointer;
}
.eli5-ai-card__lang-select:focus-visible {
  outline: 2px solid var(--e-ai-ink);
  outline-offset: 1px;
}
.eli5-ai-card__lang-note {
  margin: 0;
  font-size: 12px;
  color: var(--e-faint);
}
.eli5-ai-card__text {
  margin: 0;
  font-family: var(--e-font-text);
  font-size: 16px;
  line-height: 1.75;
  color: var(--e-ink);
}
.eli5-ai-card__text + .eli5-ai-card__text {
  margin-top: 4px;
}
.eli5-ai-card__text--typing {
  white-space: pre-wrap;
}
.eli5-ai-card__text b {
  font-weight: 700;
  color: var(--e-ai-ink);
}
.eli5-ai-card__empty {
  display: grid;
  gap: 4px;
}
.eli5-ai-card__empty-msg {
  margin: 0;
  font-family: var(--e-font-text);
  font-size: 15px;
  color: var(--e-muted);
}
.eli5-ai-card__empty-hint {
  margin: 0;
  font-size: 13px;
  color: var(--e-faint);
}
.eli5-ai-card__footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 4px;
}
.eli5-ai-card__regen-msg {
  margin: 0;
  font-size: 12.5px;
}
.eli5-ai-card__regen-msg--info,
.eli5-ai-card__regen-msg--notwired {
  color: var(--e-faint);
}
.eli5-ai-card__regen-msg--error {
  color: var(--risk-r);
}
</style>
