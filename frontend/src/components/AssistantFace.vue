<script setup>
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const DROWSE_AFTER_MS = 15000
const SLEEP_AFTER_MS = 45000

const BLINK_SIZES = [1, 2, 3]
const BLINK_SHUT_MS = 90
const BLINK_GAP_MS = 130
const BLINK_WAIT_MIN_MS = 2400
const BLINK_WAIT_MAX_MS = 6800

const BLINKING_PHASES = ['idle', 'reasoning', 'tooling', 'speaking']

const MOUTH_Y = 41
const MOUTH_X0 = 25
const MOUTH_X1 = 39
const WAVE_SAMPLES = 14
const WAVE_AMP = 2.4

const CHUNK_PERIOD = 6

const RIM_RADIUS = 26
const RIM_LENGTH = 2 * Math.PI * RIM_RADIUS

const wavePath = (phase, amplitude = WAVE_AMP) => {
  const points = []
  for (let i = 0; i <= WAVE_SAMPLES; i += 1) {
    const at = i / WAVE_SAMPLES
    const x = MOUTH_X0 + (MOUTH_X1 - MOUTH_X0) * at
    const envelope = Math.sin(Math.PI * at)
    const y = MOUTH_Y - amplitude * envelope * Math.sin(2 * Math.PI * (at - phase))
    points.push(`${i === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`)
  }
  return points.join(' ')
}

const REST_MOUTH = wavePath(0, 0)

const bowPath = (depth) => {
  const points = []
  for (let i = 0; i <= WAVE_SAMPLES; i += 1) {
    const at = i / WAVE_SAMPLES
    const x = MOUTH_X0 + (MOUTH_X1 - MOUTH_X0) * at
    const y = MOUTH_Y - depth * Math.sin(Math.PI * at)
    points.push(`${i === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`)
  }
  return points.join(' ')
}
const FROWN_MOUTH = bowPath(1.7)

const props = defineProps({
  phase: {
    type: String,
    default: 'idle',
    validator: (value) =>
      ['idle', 'reasoning', 'tooling', 'speaking', 'error', 'sleepy', 'asleep'].includes(value)
  },
  chunk: {
    type: Number,
    default: 0
  },
  animated: {
    type: Boolean,
    default: true
  },
  tokens: {
    type: Number,
    default: null
  },
  maxTokens: {
    type: Number,
    default: null
  },
  size: {
    type: Number,
    default: 40
  }
})

const uid = useId()
const glassId = `assistant-face-glass-${uid}`
const clipId = `assistant-face-clip-${uid}`
const rimId = `assistant-face-rim-${uid}`
const gaugeId = `assistant-face-gauge-${uid}`

const restStage = ref(null)
let drowseTimer = null
let sleepTimer = null

const clearRestTimers = () => {
  clearTimeout(drowseTimer)
  clearTimeout(sleepTimer)
  drowseTimer = null
  sleepTimer = null
}

const restartRest = () => {
  clearRestTimers()
  restStage.value = null
  if (!props.animated || props.phase !== 'idle') return
  drowseTimer = setTimeout(() => { restStage.value = 'sleepy' }, DROWSE_AFTER_MS)
  sleepTimer = setTimeout(() => { restStage.value = 'asleep' }, SLEEP_AFTER_MS)
}

watch(() => [props.phase, props.animated], restartRest, { immediate: true })
onBeforeUnmount(clearRestTimers)

const displayPhase = computed(() => restStage.value ?? props.phase)

const blinkShut = ref(false)
let blinkTimer = null

const clearBlink = () => {
  clearTimeout(blinkTimer)
  blinkTimer = null
  blinkShut.value = false
}

const pick = (list) => list[Math.floor(Math.random() * list.length)]
const blinkWait = () =>
  BLINK_WAIT_MIN_MS + Math.random() * (BLINK_WAIT_MAX_MS - BLINK_WAIT_MIN_MS)

const blinkOnce = (remaining) => {
  blinkShut.value = true
  blinkTimer = setTimeout(() => {
    blinkShut.value = false
    blinkTimer = remaining > 1
      ? setTimeout(() => blinkOnce(remaining - 1), BLINK_GAP_MS)
      : setTimeout(() => blinkOnce(pick(BLINK_SIZES)), blinkWait())
  }, BLINK_SHUT_MS)
}

