<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import EChart from './EChart.vue'
import { cssVar } from '../utils/cssVar'

const props = defineProps({
  kpi: { type: Object, required: true },
  trendPoints: { type: Array, required: true },
  target: { type: Number, default: null },
  tint: { type: String, required: true },
})

const { t, locale } = useI18n()
const EN_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const riskTxt = (risk) => t(`eli5.kpiTile.risk.${risk}`)

function riskColorVar(risk) {
  if (risk === 'G') return cssVar('--risk-g')
  if (risk === 'Y') return cssVar('--risk-y')
  if (risk === 'R') return cssVar('--risk-r')
  return cssVar('--e-line')
}

const delta = computed(() => {
  const m = props.kpi
  let txt
  if (m.key === 'CFQR') {
    const d = m.value - m.prev_value
    txt = d === 0 ? t('eli5.kpiTile.flatDelta') : `${d > 0 ? '+' : ''}${d} ${t('eli5.kpiTile.unitPiece')}`
  } else {
    const decimals = m.key === 'DOA' ? 3 : 2
    const pp = (m.value - m.prev_value) * 100
    const rounded = Number(pp.toFixed(decimals))
    txt = rounded === 0
      ? t('eli5.kpiTile.flatDelta')
      : `${rounded > 0 ? '+' : ''}${pp.toFixed(decimals)}pp`
  }
  const arrow = m.trend === 'up' ? '▲' : m.trend === 'down' ? '▼' : '–'
  const colorVar = m.trend_good === true ? 'var(--e-good)' : m.trend_good === false ? 'var(--e-bad)' : 'var(--e-flat)'
  return { txt, arrow, colorVar }
})

const targetTxt = computed(
  () => `${t('eli5.kpiTile.target')} ${props.kpi.key === 'FPY' ? '≥' : '≤'} ${props.kpi.target_display}`,
)

const chartOption = computed(() => {
  const pts = props.trendPoints
  const target = props.target
  const xLabels = pts.map((p) => {
    const m = Number(String(p.period).slice(4))
    return locale.value.startsWith('en') ? EN_MONTHS[m - 1] : `${m}月`
  })
  const series = [
    target !== null && target !== undefined
      ? {
          type: 'line',
          data: pts.map(() => target),
          symbol: 'none',
          lineStyle: { type: 'dashed', color: cssVar('--risk-r'), width: 1.2, opacity: 0.75 },
          silent: true,
          z: 1,
        }
      : null,
    {
      type: 'line',
      data: pts.map((p) => p.value),
      symbol: 'circle',
      symbolSize: 7,
      lineStyle: { color: cssVar('--e-series-a'), width: 1.8 },
      itemStyle: { color: (p) => riskColorVar(pts[p.dataIndex]?.risk) },
      z: 2,
    },
  ].filter(Boolean)

  return {
    grid: { left: 16, right: 16, top: 8, bottom: 20, containLabel: false },
    xAxis: {
      type: 'category',
      data: xLabels,
      boundaryGap: false,
      axisLabel: { interval: 0, fontSize: 10, color: cssVar('--e-faint') },
      axisLine: { lineStyle: { color: cssVar('--e-line') } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      show: false,
      scale: true,
      splitLine: { show: true, lineStyle: { color: cssVar('--e-line') } },
    },
    series,
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const p = params.find((x) => x.seriesIndex === series.length - 1)
        if (!p) return ''
        const point = pts[p.dataIndex]
        return `${xLabels[p.dataIndex]}<br/>${point?.display ?? ''}`
      },
    },
  }
})
</script>

<template>
  <article class="eli5-qa-kpi-tile" :style="{ background: tint }">
    <div class="eli5-qa-kpi-tile__top">
      <span>{{ kpi.label }}</span>
      <span class="eli5-pill" :class="'eli5-pill--' + kpi.risk">{{ riskTxt(kpi.risk) }}</span>
    </div>
    <div class="eli5-qa-kpi-tile__big num">{{ kpi.display }}</div>
    <div class="eli5-qa-kpi-tile__delta num" :style="{ color: delta.colorVar }">
      {{ delta.arrow }} {{ delta.txt }}
      <span class="eli5-qa-kpi-tile__delta-sub">{{ t('eli5.kpiTile.deltaSub') }}</span>
    </div>
    <div class="eli5-qa-kpi-tile__target num">{{ targetTxt }}</div>
    <EChart :option="chartOption" height="112px" />
  </article>
</template>

<style scoped>
.eli5-qa-kpi-tile {
  border-radius: var(--e-radius);
  padding: 18px 18px 14px;
  display: grid;
  gap: 6px;
  align-content: start;
  min-width: 0;
}
.eli5-qa-kpi-tile__top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--e-muted);
}
.eli5-qa-kpi-tile__big {
  font-size: 30px;
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.1;
  color: var(--e-ink);
}
.eli5-qa-kpi-tile__delta {
  font-size: 13px;
  font-weight: 700;
}
.eli5-qa-kpi-tile__delta-sub {
  color: var(--e-faint);
  font-weight: 500;
}
.eli5-qa-kpi-tile__target {
  font-size: 12.5px;
  color: var(--e-muted);
}
</style>
