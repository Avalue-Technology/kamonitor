<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  modelName: { type: String, default: '' },
  generatedAt: { type: String, default: null },
  elapsedMs: { type: Number, default: null },
  factCount: { type: Number, default: null },
  expandable: { type: Boolean, default: true },
  expanded: { type: Boolean, default: false },
})
const emit = defineEmits(['toggle'])

const generatedText = computed(() => {
  if (!props.generatedAt) return null
  const d = new Date(props.generatedAt)
  if (Number.isNaN(d.getTime())) return null
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  if (isToday) return t('generationStamp.todayTime', { time: `${hh}:${mm}` })
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const da = String(d.getDate()).padStart(2, '0')
  return `${mo}/${da} ${hh}:${mm}`
})

const elapsedText = computed(() => (props.elapsedMs !== null && props.elapsedMs !== undefined ? `${(props.elapsedMs / 1000).toFixed(1)}s` : null))
</script>

<template>
  <div class="gen-stamp">
    <span class="ai-tag">{{ t('generationStamp.aiTag') }}</span>
    <span class="stamp-text">
      {{ t('generationStamp.localGenerated') }}
      <template v-if="modelName"> · {{ modelName }}</template>
      <template v-if="generatedText"> · {{ generatedText }}</template>
      <template v-if="elapsedText"> · {{ t('generationStamp.elapsed', { value: elapsedText }) }}</template>
      <template v-if="factCount !== null"> · {{ t('generationStamp.factCount', { count: factCount }) }}</template>
    </span>
    <button v-if="expandable && factCount !== null" type="button" class="expand-toggle" @click="emit('toggle')">
      {{ expanded ? t('generationStamp.collapse') : t('generationStamp.expand') }}
    </button>
  </div>
</template>

<style scoped>
.gen-stamp {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.ai-tag {
  font-size: var(--fs-xs);
  font-weight: 700;
  color: var(--ai);
  letter-spacing: 0.02em;
}
.stamp-text {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}
.expand-toggle {
  border: none;
  background: none;
  padding: 0;
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--ai);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.expand-toggle:hover {
  color: var(--accent);
}
</style>
