<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useCustomerDirectory } from '../composables/useCustomerDirectory'
import { splitNoteSegments } from '../utils/noteSegments'
import Tabs from '../components/Tabs.vue'
import Eli5SalesTab from '../components/Eli5SalesTab.vue'
import Eli5QaTab from '../components/Eli5QaTab.vue'

const props = defineProps({
  id: { type: String, required: true },
})

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { directory } = useCustomerDirectory()

const activeTab = computed({
  get() {
    return route.query.tab === 'sales' ? 'sales' : 'quality'
  },
  set(value) {
    router.replace({
      query: { ...route.query, tab: value === 'sales' ? 'sales' : undefined },
    })
  },
})

const tabs = computed(() => [
  { key: 'quality', label: t('eli5.customerPage.tabQuality') },
  { key: 'sales', label: t('eli5.customerPage.tabSales') },
])

const displayName = computed(() => {
  const c = directory.value.find((x) => x.erp_customer_id === props.id)
  return c ? c.display_name : props.id
})

const noteSegments = computed(() => {
  const c = directory.value.find((x) => x.erp_customer_id === props.id)
  return splitNoteSegments(c?.account_profile?.note)
})

const noteOpen = ref(false)

const parentGroup = computed(() => {
  const c = directory.value.find((x) => x.erp_customer_id === props.id)
  return c?.account_profile?.parent_group || ''
})
</script>

<template>
  <div class="eli5-scope eli5-customer-page">
    <header class="eli5-band">
      <h1 class="eli5-h1">{{ displayName
        }}<span v-if="parentGroup" class="eli5-customer-page__group">{{ parentGroup }}</span></h1>
      <div class="eli5-meta num">ERP {{ props.id }}</div>
      <button
        v-if="noteSegments.length"
        type="button"
        class="eli5-customer-page__note-toggle"
        :aria-expanded="noteOpen"
        @click="noteOpen = !noteOpen"
      >{{ t('eli5.customerPage.noteToggle') }} <span aria-hidden="true">{{ noteOpen ? '▾' : '▸' }}</span></button>
      <p v-if="noteSegments.length && noteOpen" class="eli5-customer-page__note">
        <span
          v-for="(seg, i) in noteSegments"
          :key="i"
          :class="{ 'eli5-customer-page__note-nowrap': seg.nowrap }"
          >{{ seg.text }}</span
        >
      </p>
    </header>

    <Tabs v-model="activeTab" :tabs="tabs">
      <template #quality>
        <Eli5QaTab :id="props.id" />
      </template>
      <template #sales>
        <Eli5SalesTab :id="props.id" />
      </template>
    </Tabs>
  </div>
</template>

<style scoped>
.eli5-customer-page__note {
  margin: 8px 0 0;
  max-width: 860px;
  font-family: var(--e-font-text);
  font-size: 13.5px;
  line-height: 1.75;
  color: var(--e-muted);
}
.eli5-customer-page__note-nowrap {
  white-space: nowrap;
}
.eli5-customer-page__note-toggle {
  margin-top: 8px;
  padding: 0;
  border: none;
  background: none;
  font-family: inherit;
  font-size: 13px;
  color: var(--e-muted);
  cursor: pointer;
}
.eli5-customer-page__note-toggle:hover {
  color: var(--e-ink);
}

.eli5-customer-page__group {
  display: inline-block;
  margin-left: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  background: #2f6fd0;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.01em;
  vertical-align: middle;
}

.eli5-customer-page :deep(.tabs-head) {
  background: var(--e-surface);
  border-bottom: 1px solid var(--e-line);
  box-shadow: none;
  gap: 24px;
  padding-left: 40px;
}
.eli5-customer-page :deep(.tabs-btn) {
  color: var(--e-faint);
  font-family: var(--e-font);
  font-size: 14.5px;
  font-weight: 600;
  padding: 10px 0;
}
.eli5-customer-page :deep(.tabs-btn.active) {
  color: var(--e-ink);
  border-bottom-color: var(--e-ink);
  border-bottom-width: 2px;
}
.eli5-customer-page :deep(.tabs-body) {
  margin-top: 0;
}
@media (max-width: 760px) {
  .eli5-customer-page :deep(.tabs-head) {
    padding-left: 18px;
  }
}
</style>
