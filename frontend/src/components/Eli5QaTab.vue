<script setup>
import { computed, ref, toRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getEli5QaCustomer, getCustomerNarrative, regenerateCustomerNarrative } from '../api/endpoints'
import { useAsyncWatch } from '../composables/useAsync'
import { useSummaryLang } from '../composables/useSummaryLang'
import { formatPeriod } from '../utils/format'
import EmptyState from './EmptyState.vue'
import Eli5AiCard from './Eli5AiCard.vue'
import Eli5QaKpiTile from './Eli5QaKpiTile.vue'

const props = defineProps({
  id: { type: String, required: true },
})

const router = useRouter()
const { t } = useI18n()

const { data, loading, notFound, error } = useAsyncWatch(toRef(props, 'id'), getEli5QaCustomer, {
  optional: true,
})

const { effective: summaryLang } = useSummaryLang()
const {
  data: qualityNarrative,
  loading: qualityNarrativeLoading,
  error: qualityNarrativeError,
} = useAsyncWatch(
  toRef(props, 'id'),
  (id) => getCustomerNarrative(id, 'quality_summary', summaryLang.value),
  { optional: true },
)

const qualityNarrativeOverride = ref(null)
watch([toRef(props, 'id'), summaryLang], () => {
  qualityNarrativeOverride.value = null
})
const displayedQualityNarrative = computed(() => qualityNarrativeOverride.value ?? qualityNarrative.value)
async function doRegenerateQuality() {
  await regenerateCustomerNarrative(props.id, 'quality_summary', summaryLang.value)
  qualityNarrativeOverride.value = await getCustomerNarrative(props.id, 'quality_summary', summaryLang.value)
}

const METRIC_KEYS = ['DOA', 'RMA', 'CFQR', 'FPY', 'Repair']
const TINTS = ['var(--e-t1)', 'var(--e-t2)', 'var(--e-t3)', 'var(--e-t4)', 'var(--e-t5)']
const TREND_N = 6

function fmtN(n) {
  return n === null || n === undefined ? '—' : n.toLocaleString('en-US')
}

const kpiTiles = computed(() => {
  const trend = data.value?.trend
  const targets = data.value?.trend_targets
  if (!trend) return []
  return (data.value.kpis || []).map((kpi, i) => ({
    key: kpi.key,
    kpi,
    trendPoints: (trend[kpi.key] || []).slice(-TREND_N),
    target: targets?.[kpi.key] ?? null,
    tint: TINTS[i % TINTS.length],
  }))
})

function goModel(model) {
  router.push(`/eli5/customer/${props.id}/model/${model}?report=${data.value?.report_id ?? ''}`)
}

const topModels = computed(() => (data.value?.top_models ?? []).filter((m) => m.score > 0).slice(0, 3))

const totalShip = computed(() => (data.value?.models ?? []).reduce((s, m) => s + (m.shipment_qty || 0), 0))
</script>

