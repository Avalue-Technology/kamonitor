<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  data: { type: Object, required: true },
})
const emit = defineEmits(['select'])
const { t } = useI18n()

const models = computed(() => props.data.shared_models || [])

const customers = computed(() => {
  const set = new Set(models.value)
  const byId = new Map()
  for (const r of props.data.rows || []) {
    if (!set.has(r.model)) continue
    if (!byId.has(r.erp_customer_id)) {
      byId.set(r.erp_customer_id, { id: r.erp_customer_id, name: r.display_name, period: r.period, cells: new Map() })
    }
    byId.get(r.erp_customer_id).cells.set(r.model, r)
  }
  const list = [...byId.values()].map((c) => {
    const known = [...c.cells.values()]
      .map((r) => r.metrics?.RMA?.value)
      .filter((v) => v !== null && v !== undefined)
    return { ...c, worst: known.length ? Math.max(...known) : -1 }
  })
  return list.sort((a, b) => b.worst - a.worst || a.id.localeCompare(b.id))
})

function rma(row) {
  return row.metrics?.RMA || null
}

function cellKind(row) {
  const m = rma(row)
  if (!m || m.value === null || m.value === undefined || m.reliable === false) return 'hatched'
  if (m.risk === 'R') return 'r'
  if (m.risk === 'Y') return 'y'
  if (m.value === 0) return 'zero'
  return 'g'
}

function pct(v) {
  return `${(v * 100).toFixed(2)}%`
}

function cellText(row) {
  const k = cellKind(row)
  return k === 'hatched' ? '' : pct(rma(row).value)
}

function tip(c, row) {
  const m = rma(row)
  const lines = [`${c.id} ${c.name}`, row.model, t('eli5.overview.modelMatrix.tipShip', { qty: row.shipment_qty.toLocaleString() })]
  if (m && m.value !== null && m.value !== undefined) {
    lines.push(t('eli5.overview.modelMatrix.tipRma', { pct: pct(m.value), count: m.count ?? 0 }))
    if (m.reliable === false) lines.push(t('eli5.overview.modelMatrix.tipFew', { min: props.data.min_qty }))
  } else {
    lines.push(t('eli5.overview.modelMatrix.tipNoRma'))
  }
  return lines.join('\n')
}
</script>

<template>
  <div class="mm">
    <p v-if="!customers.length" class="mm__empty">{{ t('eli5.overview.modelMatrix.noShared') }}</p>
    <template v-else>
      <div class="mm__scroll">
        <table class="mm__table">
          <thead>
            <tr>
              <th class="mm__corner">{{ t('eli5.overview.modelMatrix.thCustomer') }}</th>
              <th v-for="m in models" :key="m" class="mm__col"><span>{{ m }}</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in customers" :key="c.id">
              <th class="mm__row" scope="row">
                <span class="mm__id">{{ c.id }}</span>
                <span class="mm__name">{{ c.name }}</span>
              </th>
              <template v-for="m in models" :key="m">
                <td v-if="!c.cells.get(m)" class="mm__cell mm__cell--none"></td>
                <td v-else class="mm__cell mm__cell--hit">
                  <button
                    type="button"
                    class="mm__btn"
                    :class="`mm__btn--${cellKind(c.cells.get(m))}`"
                    :title="tip(c, c.cells.get(m))"
                    :aria-label="tip(c, c.cells.get(m)).replace(/\n/g, ', ')"
                    @click="emit('select', c.id)"
                  >{{ cellText(c.cells.get(m)) }}</button>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="mm__legend" aria-hidden="true">
        <span class="mm__lg"><i class="mm__sw mm__sw--zero"></i>{{ t('eli5.overview.modelMatrix.legendZero') }}</span>
        <span class="mm__lg"><i class="mm__sw mm__sw--g"></i>{{ t('eli5.overview.modelMatrix.legendGreen') }}</span>
        <span class="mm__lg"><i class="mm__sw mm__sw--y"></i>{{ t('eli5.overview.modelMatrix.legendYellow') }}</span>
        <span class="mm__lg"><i class="mm__sw mm__sw--r"></i>{{ t('eli5.overview.modelMatrix.legendRed') }}</span>
        <span class="mm__lg"><i class="mm__sw mm__sw--hatched"></i>{{ t('eli5.overview.modelMatrix.legendFew') }}</span>
        <span class="mm__lg"><i class="mm__sw mm__sw--none"></i>{{ t('eli5.overview.modelMatrix.legendNone') }}</span>
      </div>
      <p class="mm__note">{{ t('eli5.overview.modelMatrix.note') }}</p>
    </template>
  </div>
</template>

<style scoped>
.mm {
  min-width: 0;
}
.mm__empty {
  color: var(--e-muted);
  font-size: 13px;
  padding: 24px 0;
  text-align: center;
}
.mm__scroll {
  overflow-x: auto;
}
.mm__table {
  border-collapse: separate;
  border-spacing: 3px;
  width: 100%;
  font-variant-numeric: tabular-nums;
}
.mm__corner,
.mm__col {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--e-muted);
  text-align: left;
  padding: 0 2px 4px;
  vertical-align: bottom;
}
.mm__col {
  text-align: center;
  min-width: 84px;
  max-width: 110px;
  word-break: break-all;
}
.mm__row {
  text-align: left;
  font-weight: 400;
  padding: 0 10px 0 0;
  white-space: nowrap;
  max-width: 210px;
}
.mm__id {
  display: block;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--e-ink, var(--text-primary));
}
.mm__name {
  display: block;
  font-size: 11px;
  color: var(--e-muted);
  overflow: hidden;
  text-overflow: ellipsis;
}
.mm__cell {
  padding: 0;
  height: 40px;
}
.mm__cell--none {
  background: var(--e-band);
  border-radius: 4px;
}
.mm__btn {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 40px;
  border: 1px solid transparent;
  border-radius: 4px;
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  color: var(--text-primary);
}
.mm__btn:focus-visible {
  outline: 2px solid var(--e-accent);
  outline-offset: 1px;
}
.mm__btn:hover {
  border-color: var(--e-ink, var(--text-primary));
}
.mm__btn--r,
.mm__sw--r { background: var(--risk-r); color: var(--on-solid); }
.mm__btn--y,
.mm__sw--y { background: color-mix(in srgb, var(--risk-y) 32%, var(--bg-surface)); }
.mm__btn--g,
.mm__sw--g { background: color-mix(in srgb, var(--risk-g) 26%, var(--bg-surface)); }
.mm__btn--zero,
.mm__sw--zero { background: var(--risk-g-bg); }
.mm__btn--hatched,
.mm__sw--hatched {
  background: repeating-linear-gradient(45deg, var(--border-strong) 0 1.5px, var(--bg-surface) 1.5px 6px);
  border-color: var(--e-line);
}
.mm__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 12px;
  font-size: 12px;
  color: var(--e-muted);
}
.mm__lg {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.mm__sw {
  display: inline-block;
  width: 14px;
  height: 14px;
  border-radius: 3px;
  border: 1px solid var(--e-line);
}
.mm__sw--none { background: var(--e-band); }
.mm__note {
  margin: 6px 0 0;
  font-size: 11.5px;
  color: var(--e-muted);
}
</style>
