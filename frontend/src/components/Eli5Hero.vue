<script setup>
import { i18n } from '../i18n'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { hasCitationData, citedFactIdsSet, markCitedValues } from '../utils/aiFacts'
import { prefersReducedMotion } from '../composables/useAiReveal'
import { useSummaryLang } from '../composables/useSummaryLang'
import { useAsyncWatch } from '../composables/useAsync'
import { getHomeCarousel, regenerateTodayFocusNarrative } from '../api/endpoints'
import GenerationStamp from './GenerationStamp.vue'
import RegenerateButton from './RegenerateButton.vue'
import AssistantFace from './AssistantFace.vue'
import Eli5InkText from './Eli5InkText.vue'

const props = defineProps({
  period: { type: [String, Number], default: '' },
  count: { type: Number, default: 0 },
  regenerateApiPath: { type: String, default: '/api/narratives/today/regenerate' },
})

const { t } = useI18n()

const { effective: summaryLang, setOverride: setSummaryLangOverride } = useSummaryLang()
const SUMMARY_LANG_OPTIONS = [
  { value: 'zh-TW', label: '中文' },
  { value: 'en', label: 'EN' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
]
function onLangChange(event) {
  setSummaryLangOverride(event.target.value)
}

const { data: carousel, loading, error } = useAsyncWatch(
  () => [summaryLang.value, i18n.global.locale.value],
  ([lang]) => getHomeCarousel(lang),
  { optional: true },
)

const slides = computed(() => {
  if (!carousel.value) return []
  return [
    { kind: 'focus', narrative: carousel.value.today_focus },
    ...carousel.value.customers.map((c) => ({ kind: 'customer', customer: c })),
  ]
})
const totalSlides = computed(() => slides.value.length)
const currentIndex = ref(0)
const currentSlide = computed(() => slides.value[currentIndex.value] || null)
watch(totalSlides, (n) => {
  if (n > 0 && currentIndex.value >= n) currentIndex.value = 0
})

const AUTO_ADVANCE_MS = 30000
const elapsedMs = ref(0)
const hovered = ref(false)
const focusedWithin = ref(false)
const regenerating = ref(false)
const transitioning = ref(false)
const paused = computed(() => hovered.value || focusedWithin.value || regenerating.value || totalSlides.value <= 1)
const RING_C = 2 * Math.PI * 13
const progressPct = computed(() => Math.min(100, (elapsedMs.value / AUTO_ADVANCE_MS) * 100))

let tickTimer = null
function startTicking() {
  stopTicking()
  tickTimer = setInterval(() => {
    if (paused.value || transitioning.value) return
    elapsedMs.value += 100
    if (elapsedMs.value >= AUTO_ADVANCE_MS) {
      goTo(currentIndex.value + 1)
    }
  }, 100)
}
function stopTicking() {
  if (tickTimer) {
    clearInterval(tickTimer)
    tickTimer = null
  }
}
startTicking()
onUnmounted(stopTicking)

const fadingOut = ref(false)

const contentEl = ref(null)
const measureEl = ref(null)
const reservedHeight = ref(0)
const contentWidth = ref(0)
let contentObserver = null
function measureAll() {
  const root = measureEl.value
  if (!root || !contentWidth.value) return
  let max = 0
  for (const el of root.children) max = Math.max(max, el.offsetHeight)
  if (max) reservedHeight.value = max
}
onMounted(() => {
  contentObserver = new ResizeObserver(([entry]) => {
    const w = Math.round(entry.contentRect.width)
    if (Math.abs(w - contentWidth.value) > 1) {
      contentWidth.value = w
      nextTick(measureAll)
    }
  })
  if (contentEl.value) contentObserver.observe(contentEl.value)
  document.fonts?.ready?.then(() => nextTick(measureAll))
})
onUnmounted(() => contentObserver?.disconnect())
watch([slides, () => summaryLang.value], () => nextTick(measureAll), { flush: 'post' })
const revealing = ref(false)
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function goTo(rawIndex) {
  const total = totalSlides.value
  if (total <= 0 || transitioning.value) return
  const next = ((rawIndex % total) + total) % total
  if (next === currentIndex.value) return
  elapsedMs.value = 0
  transitioning.value = true
  if (prefersReducedMotion()) {
    currentIndex.value = next
    transitioning.value = false
    return
  }
  fadingOut.value = true
  await sleep(250)
  currentIndex.value = next
  fadingOut.value = false
  revealing.value = true
  await sleep(1900)
  revealing.value = false
  transitioning.value = false
}

const faceState = ref('idle')
function onFaceState(value) {
  faceState.value = value
}
const facePhase = computed(() => {
  if (loading.value) return 'reasoning'
  if (error.value) return 'error'
  if (faceState.value === 'running') return 'reasoning'
  if (faceState.value === 'error') return 'error'
  return 'idle'
})

const regenErrorMsg = ref('')
const regenErrorKind = ref('error')
function classifyRegenerateError(status) {
  if (status === 409) return 'info'
  if (status === 501) return 'notwired'
  return 'error'
}
async function doRegenerate() {
  regenErrorMsg.value = ''
  regenerating.value = true
  elapsedMs.value = 0
  if (currentIndex.value !== 0) currentIndex.value = 0
  const reduceMotion = prefersReducedMotion()
  if (!reduceMotion) fadingOut.value = true
  try {
    await regenerateTodayFocusNarrative(summaryLang.value)
    carousel.value = await getHomeCarousel(summaryLang.value)
    faceState.value = 'idle'
    if (!reduceMotion) {
      fadingOut.value = false
      revealing.value = true
      await sleep(1900)
      revealing.value = false
    }
  } catch (e) {
    fadingOut.value = false
    regenErrorMsg.value = e.message || t('eli5.hero.regenErrorDefault')
    regenErrorKind.value = classifyRegenerateError(e.status)
    throw e
  } finally {
    regenerating.value = false
  }
}

function sentencesOf(content) {
  return (content || '')
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)
    .flatMap((p) => p.split(/(?<=。)/).map((s) => s.trim()).filter(Boolean))
}
function buildBlocks(narrative, { bySentence = false } = {}) {
  if (!narrative) return []
  const texts = bySentence ? sentencesOf(narrative.content) : [(narrative.content || '').trim()].filter(Boolean)
  const factJson = narrative.fact_json
  const cited = hasCitationData(factJson)
    ? (factJson.numbered_facts || []).filter((f) => f && citedFactIdsSet(factJson).has(f.id))
    : []
  const literalTerms = factJson?.literal_terms || []
  return texts.map((text) => markCitedValues(text, cited, literalTerms))
}