<template>
  <div class="eli5-qa-tab">
    <div v-if="loading" class="eli5-qa-loading">{{ t('eli5.qaTab.loading') }}</div>
    <EmptyState
      v-else-if="notFound"
      :message="t('eli5.qaTab.notFoundMessage')"
      :hint="t('eli5.qaTab.notFoundHint')"
    />
    <EmptyState v-else-if="error" :message="t('eli5.qaTab.errorMessage')" :hint="error.message" />

    <template v-else-if="data">
      <section class="eli5-band">
        <p class="eli5-meta num eli5-qa-tab__period">
          {{ t('eli5.qaTab.periodNote', { period: formatPeriod(data.period) }) }}
        </p>
        <Eli5AiCard
          :narrative="displayedQualityNarrative"
          :loading="qualityNarrativeLoading"
          :error="qualityNarrativeError"
          :regenerate-fn="doRegenerateQuality"
        />
      </section>

      <section class="eli5-band">
        <div class="eli5-sec-head">
          <div>
            <div class="eli5-eyebrow">{{ t('eli5.qaTab.kpiEyebrow') }}</div>
            <h3 class="eli5-h2">{{ t('eli5.qaTab.kpiTitle') }}</h3>
          </div>
          <span class="eli5-note">{{ t('eli5.qaTab.kpiNote') }}</span>
        </div>
        <div class="eli5-qa-tab__kpigrid">
          <Eli5QaKpiTile
            v-for="tile in kpiTiles"
            :key="tile.key"
            :kpi="tile.kpi"
            :trend-points="tile.trendPoints"
            :target="tile.target"
            :tint="tile.tint"
          />
        </div>
      </section>

      <section class="eli5-band eli5-band--tint">
        <div class="eli5-sec-head">
          <div>
            <div class="eli5-eyebrow">{{ t('eli5.qaTab.top3Eyebrow') }}</div>
            <h3 class="eli5-h2">{{ t('eli5.qaTab.top3Title') }}</h3>
          </div>
          <span class="eli5-note">{{ t('eli5.qaTab.top3Note') }}</span>
        </div>
        <p v-if="!topModels.length" class="eli5-qa-tab__empty">{{ t('eli5.qaTab.top3Empty') }}</p>
        <div v-else class="eli5-qa-tab__top3">
          <article
            v-for="m in topModels"
            :key="m.model"
            class="eli5-qa-model"
            role="button"
            tabindex="0"
            @click="goModel(m.model)"
            @keydown.enter="goModel(m.model)"
          >
            <div class="eli5-qa-model__head">
              <span class="eli5-qa-model__name" :class="`eli5-qa-model__name--${m.overall_risk}`">{{ m.model }}</span>
              <span class="eli5-note num">{{ t('eli5.qaTab.shipmentQty', { count: fmtN(m.shipment_qty) }) }}</span>
            </div>
            <div class="eli5-qa-model__score">
              <div class="eli5-qa-model__score-row">
                <span>{{ t('eli5.qaTab.scoreLabel') }}</span>
                <span class="num"><b>{{ m.score }}</b> / 10</span>
              </div>
              <div class="eli5-qa-model__meter" aria-hidden="true">
                <i v-for="n in 10" :key="n" :class="{ on: n <= m.score }"></i>
              </div>
            </div>
            <ul class="eli5-qa-model__flags">
              <li v-for="f in m.flagged" :key="f.key">
                <span class="eli5-dot" :class="'eli5-dot--' + f.risk"></span>
                <span>{{ f.label }}</span>
                <b class="num">{{ f.display }}</b>
              </li>
            </ul>
          </article>
        </div>
      </section>

      <section class="eli5-band">
        <div class="eli5-sec-head">
          <div>
            <div class="eli5-eyebrow">{{ t('eli5.qaTab.detailEyebrow') }}</div>
            <h3 class="eli5-h2">{{ t('eli5.qaTab.detailTitle') }}</h3>
          </div>
          <span class="eli5-note num">{{ t('eli5.qaTab.detailNote', { count: data.models.length, qty: fmtN(totalShip) }) }}</span>
        </div>
        <div class="eli5-table-wrap">
          <table class="eli5-table">
            <thead>
              <tr>
                <th>{{ t('eli5.qaTab.colModel') }}</th>
                <th class="r">{{ t('eli5.qaTab.colShipmentQty') }}</th>
                <th class="r">{{ t('eli5.qaTab.colDoa') }}</th>
                <th class="r">{{ t('eli5.qaTab.colRma') }}</th>
                <th class="r">{{ t('eli5.qaTab.colCfqr') }}</th>
                <th class="r">{{ t('eli5.qaTab.colFpy') }}</th>
                <th class="r">{{ t('eli5.qaTab.colRepairRate') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="m in data.models"
                :key="m.model"
                class="eli5-qa-tab__row"
                @click="goModel(m.model)"
              >
                <td class="eli5-qa-tab__model-name">{{ m.model }}</td>
                <td class="r num">{{ fmtN(m.shipment_qty) }}</td>
                <td v-for="k in METRIC_KEYS" :key="k" class="r">
                  <span class="eli5-qa-tab__cell num">
                    <span class="eli5-dot" :class="'eli5-dot--' + m.metrics?.[k]?.risk"></span>
                    <span>{{ m.metrics?.[k]?.display ?? '—' }}</span>
                  </span>
                </td>
              </tr>
              <tr v-if="!data.models?.length">
                <td colspan="7" class="eli5-qa-tab__empty-row">{{ t('eli5.qaTab.emptyModelsRow') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.eli5-qa-loading {
  text-align: center;
  color: var(--e-muted);
  font-size: 15px;
  padding: 40px 0;
}

.eli5-qa-tab__period {
  margin: 0 0 14px;
}

.eli5-qa-tab__kpigrid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 14px;
}
@media (max-width: 900px) {
  .eli5-qa-tab__kpigrid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.eli5-qa-tab__empty {
  margin: 0;
  color: var(--e-faint);
  font-size: 13.5px;
}

.eli5-qa-tab__top3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}
@media (max-width: 900px) {
  .eli5-qa-tab__top3 {
    grid-template-columns: 1fr;
  }
}

.eli5-qa-model {
  background: var(--e-surface);
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 20px;
  display: grid;
  gap: 12px;
  cursor: pointer;
  transition: background-color 0.15s ease;
}
.eli5-qa-model:hover {
  background: var(--e-band-soft);
}
.eli5-qa-model:focus-visible {
  outline: none;
  border-color: var(--e-accent);
  box-shadow: 0 0 0 2px var(--e-accent-soft);
}

.eli5-qa-model__head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
}
.eli5-qa-model__name {
  font-size: 17px;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: var(--e-ink);
  padding-left: 10px;
  border-left: 3px solid transparent;
}
.eli5-qa-model__name--R {
  border-left-color: var(--risk-r);
}
.eli5-qa-model__name--Y {
  border-left-color: var(--risk-y);
}
.eli5-qa-model__name--G {
  border-left-color: var(--risk-g);
}

.eli5-qa-model__score {
  display: grid;
  gap: 6px;
}
.eli5-qa-model__score-row {
  display: flex;
  justify-content: space-between;
  font-size: 12.5px;
  color: var(--e-muted);
}
.eli5-qa-model__meter {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 3px;
}
.eli5-qa-model__meter i {
  height: 6px;
  border-radius: 2px;
  background: var(--e-line);
}
.eli5-qa-model__meter i.on {
  background: var(--e-ink);
}

.eli5-qa-model__flags {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 7px;
}
.eli5-qa-model__flags li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  color: var(--e-ink);
}
.eli5-qa-model__flags li b {
  margin-left: auto;
  font-weight: 700;
}

.eli5-qa-tab__model-name {
  font-weight: 600;
  color: var(--e-ink);
}

.eli5-qa-tab__row {
  cursor: pointer;
}
.eli5-qa-tab__row:hover {
  background: var(--e-band);
}

.eli5-qa-tab__cell {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.eli5-qa-tab__empty-row {
  text-align: center;
  color: var(--e-faint);
  padding: 24px 0;
}
</style>
