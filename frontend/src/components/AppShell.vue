<script setup>
import { ref, computed, nextTick, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useCustomerDirectory } from '../composables/useCustomerDirectory'
import { setLocale } from '../i18n'
import Eli5HeroBg from './Eli5HeroBg.vue'

const props = defineProps({
  mode: { type: String, default: 'classic' },
})

const route = useRoute()
const router = useRouter()
const { directory, nameOf } = useCustomerDirectory()
const { t, locale } = useI18n()

const isEli5 = computed(() => props.mode === 'eli5')
const homePath = computed(() => (isEli5.value ? '/eli5' : '/origin'))
const aboutPath = computed(() => (isEli5.value ? '/eli5/about' : '/about'))
function customerPath(id) {
  return isEli5.value ? `/eli5/customer/${id}` : `/customer/${id}`
}

const overviewRouteName = computed(() => (isEli5.value ? 'eli5-overview' : 'overview'))
const aboutRouteName = computed(() => (isEli5.value ? 'eli5-about' : 'about'))
const customerRouteName = computed(() => (isEli5.value ? 'eli5-customer' : 'customer'))
const modelRouteName = computed(() => (isEli5.value ? 'eli5-model' : 'model-detail'))

const breadcrumb = computed(() => {
  const crumbs = []
  if (route.name === customerRouteName.value || route.name === modelRouteName.value) {
    crumbs.push({ label: nameOf(route.params.id), to: customerPath(route.params.id) })
  }
  if (route.name === modelRouteName.value) {
    crumbs.push({ label: route.params.model, to: null })
  }
  return crumbs
})

const searchTerm = ref('')
const searchOpen = ref(false)
const matches = computed(() => {
  const term = searchTerm.value.trim().toLowerCase()
  if (!term) return []
  return directory.value
    .filter(
      (c) =>
        c.display_name.toLowerCase().includes(term) ||
        c.erp_customer_id.toLowerCase().includes(term) ||
        (c.country || '').toLowerCase().includes(term),
    )
    .slice(0, 8)
})

function goTo(id) {
  searchTerm.value = ''
  searchOpen.value = false
  router.push(customerPath(id))
}

const showEli5HeroBg = computed(() => isEli5.value && route.name === overviewRouteName.value)

const scrolledFromTop = ref(false)
function onScroll() {
  scrolledFromTop.value = window.scrollY > 24
}
const topbarTransparent = computed(() => showEli5HeroBg.value && !scrolledFromTop.value)
window.addEventListener('scroll', onScroll, { passive: true })
onBeforeUnmount(() => window.removeEventListener('scroll', onScroll))

const heroBgHeight = ref(560)
let heroResizeObserver = null

function updateHeroBgHeight() {
  const appShellEl = document.querySelector('.app-shell')
  const heroEl = document.querySelector('.eli5-hero')
  const nextEl = heroEl ? heroEl.nextElementSibling : null
  if (appShellEl && nextEl) {
    heroBgHeight.value = Math.round(nextEl.getBoundingClientRect().top - appShellEl.getBoundingClientRect().top)
  }
}

watch(
  showEli5HeroBg,
  (on) => {
    if (heroResizeObserver) {
      heroResizeObserver.disconnect()
      heroResizeObserver = null
    }
    if (!on) return
    nextTick(() => {
      updateHeroBgHeight()
      const contentEl = document.querySelector('.content')
      if ('ResizeObserver' in window && contentEl) {
        heroResizeObserver = new ResizeObserver(updateHeroBgHeight)
        heroResizeObserver.observe(contentEl)
      }
    })
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (heroResizeObserver) heroResizeObserver.disconnect()
})
</script>

