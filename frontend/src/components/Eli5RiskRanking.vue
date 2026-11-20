<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  data: { type: Object, required: true },
})
const emit = defineEmits(['select'])
const { t } = useI18n()

const TOP_N = 10
const METRICS = ['RMA', 'DOA', 'Repair', 'FPY', 'CFQR']
const GROUPS = [
  { key: 'groupPost', items: ['RMA', 'DOA'] },
  { key: 'groupFactory', items: ['Repair', 'FPY'] },
  { key: 'groupNone', items: ['CFQR'] },
]
const cap = computed(() => props.data.score_cap ?? 5)
const axisMax = computed(() => cap.value * 3)

const customer = ref('all')
const expanded = ref(false)

const scored = computed(() =>
  (props.data.rows || [])
    .filter((r) => r.score_total > 0)
    .map((r) => ({
      row: r,
      parts: METRICS.map((k) => ({ key: k, score: r.metrics?.[k]?.score || 0 })).filter((p) => p.score > 0),
      few: METRICS.some((k) => (r.metrics?.[k]?.score || 0) > 0 && r.metrics[k].reliable === false),
    }))
    .sort((a, b) => b.row.score_total - a.row.score_total),
)

const customers = computed(() => {
  const m = new Map()
  scored.value.forEach((s) => m.set(s.row.erp_customer_id, s.row.display_name))
  return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]))
})

const visible = computed(() =>
  customer.value === 'all' ? scored.value : scored.value.filter((s) => s.row.erp_customer_id === customer.value),
)
const reliableRows = computed(() => visible.value.filter((s) => !s.few))
const fewRows = computed(() => visible.value.filter((s) => s.few))

function cut(list) {
  return expanded.value ? list : list.slice(0, TOP_N)
}
const shownReliable = computed(() => cut(reliableRows.value))
const shownFew = computed(() => cut(fewRows.value))
const canToggle = computed(() => reliableRows.value.length > TOP_N || fewRows.value.length > TOP_N)

function onFilter() {
  expanded.value = false
}

function tip(s) {
  return s.parts
    .map((p) => t('eli5.overview.riskRanking.tipSeg', { key: p.key, score: p.score.toFixed(2) }))
    .join('\n')
}
function pctWidth(score) {
  return `${Math.min(100, (score / axisMax.value) * 100).toFixed(2)}%`
}
</script>

<template>
  <div class="rr">
    <p v-if="!scored.length" class="rr__empty">{{ t('eli5.overview.riskRanking.empty') }}</p>
    <template v-else>
      <div class="rr__head">
        <label class="rr__filter">
          {{ t('eli5.overview.riskRanking.filterLabel') }}
          <select v-model="customer" @change="onFilter">
            <option value="all">{{ t('eli5.overview.riskRanking.filterAll', { n: customers.length }) }}</option>
            <option v-for="[id, name] in customers" :key="id" :value="id">{{ id }} — {{ name }}</option>
          </select>
        </label>
        <div class="rr__legend">
          <span v-for="g in GROUPS" :key="g.key" class="rr__lg-group">
            <span v-if="g.key !== 'groupNone'" class="rr__lg-title">{{ t(`eli5.overview.riskRanking.${g.key}`) }}</span>
            <span v-for="k in g.items" :key="k" class="rr__lg"><i class="rr__sw" :class="`rr__seg--${k}`"></i>{{ k }}</span>
          </span>
          <span class="rr__lg-note">{{ t('eli5.overview.riskRanking.legendNote', { axis: axisMax, cap }) }}</span>
        </div>
      </div>

      <p v-if="!visible.length" class="rr__empty">{{ t('eli5.overview.riskRanking.emptyCustomer') }}</p>

      <ul v-if="shownReliable.length" class="rr__list">
        <li v-for="s in shownReliable" :key="s.row.erp_customer_id + s.row.model">
          <button type="button" class="rr__row" :title="tip(s)" @click="emit('select', s.row.erp_customer_id)">
            <span class="rr__label">
              <span class="rr__id">{{ s.row.erp_customer_id }}</span>
              <span class="rr__sub">
                {{ s.row.model }} · {{ s.row.shipment_qty.toLocaleString() }}
                <span v-if="s.row.is_odm" class="rr__odm">{{ t('eli5.overview.riskRanking.odm') }}</span>
              </span>
            </span>
            <span class="rr__track">
              <span v-for="p in s.parts" :key="p.key" class="rr__seg" :class="`rr__seg--${p.key}`" :style="{ width: pctWidth(p.score) }"></span>
            </span>
            <span class="rr__total">{{ s.row.score_total.toFixed(1) }}</span>
          </button>
        </li>
      </ul>

      <template v-if="shownFew.length">
        <div class="rr__few-title">
          {{ t('eli5.overview.riskRanking.fewTitle') }}
          <span class="rr__few-note">{{ t('eli5.overview.riskRanking.fewNote') }}</span>
        </div>
        <ul class="rr__list rr__list--few">
          <li v-for="s in shownFew" :key="s.row.erp_customer_id + s.row.model">
            <button type="button" class="rr__row" :title="tip(s)" @click="emit('select', s.row.erp_customer_id)">
              <span class="rr__label">
                <span class="rr__id">{{ s.row.erp_customer_id }}</span>
                <span class="rr__sub">
                  {{ s.row.model }} · {{ s.row.shipment_qty.toLocaleString() }}
                  <span v-if="s.row.is_odm" class="rr__odm">{{ t('eli5.overview.riskRanking.odm') }}</span>
                </span>
              </span>
              <span class="rr__track">
                <span v-for="p in s.parts" :key="p.key" class="rr__seg" :class="`rr__seg--${p.key}`" :style="{ width: pctWidth(p.score) }"></span>
              </span>
              <span class="rr__total">{{ s.row.score_total.toFixed(1) }}</span>
            </button>
          </li>
        </ul>
      </template>

      <button v-if="canToggle" type="button" class="rr__more" @click="expanded = !expanded">
        {{ expanded ? t('eli5.overview.riskRanking.showTop', { n: TOP_N }) : t('eli5.overview.riskRanking.showAll', { n: visible.length }) }}
      </button>
    </template>
  </div>
