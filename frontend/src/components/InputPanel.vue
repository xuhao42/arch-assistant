<script setup lang="ts">
// 需求输入组件：统一处理文本输入、示例填充、单次语音输入和连续语音通话。
import { computed, ref } from 'vue'
import { useSpeech } from '../composables/useSpeech'

defineProps<{ isBusy?: boolean }>()

const emit = defineEmits<{
  // submit 用于文本/单次语音提交，callUtterance 用于连续语音通话的每轮累计需求。
  submit: [prompt: string, sessionId: string]
  callUtterance: [prompt: string, sessionId: string]
}>()

const { isListening, isCallActive, isSpeaking, statusText, startMic, stopMic, startCall, stopCall, stopSpeaking } = useSpeech()
const prompt = ref('')

const samplePrompts = [
  '开发银行核心交易系统，需要处理转账、存款、贷款等业务，对数据一致性和审计追踪有极高要求，支持日均百万笔交易。',
  '构建大型 B2C 电商平台，包含商品、订单、支付、物流和评价模块，日活百万级，大促期间流量暴涨。',
  '开发在线视频处理平台，用户上传视频后需要经过转码、加水印、生成缩略图、内容审核等一系列处理步骤。',
]

const canSend = computed(() => prompt.value.trim().length > 0)

function submitPrompt(text = prompt.value) {
  // 文本提交时生成新的 sessionId，让主应用能区分并发或连续请求。
  const value = text.trim()
  if (!value) return
  prompt.value = ''
  emit('submit', value, crypto.randomUUID())
}

function handleVoiceUtterance(text: string) {
  // 连续通话每识别完一轮，就把累计后的完整需求作为一次分析输入。
  emit('callUtterance', text, crypto.randomUUID())
}

function toggleCall() {
  // 通话按钮在开始和结束之间切换，实际识别循环由 useSpeech 维护。
  if (isCallActive.value) {
    stopCall()
  } else {
    startCall(handleVoiceUtterance)
  }
}

async function handleMic() {
  // 单次语音输入完成后自动提交，适合快速说出一个完整需求。
  if (isListening.value) {
    stopMic()
    return
  }
  try {
    const text = await startMic()
    prompt.value = text
    submitPrompt(text)
  } catch {
    // 浏览器语音识别可能被用户取消、拒绝授权或因设备不可用而失败。
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="glass overflow-hidden">
      <div class="border-b border-white/10 px-5 py-4">
        <p class="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200">Requirement Input</p>
        <h2 class="mt-1 text-lg font-bold text-white">描述你的软件系统需求</h2>
        <p class="mt-1 text-xs leading-5 text-slate-400">支持文本输入、单次语音输入和连续语音通话。</p>
      </div>

      <div class="p-5">
        <textarea
          v-model="prompt"
          class="h-36 w-full resize-none rounded-lg border border-white/10 bg-slate-950/70 p-4 text-sm leading-6 text-slate-100 placeholder:text-slate-500 focus:border-cyan-300/60 focus:outline-none focus:ring-2 focus:ring-cyan-400/10"
          placeholder="例如：开发一个跨平台即时通讯系统，支持万人同时在线，要求消息实时可靠，后期需要快速扩展视频通话能力。"
          :disabled="isBusy"
          @keydown.enter.exact.prevent="submitPrompt()"
        />

        <div class="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div class="flex flex-wrap items-center gap-2">
            <button
              class="toolbar-button"
              :class="isListening ? 'toolbar-button-danger' : ''"
              :disabled="isCallActive || isBusy"
              :title="isListening ? '停止语音输入' : '语音输入'"
              @click="handleMic"
            >
              <span>{{ isListening ? '■' : '🎙' }}</span>
              <span>{{ isListening ? '聆听中' : '语音' }}</span>
            </button>

            <button
              class="toolbar-button"
              :class="isCallActive ? 'toolbar-button-danger' : 'toolbar-button-success'"
              :disabled="isBusy"
              :title="isCallActive ? '结束语音通话' : '语音通话'"
              @click="toggleCall"
            >
              <span>{{ isCallActive ? '■' : '☎' }}</span>
              <span>{{ isCallActive ? '通话中' : '通话' }}</span>
            </button>

            <button
              v-if="isSpeaking"
              class="toolbar-button"
              title="停止朗读"
              @click="stopSpeaking"
            >
              <span>↯</span>
              <span>停止朗读</span>
            </button>
          </div>

          <button class="primary-action" :disabled="!canSend || isBusy" @click="submitPrompt()">
            <span v-if="isBusy" class="inline-block animate-spin">◌</span>
            <span v-else>→</span>
            <span>{{ isBusy ? '分析中' : '开始分析' }}</span>
          </button>
        </div>
      </div>
    </div>

    <div class="glass p-4">
      <div class="mb-3 flex items-center justify-between">
        <h3 class="text-sm font-semibold text-slate-100">示例场景</h3>
        <span class="text-xs text-slate-500">点击填入</span>
      </div>
      <div class="space-y-2">
        <button
          v-for="sample in samplePrompts"
          :key="sample"
          class="sample-button"
          type="button"
          @click="prompt = sample"
        >
          {{ sample }}
        </button>
      </div>
    </div>

    <div v-if="statusText" class="rounded border border-white/10 bg-slate-950/60 px-3 py-2 text-center text-xs text-slate-400">
      {{ statusText }}
    </div>
  </div>
</template>
