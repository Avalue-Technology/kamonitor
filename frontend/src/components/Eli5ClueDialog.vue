<script setup>
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { getClueQa, regenerateClueQa } from '../api/endpoints'
import { hasCitationData, citedFactIdsSet, markCitedValues } from '../utils/aiFacts'
import { useAiReveal } from '../composables/useAiReveal'
import AssistantFace from './AssistantFace.vue'
import GenerationStamp from './GenerationStamp.vue'
import FactCitationList from './FactCitationList.vue'
import RegenerateButton from './RegenerateButton.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  erpCustomerId: { type: String, required: true },
  chainKey: { type: String, required: true },
  questions: { type: Array, default: () => [] },
  step: { type: Number, default: null },
  eyebrowQuestion: { type: String, default: '' },
  cardTitle: { type: String, default: '' },
  cardAction: { type: String, default: '' },
  cardMetrics: { type: Object, default: null },
})
const emit = defineEmits(['close'])
const { t } = useI18n()

function freshEntry() {
  return reactive({
    status: 'idle', narrative: null, error: null, typing: false, typingText: '',
    regenErrorMsg: '', regenErrorKind: 'error',
  })
}
const answers = reactive({})
function entryFor(id) {
  if (!answers[id]) answers[id] = freshEntry()
  return answers[id]
}

const activeId = ref(null)
const activeEntry = computed(() => (activeId.value ? entryFor(activeId.value) : null))

const { facePhase, faceChunk, flourish, typewriter } = useAiReveal()

async function shortFlourish() {
  await flourish()
}

async function typewriterReveal(entry, fullText) {
  entry.typing = true
  entry.typingText = ''
  await typewriter(fullText, {
    onUpdate: (text) => { entry.typingText = text },
  })
  entry.typing = false
}

async function openAnswer(question) {
  activeId.value = question.id
  const entry = entryFor(question.id)
  if (entry.status === 'loaded' || entry.status === 'loading') return
  entry.status = 'loading'
  entry.error = null
  facePhase.value = 'reasoning'
  try {
    const data = await getClueQa(props.erpCustomerId, props.chainKey, question.id)
    entry.narrative = data
    entry.status = 'loaded'
    shortFlourish()
  } catch (e) {
    if (e.status === 404) {
      entry.status = 'notfound'
      facePhase.value = 'idle'
    } else {
      entry.status = 'error'
      entry.error = e
      facePhase.value = 'error'
    }
  }
}

function classifyRegenerateError(status) {
  if (status === 409) return 'info'
  if (status === 501) return 'notwired'
  return 'error'
}

function makeRegenerateFn(question) {
  return async function doRegenerate() {
    const entry = entryFor(question.id)
    entry.regenErrorMsg = ''
    facePhase.value = 'reasoning'
    try {
      const data = await regenerateClueQa(props.erpCustomerId, props.chainKey, question.id)
      entry.status = 'loaded'
      entry.narrative = data
      await typewriterReveal(entry, data.content || '')
    } catch (e) {
      entry.error = e
      entry.status = entry.status === 'idle' ? 'error' : entry.status
      entry.regenErrorMsg = e.message || t('eli5.clueDialog.regenErrorDefault')
      entry.regenErrorKind = classifyRegenerateError(e.status)
      facePhase.value = 'error'
      throw e
    }
  }
}

function numberedFacts(entry) {
  return entry?.narrative?.fact_json?.numbered_facts || []
}
function citedFactsForMark(entry) {
  const factJson = entry?.narrative?.fact_json
  if (!hasCitationData(factJson)) return []
  const ids = citedFactIdsSet(factJson)
  return numberedFacts(entry).filter((f) => f && ids.has(f.id))
}
function contentSegments(entry) {
  if (!entry?.narrative) return []
  const text = entry.narrative.content || ''
  return markCitedValues(text, citedFactsForMark(entry), entry.narrative.fact_json?.literal_terms || [])
}

