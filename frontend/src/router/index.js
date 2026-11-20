import { createRouter, createWebHistory } from 'vue-router'

const Eli5Overview = () => import('../views/Eli5Overview.vue')
const Eli5Customer = () => import('../views/Eli5Customer.vue')
const Eli5ModelQA = () => import('../views/Eli5ModelQA.vue')
const Eli5About = () => import('../views/Eli5About.vue')
const Eli5ChainEvidence = () => import('../views/Eli5ChainEvidence.vue')

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior() {
    return { top: 0 }
  },
  routes: [
    { path: '/', redirect: '/eli5' },
    { path: '/eli5', name: 'eli5-overview', component: Eli5Overview, meta: { label: 'ELI5' } },
    {
      path: '/eli5/customer/:id',
      name: 'eli5-customer',
      component: Eli5Customer,
      meta: { label: 'ELI5 客戶' },
      props: true,
    },
    {
      path: '/eli5/customer/:id/model/:model',
      name: 'eli5-model',
      component: Eli5ModelQA,
      meta: { label: 'ELI5 機種明細' },
      props: true,
    },
    {
      path: '/eli5/customer/:id/evidence/:chain',
      name: 'eli5-chain-evidence',
      component: Eli5ChainEvidence,
      meta: { label: 'ELI5 資料依據' },
      props: true,
    },
    { path: '/eli5/about', name: 'eli5-about', component: Eli5About, meta: { label: 'ELI5 說明' } },
    { path: '/eli5/:id', redirect: (to) => `/eli5/customer/${to.params.id}` },
    { path: '/:pathMatch(.*)*', redirect: '/eli5' },
  ],
})

export default router
