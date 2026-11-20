<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import echarts from '../echarts-setup'
import EChart from './EChart.vue'
import { cssVar } from '../utils/cssVar'
import { formatUSDCompact, formatPct } from '../utils/format'

const props = defineProps({
  points: { type: Array, default: () => [] },
  newCustomers: { type: Array, default: () => [] },
  shareThresholdPct: { type: Number, default: 5 },
})

const emit = defineEmits(['select'])
const { t } = useI18n()

const BUBBLE_MIN_R = 8
const BUBBLE_MAX_R = 36

function quadrantLabel(quadrant) {
  return t(`eli5.growthBubble.quadrant.${quadrant}`)
}

function cornerLabel(quadrant) {
  const spaced = quadrantLabel(quadrant).split('').join(' ')
  return quadrant === 'grow' ? `★ ${spaced}` : spaced
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

function bubbleStyle() {
  const ocean = cssVar('--e-growth-ocean')
  const atmo = cssVar('--e-growth-atmo')
  return {
    color: new echarts.graphic.RadialGradient(0.42, 0.4, 0.62, [
      { offset: 0, color: lighten(ocean, 0.3) },
      { offset: 0.55, color: ocean },
      { offset: 0.82, color: mix(ocean, echarts.color.parse(atmo).slice(0, 3), 0.45) },
      { offset: 1, color: atmo },
    ]),
    shadowColor: alpha(atmo, 0.55),
    shadowBlur: 12,
    shadowOffsetY: 0,
  }
}

function radiusFor(value, minValue, maxValue) {
  if (!(maxValue > minValue)) return (BUBBLE_MIN_R + BUBBLE_MAX_R) / 2
  const safeMin = Math.max(minValue, 0)
  const t = (Math.sqrt(value) - Math.sqrt(safeMin)) / (Math.sqrt(maxValue) - Math.sqrt(safeMin))
  return BUBBLE_MIN_R + t * (BUBBLE_MAX_R - BUBBLE_MIN_R)
}

const pipelineRange = computed(() => {
  const vals = props.points.map((p) => p.pipeline_usd || 0)
  if (!vals.length) return { min: 0, max: 0 }
  return { min: Math.min(...vals), max: Math.max(...vals) }
})

const X_AXIS_MAX = 20
const X_AXIS_TICK_INTERVAL = 5

const axisBounds = computed(() => {
  const relatives = props.points.map((p) => p.relative_growth_pp)
  const yAbsMax = relatives.length
    ? Math.ceil((Math.max(5, ...relatives.map((v) => Math.abs(v))) * 1.1) / 10) * 10
    : 10
  return { xMax: X_AXIS_MAX, yMax: yAbsMax, yMin: -yAbsMax }
})

function fmtPp(v) {
  if (v === null || v === undefined) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(1)}pp`
}

const chartOption = computed(() => {
  const { min: pMin, max: pMax } = pipelineRange.value
  const { xMax, yMin, yMax } = axisBounds.value
  const threshold = props.shareThresholdPct

  const data = props.points.map((p) => ({
    value: [p.share_pct, p.relative_growth_pp],
    name: p.display_name,
    symbolSize: radiusFor(p.pipeline_usd || 0, pMin, pMax) * 2,
    _point: p,
  }))

  const axisLabelColor = cssVar('--text-faint')
  const axisLineColor = cssVar('--e-line')
  const splitLineColor = alpha(cssVar('--e-line'), 0.5)
  const zeroLineColor = cssVar('--text-muted')
  const thresholdLineColor = cssVar('--text-faint')
  const cornerLabelColor = cssVar('--e-faint')

  function area(xRange, yRange, quadrant, position) {
    return [
      { coord: [xRange[0], yRange[0]], itemStyle: { color: 'transparent' } },
      {
        coord: [xRange[1], yRange[1]],
        label: {
          show: true,
          position,
          formatter: cornerLabel(quadrant),
          color: cornerLabelColor,
          fontSize: 11,
          fontWeight: 600,
        },
      },
    ]
  }

  function tooltipLines(pt) {
    return [
      `<strong>${pt.display_name}</strong>　${pt.quadrant === 'grow' ? '★ ' : ''}${quadrantLabel(pt.quadrant)}`,
      `${t('eli5.growthBubble.tooltipRevenue')}：${formatUSDCompact(pt.revenue_usd)}`,
      `${t('eli5.growthBubble.tooltipShare')}：${formatPct(pt.share_pct)}`,
      `${t('eli5.growthBubble.tooltipYoy')}：${formatPct(pt.yoy_pct)}`,
      `${t('eli5.growthBubble.tooltipRelative')}：${fmtPp(pt.relative_growth_pp)}`,
      `${t('eli5.growthBubble.tooltipPipeline')}：${formatUSDCompact(pt.pipeline_usd)}`,
      `${t('eli5.growthBubble.tooltipMargin')}：${pt.gross_margin_pct === null || pt.gross_margin_pct === undefined ? '—' : formatPct(pt.gross_margin_pct)}`,
    ].join('<br/>')
  }

  return {
    grid: { left: 56, right: 32, top: 24, bottom: 48, containLabel: true },
    tooltip: {
      trigger: 'item',
      formatter: (p) => tooltipLines(p.data._point),
    },
    xAxis: {
      type: 'value',
      name: t('eli5.growthBubble.axisShare'),
      nameLocation: 'middle',
      nameGap: 28,
      nameTextStyle: { color: cssVar('--text-muted'), fontSize: 12 },
      min: 0,
      max: xMax,
      interval: X_AXIS_TICK_INTERVAL,
      axisLabel: { color: axisLabelColor, fontSize: 10, formatter: (v) => `${v}%` },
      axisLine: { lineStyle: { color: axisLineColor } },
      splitLine: { lineStyle: { color: splitLineColor } },
    },
    yAxis: {
      type: 'value',
      name: t('eli5.growthBubble.axisRelative'),
      nameLocation: 'middle',
      nameGap: 40,
      nameTextStyle: { color: cssVar('--text-muted'), fontSize: 12 },
      min: yMin,
      max: yMax,
      axisLabel: { color: axisLabelColor, fontSize: 10, formatter: (v) => `${v}pp` },
      axisLine: { lineStyle: { color: axisLineColor } },
      splitLine: { lineStyle: { color: splitLineColor } },
    },
    series: [
      {
        type: 'scatter',
        cursor: 'pointer',
        data,
        itemStyle: bubbleStyle(),
        markArea: {
          silent: true,
          data: [
            area([threshold, xMax], [0, yMax], 'grow', 'insideTopRight'),
            area([threshold, xMax], [yMin, 0], 'maintain', 'insideBottomRight'),
            area([0, threshold], [0, yMax], 'nurture', 'insideTopLeft'),
            area([0, threshold], [yMin, 0], 'review', 'insideBottomLeft'),
          ],
        },
        markLine: {
          silent: true,
          symbol: 'none',
          label: { show: false },
          lineStyle: { color: zeroLineColor, width: 1.5, type: 'solid' },
          data: [
            { yAxis: 0 },
            { xAxis: threshold, lineStyle: { color: thresholdLineColor, type: 'dashed', width: 1 } },
          ],
        },
        emphasis: { itemStyle: { opacity: 1 } },
        label: { show: false },
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
    <EChart v-if="points.length" :option="chartOption" height="420px" @chart-click="onChartClick" />
    <div v-else class="eli5-bubble__empty">{{ t('eli5.growthBubble.empty') }}</div>

    <div class="eli5-bubble__legend">
      <span class="eli5-bubble__legend-note">{{ t('eli5.growthBubble.legendNote') }}</span>
    </div>

    <div v-if="newCustomers.length" class="eli5-bubble__excluded">
      ⚠ {{ t('eli5.growthBubble.newCustomerNote') }}：{{ newCustomers.map((p) => p.display_name).join('、') }}
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
