
<script setup>
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const CHAIN_ITEMS = ['item0', 'item1', 'item2', 'item3', 'item4', 'item5']
</script>

<template>
  <div class="eli5-scope eli5-about">
    <section class="eli5-band eli5-about-hero">
      <div class="eli5-about-inner">
        <p class="eli5-eyebrow">DEMO DATA</p>
        <h1 class="eli5-h1">{{ t('eli5.about.title') }}</h1>
        <p class="eli5-note eli5-about-sub">{{ t('eli5.about.subtitle') }}</p>
      </div>
    </section>

    <section class="eli5-band eli5-band--tint">
      <div class="eli5-about-inner">
        <h2 class="eli5-h2">{{ t('eli5.about.s7.heading') }}</h2>
        <p>{{ t('eli5.about.s7.p1') }}</p>
        <p>{{ t('eli5.about.s7.p2') }}</p>
        <p>{{ t('eli5.about.s7.p3') }}</p>
        <p>{{ t('eli5.about.s7.p4') }}</p>
      </div>
    </section>

    <section class="eli5-band">
      <div class="eli5-about-inner">
        <h2 class="eli5-h2">{{ t('eli5.about.s8.heading') }}</h2>
        <p>{{ t('eli5.about.s8.p1') }}</p>
        <p>{{ t('eli5.about.s8.p2') }}</p>
        <ul class="eli5-about-example-list">
          <li>{{ t('eli5.about.s8.quality') }}</li>
          <li>{{ t('eli5.about.s8.growth') }}</li>
        </ul>
        <p>{{ t('eli5.about.s8.p3') }}</p>
      </div>
    </section>

    <section class="eli5-band eli5-band--tint">
      <div class="eli5-about-inner">
        <h2 class="eli5-h2">{{ t('eli5.about.s1.heading') }}</h2>
        <p>{{ t('eli5.about.s1.p1') }}</p>
        <p>{{ t('eli5.about.s1.p2') }}</p>
        <p class="eli5-about-note-inline">{{ t('eli5.about.s1.note') }}</p>
      </div>
    </section>

    <section class="eli5-band">
      <div class="eli5-about-inner">
        <h2 class="eli5-h2">{{ t('eli5.about.s2.heading') }}</h2>
        <div class="eli5-about-tabs">
          <div class="eli5-about-tab">
            <h3 class="eli5-about-subhead">{{ t('eli5.about.s2.quality.title') }}</h3>
            <p>{{ t('eli5.about.s2.quality.desc') }}</p>
          </div>
          <div class="eli5-about-tab">
            <h3 class="eli5-about-subhead">{{ t('eli5.about.s2.sales.title') }}</h3>
            <p>{{ t('eli5.about.s2.sales.desc') }}</p>
          </div>
        </div>
      </div>
    </section>

    <section class="eli5-band eli5-band--tint">
      <div class="eli5-about-inner">
        <h2 class="eli5-h2">{{ t('eli5.about.s3.heading') }}</h2>
        <p>{{ t('eli5.about.s3.intro') }}</p>
        <ol class="eli5-about-chain">
          <li v-for="(key, idx) in CHAIN_ITEMS" :key="key" class="eli5-about-chain-item">
            <span class="eli5-about-chain-num">{{ idx }}</span>
            <span class="eli5-about-chain-label">{{ t(`eli5.about.s3.chain.${key}.label`) }}</span>
            <span v-if="t(`eli5.about.s3.chain.${key}.note`)" class="eli5-about-chain-note">
              {{ t(`eli5.about.s3.chain.${key}.note`) }}
            </span>
          </li>
        </ol>
        <p class="eli5-about-note-inline">{{ t('eli5.about.s3.quote') }}</p>
      </div>
    </section>

    <section class="eli5-band">
      <div class="eli5-about-inner">
        <h2 class="eli5-h2">{{ t('eli5.about.s4.heading') }}</h2>
        <p>{{ t('eli5.about.s4.p1') }}</p>
        <p>{{ t('eli5.about.s4.p2') }}</p>
        <p>{{ t('eli5.about.s4.p3') }}</p>
      </div>
    </section>

    <section class="eli5-band eli5-band--tint">
      <div class="eli5-about-inner">
        <h2 class="eli5-h2">{{ t('eli5.about.s5.heading') }}</h2>
        <p>{{ t('eli5.about.s5.p1') }}</p>
        <p>{{ t('eli5.about.s5.example') }}</p>
        <ul class="eli5-about-example-list">
          <li>{{ t('eli5.about.s5.exampleOdm') }}</li>
          <li>{{ t('eli5.about.s5.exampleStd') }}</li>
        </ul>
        <p>{{ t('eli5.about.s5.p2') }}</p>
      </div>
    </section>

    <section class="eli5-band">
      <div class="eli5-about-inner">
        <h2 class="eli5-h2">{{ t('eli5.about.s6.heading') }}</h2>
        <p>{{ t('eli5.about.s6.p1') }}</p>
        <p>{{ t('eli5.about.s6.p2') }}</p>
        <p>{{ t('eli5.about.s6.p3') }}</p>
      </div>
    </section>

    <section class="eli5-band eli5-band--tint">
      <div class="eli5-about-inner">
        <h2 class="eli5-h2">{{ t('eli5.about.tour.heading') }}</h2>
        <p>{{ t('eli5.about.tour.intro') }}</p>
        <div class="eli5-about-tour">
          <div class="eli5-about-tour-block">
            <h3 class="eli5-about-subhead">{{ t('eli5.about.tour.short.title') }}</h3>
            <p>{{ t('eli5.about.tour.short.body') }}</p>
          </div>
          <div class="eli5-about-tour-block">
            <h3 class="eli5-about-subhead">{{ t('eli5.about.tour.mid.title') }}</h3>
            <ol class="eli5-about-example-list">
              <li v-for="n in 3" :key="n">{{ t(`eli5.about.tour.mid.step${n}`) }}</li>
            </ol>
          </div>
          <div class="eli5-about-tour-block">
            <h3 class="eli5-about-subhead">{{ t('eli5.about.tour.long.title') }}</h3>
            <p>{{ t('eli5.about.tour.long.intro') }}</p>
            <ol class="eli5-about-example-list">
              <li v-for="n in 4" :key="n">{{ t(`eli5.about.tour.long.step${n}`) }}</li>
            </ol>
          </div>
          <div class="eli5-about-tour-block">
            <h3 class="eli5-about-subhead">{{ t('eli5.about.tour.faq.title') }}</h3>
            <div v-for="n in 4" :key="n" class="eli5-about-faq-item">
              <p class="eli5-about-faq-q">{{ t(`eli5.about.tour.faq.q${n}`) }}</p>
              <p>{{ t(`eli5.about.tour.faq.a${n}`) }}</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.eli5-about {
  min-height: 100%;
}
.eli5-about-inner {
  max-width: 760px;
  margin: 0 auto;
}
.eli5-about-hero .eli5-about-inner {
  max-width: 760px;
}
.eli5-about-sub {
  margin-top: 6px;
}

