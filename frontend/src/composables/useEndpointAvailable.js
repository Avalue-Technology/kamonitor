import { ref } from 'vue'

let specPromise = null
function loadSpec() {
  if (!specPromise) {
    specPromise = fetch('/openapi.json')
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null)
  }
  return specPromise
}

export function useEndpointAvailable(method, path) {
  const available = ref(null)
  loadSpec().then((spec) => {
    if (!spec || !spec.paths) {
      available.value = false
      return
    }
    const methods = spec.paths[path]
    available.value = !!(methods && methods[method.toLowerCase()])
  })
  return available
}
