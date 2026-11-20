<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import echarts from '../echarts-setup'

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '280px' },
})
const emit = defineEmits(['chart-click'])

const el = ref(null)
let chart = null
let resizeObserver = null

function render() {
  if (!chart || !props.option) return
  chart.setOption(props.option, true)
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  chart.on('click', (params) => emit('chart-click', params))
  resizeObserver = new ResizeObserver(() => chart && chart.resize())
  resizeObserver.observe(el.value)
})

onBeforeUnmount(() => {
  resizeObserver && resizeObserver.disconnect()
  chart && chart.dispose()
})

watch(() => props.option, render, { deep: true })
</script>

<template>
  <div ref="el" class="echart" :style="{ height }"></div>
</template>

<style scoped>
.echart {
  width: 100%;
}
</style>
