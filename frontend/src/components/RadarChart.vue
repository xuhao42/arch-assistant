<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Candidate } from './CandidateCards.vue'

const props = defineProps<{ candidates: Candidate[] }>()
const canvasRef = ref<HTMLCanvasElement | null>(null)

// 组件接收 CandidateCards 使用的候选架构数据，并将其压缩为课程验收场景下
// 更容易横向比较的质量属性视图；这里的维度顺序需要和 profileMap 分值一一对应。
const dimensions = [
  { key: 'scalability', label: '扩展性' },
  { key: 'performance', label: '性能' },
  { key: 'coupling', label: '低耦合' },
  { key: 'complexity', label: '低复杂度' },
  { key: 'deployability', label: '部署弹性' },
  { key: 'testability', label: '可测试性' },
]

// 质量画像不是用户评分，而是面向架构推荐解释的经验权重。
// 分值保持在 1-5，便于在雷达图中与网格层级直接对应。
const profileMap: Record<string, number[]> = {
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

/**
 * 将候选架构名称归一到内置画像键。
 *
 * 后端可能返回英文、中文或混合名称；前端使用关键词兜底匹配，
 * 避免因为展示名称差异导致雷达图无法绘制。
 *
 * Args:
 *   name: 后端返回的候选架构展示名称。
 * Returns:
 *   profileMap 中可用于读取质量画像的架构键。
 */
function archKey(name: string) {
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

/**
 * 获取候选架构的质量属性分值。
 *
 * 未识别的架构统一回退到分层架构画像，保证短输入或新架构名称不会让图表空白。
 *
 * Args:
 *   candidate: 后端召回并传入前端展示的候选架构。
 * Returns:
 *   与 dimensions 顺序一致的 1-5 分质量属性数组。
 */
function scoresFor(candidate: Candidate) {
  return profileMap[archKey(candidate.name)] ?? profileMap.layered
}

const lineColors = ['#22d3ee', '#a78bfa', '#f59e0b']
const fillColors = ['rgba(34, 211, 238, .16)', 'rgba(167, 139, 250, .12)', 'rgba(245, 158, 11, .10)']

/**
 * 根据当前候选架构和容器尺寸重绘雷达图。
 *
 * Canvas 不会自动响应 CSS 尺寸与设备像素比变化，因此每次候选结果更新或窗口尺寸变化时
 * 都重新同步画布真实像素，避免高分屏模糊或布局调整后图形错位。
 */
function draw() {
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

  // 网格层级固定为 5 层，与质量画像的 1-5 分制保持一致，降低用户理解成本。
  for (let level = 1; level <= levels; level++) {
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

  // 轴线和标签跟随维度配置生成，确保后续调整质量维度时不会遗漏可视化结构。
  dimensions.forEach((dimension, index) => {
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

  // 后绘制排名更靠前的候选，避免 Top 1 被后续候选的大面积填充遮挡。
  for (let candidateIndex = count - 1; candidateIndex >= 0; candidateIndex--) {
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
// candidates 可能由 SSE 分阶段补全或更新，深度监听可以让图表随推荐结果同步刷新。
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
