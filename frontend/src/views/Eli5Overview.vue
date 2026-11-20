<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getEli5QaOverview, getEli5GrowthMatrix, getEli5ModelMatrix } from '../api/endpoints'
import { useAsync } from '../composables/useAsync'
import EmptyState from '../components/EmptyState.vue'
import Eli5Hero from '../components/Eli5Hero.vue'
import Eli5QaBubble from '../components/Eli5QaBubble.vue'
import Eli5GrowthBubble from '../components/Eli5GrowthBubble.vue'
import Eli5ModelMatrix from '../components/Eli5ModelMatrix.vue'
import Eli5RiskRanking from '../components/Eli5RiskRanking.vue'
import Eli5ChartReading from '../components/Eli5ChartReading.vue'
import Eli5QaCard from '../components/Eli5QaCard.vue'

const router = useRouter()
const { t } = useI18n()

const { data, loading, notFound, error } = useAsync(getEli5QaOverview, { optional: true, localized: true })

const redCount = computed(() => {
  if (!data.value) return 0
  return data.value.cards.filter((c) => c.metrics.some((m) => m.risk === 'R')).length
})

function goCustomer(erpCustomerId) {
  router.push(`/eli5/customer/${erpCustomerId}`)
}

function goCustomerSales(erpCustomerId) {
  router.push({ path: `/eli5/customer/${erpCustomerId}`, query: { tab: 'sales' } })
}

const growthData = ref(null)
const growthLoading = ref(true)
const growthError = ref(null)
onMounted(async () => {
  try {
    growthData.value = await getEli5GrowthMatrix()
  } catch (e) {
    growthError.value = e
  } finally {
    growthLoading.value = false
  }
})

const qualityTab = ref('quadrant')
const matrixData = ref(null)
const matrixLoading = ref(false)
const matrixError = ref(null)
async function ensureMatrixLoaded() {
  if (matrixData.value || matrixLoading.value) return
  matrixLoading.value = true
  matrixError.value = null
  try {
    matrixData.value = await getEli5ModelMatrix()
  } catch (e) {
    matrixError.value = e
  } finally {
    matrixLoading.value = false
  }
}
const QUALITY_TABS = [
  { key: 'quadrant', label: 'eli5.overview.tabQuadrant' },
  { key: 'matrix', label: 'eli5.overview.tabMatrix' },
  { key: 'ranking', label: 'eli5.overview.tabRanking' },
]
function setQualityTab(key) {
  qualityTab.value = key
  if (key !== 'quadrant') ensureMatrixLoaded()
}

function useReadingSwitch(key) {
  let initial = true
  try {
    initial = localStorage.getItem(key) !== 'off'
  } catch {
  }
  const on = ref(initial)
  function toggle() {
    on.value = !on.value
    try {
      localStorage.setItem(key, on.value ? 'on' : 'off')
    } catch {
    }
  }
  return { on, toggle }
}
const { on: qualityReadingOn, toggle: toggleQualityReading } = useReadingSwitch('kam.growthReadingPanel')
const { on: salesReadingOn, toggle: toggleSalesReading } = useReadingSwitch('kam.salesReadingPanel')
const qualityAvail = ref(null)
const growthAvail = ref(null)
const showQualitySwitch = computed(() => qualityAvail.value !== false)
const showSalesSwitch = computed(() => !!growthData.value && growthAvail.value !== false)
const showQualityPanel = computed(() => qualityReadingOn.value && qualityAvail.value !== false)
const showGrowthPanel = computed(() => salesReadingOn.value && !!growthData.value && growthAvail.value !== false)

const companyYoyNote = computed(() => {
  if (!growthData.value || growthData.value.company_yoy_pct === null || growthData.value.company_yoy_pct === undefined) return ''
  return t('eli5.overview.growthCompanyYoy', { pct: growthData.value.company_yoy_pct.toFixed(1) })
})
</script>