const focusBlocks = computed(() => buildBlocks(currentSlide.value?.narrative, { bySentence: true }))
const qualityBlocks = computed(() => buildBlocks(currentSlide.value?.customer?.quality))
const salesBlocks = computed(() => buildBlocks(currentSlide.value?.customer?.sales))

const AI_TRANSLATION_NOTE = { ja: 'AI翻訳・参考情報です', ko: 'AI 번역, 참고용입니다' }
const SUMMARY_LANG_NATIVE_LABEL = { ja: '日本語', ko: '한국어' }
function fallbackNoteFor(narrative) {
  if (!narrative) return ''
  const requested = summaryLang.value
  const actual = narrative.lang
  if (!actual || !['ja', 'ko'].includes(requested) || actual === requested) return ''
  const actualLabel = t(actual === 'en' ? 'eli5.aiCard.langNameEn' : 'eli5.aiCard.langNameZhTW')
  return t('eli5.aiCard.summaryLangFallbackNote', {
    requested: SUMMARY_LANG_NATIVE_LABEL[requested],
    actual: actualLabel,
  })
}
function translationNoteFor(narrative) {
  return AI_TRANSLATION_NOTE[narrative?.lang] || ''
}
function noteFor(narrative) {
  return fallbackNoteFor(narrative) || translationNoteFor(narrative)
}
const focusNote = computed(() => noteFor(currentSlide.value?.narrative))
const qualityNote = computed(() => noteFor(currentSlide.value?.customer?.quality))
const salesNote = computed(() => noteFor(currentSlide.value?.customer?.sales))

