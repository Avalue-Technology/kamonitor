<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  message: { type: String, default: null },
  hint: { type: String, default: '' },
})

const { t } = useI18n()
const displayMessage = computed(() => props.message ?? t('common.noData'))
</script>

<template>
  <div class="empty-state">
    <div class="msg">{{ displayMessage }}</div>
    <div v-if="hint" class="hint">{{ hint }}</div>
  </div>
</template>

<style scoped>
.empty-state {
  padding: var(--sp-5) var(--sp-3);
  text-align: center;
  color: var(--text-faint);
  font-size: var(--fs-sm);
}
.msg {
  color: var(--text-muted);
}
.hint {
  margin-top: var(--sp-1);
  color: var(--text-faint);
  font-size: var(--fs-xs);
}
</style>
