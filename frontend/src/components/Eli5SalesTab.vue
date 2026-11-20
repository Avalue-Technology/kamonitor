<script setup>
import { computed, ref, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getCustomerEli5, getCustomerNarrative, regenerateCustomerNarrative } from '../api/endpoints'
import { useAsyncWatch } from '../composables/useAsync'
import { useSummaryLang } from '../composables/useSummaryLang'
import GapCard from './GapCard.vue'
import EmptyState from './EmptyState.vue'
import Eli5AiCard from './Eli5AiCard.vue'

const props = defineProps({
  id: { type: String, required: true },
})

const { t, locale } = useI18n()

const { data, loading, notFound, error } = useAsyncWatch(toRef(props, 'id'), getCustomerEli5, {
  optional: true,
})

const { effective: summaryLang } = useSummaryLang()
const {
  data: salesNarrative,
  loading: salesNarrativeLoading,
  error: salesNarrativeError,
} = useAsyncWatch(
  toRef(props, 'id'),
  (id) => getCustomerNarrative(id, 'sales_summary', summaryLang.value),
  { optional: true },
)

const salesNarrativeOverride = ref(null)
watch([toRef(props, 'id'), summaryLang], () => {
  salesNarrativeOverride.value = null
})
const displayedSalesNarrative = computed(() => salesNarrativeOverride.value ?? salesNarrative.value)
async function doRegenerateSales() {
  await regenerateCustomerNarrative(props.id, 'sales_summary', summaryLang.value)
  salesNarrativeOverride.value = await getCustomerNarrative(props.id, 'sales_summary', summaryLang.value)
}

const EN_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
function ym(dateStr) {
  if (!dateStr) return ''
  const [y, m] = dateStr.slice(0, 7).split('-')
  if (locale.value.startsWith('en')) return `${EN_MONTHS[parseInt(m, 10) - 1]} ${y}`
  return `${y}年${parseInt(m, 10)}月`
}

const metaLine = computed(() => {
  const c = data.value?.customer
  const w = data.value?.window
  if (!c || !w) return ''
  return t('eli5.salesTab.metaLine', {
    type: c.type_label,
    pct: c.odm_share_pct,
    start: ym(w.ttm_start),
    end: ym(w.ttm_end),
  })
})

const scorecard = computed(() => data.value?.chains?.find((c) => c.key === 'scorecard') || null)
const chainSteps = computed(() => (data.value?.chains || []).filter((c) => c.key !== 'scorecard'))
</script>

<template>
  <div class="eli5-sales-tab">
    <div class="eli5-band">
      <p v-if="metaLine" class="eli5-meta">{{ metaLine }}</p>
      <Eli5AiCard
        class="eli5-sales-ai"
        :narrative="displayedSalesNarrative"
        :loading="salesNarrativeLoading"
        :error="salesNarrativeError"
        :regenerate-fn="doRegenerateSales"
      />
    </div>

    <div v-if="loading" class="eli5-band eli5-loading">{{ t('eli5.salesTab.loading') }}</div>
    <div v-else-if="notFound" class="eli5-band">
      <EmptyState :message="t('eli5.salesTab.notFoundMessage')" :hint="t('eli5.salesTab.notFoundHint')" />
    </div>
    <div v-else-if="error" class="eli5-band">
      <EmptyState :message="t('eli5.salesTab.errorMessage')" :hint="error.message" />
    </div>
    <template v-else-if="data">
      <div class="eli5-band">
        <div class="eli5-sec-head">
          <div>
            <h3 class="eli5-h2">{{ t('eli5.salesTab.scorecardEyebrow') }}</h3>
          </div>
          <span class="eli5-note">{{ t('eli5.salesTab.scorecardNote') }}<router-link class="eli5-evidence-link" :to="`/eli5/customer/${id}/evidence/scorecard`">{{ t('eli5.salesTab.scorecardEvidenceLink') }}</router-link></span>
        </div>
        <div v-if="scorecard?.rows?.length" class="eli5-score">
          <article
            v-for="(row, idx) in scorecard.rows"
            :key="row.label"
            class="eli5-score-tile"
            :style="{ background: idx === 0 ? 'var(--e-t1)' : 'var(--e-t5)' }"
          >
            <div class="eli5-score-tile__label">{{ row.label }}</div>
            <div class="eli5-score-tile__big num">{{ row.headline }}</div>
            <div class="eli5-score-tile__cap" :style="{ color: row.hit == null ? 'var(--e-muted)' : row.hit ? 'var(--e-good)' : 'var(--e-bad)' }">
              {{ row.hit == null ? '' : row.hit ? '✓' : '✗' }} {{ row.caption }}
            </div>
            <div class="eli5-score-tile__det num">{{ row.detail }}</div>
          </article>
        </div>
      </div>

      <div class="eli5-band">
        <div class="eli5-sec-head">
          <div>
            <div class="eli5-eyebrow">{{ t('eli5.salesTab.chainsEyebrow') }}</div>
            <h3 class="eli5-h2">{{ t('eli5.salesTab.chainsTitle') }}</h3>
          </div>
          <span v-if="t('eli5.salesTab.chainsNote')" class="eli5-note">{{ t('eli5.salesTab.chainsNote') }}</span>
        </div>
        <div class="eli5-chains">
          <GapCard v-for="(chain, idx) in chainSteps" :key="chain.key" :chain="chain" :step="idx + 1" :erp-customer-id="id" />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>

.eli5-evidence-link {
  margin-left: 12px;
  color: var(--e-muted);
  text-decoration: none;
  white-space: nowrap;
}
.eli5-evidence-link:hover {
  color: var(--accent);
  text-decoration: underline;
}

.eli5-meta {
  margin: 0 0 12px;
  font-size: 13.5px;
  color: var(--e-muted);
}

.eli5-sales-ai {
  margin-bottom: 0;
}

.eli5-loading {
  text-align: center;
  color: var(--e-muted);
  font-size: 14px;
  padding: 32px 0;
}

.eli5-sec-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.eli5-eyebrow {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--e-faint);
  margin-bottom: 4px;
}

.eli5-h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: var(--e-ink);
}

.eli5-note {
  font-size: 12.5px;
  color: var(--e-muted);
  white-space: nowrap;
}

.eli5-score {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}

.eli5-score-tile {
  border-radius: var(--e-radius);
  padding: 22px 24px;
  display: grid;
  gap: 6px;
}

.eli5-score-tile__label {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--e-muted);
}

.eli5-score-tile__big {
  font-size: 40px;
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.1;
  color: var(--e-ink);
}

.eli5-score-tile__cap {
  font-size: 14px;
  font-weight: 700;
}

.eli5-score-tile__det {
  font-size: 13.5px;
  color: var(--e-muted);
}

.eli5-chains {
  display: grid;
  gap: 14px;
}

@media (max-width: 1000px) {
  .eli5-score {
    grid-template-columns: 1fr;
  }
}
</style>
