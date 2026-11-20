<script setup>
import { computed, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getReportModel } from '../api/endpoints'
import { useAsyncWatch } from '../composables/useAsync'
import { useCustomerDirectory } from '../composables/useCustomerDirectory'
import { formatFraction, formatInt, formatPeriod } from '../utils/format'
import RiskDot from '../components/RiskDot.vue'

const props = defineProps({
  id: { type: String, required: true },
  model: { type: String, required: true },
})

const route = useRoute()
const { t } = useI18n()
const { directory } = useCustomerDirectory()

const reportId = computed(() => route.query.report)

const source = computed(() => (reportId.value ? { reportId: reportId.value, model: props.model } : null))

const { data, loading, notFound, error } = useAsyncWatch(
  source,
  (key) => (key ? getReportModel(key.reportId, key.model) : Promise.reject({ status: 400 })),
  { optional: true },
)

const customerName = computed(() => {
  const c = directory.value.find((x) => x.erp_customer_id === props.id)
  return c ? c.display_name : props.id
})

const detail = computed(() => data.value?.detail ?? null)
const reportInfo = computed(() => data.value?.report ?? null)

const expanded = reactive({ rma: false, cfqr: false, fpy: false, repair: false })

function rowsOf(list, key) {
  const rows = list || []
  return expanded[key] ? rows : rows.slice(0, 10)
}

const rmaRows = computed(() => detail.value?.rma_detail_snapshot || [])
const cfqrRows = computed(() => detail.value?.cfqr_detail || [])
const fpyRows = computed(() => detail.value?.fpy_detail_snapshot || [])
const repairRows = computed(() => detail.value?.repair_detail_snapshot || [])
</script>

