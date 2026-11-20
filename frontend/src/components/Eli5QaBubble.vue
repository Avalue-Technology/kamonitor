<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import echarts from '../echarts-setup'
import EChart from './EChart.vue'
import { cssVar } from '../utils/cssVar'

const props = defineProps({
  points: { type: Array, default: () => [] },
  excludedNote: { type: String, default: '' },
})

const emit = defineEmits(['select'])
const { t } = useI18n()

const BUBBLE_MIN_R = 8
const BUBBLE_MAX_R = 36

const shownPoints = computed(() => props.points.filter((p) => p.excluded === false))
const excludedPoints = computed(() => props.points.filter((p) => p.excluded === true))

function riskColor(risk) {
  if (risk === 'R') return cssVar('--risk-r')
  if (risk === 'Y') return cssVar('--risk-y')
  return cssVar('--risk-g')
}

function mix(hex, target, amount) {
  const [r, g, b, a] = echarts.color.parse(hex)
  const [tr, tg, tb] = target
  return `rgba(${r + (tr - r) * amount}, ${g + (tg - g) * amount}, ${b + (tb - b) * amount}, ${a})`
}
function lighten(hex, amount) {
  return mix(hex, [255, 255, 255], amount)
}
function darken(hex, amount) {
  return mix(hex, [0, 0, 0], amount)
}
function alpha(hex, a) {
  const [r, g, b] = echarts.color.parse(hex)
  return `rgba(${r}, ${g}, ${b}, ${a})`
}

function bubbleStyle(risk) {
  const base = riskColor(risk)
  return {
    color: new echarts.graphic.RadialGradient(0.35, 0.32, 0.75, [
      { offset: 0, color: lighten(base, 0.55) },
      { offset: 0.7, color: base },
      { offset: 1, color: darken(base, 0.12) },
    ]),
    shadowColor: alpha(base, 0.45),
    shadowBlur: 10,
    shadowOffsetY: 3,
  }
}

function radiusFor(qty, minQty, maxQty) {
  if (!(maxQty > minQty)) return (BUBBLE_MIN_R + BUBBLE_MAX_R) / 2
  const t = (Math.sqrt(qty) - Math.sqrt(minQty)) / (Math.sqrt(maxQty) - Math.sqrt(minQty))
  return BUBBLE_MIN_R + t * (BUBBLE_MAX_R - BUBBLE_MIN_R)
}

const shipmentRange = computed(() => {
  const qtys = shownPoints.value.map((p) => p.total_shipment_qty || 0)
  if (!qtys.length) return { min: 0, max: 0 }
  return { min: Math.min(...qtys), max: Math.max(...qtys) }
})

function fmtPct(v, digits = 3) {
  return `${(v * 100).toFixed(digits)}%`
}

const chartOption = computed(() => {
  const { min, max } = shipmentRange.value
  const data = shownPoints.value.map((p) => ({
    value: [p.rma_rate * 100, p.doa_rate * 100],
    name: p.display_name,
    itemStyle: bubbleStyle(p.risk),
    symbolSize: radiusFor(p.total_shipment_qty || 0, min, max) * 2,
    _point: p,
  }))

  const axisLabelColor = cssVar('--text-faint')
  const axisLineColor = cssVar('--e-line')
  const splitLineColor = alpha(cssVar('--e-line'), 0.5)

  return {
    grid: { left: 56, right: 32, top: 24, bottom: 48, containLabel: true },
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const pt = p.data._point
        return `${pt.display_name} · RMA ${fmtPct(pt.rma_rate)} · DOA ${fmtPct(pt.doa_rate)} · ${t('eli5.qaBubble.tooltipShipment')} ${(pt.total_shipment_qty || 0).toLocaleString()} ${t('eli5.qaBubble.tooltipUnit')}`
      },
    },
    xAxis: {
      type: 'value',
      name: t('eli5.qaBubble.axisRma'),
      nameLocation: 'middle',
      nameGap: 28,
      nameTextStyle: { color: cssVar('--text-muted'), fontSize: 12 },
      min: 0,
      axisLabel: { color: axisLabelColor, fontSize: 10, formatter: (v) => `${v}%` },
      axisLine: { lineStyle: { color: axisLineColor } },
      splitLine: { lineStyle: { color: splitLineColor } },
    },
    yAxis: {
      type: 'value',
      name: t('eli5.qaBubble.axisDoa'),
      nameLocation: 'middle',
      nameGap: 40,
      nameTextStyle: { color: cssVar('--text-muted'), fontSize: 12 },
      min: 0,
      axisLabel: { color: axisLabelColor, fontSize: 10, formatter: (v) => `${v}%` },
      axisLine: { lineStyle: { color: axisLineColor } },
      splitLine: { lineStyle: { color: splitLineColor } },
    },
    series: [
      {
        type: 'scatter',
        data,
        itemStyle: {
          opacity: 0.92,
          borderColor: cssVar('--on-solid'),
          borderWidth: 1.5,
        },
        emphasis: { itemStyle: { opacity: 1 } },
        label: {
          show: false,
          formatter: (p) => p.data.name,
          position: 'top',
          fontSize: 10,
          color: cssVar('--text-body'),
        },
      },
    ],
  }
})

function onChartClick(params) {
  const point = params?.data?._point
  if (point) emit('select', point.erp_customer_id)
}
</script>

<template>
  <div class="eli5-bubble">
    <EChart v-if="shownPoints.length" :option="chartOption" height="420px" @chart-click="onChartClick" />
    <div v-else class="eli5-bubble__empty">{{ t('eli5.qaBubble.empty') }}</div>

    <div class="eli5-bubble__legend">
      <span class="eli5-bubble__legend-item">
        <span class="eli5-bubble__dot eli5-bubble__dot--r" />{{ t('eli5.qaBubble.legendRisk') }}
      </span>
      <span class="eli5-bubble__legend-item">
        <span class="eli5-bubble__dot eli5-bubble__dot--y" />{{ t('eli5.qaBubble.legendAttention') }}
      </span>
      <span class="eli5-bubble__legend-item">
        <span class="eli5-bubble__dot eli5-bubble__dot--g" />{{ t('eli5.qaBubble.legendNormal') }}
      </span>
      <span class="eli5-bubble__legend-note">{{ t('eli5.qaBubble.legendNote') }}</span>
    </div>

    <div v-if="excludedPoints.length" class="eli5-bubble__excluded">
      ⚠ {{ excludedNote }}：{{ excludedPoints.map((p) => p.display_name).join('、') }}
    </div>
  </div>
</template>

<style scoped>
.eli5-bubble {
  padding: 0;
}

.eli5-bubble__empty {
  height: 420px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-faint);
  font-size: var(--fs-md);
}

.eli5-bubble__legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-4);
  margin-top: var(--sp-3);
  padding-top: var(--sp-3);
  border-top: 1px solid var(--border);
  font-size: var(--fs-sm);
  color: var(--text-body);
}

.eli5-bubble__legend-item {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}

.eli5-bubble__dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.eli5-bubble__dot--r {
  background: var(--risk-r);
}
.eli5-bubble__dot--y {
  background: var(--risk-y);
}
.eli5-bubble__dot--g {
  background: var(--risk-g);
}

.eli5-bubble__legend-note {
  color: var(--text-faint);
  font-size: var(--fs-xs);
}

.eli5-bubble__excluded {
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-faint);
}
</style>