<template>
  <div class="eli5-scope eli5-overview">
    <div v-if="loading" class="eli5-overview__loading">{{ t('eli5.overview.loading') }}</div>
    <EmptyState
      v-else-if="notFound"
      :message="t('eli5.overview.notFoundMessage')"
      :hint="t('eli5.overview.notFoundHint')"
    />
    <EmptyState v-else-if="error" :message="t('eli5.overview.errorMessage')" :hint="error.message" />
    <template v-else-if="data">
      <Eli5Hero :period="data.period" :count="data.cards.length" />

      <section class="eli5-band">
        <div class="eli5-sec-head">
          <div>
            <div class="eli5-eyebrow">{{ t(`eli5.overview.qualityHead.${qualityTab}.eyebrow`) }}</div>
            <h3 class="eli5-h2">{{ t(`eli5.overview.qualityHead.${qualityTab}.title`) }}</h3>
          </div>
          <div class="eli5-sec-head__right">
            <div class="eli5-sec-head__controls">
              <button
                v-if="showQualitySwitch"
                type="button"
                role="switch"
                :aria-checked="qualityReadingOn"
                class="eli5-ai-switch eli5-ai-switch--quality"
                :class="{ 'eli5-ai-switch--on': qualityReadingOn }"
                @click="toggleQualityReading"
              >
                <span class="eli5-ai-switch__track" aria-hidden="true"><span class="eli5-ai-switch__thumb"></span></span>
                {{ t('eli5.chartReading.label') }}
              </button>
              <div class="eli5-chart-toggle" role="tablist" :aria-label="t('eli5.overview.tabsLabel')">
                <button
                  v-for="tab in QUALITY_TABS"
                  :key="tab.key"
                  type="button"
                  role="tab"
                  :aria-selected="qualityTab === tab.key"
                  class="eli5-chart-toggle__btn"
                  :class="{ 'eli5-chart-toggle__btn--active': qualityTab === tab.key }"
                  @click="setQualityTab(tab.key)"
                >
                  {{ t(tab.label) }}
                </button>
              </div>
            </div>
            <span v-if="qualityTab !== 'ranking'" class="eli5-note">{{
              qualityTab === 'quadrant' ? t('eli5.overview.redCount', { count: redCount }, redCount) : t('eli5.overview.qualityHead.matrix.note')
            }}</span>
          </div>
        </div>
        <div class="eli5-chart-row" :class="{ 'eli5-chart-row--panel': showQualityPanel }">
          <div class="eli5-chart-row__chart">
            <Eli5QaBubble
              v-if="qualityTab === 'quadrant'"
              :points="data.points"
              :excluded-note="data.excluded_note"
              @select="goCustomer"
            />
            <div v-else-if="matrixLoading && !matrixData" class="eli5-overview__loading">
              {{ t('eli5.overview.loading') }}
            </div>
            <EmptyState v-else-if="matrixError" :message="t('eli5.overview.errorMessage')" :hint="matrixError.message" />
            <Eli5ModelMatrix v-else-if="matrixData && qualityTab === 'matrix'" :data="matrixData" @select="goCustomer" />
            <Eli5RiskRanking v-else-if="matrixData && qualityTab === 'ranking'" :data="matrixData" @select="goCustomer" />
          </div>
          <Eli5ChartReading
            v-if="qualityReadingOn"
            kind="quality"
            @update:available="qualityAvail = $event"
          />
        </div>
      </section>

      <section class="eli5-band">
        <div class="eli5-sec-head">
          <div>
            <div class="eli5-eyebrow">{{ t('eli5.overview.growthEyebrow') }}</div>
            <h3 class="eli5-h2">{{ t('eli5.overview.growthTitle') }}</h3>
          </div>
          <div class="eli5-sec-head__right">
            <div class="eli5-sec-head__controls">
              <button
                v-if="showSalesSwitch"
                type="button"
                role="switch"
                :aria-checked="salesReadingOn"
                class="eli5-ai-switch eli5-ai-switch--sales"
                :class="{ 'eli5-ai-switch--on': salesReadingOn }"
                @click="toggleSalesReading"
              >
                <span class="eli5-ai-switch__track" aria-hidden="true"><span class="eli5-ai-switch__thumb"></span></span>
                {{ t('eli5.chartReading.label') }}
              </button>
            </div>
            <span class="eli5-note">{{ companyYoyNote }}</span>
          </div>
        </div>
        <div class="eli5-chart-row" :class="{ 'eli5-chart-row--panel': showGrowthPanel }">
          <div class="eli5-chart-row__chart">
            <div v-if="growthLoading" class="eli5-overview__loading">{{ t('eli5.overview.loading') }}</div>
            <EmptyState
              v-else-if="growthError"
              :message="t('eli5.overview.errorMessage')"
              :hint="growthError.message"
            />
            <Eli5GrowthBubble
              v-else-if="growthData"
              :points="growthData.points"
              :new-customers="growthData.new_customers"
              :share-threshold-pct="growthData.share_threshold_pct"
              @select="goCustomerSales"
            />
          </div>
          <Eli5ChartReading
            v-if="salesReadingOn && growthData"
            kind="growth"
            @update:available="growthAvail = $event"
          />
        </div>
      </section>

      <section class="eli5-band eli5-band--tint">
        <div class="eli5-sec-head">
          <div>
            <div class="eli5-eyebrow">{{ t('eli5.overview.byCustomerEyebrow') }}</div>
            <h3 class="eli5-h2">{{ t('eli5.overview.qaCardsTitle') }}</h3>
          </div>
          <span class="eli5-note">{{ t('eli5.overview.qaCardsNote') }}</span>
        </div>
        <div class="eli5-overview__cards">
          <Eli5QaCard
            v-for="card in data.cards"
            :key="card.erp_customer_id"
            :card="card"
            @select="goCustomer"
          />
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.eli5-overview__loading {
  text-align: center;
  color: var(--e-muted, var(--text-muted));
  font-size: var(--fs-md);
  padding: var(--sp-6) 0;
}

