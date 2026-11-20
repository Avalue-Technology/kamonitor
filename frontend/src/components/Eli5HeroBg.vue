<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

const canvasRef = ref(null)
let gl = null
let program = null
let vertShader = null
let fragShader = null
let posBuffer = null
let uTimeLoc = null
let uResLoc = null
let rafId = null
let resizeObserver = null
let reducedMotion = false
let startTime = 0
let cw = 0
let ch = 0

const glOk = ref(true)

const VERT_SRC = `
attribute vec2 aPosition;
varying vec2 vUv;
void main() {
  vUv = aPosition * 0.5 + 0.5;
  gl_Position = vec4(aPosition, 0.0, 1.0);
}
`

const FRAG_SRC = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform float uTime;
uniform vec2 uResolution;
varying vec2 vUv;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

const vec3 purpleDeep  = vec3(0.290, 0.110, 0.700);
const vec3 purpleLight = vec3(0.620, 0.420, 0.980);
const vec3 orangeC     = vec3(1.000, 0.520, 0.160);
const vec3 pinkC       = vec3(0.980, 0.280, 0.560);
const vec3 yellowC     = vec3(1.000, 0.780, 0.220);
const vec3 goldC       = vec3(0.910, 0.722, 0.294);

const vec3 LIGHT_DIR = normalize(vec3(-0.55, 0.55, 0.62));
const float LIGHT_AMBIENT = 0.46;
const float LIGHT_DIFFUSE = 0.70;
const float EDGE_SOFTNESS = 0.42;
const float LIMB_STRENGTH = 0.30;
const float SPEC_POW = 12.0;
const float SPEC_STRENGTH = 0.22;

vec2 rotate2(vec2 v, float a) {
  float c = cos(a);
  float s = sin(a);
  return vec2(v.x * c - v.y * s, v.x * s + v.y * c);
}

vec4 blob(
  vec2 uv, float aspect,
  float radius, float baseX, float period, float phase,
  float swayAmp, float swayFreq, float phaseX,
  float breathPeriod, float breathPhase,
  float colorAngle, float rotSpeed,
  int paletteId,
  float goldWeight,
  float baseAlpha
) {
  float margin = radius * 1.1 + 0.15;
  float g = fract(uTime / period + phase);
  float y = mix(-margin, 1.0 + margin, g);
  float x = baseX + swayAmp * sin(uTime * swayFreq + phaseX);

  vec2 center = vec2(x, y);
  vec2 mp = uv - center;
  mp.x *= aspect;
  float dist = length(mp);

  float edgeIn  = radius * 0.833;
  float edgeOut = radius * 1.033;
  float radial = 1.0 - smoothstep(edgeIn, edgeOut, dist);

  float fadeIn  = smoothstep(0.0, 0.12, g);
  float fadeOut = 1.0 - smoothstep(0.85, 1.0, g);
  float alpha = radial * fadeIn * fadeOut * baseAlpha;

  vec2 q = mp / radius;
  float breath = 0.5 + 0.5 * sin(uTime * (6.28318 / breathPeriod) + breathPhase);
  float sigmaScale = mix(0.80, 1.25, breath);
  float ang = colorAngle + uTime * rotSpeed;

  vec3 colA;
  vec3 colB;
  if (paletteId == 0) {
    colA = purpleDeep; colB = purpleLight;
  } else if (paletteId == 1) {
    colA = purpleDeep; colB = pinkC;
  } else if (paletteId == 2) {
    colA = pinkC; colB = orangeC;
  } else if (paletteId == 3) {
    colA = orangeC; colB = yellowC;
  } else {
    colA = goldC; colB = purpleLight;
  }

  vec2 cpA;
  vec2 cpB;
  float sA;
  float sB;
  if (paletteId == 4) {
    cpA = rotate2(vec2(0.03, 0.02), ang);
    cpB = rotate2(vec2(-0.08, -0.06), ang);
    sA = 0.26 * sigmaScale;
    sB = 0.85 * sigmaScale;
  } else {
    cpA = rotate2(vec2( 0.30,  0.22), ang);
    cpB = rotate2(vec2(-0.30, -0.22), ang);
    sA = 0.62 * sigmaScale;
    sB = 0.62 * sigmaScale;
  }

  float wA = exp(-dot(q - cpA, q - cpA) / (2.0 * sA * sA));
  float wB = exp(-dot(q - cpB, q - cpB) / (2.0 * sB * sB));
  float wSum = wA + wB + 0.0001;
  vec3 color = (wA * colA + wB * colB) / wSum;

  float qq = dot(q, q);
  vec3 sphereN = vec3(q, sqrt(max(0.0, 1.0 - min(qq, 1.0))));
  float ndl = dot(sphereN, LIGHT_DIR);
  float shade = smoothstep(-EDGE_SOFTNESS, EDGE_SOFTNESS, ndl);
  color *= LIGHT_AMBIENT + LIGHT_DIFFUSE * shade;
  float limb = 1.0 - LIMB_STRENGTH * smoothstep(0.45, 1.0, sqrt(qq));
  color *= limb;

  if (goldWeight > 0.0) {
    float hlLuma = dot(color, vec3(0.299, 0.587, 0.114));
    float highlightMask = smoothstep(0.35, 0.75, hlLuma);
    float goldAmount = goldWeight * highlightMask;
    color = mix(color, goldC, goldAmount);
  }

  float luma = dot(color, vec3(0.299, 0.587, 0.114));
  color = mix(vec3(luma), color, 1.25);
  color *= 1.15;

  float spec = pow(max(ndl, 0.0), SPEC_POW) * SPEC_STRENGTH;
  color += vec3(spec);

  return vec4(color, alpha);
}