</template>

<style scoped>
.rr {
  min-width: 0;
  font-variant-numeric: tabular-nums;
}
.rr__empty {
  color: var(--e-muted);
  font-size: 13px;
  padding: 24px 0;
  text-align: center;
}
.rr__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 18px;
  margin-bottom: 12px;
}
.rr__filter {
  font-size: 12.5px;
  color: var(--e-muted);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.rr__filter select {
  font: inherit;
  font-size: 12.5px;
  color: var(--text-primary);
  background: var(--bg-surface);
  border: 1px solid var(--e-line);
  border-radius: 6px;
  padding: 3px 6px;
  max-width: 260px;
}
.rr__legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 14px;
  font-size: 12px;
  color: var(--e-muted);
}
.rr__lg-group,
.rr__lg {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.rr__lg-group { gap: 8px; }
.rr__lg-title { font-weight: 600; }
.rr__sw {
  width: 12px;
  height: 12px;
  border-radius: 2px;
  display: inline-block;
}
.rr__lg-note { margin-left: auto; font-size: 11.5px; }

.rr__list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.rr__row {
  display: grid;
  grid-template-columns: minmax(130px, 190px) minmax(0, 1fr) 40px;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 5px 4px;
  border: none;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  border-radius: 4px;
}
.rr__row:hover { background: var(--e-band); }
.rr__row:focus-visible { outline: 2px solid var(--e-accent); outline-offset: 1px; }
.rr__label { min-width: 0; display: block; }
.rr__id {
  display: block;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-primary);
}
.rr__sub {
  display: block;
  font-size: 11px;
  color: var(--e-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rr__odm {
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--e-muted);
  border: 1px solid var(--e-line);
  border-radius: 3px;
  padding: 0 3px;
  margin-left: 4px;
}
.rr__track {
  display: flex;
  height: 18px;
  background:
    linear-gradient(to right, transparent calc(33.333% - 1px), var(--e-line) calc(33.333% - 1px) 33.333%, transparent 33.333% calc(66.666% - 1px), var(--e-line) calc(66.666% - 1px) 66.666%, transparent 66.666%),
    var(--e-band);
  border-radius: 3px;
  overflow: hidden;
}
.rr__seg {
  height: 100%;
  box-shadow: inset -1.5px 0 0 var(--bg-surface);
}
.rr__total {
  font-size: 12.5px;
  font-weight: 700;
  text-align: right;
  color: var(--text-primary);
}
.rr__seg--RMA { background: var(--e-rank-rma); }
.rr__seg--DOA { background: var(--e-rank-doa); }
.rr__seg--Repair { background: var(--e-rank-repair); }
.rr__seg--FPY { background: var(--e-rank-fpy); }
.rr__seg--CFQR { background: var(--e-rank-cfqr); }

.rr__few-title {
  margin: 16px 0 6px;
  padding-top: 10px;
  border-top: 1px dashed var(--e-line);
  font-size: 12.5px;
  font-weight: 700;
  color: var(--e-muted);
}
.rr__few-note {
  font-weight: 400;
  font-size: 11.5px;
  margin-left: 8px;
}
.rr__list--few .rr__track { opacity: 0.8; }
.rr__more {
  margin-top: 10px;
  border: 1px solid var(--e-line);
  background: var(--bg-surface);
  color: var(--e-muted);
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  border-radius: 999px;
  padding: 4px 14px;
  cursor: pointer;
}
.rr__more:hover { color: var(--text-primary); }

@media (max-width: 600px) {
  .rr__row { grid-template-columns: minmax(100px, 130px) minmax(0, 1fr) 34px; gap: 8px; }
  .rr__lg-note { margin-left: 0; }
}
</style>
