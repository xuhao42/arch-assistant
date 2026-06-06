import { readonly, ref } from 'vue'

// SSEStep 描述前端进度条中的一个阶段，和后端事件名称保持松耦合。
export interface SSEStep {
  name: string
  status: 'pending' | 'active' | 'done' | 'error'
  message: string
}

const initialSteps: SSEStep[] = [
  { name: 'connect', status: 'pending', message: '连接后端服务' },
  { name: 'features', status: 'pending', message: '提取需求特征' },
  { name: 'candidates', status: 'pending', message: '匹配候选架构' },
  { name: 'report', status: 'pending', message: '生成评估报告' },
  { name: 'done', status: 'pending', message: '完成分析' },
]

export function useSSE() {
  // 组合函数封装 SSE 分析流程，适合独立组件复用流式进度和错误状态。
  const steps = ref<SSEStep[]>(initialSteps.map(step => ({ ...step })))
  const isStreaming = ref(false)
  const error = ref<string | null>(null)

  function resetSteps() {
    // 每次新请求都复制初始数组，避免直接复用对象造成状态串扰。
    steps.value = initialSteps.map(step => ({ ...step }))
  }

  function updateStep(name: string, status: SSEStep['status']) {
    // 根据阶段名更新状态；未知阶段直接忽略，兼容后端新增事件。
    const step = steps.value.find(item => item.name === name)
    if (step) step.status = status
  }

  async function streamAnalyze(prompt: string, sessionId: string): Promise<any> {
    // 发起流式分析请求，并把 SSE 事件累积成一个最终结果对象返回。
    isStreaming.value = true
    error.value = null
    resetSteps()
    updateStep('connect', 'active')

    const result: any = { features: null, candidates: null, report: null }

    try {
      const response = await fetch('/api/v1/analyze/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, session_id: sessionId }),
      })

      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`)

      updateStep('connect', 'done')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        // SSE frame 可能跨网络包到达，因此最后一段暂存到 buffer。
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''

        for (const frame of frames) {
          const line = frame.split('\n').find(item => item.startsWith('data: '))
          if (!line) continue
          try {
            const data = JSON.parse(line.slice(6))
            switch (data.event) {
              case 'features':
                updateStep('features', 'done')
                result.features = data.data
                break
              case 'candidates':
                updateStep('candidates', 'done')
                result.candidates = data.data
                break
              case 'report':
                updateStep('report', 'done')
                result.report = data.data
                break
              case 'done':
                updateStep('done', 'done')
                break
              case 'error':
                error.value = data.message
                updateStep('report', 'error')
                break
            }
          } catch {
            // 忽略暂时不完整或格式异常的帧，避免单条坏数据中断整个流。
          }
        }
      }
    } catch (event: any) {
      error.value = event.message
      if (!result.features && !result.candidates) throw event
    } finally {
      isStreaming.value = false
    }

    return result
  }

  return {
    steps: readonly(steps),
    isStreaming: readonly(isStreaming),
    error: readonly(error),
    streamAnalyze,
  }
}
