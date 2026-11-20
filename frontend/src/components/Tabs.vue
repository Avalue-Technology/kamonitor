<script setup>
const props = defineProps({
  tabs: {
    type: Array,
    required: true,
  },
  modelValue: { type: String, required: true },
})
defineEmits(['update:modelValue'])
</script>

<template>
  <div class="tabs">
    <div class="tabs-head" role="tablist">
      <button
        v-for="t in tabs"
        :key="t.key"
        type="button"
        role="tab"
        class="tabs-btn"
        :class="{ active: modelValue === t.key }"
        :aria-selected="modelValue === t.key"
        @click="$emit('update:modelValue', t.key)"
      >
        {{ t.label }}
        <span
          v-if="t.risk"
          class="tabs-dot"
          :class="'tabs-dot--' + t.risk"
          :title="t.riskDetail || ''"
          role="img"
          :aria-label="t.riskDetail || ''"
        />
      </button>
    </div>
    <div class="tabs-body">
      <template v-for="t in tabs" :key="t.key">
        <div v-show="modelValue === t.key" role="tabpanel">
          <slot :name="t.key" />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.tabs-head {
  display: flex;
  gap: var(--sp-2);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 60px;
  z-index: 10;
  background: var(--bg-app);
  box-shadow: var(--shadow-card);
  overflow-x: auto;
  overflow-y: hidden;
}
.tabs-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  border: none;
  background: none;
  cursor: pointer;
  font: inherit;
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-muted);
  padding: var(--sp-3) var(--sp-2);
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: color 150ms, border-color 150ms;
}
.tabs-btn:hover {
  color: var(--text-primary);
}
.tabs-btn.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}
.tabs-body {
  margin-top: var(--sp-4);
}

.tabs-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.tabs-dot--G {
  background: var(--risk-g);
}
.tabs-dot--Y {
  background: transparent;
  border: 2px solid var(--risk-y);
  width: 6px;
  height: 6px;
}
.tabs-dot--R {
  background: var(--risk-r);
  border: 2px solid var(--risk-r);
  box-shadow: 0 0 0 2px var(--risk-r-bg);
}
</style>
