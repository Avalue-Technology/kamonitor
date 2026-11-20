<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from './components/AppShell.vue'

const route = useRoute()

const mode = computed(() => (route.path.startsWith('/eli5') ? 'eli5' : 'classic'))
</script>

<template>
  <AppShell :mode="mode">
    <RouterView />
  </AppShell>
</template>