const wantsMotion = () =>
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : true

const restartBlink = () => {
  clearBlink()
  if (!props.animated || !wantsMotion()) return
  if (!BLINKING_PHASES.includes(displayPhase.value)) return
  blinkTimer = setTimeout(() => blinkOnce(pick(BLINK_SIZES)), blinkWait())
}

watch(() => [displayPhase.value, props.animated], restartBlink, { immediate: true })
onBeforeUnmount(clearBlink)

const mouthShape = computed(() => {
  if (displayPhase.value === 'reasoning' || displayPhase.value === 'speaking') return 'wave'
  if (displayPhase.value === 'tooling') return 'dots'
  return 'rest'
})

const mouthPath = computed(() => {
  if (displayPhase.value === 'error') return FROWN_MOUTH
  if (mouthShape.value !== 'wave') return REST_MOUTH
  const count = Number.isFinite(props.chunk) ? Math.abs(Math.round(props.chunk)) : 0
  return wavePath((count % CHUNK_PERIOD) / CHUNK_PERIOD)
})

const contextRatio = computed(() => {
  const used = props.tokens
  const total = props.maxTokens
  if (!Number.isFinite(used) || !Number.isFinite(total)) return null
  if (used <= 0 || total <= 0) return null
  return Math.min(1, used / total)
})

const contextPercent = computed(() =>
  contextRatio.value === null ? null : Math.round(contextRatio.value * 100)
)

const gaugeOffset = computed(() =>
  contextRatio.value === null ? RIM_LENGTH : RIM_LENGTH * (1 - contextRatio.value)
)

const PHASE_LABEL_KEY = {
  idle: 'assistantFace.phaseIdle',
  reasoning: 'assistantFace.phaseReasoning',
  tooling: 'assistantFace.phaseTooling',
  speaking: 'assistantFace.phaseSpeaking',
  error: 'assistantFace.phaseError',
  sleepy: 'assistantFace.phaseSleepy',
  asleep: 'assistantFace.phaseAsleep',
}
const label = computed(() => {
  const phase = t(PHASE_LABEL_KEY[displayPhase.value] || PHASE_LABEL_KEY.idle)
  if (contextPercent.value === null) return phase
  return t('assistantFace.labelWithContext', { phase, percent: contextPercent.value })
})
</script>

<template>
  <svg
    class="af"
    :class="{ 'af-still': !animated }"
    :width="size"
    :height="size"
    viewBox="0 0 64 64"
    :data-phase="displayPhase"
    :data-animated="String(animated)"
    :data-blink="blinkShut ? 'shut' : null"
    :data-gauge="contextPercent === null ? null : String(contextPercent)"
    role="img"
    :aria-label="label"
    data-testid="assistant-face"
  >
    <defs>
      <linearGradient :id="glassId" x1="0" y1="0" x2="0.7" y2="1">
        <stop offset="0" stop-color="#ffffff" stop-opacity="0.16" />
        <stop offset="0.55" stop-color="#ffffff" stop-opacity="0.02" />
        <stop offset="1" stop-color="#ffffff" stop-opacity="0" />
      </linearGradient>
      <linearGradient :id="rimId" gradientUnits="userSpaceOnUse" x1="6" y1="6" x2="58" y2="58">
        <stop class="af-stop-near" offset="0" />
        <stop class="af-stop-far" offset="1" />
      </linearGradient>
      <linearGradient
        :id="gaugeId"
        gradientUnits="userSpaceOnUse"
        x1="6"
        y1="6"
        x2="58"
        y2="58"
        gradientTransform="rotate(90 32 32)"
      >
        <stop class="af-stop-near" offset="0" />
        <stop class="af-stop-far" offset="1" />
      </linearGradient>
      <clipPath :id="clipId">
        <circle cx="32" cy="32" r="26" />
      </clipPath>
    </defs>

    <g class="af-body">
      <circle class="af-screen" cx="32" cy="32" r="26" />
      <g :clip-path="`url(#${clipId})`">
        <circle cx="32" cy="32" r="26" :fill="`url(#${glassId})`" />
      </g>
      <circle class="af-rim" cx="32" cy="32" r="26" :stroke="`url(#${rimId})`" />
      <circle
        v-if="contextRatio !== null"
        class="af-gauge"
        cx="32"
        cy="32"
        r="26"
        transform="rotate(-90 32 32)"
        :stroke="`url(#${gaugeId})`"
        :stroke-dasharray="RIM_LENGTH"
        :stroke-dashoffset="gaugeOffset"
        data-testid="assistant-face-gauge"
      />

      <g class="af-gaze">
        <g class="af-lids">
          <ellipse class="af-eye af-eye-l" cx="23" cy="28" rx="6" ry="4.6" />
          <ellipse class="af-eye af-eye-r" cx="41" cy="28" rx="6" ry="4.6" />
        </g>
      </g>

      <g class="af-mouth">
        <path class="af-mouth-line" :d="mouthPath" />
        <g class="af-dots">
          <circle cx="26.5" cy="41" r="1.7" />
          <circle cx="32" cy="41" r="1.7" />
          <circle cx="37.5" cy="41" r="1.7" />
        </g>
      </g>
    </g>
  </svg>