<template>
  <div class="app-shell">
    <Eli5HeroBg
      v-if="showEli5HeroBg"
      class="app-shell__eli5-bg"
      :style="{ height: heroBgHeight + 'px' }"
    />
    <header class="topbar" :class="{ 'topbar--eli5-transparent': topbarTransparent }">
      <div class="topbar-inner">
        <RouterLink :to="homePath" class="logo" :class="{ 'logo--eli5': isEli5 }">KAMonitor</RouterLink>
        <RouterLink v-if="isEli5" :to="homePath" class="eli5-badge">DEMO DATA</RouterLink>

        <nav class="main-nav" :aria-label="t('nav.mainNavAriaLabel')">
          <RouterLink :to="homePath" class="nav-link" :class="{ active: route.name === overviewRouteName }">{{ t('nav.overview') }}</RouterLink>
          <RouterLink :to="aboutPath" class="nav-link" :class="{ active: route.name === aboutRouteName }">{{ t('nav.about') }}</RouterLink>
        </nav>

        <nav v-if="breadcrumb.length" class="breadcrumb" aria-label="breadcrumb">
          <template v-for="(c, i) in breadcrumb" :key="i">
            <span v-if="i > 0" class="sep">/</span>
            <RouterLink v-if="c.to" :to="c.to" class="crumb">{{ c.label }}</RouterLink>
            <span v-else class="crumb crumb--current">{{ c.label }}</span>
          </template>
        </nav>

        <div class="spacer" />

        <div class="search-wrap">
          <input
            v-model="searchTerm"
            type="text"
            class="search-input"
            :placeholder="t('nav.searchPlaceholder')"
            @focus="searchOpen = true"
            @blur="() => setTimeout(() => (searchOpen = false), 150)"
          />
          <div v-if="searchOpen && matches.length" class="search-dropdown">
            <button v-for="m in matches" :key="m.erp_customer_id" type="button" class="search-item" @click="goTo(m.erp_customer_id)">
              <span class="s-name">{{ m.display_name }}</span>
              <span class="s-meta">{{ m.country }} · {{ m.erp_customer_id }}</span>
            </button>
          </div>
        </div>

        <div class="lang-switch" role="group" :aria-label="t('nav.language.ariaLabel')">
          <button
            type="button"
            class="lang-btn"
            :class="{ active: locale === 'zh-TW' }"
            @click="setLocale('zh-TW')"
          >{{ t('nav.language.zhLabel') }}</button>
          <span class="lang-sep">|</span>
          <button
            type="button"
            class="lang-btn"
            :class="{ active: locale === 'zh-CN' }"
            @click="setLocale('zh-CN')"
          >{{ t('nav.language.zhCnLabel') }}</button>
          <span class="lang-sep">|</span>
          <button
            type="button"
            class="lang-btn"
            :class="{ active: locale === 'en' }"
            @click="setLocale('en')"
          >{{ t('nav.language.enLabel') }}</button>
        </div>
      </div>
    </header>

    <main class="content">
      <slot />
    </main>
  </div>
</template>

<style scoped>
.app-shell {
  position: relative;
  min-height: 100vh;
}

.app-shell__eli5-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 0;
  pointer-events: none;
  background: var(--e-surface);
}

.topbar {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 20;
  transition: background-color 180ms ease, border-bottom-color 180ms ease;
}
.topbar--eli5-transparent {
  background: transparent;
  border-bottom-color: transparent;
}
.topbar--eli5-transparent .search-input {
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(6px);
}
.topbar--eli5-transparent .search-dropdown {
  background: var(--bg-surface);
}
.topbar-inner {
  max-width: 1280px;
  margin: 0 auto;
  padding: var(--sp-3) var(--sp-5);
  display: flex;
  align-items: center;
  gap: var(--sp-5);
}

.logo {
  font-size: var(--fs-lg);
  font-weight: 700;
  letter-spacing: 0.3px;
  color: var(--accent);
  flex-shrink: 0;
}
.logo:hover {
  text-decoration: none;
}
.logo--eli5 {
  color: var(--e-brand);
}

.eli5-badge {
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-sm);
  padding: 2px 6px;
  flex-shrink: 0;
}
.eli5-badge:hover {
  text-decoration: none;
}

.main-nav {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-shrink: 0;
}
.nav-link {
  font-size: var(--fs-sm);
  color: var(--text-muted);
  padding: 3px 2px;
}
.nav-link:hover {
  color: var(--accent);
  text-decoration: none;
}
.nav-link.active {
  color: var(--accent);
  font-weight: 600;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--fs-sm);
  color: var(--text-muted);
  min-width: 0;
}
.crumb {
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 220px;
}
.crumb:hover {
  color: var(--accent);
}
.crumb--current {
  color: var(--text-primary);
  font-weight: 600;
}
.crumb--current:hover {
  text-decoration: none;
}
.sep {
  color: var(--text-faint);
}

.spacer {
  flex: 1;
}

.search-wrap {
  position: relative;
  width: 300px;
}
.search-input {
  width: 100%;
  font: inherit;
  font-size: var(--fs-sm);
  padding: 7px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  color: var(--text-body);
}
.search-input:focus {
  outline: none;
  border-color: var(--accent);
  background: var(--bg-surface);
}
.search-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-card);
  z-index: 30;
  overflow: hidden;
}
.search-item {
  display: flex;
  flex-direction: column;
  width: 100%;
  text-align: left;
  padding: var(--sp-2) var(--sp-3);
  border: none;
  background: none;
  cursor: pointer;
}
.search-item:hover {
  background: var(--accent-soft);
}
.s-name {
  font-size: var(--fs-sm);
  color: var(--text-primary);
  font-weight: 600;
}
.s-meta {
  font-size: var(--fs-xs);
  color: var(--text-faint);
}

.content {
  max-width: 1280px;
  margin: 0 auto;
  padding: var(--sp-5) var(--sp-5) var(--sp-6);
  position: relative;
  z-index: 1;
}

.lang-switch {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  font-size: var(--fs-sm);
}
.lang-btn {
  background: none;
  border: none;
  padding: 2px 3px;
  color: var(--text-faint);
  cursor: pointer;
  font: inherit;
}
.lang-btn:hover {
  color: var(--text-body);
}
.lang-btn.active {
  color: var(--text-primary);
  font-weight: 600;
}
.lang-sep {
  color: var(--border-strong);
}
</style>