void main() {
  vec2 uv = vUv;
  float aspect = uResolution.x / uResolution.y;

  vec3 acc = vec3(0.0);
  float accA = 0.0;
  vec4 b;

  b = blob(uv, aspect, 0.55, 0.92, 31.0, 0.10, 0.04, 0.09, 0.5, 12.5, 0.8, 0.00, 0.020, 0, 0.18, 0.78);
  acc = b.rgb * b.a + acc * (1.0 - b.a);
  accA = b.a + accA * (1.0 - b.a);

  b = blob(uv, aspect, 0.42, 1.05, 23.0, 0.55, 0.03, 0.13, 1.9, 9.5, 2.3, 1.05, -0.025, 0, 0.0, 0.70);
  acc = b.rgb * b.a + acc * (1.0 - b.a);
  accA = b.a + accA * (1.0 - b.a);

  b = blob(uv, aspect, 0.35, 0.72, 19.0, 0.30, 0.05, 0.07, 3.4, 11.0, 4.0, 2.10, 0.030, 2, 0.0, 0.62);
  acc = b.rgb * b.a + acc * (1.0 - b.a);
  accA = b.a + accA * (1.0 - b.a);

  b = blob(uv, aspect, 0.28, 0.60, 17.0, 0.75, 0.03, 0.16, 0.2, 14.0, 1.1, 3.15, -0.020, 2, 0.0, 0.36);
  acc = b.rgb * b.a + acc * (1.0 - b.a);
  accA = b.a + accA * (1.0 - b.a);

  b = blob(uv, aspect, 0.50, 0.82, 29.0, 0.05, 0.04, 0.11, 2.6, 8.0, 3.3, 4.20, 0.015, 1, 0.0, 0.72);
  acc = b.rgb * b.a + acc * (1.0 - b.a);
  accA = b.a + accA * (1.0 - b.a);

  b = blob(uv, aspect, 0.20, 0.98, 13.0, 0.42, 0.05, 0.19, 4.7, 10.0, 5.5, 5.25, -0.035, 4, 0.0, 0.58);
  acc = b.rgb * b.a + acc * (1.0 - b.a);
  accA = b.a + accA * (1.0 - b.a);

  vec3 straightColor = acc / max(accA, 0.0001);

  float dither = (hash(gl_FragCoord.xy + fract(uTime) * 97.0) - 0.5) * (2.5 / 255.0);
  straightColor += dither;

  gl_FragColor = vec4(straightColor, accA);
}
`

function compileShader(type, src) {
  const shader = gl.createShader(type)
  gl.shaderSource(shader, src)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader)
    return null
  }
  return shader
}

function setupGl() {
  const canvas = canvasRef.value
  if (!canvas) return false
  gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: false, antialias: false })
    || canvas.getContext('experimental-webgl', { alpha: true, premultipliedAlpha: false, antialias: false })
  if (!gl) return false

  vertShader = compileShader(gl.VERTEX_SHADER, VERT_SRC)
  fragShader = compileShader(gl.FRAGMENT_SHADER, FRAG_SRC)
  if (!vertShader || !fragShader) return false

  program = gl.createProgram()
  gl.attachShader(program, vertShader)
  gl.attachShader(program, fragShader)
  gl.linkProgram(program)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return false

  gl.useProgram(program)

  posBuffer = gl.createBuffer()
  gl.bindBuffer(gl.ARRAY_BUFFER, posBuffer)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
  const aPosition = gl.getAttribLocation(program, 'aPosition')
  gl.enableVertexAttribArray(aPosition)
  gl.vertexAttribPointer(aPosition, 2, gl.FLOAT, false, 0, 0)

  uTimeLoc = gl.getUniformLocation(program, 'uTime')
  uResLoc = gl.getUniformLocation(program, 'uResolution')

  gl.disable(gl.DEPTH_TEST)
  gl.enable(gl.BLEND)
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)

  return true
}

function resize() {
  const canvas = canvasRef.value
  if (!canvas || !gl) return
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const rect = canvas.getBoundingClientRect()
  cw = Math.max(1, Math.round(rect.width * dpr))
  ch = Math.max(1, Math.round(rect.height * dpr))
  if (canvas.width !== cw || canvas.height !== ch) {
    canvas.width = cw
    canvas.height = ch
  }
  gl.viewport(0, 0, cw, ch)
}

function render(timeMs) {
  if (!gl || !program) return
  gl.clearColor(0, 0, 0, 0)
  gl.clear(gl.COLOR_BUFFER_BIT)
  gl.uniform1f(uTimeLoc, (timeMs - startTime) / 1000)
  gl.uniform2f(uResLoc, cw, ch)
  gl.drawArrays(gl.TRIANGLES, 0, 3)
}

function loop(t) {
  if (!document.hidden) render(t)
  rafId = requestAnimationFrame(loop)
}

function releaseGl() {
  if (!gl) return
  if (posBuffer) gl.deleteBuffer(posBuffer)
  if (program) gl.deleteProgram(program)
  if (vertShader) gl.deleteShader(vertShader)
  if (fragShader) gl.deleteShader(fragShader)
  const ext = gl.getExtension('WEBGL_lose_context')
  if (ext) ext.loseContext()
  gl = null
  program = null
  vertShader = null
  fragShader = null
  posBuffer = null
}

onMounted(() => {
  reducedMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches)

  const ok = setupGl()
  glOk.value = ok
  if (!ok) return

  startTime = performance.now()
  resize()
  render(performance.now())

  resizeObserver = new ResizeObserver(() => {
    resize()
    render(performance.now())
  })
  resizeObserver.observe(canvasRef.value)

  if (!reducedMotion) {
    rafId = requestAnimationFrame(loop)
  }
})

onBeforeUnmount(() => {
  if (rafId != null) cancelAnimationFrame(rafId)
  if (resizeObserver) resizeObserver.disconnect()
  releaseGl()
})
</script>

<template>
  <div class="eli5-hero-bg" :class="{ 'eli5-hero-bg--fallback': !glOk }">
    <canvas ref="canvasRef" class="eli5-hero-bg__canvas" aria-hidden="true"></canvas>
  </div>
</template>

<style scoped>
.eli5-hero-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
}
.eli5-hero-bg__canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}
.eli5-hero-bg--fallback {
  background: linear-gradient(
    100deg,
    rgba(255, 255, 255, 0) 0%,
    rgba(255, 255, 255, 0) 45%,
    rgba(101, 81, 216, 0.5) 60%,
    rgba(155, 100, 210, 0.42) 72%,
    rgba(237, 92, 148, 0.38) 82%,
    rgba(250, 160, 90, 0.32) 92%,
    rgba(250, 199, 82, 0.28) 100%
  );
}
.eli5-hero-bg--fallback .eli5-hero-bg__canvas {
  display: none;
}
</style>
