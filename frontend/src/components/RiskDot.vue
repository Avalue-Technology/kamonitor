<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { riskLabel } from '../utils/risk'

const props = defineProps({
  risk: { type: String, default: null },
  detail: { type: String, default: '' },
})

const { t } = useI18n()

const title = computed(() => {
  const label = riskLabel(props.risk)
  return props.detail ? t('riskDot.titleWithDetail', { label, detail: props.detail }) : label
})
</script>

<template>
  <span class="risk-dot" :class="'risk-dot--' + (risk || 'none')" :title="title" role="img" :aria-label="title">
  </span>
</template>

<style scoped>
.risk-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  vertical-align: middle;
}

.risk-dot--G {
  background: var(--risk-g);
}

.risk-dot--Y {
  background: transparent;
  border: 2px solid var(--risk-y);
  width: 8px;
  height: 8px;
}

.risk-dot--R {
  background: var(--risk-r);
  border: 2px solid var(--risk-r);
  box-shadow: 0 0 0 2px var(--risk-r-bg);
}

.risk-dot--none {
  background: var(--border-strong);
}
</style>
