<script setup>
import { ref, computed, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEndpointAvailable } from '../composables/useEndpointAvailable'

const { t } = useI18n()

const props = defineProps({
  apiPath: { type: String, required: true },
  regenerateFn: { type: Function, required: true },
})

const emit = defineEmits(['update:state'])

const available = useEndpointAvailable('post', props.apiPath)

const STATE = { IDLE: 'idle', RUNNING: 'running', DONE: 'done', ERROR: 'error' }
const state = ref(STATE.IDLE)
watch(state, (value) => emit('update:state', value), { immediate: true })
const elapsedS = ref(0)
let timer = null

function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
onUnmounted(stopTimer)

async function run() {
  if (available.value !== true || state.value === STATE.RUNNING) return
  state.value = STATE.RUNNING
  elapsedS.value = 0
  const t0 = performance.now()
  stopTimer()
  timer = setInterval(() => {
    elapsedS.value = (performance.now() - t0) / 1000
  }, 100)
  try {
    await props.regenerateFn()
    state.value = STATE.DONE
  } catch (e) {
    state.value = STATE.ERROR
  } finally {
    stopTimer()
    elapsedS.value = (performance.now() - t0) / 1000
  }
}

const label = computed(() => {
  if (available.value === null) return t('regenerateButton.labelDefault')
  if (available.value === false) return t('regenerateButton.labelNotWired')
  if (state.value === STATE.RUNNING) return t('regenerateButton.labelRunning', { elapsed: elapsedS.value.toFixed(1) })
  if (state.value === STATE.DONE) return t('regenerateButton.labelDone', { elapsed: elapsedS.value.toFixed(1) })
  if (state.value === STATE.ERROR) return t('regenerateButton.labelError')
  return t('regenerateButton.labelDefault')
})

const disabled = computed(() => available.value !== true || state.value === STATE.RUNNING)
const title = computed(() =>
  available.value === false ? t('regenerateButton.titleNotWired') : t('regenerateButton.titleDefault'),
)
</script>

<template>
  <button v-if="available !== false" type="button" class="btn-quiet regen-btn" :class="{ 'regen-btn--error': state === 'error' }" :disabled="disabled" :title="title" @click="run">
    {{ label }}
  </button>
</template>

<style scoped>
.regen-btn {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.regen-btn--error {
  color: var(--risk-r);
  border-color: var(--risk-r);
}
</style>
