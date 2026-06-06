<script setup lang="ts">
// 雷达图组件：把候选架构映射到六个质量属性维度，用 canvas 绘制对比图。
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Candidate } from './CandidateCards.vue'

const props = defineProps<{ candidates: Candidate[] }>()
const canvasRef = ref<HTMLCanvasElement | null>(null)

const dimensions = [
  // 维度顺序同时决定雷达图轴线顺序和得分数组索引。
  { key: 'scalability', label: '扩展性' },
  { key: 'performance', label: '性能' },
  { key: 'coupling', label: '低耦合' },
  { key: 'complexity', label: '低复杂度' },
  { key: 'deployability', label: '部署弹性' },
  { key: 'testability', label: '可测试性' },
]

const profileMap: Record<string, number[]> = {
  // 每类架构的课程化经验评分，范围 1-5，越高代表该维度越有优势。
  layered: [2, 3, 2, 5, 2, 3],
  microservices: [5, 3, 5, 2, 5, 4],
  event: [5, 5, 5, 2, 4, 3],
  cqrs: [5, 5, 4, 2, 4, 4],
  pipe: [3, 5, 5, 4, 3, 5],
  soa: [3, 2, 3, 2, 3, 3],
  hexagonal: [3, 3, 5, 3, 4, 5],
  mvc: [2, 3, 3, 5, 2, 3],
  space: [5, 5, 4, 1, 4, 2],
  p2p: [5, 3, 5, 2, 4, 2],
  serverless: [5, 3, 5, 3, 5, 3],
  plugin: [3, 3, 5, 3, 4, 5],
}

function archKey(name: string) {
  // 把中英文架构名称归一化为 profileMap 的键。
  const n = name.toLowerCase()
  if (n.includes('microservice') || n.includes('微服务')) return 'microservices'
  if (n.includes('event') || n.includes('事件')) return 'event'
  if (n.includes('cqrs')) return 'cqrs'
  if (n.includes('pipe') || n.includes('管道')) return 'pipe'
  if (n.includes('soa')) return 'soa'
  if (n.includes('hexagonal') || n.includes('六边形')) return 'hexagonal'
  if (n.includes('mvc')) return 'mvc'
  if (n.includes('space')) return 'space'
  if (n.includes('peer') || n.includes('p2p') || n.includes('对等')) return 'p2p'
  if (n.includes('serverless')) return 'serverless'
  if (n.includes('plugin') || n.includes('microkernel') || n.includes('插件')) return 'plugin'
  return 'layered'
}

function scoresFor(candidate: Candidate) {
  // 未识别架构默认按分层架构展示，避免图表空白。
  return profileMap[archKey(candidate.name)] ?? profileMap.layered
}

const lineColors = ['#22d3ee', '#a78bfa', '#f59e0b']
const fillColors = ['rgba(34, 211, 238, .16)', 'rgba(167, 139, 250, .12)', 'rgba(245, 158, 11, .10)']

function draw() {
  // 根据当前 canvas 尺寸和设备像素比重绘雷达图，确保高分屏清晰。
  const canvas = canvasRef.value
  if (!canvas || !props.candidates.length) return

  const dpr = window.devicePixelRatio || 1
  const rect = canvas.getBoundingClientRect()
  canvas.width = rect.width * dpr
  canvas.height = rect.height * dpr

  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

  const width = rect.width
  const height = rect.height
  const cx = width / 2
  const cy = height / 2
  const radius = Math.min(width, height) * 0.34
  const levels = 5
  const count = Math.min(props.candidates.length, 3)

  ctx.clearRect(0, 0, width, height)

  for (let level = 1; level <= levels; level++) {
    // 绘制从内到外的多边形网格。
    ctx.beginPath()
    dimensions.forEach((_, index) => {
      const angle = (Math.PI * 2 * index) / dimensions.length - Math.PI / 2
      const r = (radius * level) / levels
      const x = cx + r * Math.cos(angle)
      const y = cy + r * Math.sin(angle)
      index === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.closePath()
    ctx.strokeStyle = level === levels ? 'rgba(148, 163, 184, .38)' : 'rgba(71, 85, 105, .30)'
    ctx.lineWidth = 1
    ctx.stroke()
  }

  dimensions.forEach((dimension, index) => {
    // 绘制每个质量属性的轴线和标签。
    const angle = (Math.PI * 2 * index) / dimensions.length - Math.PI / 2
    ctx.beginPath()
    ctx.moveTo(cx, cy)
    ctx.lineTo(cx + radius * Math.cos(angle), cy + radius * Math.sin(angle))
    ctx.strokeStyle = 'rgba(71, 85, 105, .28)'
    ctx.stroke()

    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text-soft') || '#cbd5e1'
    ctx.font = '12px Microsoft YaHei, system-ui, sans-serif'
    ctx.textAlign = 'center'
    const labelRadius = radius + 24
    ctx.fillText(dimension.label, cx + labelRadius * Math.cos(angle), cy + labelRadius * Math.sin(angle) + 4)
  })

  for (let candidateIndex = count - 1; candidateIndex >= 0; candidateIndex--) {
    // 从后往前绘制候选架构区域，保证首选架构线条显示在最上层。
    const scores = scoresFor(props.candidates[candidateIndex])
    ctx.beginPath()
    scores.forEach((score, index) => {
      const angle = (Math.PI * 2 * index) / dimensions.length - Math.PI / 2
      const r = (radius * score) / levels
      const x = cx + r * Math.cos(angle)
      const y = cy + r * Math.sin(angle)
      index === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.closePath()
    ctx.fillStyle = fillColors[candidateIndex]
    ctx.fill()
    ctx.strokeStyle = lineColors[candidateIndex]
    ctx.lineWidth = 2
    ctx.stroke()
  }
}

onMounted(() => {
  nextTick(draw)
  window.addEventListener('resize', draw)
})

onUnmounted(() => window.removeEventListener('resize', draw))
watch(() => props.candidates, () => nextTick(draw), { deep: true })
</script>

<template>
  <section class="glass p-5 animate-in">
    <div class="mb-4">
      <p class="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200">Quality Matrix</p>
      <h3 class="mt-1 text-lg font-bold text-white">多维质量属性雷达</h3>
    </div>
    <canvas ref="canvasRef" class="mx-auto aspect-square max-h-[360px] w-full" />
  </section>
</template>
