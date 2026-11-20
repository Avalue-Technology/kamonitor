<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import EChart from './EChart.vue'
import Eli5ClueDialog from './Eli5ClueDialog.vue'

const props = defineProps({
  chain: { type: Object, required: true },
  step: { type: Number, required: true },
  erpCustomerId: { type: String, default: null },
})

const { t } = useI18n()

const hasQuestions = computed(() => (props.chain.questions || []).length > 0)
const showClueDialog = ref(false)
const clueButtonEl = ref(null)
function openClueDialog() {
  showClueDialog.value = true
}
function closeClueDialog() {
  showClueDialog.value = false
  clueButtonEl.value?.focus()
}

const STEP_QUESTION_KEYS = [
  'pipeline_vs_orders',
  'won_vs_lost',
  'orders_vs_revenue',
  'orders_vs_shipments',
  'orders_vs_ontime',
]
const question = computed(() =>
  STEP_QUESTION_KEYS.includes(props.chain.key) ? t(`eli5.gapCard.stepQuestion.${props.chain.key}`) : '',
)

const isNeutral = computed(() => props.chain.muted === true)

const tileBg = computed(() => `var(--e-t${((props.step - 1) % 5) + 1})`)

const rootEl = ref(null)
function themeVar(name) {
  const el = rootEl.value || document.documentElement
  return getComputedStyle(el).getPropertyValue(name).trim()
}
const colorA = () => themeVar('--e-series-a')
const colorB = () => themeVar('--e-series-b')
const colorAxis = () => themeVar('--e-faint')
const colorLine = () => themeVar('--e-line')
const colorBand = () => themeVar('--e-band')

const hasMoveData = computed(() => {
  const chain = props.chain
  if (chain.chart !== 'move') return false
  const points = chain.points
  if (!points?.prev || !points?.cur) return false
  const { prev, cur } = points
  return [prev.ontime, prev.orders, cur.ontime, cur.orders].every(
    (v) => v !== null && v !== undefined
  )
})

const chartHeight = computed(() => (props.chain.chart === 'move' ? '180px' : '140px'))

const barMax = computed(() => {
  const chain = props.chain
  return Math.max(chain.left?.cur || 0, chain.right?.cur || 0) || 1
})
const barScale = computed(() => (props.chain.left?.share_pct != null ? 62 : 78))
const barLeftPct = computed(() => ((props.chain.left?.cur || 0) / barMax.value) * barScale.value)
const barRightPct = computed(() => ((props.chain.right?.cur || 0) / barMax.value) * barScale.value)

function pairBarPct(pair, value) {
  const max = Math.max(pair.prev || 0, pair.cur || 0) || 1
  return ((value || 0) / max) * 78
}

const chartOption = computed(() => {
  const chain = props.chain
  if (chain.chart === 'move') {
    if (!hasMoveData.value) return {}
    const prev = chain.points.prev
    const cur = chain.points.cur
    const deltaOntime = Math.abs(cur.ontime - prev.ontime)
    const deltaOrders = Math.abs(cur.orders - prev.orders)
    const midOntime = (prev.ontime + cur.ontime) / 2
    const midOrders = (prev.orders + cur.orders) / 2
    const xSpan = Math.max(deltaOntime * 2, 10)
    const ySpan = Math.max(deltaOrders * 2, Math.max(prev.orders, cur.orders) * 0.4)
    const xMin = () => Math.max(0, Math.floor(midOntime - xSpan / 2))
    const xMax = () => Math.min(100, Math.ceil(midOntime + xSpan / 2))
    const yMin = () => Math.max(0, Math.floor(midOrders - ySpan / 2))
    const yMax = () => Math.ceil(midOrders + ySpan / 2)
    return {
      grid: {
        left: 8,
        right: 64,
        top: 32,
        bottom: 8,
        containLabel: true,
        show: true,
        backgroundColor: colorBand(),
        borderWidth: 0,
      },
      xAxis: {
        type: 'value',
        name: t('eli5.gapCard.axisOntime'),
        nameTextStyle: { color: colorAxis(), fontSize: 10, align: 'right' },
        splitLine: { show: false },
        axisLabel: { color: colorAxis(), fontSize: 10, formatter: (v) => (v === xMin() || v === xMax() ? v : '') },
        axisLine: { lineStyle: { color: colorLine() } },
        min: xMin,
        max: xMax,
      },
      yAxis: {
        type: 'value',
        name: t('eli5.gapCard.axisOrders'),
        nameTextStyle: { color: colorAxis(), fontSize: 10 },
        splitLine: { show: false },
        axisLabel: { color: colorAxis(), fontSize: 10, formatter: (v) => (v === yMin() || v === yMax() ? v : '') },
        axisLine: { lineStyle: { color: colorLine() } },
        min: yMin,
        max: yMax,
      },
      series: [
        {
          name: prev.label,
          type: 'scatter',
          data: [[prev.ontime, prev.orders]],
          symbolSize: 12,
          itemStyle: { color: colorB() },
          label: {
            show: true,
            formatter: prev.label,
            position: 'top',
            color: colorAxis(),
            fontSize: 11,
          },
        },
        {
          name: cur.label,
          type: 'scatter',
          data: [[cur.ontime, cur.orders]],
          symbolSize: 12,
          itemStyle: { color: colorA() },
          label: {
            show: true,
            formatter: cur.label,
            position: 'bottom',
            color: colorAxis(),
            fontSize: 11,
            fontWeight: 700,
          },
          markLine: {
            symbol: ['none', 'arrow'],
            silent: true,
            lineStyle: { color: colorAxis(), width: 2 },
            label: { show: false },
            data: [[{ coord: [prev.ontime, prev.orders] }, { coord: [cur.ontime, cur.orders] }]],
          },
        },
      ],
    }
  }
  return {}
})
</script>

