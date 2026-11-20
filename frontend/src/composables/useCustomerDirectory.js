import { ref } from 'vue'
import { listCustomers } from '../api/endpoints'

const directory = ref([])
const loaded = ref(false)
const loading = ref(false)

async function ensureLoaded() {
  if (loaded.value || loading.value) return
  loading.value = true
  try {
    directory.value = await listCustomers()
    loaded.value = true
  } catch (e) {
    directory.value = []
  } finally {
    loading.value = false
  }
}

export function useCustomerDirectory() {
  ensureLoaded()
  function nameOf(id) {
    const c = directory.value.find((x) => x.erp_customer_id === id)
    return c ? c.display_name : id
  }
  return { directory, loaded, nameOf }
}
