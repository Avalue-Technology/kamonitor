<script setup>
const props = defineProps({
  card: { type: Object, required: true },
})

const emit = defineEmits(['select'])

function overallRisk(metrics) {
  if (metrics.some((m) => m.risk === 'R')) return 'R'
  if (metrics.some((m) => m.risk === 'Y')) return 'Y'
  return 'G'
}

function trendSymbol(trend) {
  if (trend === 'up') return '▲'
  if (trend === 'down') return '▼'
  return '–'
}

function trendClass(trendGood) {
  if (trendGood === true) return 'eli5-qa-card__trend--pos'
  if (trendGood === false) return 'eli5-qa-card__trend--neg'
  return 'eli5-qa-card__trend--flat'
}

function dotClass(risk) {
  return `eli5-dot eli5-dot--${risk}`
}

function onSelect() {
  emit('select', props.card.erp_customer_id)
}
</script>

<template>
  <div
    class="eli5-qa-card"
    role="button"
    tabindex="0"
    @click="onSelect"
    @keydown.enter="onSelect"
  >
    <div class="eli5-qa-card__name" :class="`eli5-qa-card__name--${overallRisk(card.metrics)}`">
      {{ card.display_name }}
    </div>

    <ul class="eli5-qa-card__metrics">
      <li v-for="m in card.metrics" :key="m.key" class="eli5-qa-card__row">
        <span :class="dotClass(m.risk)"></span>
        <span class="eli5-qa-card__label">{{ m.label }}</span>
        <span class="eli5-qa-card__value num">{{ m.display }}</span>
        <span class="eli5-qa-card__trend" :class="trendClass(m.trend_good)">{{ trendSymbol(m.trend) }}</span>
      </li>
    </ul>

    <div v-if="card.parent_group" class="eli5-qa-card__group-row">
      <span class="eli5-qa-card__group">{{ card.parent_group }}</span>
    </div>
  </div>
</template>

<style scoped>
.eli5-qa-card {
  background: var(--e-surface);
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 18px 18px 30px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  position: relative;
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.eli5-qa-card:hover,
.eli5-qa-card:focus-visible {
  border-color: var(--e-accent);
  outline: none;
}
.eli5-qa-card:focus-visible {
  box-shadow: 0 0 0 2px var(--e-accent-soft);
}

.eli5-qa-card__group-row {
  position: absolute;
  right: 0;
  bottom: 0;
}
.eli5-qa-card__group {
  max-width: 100%;
  display: block;
  padding: 4px 10px;
  border-radius: 6px 0 9px 0;
  background: #2f6fd0;
  color: #fff;
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.eli5-qa-card__name {
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.01em;
  line-height: 1.35;
  color: var(--e-ink);
  padding-left: 10px;
  border-left: 3px solid transparent;
}
.eli5-qa-card__name--R {
  border-left-color: var(--risk-r);
}
.eli5-qa-card__name--Y {
  border-left-color: var(--risk-y);
}
.eli5-qa-card__name--G {
  border-left-color: var(--risk-g);
}

.eli5-qa-card__metrics {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}

.eli5-qa-card__row {
  display: grid;
  grid-template-columns: 8px 1fr auto 14px;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
}

.eli5-qa-card__label {
  color: var(--e-muted);
}

.eli5-qa-card__value {
  font-weight: 700;
  text-align: right;
  color: var(--e-ink);
}

.eli5-qa-card__trend {
  font-style: normal;
  font-size: 11px;
  text-align: center;
}
.eli5-qa-card__trend--pos {
  color: var(--e-good);
}
.eli5-qa-card__trend--neg {
  color: var(--e-bad);
}
.eli5-qa-card__trend--flat {
  color: var(--e-flat);
}
</style>