<template>
  <article ref="rootEl" class="gap-chain" :class="{ 'gap-chain--neutral': isNeutral }" :style="{ background: tileBg }">
    <div class="gap-chain__left">
      <div class="gap-chain__step">{{ step }} · {{ question }}</div>
      <h4 class="gap-chain__title">{{ chain.title }}<button
        v-if="hasQuestions"
        ref="clueButtonEl"
        type="button"
        class="gap-chain__clue-btn"
        :title="t('eli5.gapCard.clueButtonTitle')"
        aria-haspopup="dialog"
        :aria-label="t('eli5.gapCard.clueButtonAriaLabel')"
        @click="openClueDialog"
      ><span aria-hidden="true">✦</span> AI</button></h4>

      <div class="gap-chain__pairs">
        <div>
          <span><span class="gap-chain__sw" style="background: var(--e-series-a)" />{{ chain.left?.label }}</span>
          <b>{{ chain.left?.display }}</b>
        </div>
        <div>
          <span><span class="gap-chain__sw" style="background: var(--e-series-b)" />{{ chain.right?.label }}</span>
          <b>{{ chain.right?.display }}</b>
        </div>
      </div>

      <div class="gap-chain__gap">{{ chain.gap?.display }}</div>

      <div v-if="chain.action" class="gap-chain__action">
        <span class="gap-chain__action-label">{{ t('eli5.gapCard.actionLabel') }}</span>{{ chain.action }}
      </div>

      <router-link
        class="gap-chain__evidence"
        :to="`/eli5/customer/${erpCustomerId}/evidence/${chain.key}`"
      >{{ t('eli5.gapCard.evidenceLink') }}</router-link>

      <div v-if="!hasQuestions" class="gap-chain__ainote">
        {{ t('eli5.gapCard.aiNoteLabel') }} · {{ chain.ai_note || t('eli5.gapCard.aiNoteEmpty') }}
      </div>
    </div>

    <Eli5ClueDialog
      v-if="hasQuestions"
      :open="showClueDialog"
      :erp-customer-id="erpCustomerId"
      :chain-key="chain.key"
      :questions="chain.questions"
      :step="step"
      :eyebrow-question="question"
      :card-title="chain.title"
      :card-action="chain.action"
      :card-metrics="{
        leftLabel: chain.left?.label,
        leftDisplay: chain.left?.display,
        rightLabel: chain.right?.label,
        rightDisplay: chain.right?.display,
        gapDisplay: chain.gap?.display,
      }"
      @close="closeClueDialog"
    />

    <div class="gap-chain__right">
      <div v-if="chain.chart === 'bars'" class="gap-hbars">
        <div class="gap-hbar">
          <span class="gap-hbar__label">{{ chain.left?.label }}</span>
          <div class="gap-hbar__track">
            <div class="gap-hbar__fill" :style="{ width: barLeftPct + '%', background: 'var(--e-series-a)' }" />
            <b :style="{ left: `calc(${barLeftPct}% + 8px)` }">{{ chain.left?.display }}<span v-if="chain.left?.share_pct != null" class="gap-hbar__share">（{{ chain.left.share_pct }}%）</span></b>
          </div>
        </div>
        <div class="gap-hbar">
          <span class="gap-hbar__label">{{ chain.right?.label }}</span>
          <div class="gap-hbar__track">
            <div class="gap-hbar__fill" :style="{ width: barRightPct + '%', background: 'var(--e-series-b)' }" />
            <b :style="{ left: `calc(${barRightPct}% + 8px)` }">{{ chain.right?.display }}<span v-if="chain.right?.share_pct != null" class="gap-hbar__share">（{{ chain.right.share_pct }}%）</span></b>
          </div>
        </div>
        <p v-if="chain.chart_note" class="gap-hbars__note">{{ chain.chart_note }}</p>
      </div>
      <template v-else-if="chain.chart === 'move'">
        <EChart v-if="hasMoveData" :option="chartOption" :height="chartHeight" />
        <div v-else class="gap-chain__empty">{{ t('eli5.gapCard.emptyData') }}</div>
      </template>
      <div v-else-if="chain.chart === 'pairs'" class="gap-pairs">
        <template v-if="chain.pairs">
          <div v-for="(pair, i) in chain.pairs" :key="pair.label" class="gap-pair">
            <div class="gap-pair__label">{{ pair.label }}<span class="gap-pair__yoy">{{ pair.yoy_display }}</span></div>
            <div class="gap-hbar">
              <span class="gap-hbar__label">{{ chain.period_labels?.prev }}</span>
              <div class="gap-hbar__track">
                <div class="gap-hbar__fill gap-hbar__fill--prev" :style="{ width: pairBarPct(pair, pair.prev) + '%' }" />
                <b :style="{ left: `calc(${pairBarPct(pair, pair.prev)}% + 8px)` }">{{ pair.prev_display }}</b>
              </div>
            </div>
            <div class="gap-hbar">
              <span class="gap-hbar__label">{{ chain.period_labels?.cur }}</span>
              <div class="gap-hbar__track">
                <div class="gap-hbar__fill" :style="{ width: pairBarPct(pair, pair.cur) + '%', background: i === 0 ? 'var(--e-series-a)' : 'var(--e-series-b)' }" />
                <b :style="{ left: `calc(${pairBarPct(pair, pair.cur)}% + 8px)` }">{{ pair.cur_display }}</b>
              </div>
            </div>
          </div>
        </template>
        <div v-else class="gap-chain__empty">{{ t('eli5.gapCard.emptyData') }}</div>
      </div>
      <EChart v-else :option="chartOption" :height="chartHeight" />
    </div>
  </article>