const measureSlides = computed(() =>
  slides.value.map((sl) =>
    sl.kind === 'focus'
      ? { kind: 'focus', narrative: sl.narrative, blocks: buildBlocks(sl.narrative, { bySentence: true }), note: noteFor(sl.narrative) }
      : {
          kind: 'customer',
          customer: sl.customer,
          qBlocks: buildBlocks(sl.customer.quality),
          qNote: noteFor(sl.customer.quality),
          sBlocks: buildBlocks(sl.customer.sales),
          sNote: noteFor(sl.customer.sales),
        },
  ),
)
</script>

<template>
  <section
    class="eli5-hero"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
    @focusin="focusedWithin = true"
    @focusout="focusedWithin = false"
  >
    <div class="eli5-hero__inner">
      <div class="eli5-hero__title">
        <h2 class="eli5-hero__h2">{{ t('eli5.hero.title') }}</h2>
        <span class="eli5-pill eli5-pill--accent">{{ t('eli5.hero.pill') }}</span>
        <span class="eli5-hero__meta num">{{ t('eli5.hero.meta', { period: props.period, count: props.count }) }}</span>
      </div>
      <div class="eli5-hero__control-row">
        <div class="eli5-hero__control-left">
          <div class="eli5-eyebrow">{{ t('eli5.hero.aiEyebrow') }}</div>
          <span class="eli5-hero__sep">·</span>
          <select
            class="eli5-hero__lang-select"
            :value="summaryLang"
            :aria-label="t('eli5.hero.langMenuLabel')"
            @change="onLangChange"
          >
            <option v-for="opt in SUMMARY_LANG_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
          </select>
          <RegenerateButton :api-path="regenerateApiPath" :regenerate-fn="doRegenerate" @update:state="onFaceState" />
          <div class="eli5-hero__nav">
          <button
            type="button"
            class="eli5-hero__nav-btn"
            :aria-label="t('eli5.hero.prevSlide')"
            @click="goTo(currentIndex - 1)"
          >‹</button>
          <span class="eli5-hero__indicator num">{{ currentIndex + 1 }} / {{ totalSlides }}</span>
          <button
            type="button"
            class="eli5-hero__nav-btn eli5-hero__nav-btn--next"
            :aria-label="t('eli5.hero.nextSlide')"
            @click="goTo(currentIndex + 1)"
          >›<svg class="eli5-hero__ring" viewBox="0 0 30 30" aria-hidden="true"><circle
            cx="15" cy="15" r="13" :style="{ strokeDashoffset: RING_C * (1 - progressPct / 100) }" /></svg></button>
          </div>
        </div>
      </div>

      <div class="eli5-hero__body">
        <AssistantFace class="eli5-hero__face" :phase="facePhase" :chunk="0" :size="48" />
        <div
          ref="contentEl"
          class="eli5-hero__content"
          :class="{ 'eli5-hero__content--fading': fadingOut }"
          :style="reservedHeight ? { minHeight: reservedHeight + 'px' } : null"
        >
          <template v-if="loading && !carousel">
            <p class="eli5-hero__text eli5-hero__text--empty">{{ t('eli5.hero.loading') }}</p>
          </template>
          <template v-else-if="error">
            <p class="eli5-hero__text eli5-hero__text--empty">{{ t('eli5.hero.errorMessage') }}</p>
            <div class="eli5-hero__hint">{{ error.message }}</div>
          </template>
          <template v-else-if="currentSlide && currentSlide.kind === 'focus'">
            <template v-if="!currentSlide.narrative">
              <p class="eli5-hero__text eli5-hero__text--empty">{{ t('eli5.hero.emptyMessage') }}</p>
              <div class="eli5-hero__hint">{{ t('eli5.hero.emptyHint') }}</div>
            </template>
            <template v-else>
              <Eli5InkText :blocks="focusBlocks" :revealing="revealing" tag="p" />
              <p v-if="focusNote" class="eli5-hero__lang-note">{{ focusNote }}</p>
              <GenerationStamp
                :model-name="currentSlide.narrative.model_name"
                :generated-at="currentSlide.narrative.generated_at"
                :elapsed-ms="currentSlide.narrative.elapsed_ms"
                :fact-count="(currentSlide.narrative.fact_json?.numbered_facts || []).length"
                :expandable="false"
              />
            </template>
          </template>
          <template v-else-if="currentSlide && currentSlide.kind === 'customer'">
            <div class="eli5-hero__eyebrow-row">
              <RouterLink
                class="eli5-hero__customer-link"
                :to="`/eli5/customer/${currentSlide.customer.erp_customer_id}`"
              >{{ currentSlide.customer.display_name }}</RouterLink>
            </div>
            <template v-if="!currentSlide.customer.quality && !currentSlide.customer.sales">
              <p class="eli5-hero__text eli5-hero__text--empty">{{ t('eli5.hero.customerEmptyMessage') }}</p>
            </template>
            <template v-else>
              <template v-if="currentSlide.customer.quality">
                <div class="eli5-hero__slide-label">{{ t('eli5.hero.qualityLabel') }}</div>
                <Eli5InkText :blocks="qualityBlocks" :revealing="revealing" tag="p" />
                <p v-if="qualityNote" class="eli5-hero__lang-note">{{ qualityNote }}</p>
              </template>
              <template v-if="currentSlide.customer.sales">
                <div class="eli5-hero__slide-label">{{ t('eli5.hero.salesLabel') }}</div>
                <Eli5InkText :blocks="salesBlocks" :revealing="revealing" tag="p" />
                <p v-if="salesNote" class="eli5-hero__lang-note">{{ salesNote }}</p>
              </template>
            </template>
          </template>
          <p v-if="regenErrorMsg" class="eli5-hero__regen-msg" :class="'eli5-hero__regen-msg--' + regenErrorKind">{{ regenErrorMsg }}</p>
        </div>
        <div
          ref="measureEl"
          class="eli5-hero__measure"
          aria-hidden="true"
          inert
          :style="contentWidth ? { width: contentWidth + 'px' } : null"
        >
          <div v-for="(ms, mi) in measureSlides" :key="mi" class="eli5-hero__content eli5-hero__content--measure">
            <template v-if="ms.kind === 'focus'">
              <template v-if="ms.narrative">
                <Eli5InkText :blocks="ms.blocks" :revealing="false" tag="p" />
                <p v-if="ms.note" class="eli5-hero__lang-note">{{ ms.note }}</p>
                <GenerationStamp
                  :model-name="ms.narrative.model_name"
                  :generated-at="ms.narrative.generated_at"
                  :elapsed-ms="ms.narrative.elapsed_ms"
                  :fact-count="(ms.narrative.fact_json?.numbered_facts || []).length"
                  :expandable="false"
                />
              </template>
              <p v-else class="eli5-hero__text eli5-hero__text--empty">{{ t('eli5.hero.emptyMessage') }}</p>
            </template>
            <template v-else>
              <div class="eli5-hero__eyebrow-row">
                <span class="eli5-hero__customer-link">{{ ms.customer.display_name }}</span>
              </div>
              <template v-if="!ms.customer.quality && !ms.customer.sales">
                <p class="eli5-hero__text eli5-hero__text--empty">{{ t('eli5.hero.customerEmptyMessage') }}</p>
              </template>
              <template v-else>
                <template v-if="ms.customer.quality">
                  <div class="eli5-hero__slide-label">{{ t('eli5.hero.qualityLabel') }}</div>
                  <Eli5InkText :blocks="ms.qBlocks" :revealing="false" tag="p" />
                  <p v-if="ms.qNote" class="eli5-hero__lang-note">{{ ms.qNote }}</p>
                </template>
                <template v-if="ms.customer.sales">
                  <div class="eli5-hero__slide-label">{{ t('eli5.hero.salesLabel') }}</div>
                  <Eli5InkText :blocks="ms.sBlocks" :revealing="false" tag="p" />
                  <p v-if="ms.sNote" class="eli5-hero__lang-note">{{ ms.sNote }}</p>
                </template>
              </template>
            </template>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.eli5-hero {
  position: relative;
  overflow: hidden;
  padding: 32px 40px 44px;
  background: transparent;
}
.eli5-hero__inner {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 10px;
}
.eli5-hero__title {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.eli5-hero__meta {
  font-size: 13px;
  color: var(--e-muted);
}
.eli5-hero__control-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.eli5-hero__control-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.eli5-hero__nav {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 10px;
}
.eli5-hero__h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: var(--e-ink);
}
.eli5-hero__sep {
  color: var(--e-faint);
}
.eli5-hero__lang-select {
  font-family: inherit;
  font-size: 12px;
  color: var(--e-ai-ink);
  background: var(--e-surface);
  border: 1px solid var(--e-ai-line);
  border-radius: var(--radius-sm);
  padding: 2px 6px;
  cursor: pointer;
}
.eli5-hero__lang-select:focus-visible {
  outline: 2px solid var(--e-ai-ink);
  outline-offset: 1px;
}
.eli5-hero__indicator {
  font-size: 12.5px;
  color: var(--e-muted);
  min-width: 44px;
  text-align: center;
}
.eli5-hero__nav-btn {
  width: 22px;
  height: 22px;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--e-line);
  background: var(--e-surface);
  color: var(--e-ink);
  border-radius: 50%;
  cursor: pointer;
  font-size: 14px;
}
.eli5-hero__nav-btn:hover {
  background: var(--e-ai-bg);
  border-color: var(--e-ai-line);
}
.eli5-hero__nav-btn:focus-visible {
  outline: 2px solid var(--e-ai-ink);
  outline-offset: 1px;
}

