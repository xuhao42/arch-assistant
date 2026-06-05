<script setup lang="ts">
// 本入口组件负责承接用户架构分析请求，并把后端分阶段返回的特征、
// 候选架构、拓扑图和报告分发给各展示组件；核心下游为分析 API、
// SSE 流式通道以及各个结果可视化组件。
import { computed, onBeforeUnmount, ref } from 'vue'
import axios from 'axios'
import CandidateCards, { type Candidate } from './components/CandidateCards.vue'
import ComboRec from './components/ComboRec.vue'
import DecisionTrace from './components/DecisionTrace.vue'
import FeatureTags from './components/FeatureTags.vue'
import InputPanel from './components/InputPanel.vue'
import RadarChart from './components/RadarChart.vue'
import ReportPanel from './components/ReportPanel.vue'
import TopologyDiagram, { type RequirementTopology } from './components/TopologyDiagram.vue'

interface AnalyzeResult {
  // 后端会按阶段返回部分字段，因此页面状态允许缺省值；
  // 这样可以在报告尚未完成前先展示已完成的特征和候选结果。
  features: Record<string, any> | null
  candidates: Candidate[]
  topology: RequirementTopology | null
  case_matches: CaseMatch[]
  report: string | null
  cached?: boolean
}

interface CaseMatch {
  prompt: string
  matched_terms?: string[]
  recommendations?: string[]
  score?: number
  count?: number
}

const theme = ref<'dark' | 'light'>('dark')
const result = ref<AnalyzeResult>({
  features: null,
  candidates: [],
  topology: null,
  case_matches: [],
  report: null,
})
const isAnalyzing = ref(false)
const statusMessage = ref('')
const errorMessage = ref('')
let reportTimer: number | undefined
const activeSessionId = ref<string | null>(null)
let streamController: AbortController | undefined

const featureList = computed(() => {
  const features = result.value.features
  if (!features) return []
  // 后端兼容历史字段 features 与新字段 key_requirements；
  // 前端在这里统一去重和截断，避免标签区被相近特征撑满。
  const raw = [
    ...(Array.isArray(features.features) ? features.features : []),
    ...(Array.isArray(features.key_requirements) ? features.key_requirements : []),
  ]
  return Array.from(new Set(raw.filter(Boolean).map(String))).slice(0, 10)
})

const topArchName = computed(() => result.value.candidates[0]?.name || '')
const hasPartialResult = computed(() => Boolean(result.value.features || result.value.candidates.length || result.value.report))
const appClasses = computed(() => ['min-h-screen app-shell', theme.value === 'light' ? 'theme-light' : 'theme-dark'])

function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark'
}

function emptyResult(): AnalyzeResult {
  return {
    features: null,
    candidates: [],
    topology: null,
    case_matches: [],
    report: null,
    cached: false,
  }
}

function stopReportTyping() {
  if (reportTimer) {
    window.clearInterval(reportTimer)
    reportTimer = undefined
  }
}

function isActiveSession(sessionId: string) {
  return activeSessionId.value === sessionId
}

function typeReport(fullText: string, sessionId: string) {
  // 报告可能在流式请求或 fallback 请求结束后到达；
  // 每次启动打字机前先停止旧计时器，防止过期会话继续改写当前结果。
  stopReportTyping()
  if (!isActiveSession(sessionId)) return

  result.value = { ...result.value, report: '' }

  let index = 0
  const step = Math.max(1, Math.ceil(fullText.length / 260))
  reportTimer = window.setInterval(() => {
    if (!isActiveSession(sessionId)) {
      stopReportTyping()
      return
    }

    index = Math.min(fullText.length, index + step)
    result.value = { ...result.value, report: fullText.slice(0, index) }
    if (index >= fullText.length) stopReportTyping()
  }, 12)
}

function normalizeCandidates(value: unknown): Candidate[] {
  return Array.isArray(value) ? value as Candidate[] : []
}