const panelEl = ref(null)
function close() {
  emit('close')
}
function onKeydown(e) {
  if (e.key === 'Escape') close()
}
function onBackdropClick(e) {
  if (e.target === e.currentTarget) close()
}
watch(
  () => props.open,
  async (isOpen) => {
    if (isOpen) {
      document.addEventListener('keydown', onKeydown)
      await nextTick()
      panelEl.value?.focus()
    } else {
      document.removeEventListener('keydown', onKeydown)
      activeId.value = null
      facePhase.value = 'idle'
      faceChunk.value = 0
    }
  },
)
onMounted(() => {
  if (props.open) document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
  <div v-if="open" class="clue-dialog-backdrop" @mousedown="onBackdropClick">
    <div
      ref="panelEl"
      class="clue-dialog"
      role="dialog"
      aria-modal="true"
      :aria-label="t('eli5.clueDialog.dialogLabel')"
      tabindex="-1"
    >
      <button type="button" class="clue-dialog__close" :aria-label="t('eli5.clueDialog.closeLabel')" @click="close">×</button>

      <div class="clue-dialog__header">
        <h3 class="clue-dialog__title">{{ cardTitle
          }}<span v-if="cardAction" class="clue-dialog__title-action">{{ cardAction }}</span></h3>
      </div>

      <div class="clue-dialog__layout">
      <div class="clue-dialog__questions">
        <button
          v-for="q in questions"
          :key="q.id"
          type="button"
          class="clue-dialog__q"
          :class="{ 'clue-dialog__q--active': activeId === q.id }"
          @click="openAnswer(q)"
        >
          {{ q.text }}
        </button>

        <div v-if="cardMetrics" class="clue-dialog__facts">
          <div class="clue-dialog__fact">
            <span class="clue-dialog__fact-dot clue-dialog__fact-dot--a" />
            <span class="clue-dialog__fact-label">{{ cardMetrics.leftLabel }}</span>
            <span class="clue-dialog__fact-value num">{{ cardMetrics.leftDisplay }}</span>
          </div>
          <div class="clue-dialog__fact">
            <span class="clue-dialog__fact-dot clue-dialog__fact-dot--b" />
            <span class="clue-dialog__fact-label">{{ cardMetrics.rightLabel }}</span>
            <span class="clue-dialog__fact-value num">{{ cardMetrics.rightDisplay }}</span>
          </div>
          <div class="clue-dialog__fact-gap">{{ cardMetrics.gapDisplay }}</div>
        </div>
      </div>

      <div class="clue-dialog__answer">
      <p v-if="!activeEntry" class="clue-dialog__placeholder">{{ t('eli5.clueDialog.placeholder') }}</p>

      <div v-else class="clue-answer-card">
        <span class="clue-answer-card__eyebrow">{{ t('eli5.clueDialog.answerEyebrow') }}</span>
        <div class="clue-dialog__body">
          <AssistantFace class="clue-dialog__face" :phase="facePhase" :chunk="faceChunk" :size="40" />
          <div class="clue-dialog__main">
            <div v-if="activeEntry.status === 'loading'" class="clue-dialog__empty">{{ t('eli5.clueDialog.loading') }}</div>

            <div v-else-if="activeEntry.status === 'notfound'" class="clue-dialog__empty">
              <p class="clue-dialog__empty-msg">{{ t('eli5.clueDialog.notFoundMessage') }}</p>
              <p class="clue-dialog__empty-hint">{{ t('eli5.clueDialog.notFoundHint') }}</p>
              <div class="clue-dialog__regen">
                <RegenerateButton
                  api-path="/api/customers/{erp_customer_id}/clue-qa/{chain_key}/{question_id}/regenerate"
                  :regenerate-fn="makeRegenerateFn(questions.find((q) => q.id === activeId))"
                />
                <p v-if="activeEntry.regenErrorMsg" class="clue-dialog__regen-msg" :class="'clue-dialog__regen-msg--' + activeEntry.regenErrorKind">{{ activeEntry.regenErrorMsg }}</p>
              </div>
            </div>

            <div v-else-if="activeEntry.status === 'error'" class="clue-dialog__empty">
              <p class="clue-dialog__empty-msg">{{ t('eli5.clueDialog.errorMessage') }}</p>
              <p class="clue-dialog__empty-hint">{{ activeEntry.error?.message }}</p>
            </div>

            <template v-else-if="activeEntry.status === 'loaded'">
              <p v-if="activeEntry.typing" class="clue-dialog__text">{{ activeEntry.typingText }}</p>
              <p v-else class="clue-dialog__text"><template
                v-for="(seg, j) in contentSegments(activeEntry)"
                :key="j"
              ><b v-if="seg.type">{{ seg.text }}</b><template v-else>{{ seg.text }}</template></template></p>

              <div class="clue-dialog__footer">
                <GenerationStamp
                  :model-name="activeEntry.narrative.model_name"
                  :generated-at="activeEntry.narrative.generated_at"
                  :elapsed-ms="activeEntry.narrative.elapsed_ms"
                  :expandable="false"
                />
                <FactCitationList
                  :fact-json="activeEntry.narrative.fact_json || {}"
                  collapsible
                  :show-authoritative-note="false"
                />
                <div class="clue-dialog__regen">
                  <RegenerateButton
                    api-path="/api/customers/{erp_customer_id}/clue-qa/{chain_key}/{question_id}/regenerate"
                    :regenerate-fn="makeRegenerateFn(questions.find((q) => q.id === activeId))"
                  />
                  <p v-if="activeEntry.regenErrorMsg" class="clue-dialog__regen-msg" :class="'clue-dialog__regen-msg--' + activeEntry.regenErrorKind">{{ activeEntry.regenErrorMsg }}</p>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>
      </div>
      </div>
    </div>
  </div>
  </Teleport>
</template>

<style scoped>
.clue-dialog-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(20, 20, 30, 0.42);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 16px;
}
.clue-dialog {
  position: relative;
  width: 100%;
  max-width: 960px;
  max-height: 84vh;
  overflow-y: auto;
  background: var(--e-surface, #fff);
  border-radius: var(--e-radius, 16px);
  padding: 28px 26px 22px;
  outline: none;
  box-shadow: var(--shadow-ai, 0 2px 4px rgba(15, 23, 42, 0.08), 0 6px 16px rgba(15, 23, 42, 0.1));
}
.clue-dialog::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: radial-gradient(220px 180px at calc(100% + 20px) -20px, var(--e-ai-bg, #f5f2ff) 0%, transparent 70%);
  opacity: 0.8;
  pointer-events: none;
  z-index: -1;
}
.clue-dialog__header {
  margin: 0 34px 14px 0;
}
.clue-dialog__title-action {
  margin-left: 10px;
  font-size: 13.5px;
  font-weight: 500;
  letter-spacing: 0;
  color: var(--e-muted, #5c6279);
}
.clue-dialog__facts {
  margin-top: 18px;
  padding: 14px 14px 12px;
  border-radius: 12px;
  background: var(--e-band-soft, #f9fafd);
  border: 1px solid var(--e-line-soft, #eef0f6);
}
.clue-dialog__fact {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
  color: var(--e-muted, #5c6279);
}
.clue-dialog__fact + .clue-dialog__fact {
  margin-top: 6px;
}
.clue-dialog__fact-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  flex: none;
}
.clue-dialog__fact-dot--a {
  background: var(--e-series-a, #171a2c);
}
.clue-dialog__fact-dot--b {
  background: var(--e-series-b, #a3a0f5);
}
.clue-dialog__fact-label {
  flex: 1;
}
.clue-dialog__fact-value {
  font-weight: 700;
  color: var(--e-ink, #171a2c);
}
.clue-dialog__fact-gap {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--e-line-soft, #eef0f6);
  font-size: 13.5px;
  font-weight: 700;
  color: var(--e-ink, #171a2c);
}
.clue-dialog__title {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: var(--e-ink, #171a2c);
}
.clue-dialog__close {
  position: absolute;
  top: 12px;
  right: 14px;
  border: none;
  background: none;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  color: var(--e-faint, #8a90a6);
}
.clue-dialog__close:hover {
  color: var(--e-ink, #171a2c);
}
.clue-dialog__layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
  margin-top: 8px;
}
.clue-dialog__questions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  counter-reset: clue-q;
}
.clue-dialog__answer {
  min-width: 0;
  min-height: 260px;
  display: flex;
  flex-direction: column;
}
.clue-dialog__placeholder {
  margin: 0;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: var(--e-faint, #8a90a6);
  border: 1px dashed var(--e-line, #e6e8ef);
  border-radius: 12px;
}
@media (max-width: 760px) {
  .clue-dialog__layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .clue-dialog__answer {
    min-height: 0;
  }
  .clue-dialog__placeholder {
    padding: 18px 0;
  }
}
.clue-dialog__q {
  display: flex;
  align-items: center;
  gap: 10px;
  text-align: left;
  border: 1px solid var(--e-line, #e6e8ef);
  background: var(--e-surface, #fff);
  border-radius: 10px;
  padding: 10px 14px;
  font-size: 14.5px;
  font-weight: 600;
  color: var(--e-ink, #171a2c);
  cursor: pointer;
}
.clue-dialog__q::before {
  counter-increment: clue-q;
  content: counter(clue-q);
  flex: none;
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--e-line, #e6e8ef);
  color: var(--e-muted, #5c6279);
  font-size: 11px;
  font-weight: 700;
}
.clue-dialog__q--active {
  border-color: var(--e-ai-ink, #5b45c9);
  background: var(--e-ai-ink, #5b45c9);
  color: #fff;
}
.clue-dialog__q--active::before {
  background: rgba(255, 255, 255, 0.28);
  color: #fff;
}
.clue-answer-card {
  position: relative;
  margin-top: 0;
  padding: 18px 20px;
  border-radius: var(--e-radius, 16px);
  background: var(--e-ai-bg, #f5f2ff);
}
.clue-answer-card::before {
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
  animation: clue-ai-orbit 5.5s linear infinite;
}
@keyframes clue-ai-orbit {
  to { --e-ai-angle: 360deg; }
}
@media (prefers-reduced-motion: reduce) {
  .clue-answer-card::before {
    animation: none;
  }
}
.clue-answer-card__eyebrow {
  display: block;
  margin-bottom: 10px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--e-ai-ink, #5b45c9);
}
.clue-dialog__body {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.clue-dialog__face {
  flex: none;
  margin-top: 2px;
}
.clue-dialog__main {
  min-width: 0;
  flex: 1 1 auto;
  display: grid;
  gap: 10px;
}
.clue-dialog__text {
  margin: 0;
  font-size: 15.5px;
  line-height: 1.75;
  color: var(--e-ink, #171a2c);
  animation: clue-fade-in 0.35s ease;
}
.clue-dialog__text b {
  font-weight: 700;
  color: var(--e-ai-ink, #5b45c9);
}
@keyframes clue-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .clue-dialog__text {
    animation: none;
  }
}
.clue-dialog__empty {
  display: grid;
  gap: 4px;
}
.clue-dialog__empty-msg {
  margin: 0;
  font-size: 15px;
  color: var(--e-muted, #5c6279);
}
.clue-dialog__empty-hint {
  margin: 0;
  font-size: 13px;
  color: var(--e-faint, #8a90a6);
}
.clue-dialog__footer {
  display: grid;
  gap: 10px;
  margin-top: 4px;
}
.clue-dialog__regen {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.clue-dialog__regen-msg {
  margin: 0;
  font-size: 12.5px;
}
.clue-dialog__regen-msg--info,
.clue-dialog__regen-msg--notwired {
  color: var(--e-faint, #8a90a6);
}
.clue-dialog__regen-msg--error {
  color: var(--risk-r);
}
</style>