</template>

<style scoped>
.gap-chain {
  border-radius: var(--e-radius);
  padding: 22px 24px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 28px;
  align-items: center;
}

.gap-chain--neutral {
  opacity: 0.65;
}

.gap-chain__left {
  min-width: 0;
}

.gap-chain__step {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--e-faint);
}

.gap-chain__title {
  margin: 4px 0 12px;
  font-size: 19px;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: var(--e-ink);
}

.gap-chain__pairs {
  display: grid;
  gap: 6px;
  margin-bottom: 10px;
}
.gap-chain__pairs div {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  font-size: 14px;
  max-width: 360px;
}
.gap-chain__pairs div span {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--e-muted);
}
.gap-chain__pairs div b {
  font-weight: 700;
  color: var(--e-ink);
}

.gap-chain__sw {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  display: inline-block;
  flex-shrink: 0;
}

.gap-chain__gap {
  font-size: 15px;
  font-weight: 800;
  margin-bottom: 12px;
  color: var(--e-ink);
}

.gap-chain__action {
  font-size: 13.5px;
  color: var(--e-ink);
  margin-bottom: 8px;
}
.gap-chain__action-label {
  color: var(--e-faint);
  font-weight: 600;
  margin-right: 8px;
}

.gap-chain__evidence {
  display: inline-block;
  margin-top: 8px;
  font-size: 12.5px;
  color: var(--e-muted);
  text-decoration: none;
}
.gap-chain__evidence:hover {
  color: var(--accent);
  text-decoration: underline;
}

.gap-chain__ainote {
  font-size: 12.5px;
  color: var(--e-ai-ink);
}

.gap-hbars__note {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--e-faint);
  text-align: right;
}
.gap-hbar__share {
  font-weight: 500;
  color: var(--e-faint);
  margin-left: 2px;
}
.gap-chain__clue-btn {
  margin-left: 6px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 19px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid var(--e-ai-line);
  background: var(--e-ai-bg);
  color: var(--e-ai-ink);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.01em;
  line-height: 1;
  cursor: pointer;
  vertical-align: middle;
}
.gap-chain__clue-btn:hover {
  background: var(--e-ai-line);
}
.gap-chain__clue-btn:focus-visible {
  outline: 2px solid var(--e-ai-ink);
  outline-offset: 2px;
}

.gap-chain__right {
  min-width: 0;
}

.gap-chain__empty {
  height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--e-faint);
  font-size: 13px;
}

.gap-hbars {
  display: grid;
  gap: 12px;
}

.gap-pairs {
  display: grid;
  gap: 16px;
}
.gap-pair {
  display: grid;
  gap: 6px;
}
.gap-pair__label {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--e-ink);
}
.gap-pair__yoy {
  font-weight: 600;
  color: var(--e-faint);
}
.gap-hbar__fill--prev {
  background: var(--e-faint);
  opacity: 0.4;
}
.gap-hbar {
  display: grid;
  grid-template-columns: 96px 1fr;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  color: var(--e-muted);
}
.gap-hbar__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.gap-hbar__track {
  height: 22px;
  background: var(--e-line);
  border-radius: 6px;
  position: relative;
}
.gap-hbar__fill {
  height: 100%;
  border-radius: 6px;
}
.gap-hbar__track b {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  font-size: 12.5px;
  color: var(--e-ink);
  white-space: nowrap;
}

@media (max-width: 900px) {
  .gap-chain {
    grid-template-columns: 1fr;
  }
}
</style>