function applyStreamEvent(data: any, sessionId: string) {
  // SSE 会按 status、features、candidates、report 等业务阶段推送；
  // 会话校验可以避免用户连续提交时，较慢的旧请求覆盖新请求页面。
  if (!isActiveSession(sessionId)) return

  if (data.event === 'status') {
    statusMessage.value = data.message || ''
    return
  }

  if (data.event === 'features') {
    result.value = { ...result.value, features: data.data || null }
    statusMessage.value = '已提取需求特征，继续匹配候选架构...'
    return
  }

  if (data.event === 'case_matches') {
    result.value = { ...result.value, case_matches: Array.isArray(data.data) ? data.data : [] }
    return
  }

  if (data.event === 'candidates') {
    result.value = { ...result.value, candidates: normalizeCandidates(data.data) }
    statusMessage.value = '候选架构已生成，正在整理评估报告...'
    return
  }

  if (data.event === 'topology') {
    result.value = { ...result.value, topology: data.data || null }
    statusMessage.value = '已生成贴合需求的架构拓扑图...'
    return
  }

  if (data.event === 'report') {
    statusMessage.value = '报告生成完成，正在逐字呈现...'
    typeReport(data.data || '', sessionId)
    return
  }

  if (data.event === 'done') {
    if (data.report && !result.value.report) typeReport(data.report, sessionId)
    statusMessage.value = '分析完成'
    return
  }

  if (data.event === 'error') {
    throw new Error(data.message || '流式分析失败')
  }
}

