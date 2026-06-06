import { onUnmounted, readonly, ref } from 'vue'

export function useSpeech() {
  // 语音组合函数封装浏览器识别、语音播报和连续通话状态。
  const isListening = ref(false)
  const isCallActive = ref(false)
  const isSpeaking = ref(false)
  const statusText = ref('')
  const interimText = ref('')

  let recognition: any = null
  let synthesis: SpeechSynthesis | null = null
  let callTurns: string[] = []
  let onCallUtterance: ((text: string) => void) | null = null

  if (typeof window !== 'undefined') {
    // SSR 或测试环境中没有 window，因此只在浏览器内绑定 speechSynthesis。
    synthesis = window.speechSynthesis
  }

  function speechRecognitionSupported() {
    // Chrome/Edge 使用 webkitSpeechRecognition，标准实现则使用 SpeechRecognition。
    return typeof window !== 'undefined' && ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)
  }

  function createRecognition() {
    // 创建一次性中文识别器；连续通话通过 onend 后重新创建来实现。
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    const instance = new SpeechRecognition()
    instance.lang = 'zh-CN'
    instance.interimResults = true
    instance.continuous = false
    return instance
  }

  function startMic(): Promise<string> {
    // 单次麦克风输入：返回最终识别文本，供输入框直接提交。
    return new Promise((resolve, reject) => {
      if (!speechRecognitionSupported()) {
        reject(new Error('当前浏览器不支持语音识别，请使用 Chrome 或 Edge。'))
        return
      }

      interimText.value = ''
      recognition = createRecognition()
      isListening.value = true
      statusText.value = '正在聆听，请说出需求...'

      recognition.onresult = (event: any) => {
        // interimResults 会持续返回临时识别文本，这里合并成实时预览。
        let text = ''
        for (let index = 0; index < event.results.length; index++) {
          text += event.results[index][0].transcript
        }
        interimText.value = text
      }

      recognition.onerror = (event: any) => {
        statusText.value = '语音识别失败：' + event.error
        stopMic()
        reject(event)
      }

      recognition.onend = () => {
        stopMic()
        const finalText = interimText.value.trim()
        if (finalText) resolve(finalText)
      }

      recognition.start()
    })
  }

  function stopMic() {
    // 停止当前识别器；浏览器可能已自动结束，所以 stop 需要容错。
    isListening.value = false
    if (!isCallActive.value) statusText.value = ''
    if (recognition) {
      try {
        recognition.stop()
      } catch {
        // Recognition may already be stopped.
      }
      recognition = null
    }
  }

  function startCall(callback: (text: string) => void) {
    // 连续语音通话模式：每轮识别结束后把累计需求交给调用方分析。
    if (!speechRecognitionSupported()) {
      statusText.value = '语音通话需要 Chrome 或 Edge 桌面浏览器。'
      return
    }

    isCallActive.value = true
    callTurns = []
    onCallUtterance = callback
    synthesis?.cancel()
    statusText.value = '语音通话已开始，说完稍停即可自动分析。'
    startCallRecognition()
  }

  function stopCall() {
    // 结束通话时清空轮次、回调和播报，避免后续识别继续触发分析。
    isCallActive.value = false
    callTurns = []
    onCallUtterance = null
    synthesis?.cancel()
    stopMic()
    statusText.value = '语音通话已结束。'
  }

  function startCallRecognition() {
    // 启动通话中的一轮识别；结束后根据内容决定继续监听或提交分析。
    if (!isCallActive.value || isListening.value) return

    interimText.value = ''
    recognition = createRecognition()

    recognition.onstart = () => {
      isListening.value = true
      statusText.value = '请说话，说完后停顿一下。'
    }

    recognition.onresult = (event: any) => {
      let text = ''
      for (let index = 0; index < event.results.length; index++) {
        text += event.results[index][0].transcript
      }
      interimText.value = text
    }

    recognition.onerror = (event: any) => {
      if (!isCallActive.value) return
      if (event.error === 'no-speech' || event.error === 'audio-capture') {
        // 无声音或临时采集失败属于可恢复状态，短暂等待后继续聆听。
        statusText.value = '没有听到声音，正在重新聆听...'
        isListening.value = false
        recognition = null
        setTimeout(() => startCallRecognition(), 700)
        return
      }
      statusText.value = '语音识别失败：' + event.error
      isListening.value = false
      recognition = null
      setTimeout(() => startCallRecognition(), 900)
    }

    recognition.onend = () => {
      isListening.value = false
      recognition = null
      const raw = interimText.value.trim()
      interimText.value = ''

      if (!isCallActive.value) return
      if (!raw) {
        startCallRecognition()
        return
      }

      const hangup = /结束通话|挂断电话|停止通话|结束对话|不要说了/i
      if (hangup.test(raw)) {
        // 用户说出结束意图时停止通话，不再把这句话当作需求提交。
        stopCall()
        return
      }

      callTurns.push(raw)
      const prompt = callTurns.length === 1
        ? callTurns[0]
        : `【初始需求】\n${callTurns[0]}\n\n${callTurns.slice(1).map((turn, index) => `【补充说明${index + 1}】\n${turn}`).join('\n\n')}`

      onCallUtterance?.(prompt)
    }

    recognition.start()
  }

  function speak(text: string, onEnd?: () => void) {
    // 把 Markdown 报告清洗成适合语音播报的纯文本。
    if (!synthesis) return

    synthesis.cancel()
    const cleaned = text
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/#{1,6}\s*/g, '')
      .replace(/`+/g, '')
      .replace(/\|/g, ' ')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/\s+/g, ' ')
      .trim()

    const utterance = new SpeechSynthesisUtterance(cleaned)
    utterance.lang = 'zh-CN'
    utterance.rate = 1.03
    isSpeaking.value = true
    utterance.onend = () => {
      isSpeaking.value = false
      onEnd?.()
    }
    utterance.onerror = () => {
      isSpeaking.value = false
      onEnd?.()
    }
    synthesis.speak(utterance)
  }

  function stopSpeaking() {
    // 停止当前播报，通常用于新一轮分析或组件卸载。
    synthesis?.cancel()
    isSpeaking.value = false
  }

  onUnmounted(() => {
    // 组件卸载时释放浏览器语音识别和播报状态。
    stopCall()
    stopSpeaking()
  })

  return {
    isListening: readonly(isListening),
    isCallActive: readonly(isCallActive),
    isSpeaking: readonly(isSpeaking),
    statusText: readonly(statusText),
    interimText: readonly(interimText),
    startMic,
    stopMic,
    startCall,
    stopCall,
    speak,
    stopSpeaking,
  }
}