.eli5-about-inner p {
  line-height: 1.7;
  color: var(--e-muted);
  margin: 0 0 12px;
}
.eli5-about-inner p:last-child {
  margin-bottom: 0;
}

.eli5-about-subhead {
  font-size: 15px;
  font-weight: 800;
  color: var(--e-ink);
  margin: 0 0 6px;
}

.eli5-about-note-inline {
  font-size: 13.5px;
  color: var(--e-faint);
  background: var(--e-band-soft);
  border: 1px solid var(--e-line-soft);
  border-radius: var(--e-radius);
  padding: 12px 16px;
  margin-top: 14px !important;
}

.eli5-about-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
@media (max-width: 640px) {
  .eli5-about-tabs {
    grid-template-columns: 1fr;
  }
}

.eli5-about-chain {
  list-style: none;
  margin: 0 0 16px;
  padding: 0;
  border-left: 2px solid var(--e-line);
  margin-left: 10px;
}
.eli5-about-chain-item {
  position: relative;
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 9px 0 9px 22px;
}
.eli5-about-chain-num {
  position: absolute;
  left: -11px;
  top: 10px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--e-accent);
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
}
.eli5-about-chain-label {
  font-weight: 700;
  color: var(--e-ink);
}
.eli5-about-chain-note {
  font-size: 12.5px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--e-accent);
  background: var(--e-accent-soft);
  border-radius: 999px;
  padding: 2px 9px;
  margin-left: auto;
  white-space: nowrap;
}

.eli5-about-example-list {
  margin: 0 0 12px;
  padding-left: 1.3em;
  line-height: 1.7;
  color: var(--e-muted);
}
.eli5-about-example-list li {
  margin-bottom: 4px;
}

.eli5-about-tour {
  display: grid;
  grid-template-columns: 1fr;
  gap: 22px;
  margin-top: 16px;
}
.eli5-about-tour-block {
  min-width: 0;
}
.eli5-about-faq-item {
  margin-bottom: 10px;
}
.eli5-about-inner p.eli5-about-faq-q {
  font-weight: 700;
  color: var(--e-ink);
  margin-bottom: 2px;
}
.eli5-about-example-list {
  overflow-wrap: anywhere;
}
</style>