</template>

<style scoped>
.af {
  --af-brand: var(--agent-c-1, var(--ai));
  --af-brand-far: var(--agent-c-2, color-mix(in srgb, var(--ai) 65%, black));
  --af-brand-dim: color-mix(in srgb, var(--af-brand) 50%, var(--af-screen));
  --af-screen: color-mix(in srgb, var(--ai) 55%, #05070d);
  --af-eye: #f2f6fc;
  --af-eye-dim: color-mix(in srgb, var(--ai) 25%, #f2f6fc);
  --af-alert: #dc2626;
  display: block;
  overflow: visible;
}

.af-screen { fill: var(--af-screen); }
.af-rim { fill: none; stroke-width: 3; }
.af-stop-near { stop-color: var(--af-brand); }
.af-stop-far { stop-color: var(--af-brand-far); }
.af[data-gauge] .af-rim { opacity: 0.22; }
.af-gauge {
  fill: none;
  stroke-width: 3;
  stroke-linecap: round;
  transition: stroke-dashoffset 450ms ease-out;
}
.af-eye { fill: var(--af-eye); transform-box: fill-box; transform-origin: center; }
.af-gaze, .af-lids, .af-mouth, .af-body { transform-box: fill-box; transform-origin: center; }
.af-lids { transition: transform 70ms ease-in-out; }
.af[data-blink='shut'] .af-lids { transform: scaleY(0.08); }

.af-mouth-line {
  fill: none;
  stroke: var(--af-eye);
  stroke-width: 2.6;
  stroke-linecap: round;
  stroke-linejoin: round;
  transition: d 200ms ease-out;
}
.af-dots { fill: var(--af-eye); opacity: 0; }
.af[data-phase='tooling'] .af-dots { opacity: 1; }
.af[data-phase='tooling'] .af-mouth-line { opacity: 0; }

.af[data-phase='idle'] .af-gaze { animation: af-drift 7s ease-in-out infinite; }

.af[data-phase='reasoning'] .af-gaze { animation: af-wander 2.8s steps(1, end) infinite; }
.af[data-phase='reasoning'] .af-eye { animation: af-squint 2.8s ease-in-out infinite; }
.af[data-phase='reasoning'] .af-mouth { animation: af-mouth-breathe 1.1s ease-in-out infinite; }

.af[data-phase='tooling'] .af-gaze { animation: af-scan 2.2s steps(1, end) infinite; }
.af[data-phase='tooling'] .af-eye { animation: af-squint 2.2s ease-in-out infinite; }
.af[data-phase='tooling'] .af-dots circle { animation: af-dot 1.2s ease-in-out infinite; }
.af[data-phase='tooling'] .af-dots circle:nth-child(2) { animation-delay: 0.16s; }
.af[data-phase='tooling'] .af-dots circle:nth-child(3) { animation-delay: 0.32s; }

.af[data-phase='speaking'] .af-gaze { animation: af-bob 0.62s ease-in-out infinite; }
.af[data-phase='speaking'] .af-mouth { animation: af-mouth-breathe 0.62s ease-in-out infinite; }

.af[data-phase='sleepy'] .af-eye { animation: af-doze 3.4s ease-in-out infinite; }
.af[data-phase='sleepy'] .af-gaze { transform: translateY(2.4px); }
.af[data-phase='sleepy'] .af-mouth-line { stroke: var(--af-eye-dim); }

.af[data-phase='asleep'] .af-eye { transform: scaleY(0.1); fill: var(--af-eye-dim); }
.af[data-phase='asleep'] .af-gaze { transform: translateY(3px); }
.af[data-phase='asleep'] .af-body { animation: af-breathe 4.6s ease-in-out infinite; }
.af[data-phase='asleep'] .af-rim { stroke: var(--af-brand-dim); }
.af[data-phase='asleep'] .af-gauge { stroke: var(--af-brand-dim); }
.af[data-phase='asleep'] .af-mouth-line { stroke: var(--af-eye-dim); }

.af[data-phase='error'] .af-rim { stroke: var(--af-alert); }
.af[data-phase='error'] .af-gauge { stroke: var(--af-alert); }
.af[data-phase='error'] .af-eye-l { transform: translateY(1px) rotate(-16deg) scaleY(0.62); }
.af[data-phase='error'] .af-eye-r { transform: translateY(1px) rotate(16deg) scaleY(0.62); }
.af[data-phase='error'] .af-mouth { transform: translateY(1.5px) scaleX(0.86); }

@keyframes af-drift {
  0%, 100% { transform: translate(-3.2px, 0.8px); }
  30% { transform: translate(3.6px, -1px); }
  60% { transform: translate(1.2px, 1.6px); }
}
@keyframes af-wander {
  0% { transform: translate(-4.7px, -3.1px); }
  17% { transform: translate(4.3px, -2.2px); }
  34% { transform: translate(2.2px, 3.2px); }
  51% { transform: translate(-4px, 2.7px); }
  68% { transform: translate(0.4px, -4px); }
  85% { transform: translate(5px, 1.3px); }
  100% { transform: translate(-4.7px, -3.1px); }
}
@keyframes af-scan {
  0% { transform: translate(-5px, -2.9px); }
  17% { transform: translate(0px, -2.9px); }
  34% { transform: translate(5px, -2.9px); }
  50% { transform: translate(-5px, 2.9px); }
  67% { transform: translate(0px, 2.9px); }
  84% { transform: translate(5px, 2.9px); }
  100% { transform: translate(-5px, -2.9px); }
}
@keyframes af-squint {
  0%, 100% { transform: scaleY(0.86); }
  50% { transform: scaleY(1); }
}
@keyframes af-bob {
  0%, 100% { transform: translateY(1.1px); }
  50% { transform: translateY(-1.1px); }
}
@keyframes af-mouth-breathe {
  0%, 100% { transform: scaleY(0.86); }
  50% { transform: scaleY(1.16); }
}
@keyframes af-dot {
  0%, 100% { transform: translateY(0); opacity: 0.45; }
  40% { transform: translateY(-1.6px); opacity: 1; }
}
@keyframes af-doze {
  0%, 100% { transform: scaleY(0.46); }
  45% { transform: scaleY(0.5); }
  52% { transform: scaleY(0.12); }
  60% { transform: scaleY(0.46); }
}
@keyframes af-breathe {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.03); }
}

.af-dots circle { transform-box: fill-box; transform-origin: center; }

:where(.dark) .af {
  --af-brand: var(--agent-c-1, var(--ai));
  --af-brand-far: var(--agent-c-2, color-mix(in srgb, var(--ai) 65%, black));
}
:where(.dark) .af[data-phase='asleep'] .af-rim { stroke: var(--af-brand-dim); }
:where(.dark) .af[data-phase='asleep'] .af-gauge { stroke: var(--af-brand-dim); }
:where(.dark) .af[data-phase='error'] .af-rim { stroke: #f87171; }
:where(.dark) .af[data-phase='error'] .af-gauge { stroke: #f87171; }

.af-still *, .af-still {
  animation: none !important;
}
@media (prefers-reduced-motion: reduce) {
  .af *, .af {
    animation: none !important;
  }
  .af-lids { transition: none; }
  .af-gauge { transition: none; }

  .af[data-phase='reasoning'] .af-gaze { transform: translate(-4.7px, -3.1px); }
  .af[data-phase='reasoning'] .af-eye { transform: scaleY(0.86); }
}
</style>
