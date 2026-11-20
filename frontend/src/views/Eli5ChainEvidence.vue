<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getChainEvidence } from '../api/endpoints'
import { useAsyncWatch } from '../composables/useAsync'
import { useCustomerDirectory } from '../composables/useCustomerDirectory'
import { formatInt, formatUSDFull } from '../utils/format'

const props = defineProps({
  id: { type: String, required: true },
  chain: { type: String, required: true },
})

const { t } = useI18n()
const { directory } = useCustomerDirectory()

const source = computed(() => ({ id: props.id, chain: props.chain }))
const { data, loading, notFound, error } = useAsyncWatch(
  source,
  (key) => getChainEvidence(key.id, key.chain),
  { optional: true },
)

const customerName = computed(() => {
  const c = directory.value.find((x) => x.erp_customer_id === props.id)
  return c ? c.display_name : props.id
})

function fmt(value, kind) {
  if (value == null) return '—'
  if (kind === 'money') return formatUSDFull(value)
  if (kind === 'int') return formatInt(value)
  if (kind === 'pct') return `${value}%`
  return value
}

function cell(row, col) {
  if (col.kind === 'i18n') {
    return row[col.key] ? t(row[col.key], row[`${col.key}_params`] || {}) : '—'
  }
  return fmt(row[col.key], col.kind)
}

function cellClass(row, col) {
  return {
    num: col.kind === 'money' || col.kind === 'int',
    [`eli5-ev-tone--${row.tone}`]: col.kind === 'i18n' && !!row.tone,
  }
}

function tablesOf(section) {
  if (section.groups == null) {
    return [{ key: 'all', label: null, params: {}, rows: section.rows }]
  }
  return section.groups.map((g) => ({
    key: g.key,
    label: g.label,
    params: g.params,
    rows: section.rows.filter((r) => r.group === g.key),
  }))
}

const expanded = ref({})
function shownRows(section, table) {
  const key = `${section.key}:${table.key}`
  return expanded.value[key] ? table.rows : table.rows.slice(0, 10)
}
function toggle(section, table) {
  const key = `${section.key}:${table.key}`
  expanded.value = { ...expanded.value, [key]: !expanded.value[key] }
}
</script>

<template>
  <div class="eli5-ev-page">
    <div class="eli5-ev-back">
      <router-link :to="`/eli5/customer/${props.id}?tab=sales`">{{ t('eli5.evidence.back', { name: customerName }) }}</router-link>
    </div>

    <div v-if="loading" class="eli5-ev-loading">{{ t('eli5.evidence.loading') }}</div>
    <div v-else-if="notFound" class="eli5-ev-notice">{{ t('eli5.evidence.notFound') }}</div>
    <div v-else-if="error" class="eli5-ev-notice">{{ t('eli5.evidence.errorMessage', { message: error.message }) }}</div>

    <template v-else-if="data">
      <header class="eli5-ev-header">
        <h1 class="eli5-ev-title">{{ t(`eli5.evidence.titles.${props.chain}`) }}</h1>
        <p class="eli5-ev-rule">{{ t(`eli5.evidence.notes.${props.chain}`) }}</p>
      </header>

      <section v-for="section in data.sections" :key="section.key" class="eli5-ev-section">
        <h2>{{ t(section.title, section.title_params) }}</h2>

        <div class="eli5-ev-summary">
          <div v-for="(tile, i) in section.tiles" :key="i" class="eli5-ev-summary-group">
            <div class="eli5-ev-summary-title">{{ t(tile.label, tile.params) }}</div>
            <div class="eli5-ev-tile-value">{{ fmt(tile.value, tile.kind) }}</div>
          </div>
        </div>

        <div v-for="table in tablesOf(section)" :key="table.key" class="eli5-ev-block">
          <h3 v-if="table.label != null">{{ t(table.label, table.params) }}（{{ table.rows.length }}）</h3>
          <div v-if="!table.rows.length" class="eli5-ev-empty">{{ t('eli5.evidence.noRows') }}</div>
          <template v-else>
            <div class="eli5-ev-table-wrap">
              <table class="eli5-ev-table">
                <thead>
                  <tr>
                    <th v-for="col in section.columns" :key="col.key" :class="{ num: col.kind === 'money' || col.kind === 'int' }">{{ t(col.label) }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(r, i) in shownRows(section, table)" :key="i">
                    <td v-for="col in section.columns" :key="col.key" :class="cellClass(r, col)">{{ cell(r, col) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <button v-if="table.rows.length > 10" type="button" class="eli5-ev-toggle" @click="toggle(section, table)">
              {{ expanded[`${section.key}:${table.key}`] ? t('eli5.evidence.collapse') : t('eli5.evidence.showAll', { count: table.rows.length }) }}
            </button>
          </template>
        </div>
      </section>
    </template>
  </div>
</template>
<style scoped>
.eli5-ev-page {
  max-width: 1080px;
  margin: 0 auto;
  padding: var(--sp-6) var(--sp-4) var(--sp-7);
}

.eli5-ev-back {
  margin-bottom: var(--sp-3);
  font-size: var(--fs-sm);
}
.eli5-ev-back a {
  color: var(--text-muted);
  text-decoration: none;
}
.eli5-ev-back a:hover {
  color: var(--accent);
  text-decoration: underline;
}

.eli5-ev-loading,
.eli5-ev-notice {
  text-align: center;
  color: var(--text-muted);
  font-size: var(--fs-md);
  padding: var(--sp-6) 0;
}

.eli5-ev-header {
  margin-bottom: var(--sp-5);
}
.eli5-ev-title {
  font-size: var(--fs-2xl);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}
.eli5-ev-rule {
  margin: var(--sp-1) 0 0;
  font-size: var(--fs-sm);
  color: var(--text-muted);
}

.eli5-ev-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--sp-3);
  margin-bottom: var(--sp-6);
}
.eli5-ev-summary-group {
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: var(--sp-3);
}
.eli5-ev-summary-title {
  font-size: var(--fs-xs);
  font-weight: 700;
  color: var(--text-faint);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: var(--sp-1);
}
.eli5-ev-summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.eli5-ev-summary-row strong {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  color: var(--text-primary);
  font-size: var(--fs-md);
  font-variant-numeric: tabular-nums;
}

.eli5-ev-block {
  margin-bottom: var(--sp-6);
}
.eli5-ev-block h2 {
  font-size: var(--fs-md);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 var(--sp-3);
}

.eli5-ev-empty {
  color: var(--text-faint);
  font-size: var(--fs-sm);
  padding: var(--sp-3) 0;
}

.eli5-ev-table-wrap {
  overflow-x: auto;
}

.eli5-ev-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}
.eli5-ev-table th {
  text-align: left;
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--border-strong);
  color: var(--text-muted);
  white-space: nowrap;
}
.eli5-ev-table td {
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.eli5-ev-toggle {
  margin-top: var(--sp-2);
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--accent);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
}
.eli5-ev-toggle:hover {
  text-decoration: underline;
}
.eli5-ev-tile-value {
  margin-top: var(--sp-1);
  font-size: var(--fs-lg);
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.eli5-ev-section {
  margin-bottom: var(--sp-7);
}
.eli5-ev-section > h2 {
  font-size: var(--fs-lg);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 var(--sp-3);
}
.eli5-ev-block h3 {
  font-size: var(--fs-md);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 var(--sp-3);
}
.eli5-ev-table td.num,
.eli5-ev-table th.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.eli5-ev-tone--bad {
  color: var(--e-bad);
  font-weight: 700;
}
.eli5-ev-tone--muted {
  color: var(--text-faint);
}
</style>