.eli5-hero__nav-btn--next {
  position: relative;
}
.eli5-hero__ring {
  position: absolute;
  inset: -5px;
  width: 30px;
  height: 30px;
  transform: rotate(-90deg);
  pointer-events: none;
  overflow: visible;
}
.eli5-hero__ring circle {
  fill: none;
  stroke: var(--e-ai-ink);
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-dasharray: 81.681;
  opacity: 0.6;
}

.eli5-hero__body {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-top: 10px;
}
.eli5-hero__face {
  flex: none;
  margin-top: 2px;
}
.eli5-hero__content {
  width: 100%;
  display: grid;
  gap: 14px;
  align-content: start;
  min-width: 0;
  max-width: min(1000px, 75%);
  transition: opacity 250ms ease, filter 250ms ease;
}
.eli5-hero__measure {
  position: absolute;
  left: 0;
  top: 0;
  visibility: hidden;
  pointer-events: none;
  z-index: -1;
}
.eli5-hero__content--measure {
  max-width: none;
  width: 100%;
  transition: none;
}
.eli5-hero__content--fading {
  opacity: 0;
  filter: blur(3px);
}
.eli5-hero__eyebrow-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.eli5-hero__customer-link {
  font-size: 16px;
  font-weight: 800;
  color: var(--e-ink);
}
.eli5-hero__customer-link:hover {
  text-decoration: underline;
}
.eli5-hero__slide-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--e-faint);
  margin-top: 2px;
}
.eli5-hero__text,
:deep(.eli5-ink-text) {
  margin: 0;
  font-family: var(--e-font-text);
  font-size: 20px;
  line-height: 1.6;
  font-weight: 500;
  color: var(--e-ink);
  letter-spacing: 0.005em;
  text-wrap: pretty;
}
.eli5-hero__text + .eli5-hero__text,
:deep(.eli5-ink-text + .eli5-ink-text) {
  margin-top: 2px;
}
.eli5-hero__text--empty {
  color: var(--e-faint);
}
.eli5-hero__hint {
  margin-top: -4px;
  font-size: 13px;
  color: var(--e-faint);
}
.eli5-hero__lang-note {
  margin: 0;
  font-size: 12px;
  color: var(--e-faint);
}
.eli5-hero__text :deep(b),
:deep(.eli5-ink-text b) {
  font-weight: 700;
  color: inherit;
  background-image: linear-gradient(180deg, transparent 62%, var(--e-ai-glow) 62%, var(--e-ai-glow) 88%, transparent 88%);
}
.eli5-hero__regen-msg {
  margin: 0;
  font-size: 13px;
}
.eli5-hero__regen-msg--info,
.eli5-hero__regen-msg--notwired {
  color: var(--e-faint);
}
.eli5-hero__regen-msg--error {
  color: var(--risk-r);
}

@media (max-width: 760px) {
  .eli5-hero {
    padding: 24px 18px 32px;
  }
  .eli5-hero__content {
    max-width: 100%;
  }
  .eli5-hero__text,
  :deep(.eli5-ink-text) {
    font-size: 17px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .eli5-hero__content {
    transition: none;
  }
}
</style>