.eli5-overview__cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

@media (max-width: 1000px) {
  .eli5-overview__cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

.eli5-sec-head__right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
}

.eli5-sec-head__controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.eli5-ai-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  color: var(--e-muted);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  padding: 4px 2px;
}
.eli5-ai-switch--on {
  color: var(--e-ai-ink);
}
.eli5-ai-switch:focus-visible {
  outline: 2px solid var(--e-ai-ink);
  outline-offset: 2px;
  border-radius: 6px;
}
.eli5-ai-switch__track {
  width: 28px;
  height: 16px;
  border-radius: 999px;
  background: var(--e-line);
  position: relative;
  transition: background 0.15s ease;
}
.eli5-ai-switch--on .eli5-ai-switch__track {
  background: var(--e-ai-ink);
}
.eli5-ai-switch__thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--e-surface);
  transition: transform 0.15s ease;
}
.eli5-ai-switch--on .eli5-ai-switch__thumb {
  transform: translateX(12px);
}

.eli5-chart-row {
  display: block;
}
.eli5-chart-row--panel {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: var(--sp-4, 16px);
  align-items: start;
}
.eli5-chart-row__chart {
  min-width: 0;
}
@media (max-width: 900px) {
  .eli5-chart-row--panel {
    grid-template-columns: minmax(0, 1fr);
  }
}

.eli5-chart-toggle {
  display: inline-flex;
  border: 1px solid var(--e-line);
  border-radius: 999px;
  padding: 2px;
  background: var(--e-band);
}

.eli5-chart-toggle__btn {
  border: none;
  background: transparent;
  color: var(--e-muted);
  font-size: 12.5px;
  font-weight: 600;
  padding: 5px 14px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.eli5-chart-toggle__btn:focus-visible {
  outline: 2px solid var(--e-accent);
  outline-offset: 1px;
}

.eli5-chart-toggle__btn--active {
  background: var(--e-accent);
  color: var(--on-solid);
}

.eli5-crossfade-enter-active,
.eli5-crossfade-leave-active {
  transition: opacity 0.2s ease;
}
.eli5-crossfade-enter-from,
.eli5-crossfade-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .eli5-crossfade-enter-active,
  .eli5-crossfade-leave-active {
    transition: none;
  }
}
</style>
