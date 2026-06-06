<script setup lang="ts">
// 候选架构卡片组件：展示前三个推荐架构、匹配度、推荐理由和风险提示。
export interface Candidate {
  // 后端返回的候选架构结构，rule_engine_note 用于解释规则引擎的加减分。
  name: string
  match_score: number
  match_reasons?: string[]
  risks?: string[]
  rule_engine_note?: string
}

defineProps<{ candidates: Candidate[] }>()

const rankLabels = ['首选', '备选', '补充']
const rankClasses = ['candidate-primary', 'candidate-secondary', 'candidate-tertiary']

function shortName(name: string) {
  // 去掉括号中的英文全称，让卡片标题在窄屏中更紧凑。
  return name.replace(/\s*\(.+?\)/g, '').trim()
}
</script>

<template>
  <div class="animate-in">
    <div class="mb-4 flex items-end justify-between gap-3">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200">Candidates</p>
        <h3 class="mt-1 text-lg font-bold text-white">候选架构对比</h3>
      </div>
      <span class="text-xs text-slate-500">按综合匹配度排序</span>
    </div>

    <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
      <article
        v-for="(candidate, index) in candidates.slice(0, 3)"
        :key="candidate.name"
        class="candidate-card glass"
        :class="rankClasses[index]"
      >
        <div class="mb-4 flex items-start justify-between gap-3">
          <div>
            <span class="rank-chip">{{ rankLabels[index] || `候选 ${index + 1}` }}</span>
            <h4 class="mt-3 text-base font-bold leading-6 text-white">{{ shortName(candidate.name) }}</h4>
          </div>
          <div class="score-bubble">{{ (candidate.match_score * 100).toFixed(0) }}</div>
        </div>

        <div class="mb-4">
          <div class="mb-1 flex justify-between text-xs text-slate-400">
            <span>匹配度</span>
            <span>{{ (candidate.match_score * 100).toFixed(0) }}%</span>
          </div>
          <div class="h-2 overflow-hidden rounded-full bg-slate-800/70">
            <div class="h-full rounded-full bg-current transition-all duration-700" :style="{ width: `${candidate.match_score * 100}%` }" />
          </div>
        </div>

        <p v-if="candidate.rule_engine_note" class="rule-engine-note mb-3 rounded border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-xs">
          {{ candidate.rule_engine_note }}
        </p>

        <div v-if="candidate.match_reasons?.length" class="space-y-2">
          <p class="text-xs font-semibold text-slate-400">推荐理由</p>
          <ul class="space-y-2">
            <li v-for="reason in candidate.match_reasons.slice(0, 2)" :key="reason" class="flex gap-2 text-xs leading-5 text-slate-300">
              <span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-300" />
              <span>{{ reason }}</span>
            </li>
          </ul>
        </div>

        <div v-if="candidate.risks?.length" class="mt-4 space-y-2">
          <p class="text-xs font-semibold text-slate-400">风险提示</p>
          <ul class="space-y-2">
            <li v-for="risk in candidate.risks.slice(0, 2)" :key="risk" class="flex gap-2 text-xs leading-5 text-rose-200">
              <span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-rose-300" />
              <span>{{ risk }}</span>
            </li>
          </ul>
        </div>
      </article>
    </div>
  </div>
</template>