async function analyzeWithStream(prompt: string, sessionId: string) {
  // 优先使用流式接口，让用户在特征抽取和候选召回完成后立即看到部分结果；
  // AbortController 用于在新一轮提交或组件卸载时主动释放连接。
  streamController = new AbortController()
  const response = await fetch('/api/v1/analyze/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, session_id: sessionId }),
    signal: streamController.signal,
  })

  if (!isActiveSession(sessionId)) return

  if (!response.ok || !response.body) {
    throw new Error(`HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    // 请求取消后主动 cancel reader，避免浏览器仍持有已经无用的 SSE 连接。
    if (!isActiveSession(sessionId)) {
      await reader.cancel()
      break
    }

    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''

    for (const frame of frames) {
      // 后端使用标准 SSE data 行承载 JSON；忽略非 data 行可兼容心跳或扩展字段。
      const dataLine = frame.split('\n').find(line => line.startsWith('data: '))
      if (!dataLine) continue
      applyStreamEvent(JSON.parse(dataLine.slice(6)), sessionId)
    }
  }
}

async function analyzeWithFallback(prompt: string, sessionId: string) {
  // 普通接口作为流式通道不可用时的兜底，保证代理、网关或浏览器不支持 SSE 时
  // 仍能得到完整分析结果，只是失去分阶段展示体验。
  const response = await axios.post('/api/v1/analyze', { prompt, session_id: sessionId }, { timeout: 180000 })
  if (!isActiveSession(sessionId)) return

  const data = response.data || {}
  result.value = {
    features: data.features || null,
    candidates: normalizeCandidates(data.candidates),
    topology: data.topology || null,
    case_matches: Array.isArray(data.case_matches) ? data.case_matches : [],
    report: '',
    cached: data.cached,
  }
  typeReport(data.report || '', sessionId)
}

async function handleSubmit(prompt: string, sessionId: string) {
  // 每次提交都视为新的分析会话：清空旧结果、终止旧连接，并通过 sessionId
  // 约束异步回写范围，避免高延迟响应造成界面状态串扰。
  streamController?.abort()
  stopReportTyping()
  activeSessionId.value = sessionId
  result.value = emptyResult()
  errorMessage.value = ''
  statusMessage.value = '正在连接分析服务...'
  isAnalyzing.value = true

  try {
    await analyzeWithStream(prompt, sessionId)
  } catch (streamError: any) {
    if (!isActiveSession(sessionId) || streamError?.name === 'AbortError') return

    try {
      statusMessage.value = '流式通道不可用，切换为普通分析...'
      await analyzeWithFallback(prompt, sessionId)
    } catch (fallbackError: any) {
      if (!isActiveSession(sessionId)) return

      errorMessage.value = `请求失败：${fallbackError?.response?.data?.detail || fallbackError?.message || streamError?.message || '未知错误'}`
      result.value = { ...result.value, report: errorMessage.value }
    }
  } finally {
    if (isActiveSession(sessionId)) {
      isAnalyzing.value = false
      streamController = undefined
    }
  }
}

onBeforeUnmount(() => {
  streamController?.abort()
  stopReportTyping()
})
</script>

<template>
  <div :class="appClasses">
    <header class="app-header-shell sticky top-0 z-20 border-b border-white/10">
      <div class="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4 md:px-8">
        <div class="flex items-center gap-3">
          <div class="flex h-12 w-12 items-center justify-center rounded-xl bg-cyan-400 text-lg font-black text-slate-950 shadow-lg shadow-cyan-500/20">
            AA
          </div>
          <div>
            <h1 class="text-xl font-black text-white md:text-2xl">Architecture Assistant</h1>
            <p class="text-sm text-slate-400">软件架构风格智能助手 · 多 Agent 决策工作台</p>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <button class="theme-toggle" type="button" :title="theme === 'dark' ? '切换日间模式' : '切换夜间模式'" @click="toggleTheme">
            <span>{{ theme === 'dark' ? '日间' : '夜间' }}</span>
          </button>
          <span class="rounded-lg border border-emerald-300/25 bg-emerald-300/10 px-3 py-2 text-sm font-bold text-emerald-200">4 个微服务</span>
          <span class="rounded-lg border border-cyan-300/25 bg-cyan-300/10 px-3 py-2 text-sm font-bold text-cyan-200">3 个智能体</span>
        </div>
      </div>
    </header>

    <main class="app-main-surface mx-auto grid max-w-7xl grid-cols-1 gap-6 px-4 py-6 md:px-8 xl:grid-cols-[390px_1fr]">
      <section class="space-y-5">
        <InputPanel :is-busy="isAnalyzing" @submit="handleSubmit" @call-utterance="handleSubmit" />

        <div class="grid grid-cols-1 gap-4 sm:grid-cols-3 xl:grid-cols-1">
          <div class="metric-card">
            <span class="metric-label">首选架构</span>
            <strong class="metric-value">{{ topArchName || '暂无' }}</strong>
          </div>
          <div class="metric-card">
            <span class="metric-label">匹配度</span>
            <strong class="metric-value">{{ result.candidates[0] ? `${(result.candidates[0].match_score * 100).toFixed(0)}%` : '--' }}</strong>
          </div>
          <div class="metric-card">
            <span class="metric-label">提取特征</span>
            <strong class="metric-value">{{ featureList.length }} 项</strong>
          </div>
        </div>

        <div v-if="statusMessage || isAnalyzing" class="glass px-4 py-3 text-sm text-slate-300">
          <span v-if="isAnalyzing" class="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-cyan-300" />
          {{ statusMessage }}
        </div>
      </section>

      <section class="space-y-5">
        <section v-if="!hasPartialResult" class="hero-panel glass p-6">
          <p class="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200">Architecture Workbench</p>
          <h2 class="mt-2 text-2xl font-black text-white">输入需求后，系统会分阶段展示分析结果</h2>
          <p class="mt-3 max-w-2xl text-sm leading-7 text-slate-300">
            特征抽取、候选架构、拓扑图和评估报告会按处理进度陆续出现；报告正文采用打字机效果，减少等待完整响应时的空白感。
          </p>
        </section>

        <!-- 下列结果组件消费 SSE 或 fallback 返回的阶段性状态，按分析进度逐步展开页面。 -->
        <FeatureTags v-if="featureList.length" :features="featureList" />
        <CandidateCards v-if="result.candidates.length" :candidates="result.candidates" />
        <div v-if="result.candidates.length" class="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <RadarChart :candidates="result.candidates" />
          <TopologyDiagram :arch-name="topArchName" :topology="result.topology" />
        </div>
        <DecisionTrace v-if="result.candidates.length" :candidates="result.candidates" :case-matches="result.case_matches" />
        <ComboRec v-if="result.candidates.length >= 2" :candidates="result.candidates" />
        <ReportPanel v-if="result.report" :report="result.report" />
        <div v-if="errorMessage && !result.report" class="glass border-rose-400/30 p-4 text-sm text-rose-200">
          {{ errorMessage }}
        </div>
      </section>
    </main>
  </div>
</template>