<template>
  <div class="eli5-model-page">
    <div class="eli5-model-back">
      <router-link :to="`/eli5/customer/${props.id}`">{{ t('eli5.modelQa.back', { name: customerName }) }}</router-link>
    </div>

    <div v-if="!reportId" class="eli5-model-notice">
      {{ t('eli5.modelQa.missingReport') }}
    </div>

    <template v-else>
      <div v-if="loading" class="eli5-model-loading">{{ t('eli5.modelQa.loading') }}</div>
      <div v-else-if="notFound" class="eli5-model-notice">{{ t('eli5.modelQa.notFound') }}</div>
      <div v-else-if="error" class="eli5-model-notice">{{ t('eli5.modelQa.errorMessage', { message: error.message }) }}</div>

      <template v-else-if="detail">
        <header class="eli5-model-header">
          <h1 class="eli5-model-title">{{ detail.model }}</h1>
          <p class="eli5-model-period">{{ t('eli5.modelQa.period', { period: formatPeriod(reportInfo?.period) }) }}</p>
        </header>

        <section class="eli5-model-summary">
          <div class="eli5-model-summary-group">
            <div class="eli5-model-summary-row">
              <span>{{ t('eli5.modelQa.shipmentQty') }}</span>
              <strong>{{ formatInt(detail.shipment_qty) }}</strong>
            </div>
          </div>
          <div class="eli5-model-summary-group">
            <div class="eli5-model-summary-title">{{ t('eli5.modelQa.doa') }}</div>
            <div class="eli5-model-summary-row">
              <span>{{ t('eli5.modelQa.count') }}</span>
              <strong>{{ formatInt(detail.doa_count) }}</strong>
            </div>
            <div class="eli5-model-summary-row">
              <span>{{ t('eli5.modelQa.rate') }}</span>
              <strong><RiskDot :risk="detail.doa_risk" /> {{ formatFraction(detail.doa_rate) }}</strong>
            </div>
          </div>
          <div class="eli5-model-summary-group">
            <div class="eli5-model-summary-title">{{ t('eli5.modelQa.rma') }}</div>
            <div class="eli5-model-summary-row">
              <span>{{ t('eli5.modelQa.count') }}</span>
              <strong>{{ formatInt(detail.rma_count) }}</strong>
            </div>
            <div class="eli5-model-summary-row">
              <span>{{ t('eli5.modelQa.rate') }}</span>
              <strong><RiskDot :risk="detail.rma_risk" /> {{ formatFraction(detail.rma_rate) }}</strong>
            </div>
          </div>
          <div class="eli5-model-summary-group">
            <div class="eli5-model-summary-title">{{ t('eli5.modelQa.cfqr') }}</div>
            <div class="eli5-model-summary-row">
              <span>{{ t('eli5.modelQa.count') }}</span>
              <strong><RiskDot :risk="detail.cfqr_risk" /> {{ formatInt(detail.cfqr_count) }}</strong>
            </div>
          </div>
          <div class="eli5-model-summary-group">
            <div class="eli5-model-summary-title">{{ t('eli5.modelQa.fpy') }}</div>
            <div class="eli5-model-summary-row">
              <span>{{ t('eli5.modelQa.fpyInput') }}</span>
              <strong>{{ formatInt(detail.fpy_input) }}</strong>
            </div>
            <div class="eli5-model-summary-row">
              <span>{{ t('eli5.modelQa.rate') }}</span>
              <strong><RiskDot :risk="detail.fpy_risk" /> {{ formatFraction(detail.fpy_rate) }}</strong>
            </div>
          </div>
          <div class="eli5-model-summary-group">
            <div class="eli5-model-summary-title">{{ t('eli5.modelQa.repair') }}</div>
            <div class="eli5-model-summary-row">
              <span>{{ t('eli5.modelQa.count') }}</span>
              <strong>{{ formatInt(detail.repair_count) }}</strong>
            </div>
            <div class="eli5-model-summary-row">
              <span>{{ t('eli5.modelQa.rate') }}</span>
              <strong><RiskDot :risk="detail.repair_risk" /> {{ formatFraction(detail.repair_rate) }}</strong>
            </div>
          </div>
        </section>

        <section class="eli5-model-block">
          <h2>{{ t('eli5.modelQa.materialSectionTitle') }}</h2>
          <div v-if="!detail.shipment_by_material?.length" class="eli5-model-empty">{{ t('eli5.modelQa.noDataThisPeriod') }}</div>
          <div v-else class="eli5-model-table-wrap">
            <table class="eli5-model-table">
              <thead>
                <tr>
                  <th>{{ t('eli5.modelQa.colMaterial') }}</th>
                  <th>{{ t('eli5.modelQa.shipmentQty') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, i) in detail.shipment_by_material" :key="i">
                  <td>{{ r.Material }}</td>
                  <td>{{ formatInt(r['Shipment Qty']) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="eli5-model-ranking-row">
          <div class="eli5-model-block">
            <h2>{{ t('eli5.modelQa.topRmaTitle') }}</h2>
            <div v-if="!detail.top_rma_identification?.length" class="eli5-model-empty">{{ t('eli5.modelQa.noDataThisPeriod') }}</div>
            <table v-else class="eli5-model-table">
              <thead>
                <tr>
                  <th>{{ t('eli5.modelQa.colReason') }}</th>
                  <th>{{ t('eli5.modelQa.colCount') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, i) in detail.top_rma_identification" :key="i">
                  <td>{{ r['Trouble Code Desc'] }}</td>
                  <td>{{ formatInt(r.Count) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="eli5-model-block">
            <h2>{{ t('eli5.modelQa.topRepairDefectTitle') }}</h2>
            <div v-if="!detail.top_repair_defect?.length" class="eli5-model-empty">{{ t('eli5.modelQa.noDataThisPeriod') }}</div>
            <table v-else class="eli5-model-table">
              <thead>
                <tr>
                  <th>{{ t('eli5.modelQa.colDefectDesc') }}</th>
                  <th>{{ t('eli5.modelQa.colCount') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, i) in detail.top_repair_defect" :key="i">
                  <td>{{ r['Defect Desc'] }}</td>
                  <td>{{ formatInt(r.Count) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="eli5-model-block">
            <h2>{{ t('eli5.modelQa.topRepairMaterialTitle') }}</h2>
            <div v-if="!detail.top_repair_material?.length" class="eli5-model-empty">{{ t('eli5.modelQa.noDataThisPeriod') }}</div>
            <table v-else class="eli5-model-table">
              <thead>
                <tr>
                  <th>{{ t('eli5.modelQa.colMaterial') }}</th>
                  <th>{{ t('eli5.modelQa.colCount') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, i) in detail.top_repair_material" :key="i">
                  <td>{{ r.Material }}</td>
                  <td>{{ formatInt(r.Count) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="eli5-model-block">
          <h2>{{ t('eli5.modelQa.rmaDetailTitle') }}</h2>
          <div v-if="!rmaRows.length" class="eli5-model-empty">{{ t('eli5.modelQa.noDataThisPeriod') }}</div>
          <template v-else>
            <div class="eli5-model-table-wrap">
              <table class="eli5-model-table eli5-model-table--snapshot">
                <thead>
                  <tr>
                    <th>{{ t('eli5.modelQa.colRmaNo') }}</th>
                    <th>{{ t('eli5.modelQa.colProductId') }}</th>
                    <th>{{ t('eli5.modelQa.colReceiveDate') }}</th>
                    <th class="col-text">{{ t('eli5.modelQa.colProblemDesc') }}</th>
                    <th class="col-text">{{ t('eli5.modelQa.colFailDesc') }}</th>
                    <th>{{ t('eli5.modelQa.colTroubleCode') }}</th>
                    <th>{{ t('eli5.modelQa.colReasonCode') }}</th>
                    <th class="col-text">{{ t('eli5.modelQa.colAnalysis') }}</th>
                    <th>{{ t('eli5.modelQa.colDoaShort') }}</th>
                    <th>{{ t('eli5.modelQa.colWarranty') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(r, i) in rowsOf(rmaRows, 'rma')" :key="i">
                    <td>{{ r.ZRmaID }}</td>
                    <td>{{ r.ProductID }}</td>
                    <td>{{ r.r2_receive_date }}</td>
                    <td class="col-text">{{ r.r2_problem_desc }}</td>
                    <td class="col-text">{{ r.FailDescriptionENG }}</td>
                    <td>{{ r.r3_Trouble_Code }}</td>
                    <td>{{ r.r3_Reason_Code }}</td>
                    <td class="col-text">{{ r.r3_defective_analysis }}</td>
                    <td>{{ r.r2_product_doa ? t('eli5.modelQa.yes') : t('eli5.modelQa.no') }}</td>
                    <td>{{ r.OutOfWarranty ? t('eli5.modelQa.no') : t('eli5.modelQa.yes') }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <button v-if="rmaRows.length > 10" type="button" class="eli5-model-toggle" @click="expanded.rma = !expanded.rma">
              {{ expanded.rma ? t('eli5.modelQa.collapse') : t('eli5.modelQa.showAll', { count: rmaRows.length }) }}
            </button>
          </template>
        </section>

        <section class="eli5-model-block">
          <h2>{{ t('eli5.modelQa.cfqrDetailTitle') }}</h2>
          <div v-if="!cfqrRows.length" class="eli5-model-empty">{{ t('eli5.modelQa.noDataThisPeriod') }}</div>
          <template v-else>
            <div class="eli5-model-table-wrap">
              <table class="eli5-model-table eli5-model-table--snapshot">
                <thead>
                  <tr>
                    <th>{{ t('eli5.modelQa.colCarNo') }}</th>
                    <th>{{ t('eli5.modelQa.colIssueDate') }}</th>
                    <th>{{ t('eli5.modelQa.colMaterial') }}</th>
                    <th>{{ t('eli5.modelQa.colDefectQty') }}</th>
                    <th>{{ t('eli5.modelQa.colStatus') }}</th>
                    <th class="col-text">{{ t('eli5.modelQa.colProblemDesc') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(r, i) in rowsOf(cfqrRows, 'cfqr')" :key="i">
                    <td>{{ r.CAR_NUMBER }}</td>
                    <td>{{ r.ISSUE_DATE }}</td>
                    <td>{{ r.VALUE_PART_NUMBER }}</td>
                    <td>{{ formatInt(r.DEFECT_QTY) }}</td>
                    <td>{{ r.STATUS }}</td>
                    <td class="col-text">{{ r.PROBLEM_DESCRIPTION }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <button
              v-if="cfqrRows.length > 10"
              type="button"
              class="eli5-model-toggle"
              @click="expanded.cfqr = !expanded.cfqr"
            >
              {{ expanded.cfqr ? t('eli5.modelQa.collapse') : t('eli5.modelQa.showAll', { count: cfqrRows.length }) }}
            </button>
          </template>
        </section>

        <section class="eli5-model-block">
          <h2>{{ t('eli5.modelQa.fpyDetailTitle') }}</h2>
          <div v-if="!fpyRows.length" class="eli5-model-empty">{{ t('eli5.modelQa.noDataThisPeriod') }}</div>
          <template v-else>
            <div class="eli5-model-table-wrap">
              <table class="eli5-model-table eli5-model-table--snapshot">
                <thead>
                  <tr>
                    <th>{{ t('eli5.modelQa.colWorkOrder') }}</th>
                    <th>{{ t('eli5.modelQa.colMaterial') }}</th>
                    <th>{{ t('eli5.modelQa.colT1Input') }}</th>
                    <th>{{ t('eli5.modelQa.colT1Yield') }}</th>
                    <th>{{ t('eli5.modelQa.colT2Input') }}</th>
                    <th>{{ t('eli5.modelQa.colT2Yield') }}</th>
                    <th>{{ t('eli5.modelQa.colT3Input') }}</th>
                    <th>{{ t('eli5.modelQa.colT3Yield') }}</th>
                    <th>{{ t('eli5.modelQa.colFpyShort') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(r, i) in rowsOf(fpyRows, 'fpy')" :key="i">
                    <td>{{ r['工單號碼'] }}</td>
                    <td>{{ r['料號'] }}</td>
                    <td>{{ formatInt(r.T1_Input) }}</td>
                    <td>{{ formatFraction(r.T1_Yield) }}</td>
                    <td>{{ formatInt(r.T2_Input) }}</td>
                    <td>{{ formatFraction(r.T2_Yield) }}</td>
                    <td>{{ formatInt(r.T3_Input) }}</td>
                    <td>{{ formatFraction(r.T3_Yield) }}</td>
                    <td>{{ formatFraction(r.FPY) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <button v-if="fpyRows.length > 10" type="button" class="eli5-model-toggle" @click="expanded.fpy = !expanded.fpy">
              {{ expanded.fpy ? t('eli5.modelQa.collapse') : t('eli5.modelQa.showAll', { count: fpyRows.length }) }}
            </button>
          </template>
        </section>

        <section class="eli5-model-block">
          <h2>{{ t('eli5.modelQa.repairDetailTitle') }}</h2>
          <div v-if="!repairRows.length" class="eli5-model-empty">{{ t('eli5.modelQa.noDataThisPeriod') }}</div>
          <template v-else>
            <div class="eli5-model-table-wrap">
              <table class="eli5-model-table eli5-model-table--snapshot">
                <thead>
                  <tr>
                    <th>{{ t('eli5.modelQa.colWip') }}</th>
                    <th>{{ t('eli5.modelQa.colRepairDate') }}</th>
                    <th>{{ t('eli5.modelQa.colStation') }}</th>
                    <th>{{ t('eli5.modelQa.colMaterial') }}</th>
                    <th class="col-text">{{ t('eli5.modelQa.colRepairType') }}</th>
                    <th class="col-text">{{ t('eli5.modelQa.colNgType') }}</th>
                    <th class="col-text">{{ t('eli5.modelQa.colFailDesc') }}</th>
                    <th class="col-text">{{ t('eli5.modelQa.colRepairDesc') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(r, i) in rowsOf(repairRows, 'repair')" :key="i">
                    <td>{{ r.wipNO }}</td>
                    <td>{{ r.repairDate }}</td>
                    <td>{{ r.stationName }}</td>
                    <td>{{ r.partNo }}</td>
                    <td class="col-text">{{ r.repairType2 }}</td>
                    <td class="col-text">{{ r.ngType2 }}</td>
                    <td class="col-text">{{ r.ngReasonDescEn }}</td>
                    <td class="col-text">{{ r.repairDesc }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <button
              v-if="repairRows.length > 10"
              type="button"
              class="eli5-model-toggle"
              @click="expanded.repair = !expanded.repair"
            >
              {{ expanded.repair ? t('eli5.modelQa.collapse') : t('eli5.modelQa.showAll', { count: repairRows.length }) }}
            </button>
          </template>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.eli5-model-page {
  max-width: 1080px;
  margin: 0 auto;
  padding: var(--sp-6) var(--sp-4) var(--sp-7);
}

.eli5-model-back {
  margin-bottom: var(--sp-3);
  font-size: var(--fs-sm);
}
.eli5-model-back a {
  color: var(--text-muted);
  text-decoration: none;
}
.eli5-model-back a:hover {
  color: var(--accent);
  text-decoration: underline;
}

.eli5-model-loading,
.eli5-model-notice {
  text-align: center;
  color: var(--text-muted);
  font-size: var(--fs-md);
  padding: var(--sp-6) 0;
}

.eli5-model-header {
  margin-bottom: var(--sp-5);
}
.eli5-model-title {
  font-size: var(--fs-2xl);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}
.eli5-model-period {
  margin: var(--sp-1) 0 0;
  font-size: var(--fs-sm);
  color: var(--text-muted);
}

.eli5-model-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--sp-3);
  margin-bottom: var(--sp-6);
}
.eli5-model-summary-group {
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: var(--sp-3);
}
.eli5-model-summary-title {
  font-size: var(--fs-xs);
  font-weight: 700;
  color: var(--text-faint);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: var(--sp-1);
}
.eli5-model-summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
  font-size: var(--fs-sm);
  color: var(--text-muted);
}
.eli5-model-summary-row strong {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  color: var(--text-primary);
  font-size: var(--fs-md);
  font-variant-numeric: tabular-nums;
}

.eli5-model-block {
  margin-bottom: var(--sp-6);
}
.eli5-model-block h2 {
  font-size: var(--fs-md);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 var(--sp-3);
}

.eli5-model-ranking-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sp-4);
}
.eli5-model-ranking-row .eli5-model-block {
  margin-bottom: 0;
}

.eli5-model-empty {
  color: var(--text-faint);
  font-size: var(--fs-sm);
  padding: var(--sp-3) 0;
}

.eli5-model-table-wrap {
  overflow-x: auto;
}

.eli5-model-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}
.eli5-model-table th {
  text-align: left;
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--border-strong);
  color: var(--text-muted);
  white-space: nowrap;
}
.eli5-model-table td {
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.eli5-model-table--snapshot td.col-text,
.eli5-model-table--snapshot th.col-text {
  white-space: normal;
  min-width: 180px;
}

.eli5-model-toggle {
  margin-top: var(--sp-2);
  font: inherit;
  font-size: var(--fs-sm);
  color: var(--accent);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
}
.eli5-model-toggle:hover {
  text-decoration: underline;
}
</style>
