<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { groupFactsByDomain, hasCitationData, citedFactIdsSet } from '../utils/aiFacts'

const { t } = useI18n()

const props = defineProps({
  factJson: { type: Object, default: () => ({}) },
  collapsible: { type: Boolean, default: false },
  showAuthoritativeNote: { type: Boolean, default: true },
})
const expanded = ref(false)

const numberedFacts = computed(() => (props.factJson && props.factJson.numbered_facts) || [])
const citationAvailable = computed(() => hasCitationData(props.factJson))
const citedIds = computed(() => (citationAvailable.value ? citedFactIdsSet(props.factJson) : new Set()))
const groups = computed(() => groupFactsByDomain(numberedFacts.value, citedIds.value))
const citedGroups = computed(() => groups.value.filter((g) => g.cited.length))
const uncitedGroups = computed(() => groups.value.filter((g) => g.uncited.length).map((g) => ({ ...g })))
const allGroups = computed(() => groups.value.filter((g) => g.uncited.length))
const citedCount = computed(() => citedIds.value.size)
const totalCount = computed(() => numberedFacts.value.length)
const uncitedCount = computed(() => totalCount.value - citedCount.value)
</script>

<template>
  <div class="fact-citation">
    <button
      v-if="collapsible && totalCount > 0"
      type="button"
      class="fc-toggle"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      {{ t('factCitationList.collapsedToggle', { total: totalCount }) }}
      <span class="fc-toggle-caret">{{ expanded ? '▾' : '▸' }}</span>
    </button>

  <div v-if="!collapsible || expanded || totalCount === 0">
    <template v-if="citationAvailable">
      <i18n-t keypath="factCitationList.summaryWithCited" tag="p" class="fc-summary">
        <template #total><b class="num">{{ totalCount }}</b></template>
        <template #cited><b class="num">{{ citedCount }}</b></template>
      </i18n-t>

      <div v-if="citedGroups.length" class="fc-section">
        <div class="fc-section-title">{{ t('factCitationList.citedSectionTitle') }}</div>
        <div v-for="g in citedGroups" :key="'cited-' + g.domain" class="fc-domain">
          <span class="fc-domain-label tag">{{ g.label }}</span>
          <dl class="fc-rows">
            <template v-for="f in g.cited" :key="f.id">
              <dt>{{ f.label }}</dt>
              <dd class="num">{{ f.value }}</dd>
            </template>
          </dl>
        </div>
      </div>

      <details v-if="uncitedGroups.length" class="fc-uncited">
        <summary>{{ t('factCitationList.uncitedSummary', { count: uncitedCount }) }}</summary>
        <div v-for="g in uncitedGroups" :key="'uncited-' + g.domain" class="fc-domain">
          <span class="fc-domain-label tag">{{ g.label }}</span>
          <dl class="fc-rows">
            <template v-for="f in g.uncited" :key="f.id">
              <dt>{{ f.label }}</dt>
              <dd class="num">{{ f.value }}</dd>
            </template>
          </dl>
        </div>
      </details>

      <p v-if="totalCount === 0" class="fc-disclaimer">
        {{ t('factCitationList.disclaimerZeroFacts') }}
      </p>
      <p v-else-if="showAuthoritativeNote" class="fc-disclaimer">
        {{ t('factCitationList.disclaimerAuthoritative') }}
      </p>
    </template>

    <template v-else-if="totalCount">
      <p class="fc-summary">
        {{ t('factCitationList.summaryTotalOnly', { total: totalCount }) }}
      </p>
      <div v-for="g in allGroups" :key="'all-' + g.domain" class="fc-domain">
        <span class="fc-domain-label tag">{{ g.label }}</span>
        <dl class="fc-rows">
          <template v-for="f in g.uncited" :key="f.id">
            <dt>{{ f.label }}</dt>
            <dd class="num">{{ f.value }}</dd>
          </template>
        </dl>
      </div>
      <p class="fc-disclaimer">
        {{ t('factCitationList.disclaimerNoCitationData') }}
      </p>
    </template>

    <p v-else class="fc-summary">{{ t('factCitationList.emptyMessage') }}</p>
  </div>
  </div>
</template>

<style scoped>
.fact-citation {
  margin-top: var(--sp-3);
  padding-top: var(--sp-3);
  border-top: 1px solid var(--border);
}
.fc-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: none;
  padding: 0;
  font-size: var(--fs-xs);
  color: var(--text-faint);
  cursor: pointer;
}
.fc-toggle:hover {
  color: var(--accent);
}
.fc-toggle-caret {
  font-size: 10px;
}
.fc-summary {
  margin: 0 0 var(--sp-3);
  font-size: var(--fs-sm);
  color: var(--text-body);
}
.fc-section-title {
  font-size: var(--fs-xs);
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-bottom: var(--sp-2);
}
.fc-domain {
  margin-bottom: var(--sp-3);
}
.fc-domain-label {
  margin-bottom: var(--sp-1);
}
.fc-rows {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 3px var(--sp-3);
  margin: var(--sp-1) 0 0;
}
.fc-rows dt {
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.fc-rows dd {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--text-body);
  text-align: right;
}
.fc-uncited {
  margin-top: var(--sp-3);
  padding-top: var(--sp-2);
  border-top: 1px dashed var(--border);
}
.fc-uncited summary {
  font-size: var(--fs-xs);
  color: var(--text-faint);
  cursor: pointer;
}
.fc-uncited summary:hover {
  color: var(--accent);
}
.fc-uncited .fc-domain {
  margin-top: var(--sp-3);
}
.fc-disclaimer {
  margin: var(--sp-3) 0 0;
  font-size: var(--fs-xs);
  color: var(--text-faint);
}
</style>
