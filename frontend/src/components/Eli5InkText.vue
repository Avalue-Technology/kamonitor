<script setup>
import { computed } from 'vue'

const props = defineProps({
  blocks: { type: Array, default: () => [] },
  revealing: { type: Boolean, default: false },
  tag: { type: String, default: 'p' },
})

const TOTAL_MS = 1900
const WORD_MS = 900

function segmentWords(text) {
  if (!text) return []
  if (typeof Intl !== 'undefined' && Intl.Segmenter) {
    try {
      return [...new Intl.Segmenter(undefined, { granularity: 'word' }).segment(text)].map((s) => s.segment)
    } catch {
    }
  }
  return text.split(/(\s+)/).filter((s) => s.length)
}

const wordBlocks = computed(() => {
  const flat = []
  const perBlock = props.blocks.map((segs) => {
    const words = []
    for (const seg of segs || []) {
      for (const w of segmentWords(seg.text)) {
        const rec = { text: w, bold: !!seg.type }
        words.push(rec)
        flat.push(rec)
      }
    }
    return words
  })
  const total = flat.length
  const step = total > 1 ? (TOTAL_MS - WORD_MS) / (total - 1) : 0
  flat.forEach((w, i) => {
    w.delay = Math.round(i * step)
  })
  return perBlock
})
</script>

<template>
  <component :is="tag" v-for="(block, bi) in blocks" :key="bi" class="eli5-ink-text">
    <template v-if="revealing">
      <template v-for="(w, wi) in wordBlocks[bi]" :key="wi">
        <b v-if="w.bold" class="eli5-ink-text__w" :style="{ '--wd': WORD_MS + 'ms', '--dl': w.delay + 'ms' }">{{ w.text }}</b><span
          v-else
          class="eli5-ink-text__w"
          :style="{ '--wd': WORD_MS + 'ms', '--dl': w.delay + 'ms' }"
        >{{ w.text }}</span>
      </template>
    </template>
    <template v-else>
      <template v-for="(seg, si) in block" :key="si"><b v-if="seg.type">{{ seg.text }}</b><template v-else>{{ seg.text }}</template></template>
    </template>
  </component>
</template>

<style scoped>
.eli5-ink-text__w {
  display: inline;
  animation: eli5-ink-seep var(--wd) ease-out both;
  animation-delay: var(--dl);
}
@keyframes eli5-ink-seep {
  0% {
    opacity: 0;
    filter: blur(7px);
    color: var(--e-ai-ink);
  }
  55% {
    opacity: 1;
    filter: blur(1.2px);
    color: color-mix(in srgb, var(--e-ai-ink) 45%, var(--e-ink));
  }
  100% {
    opacity: 1;
    filter: blur(0);
    color: var(--e-ink);
  }
}
@media (prefers-reduced-motion: reduce) {
  .eli5-ink-text__w {
    animation: none;
  }
}
</style>
