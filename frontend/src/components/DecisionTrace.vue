<script setup lang="ts">
// 决策溯源组件：把首选架构的推荐理由、备选风险和相似案例放在同一条证据链中展示。
import type { Candidate } from './CandidateCards.vue'

interface CaseMatch {
  // Agent Runtime 从历史案例库中召回的相似需求摘要。
  prompt: string
  matched_terms?: string[]
  recommendations?: string[]
  score?: number
  count?: number
}

defineProps<{ candidates: Candidate[]; caseMatches?: CaseMatch[] }>()
</script>

<template>
  <section v-if="candidates.length" class="glass p-5 animate-in">
    <div class="mb-4">
      <p class="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200">Decision Trace</p>
      <h3 class="mt-1 text-lg font-bold text-white">决策溯源</h3>
    </div>

    <div class="space-y-3">
      <div
        v-for="(reason, index) in candidates[0]?.match_reasons || []"
        :key="reason"
        class="trace-row"
      >
        <span class="trace-index">{{ index + 1 }}</span>
        <span class="text-sm leading-6 text-slate-300">{{ reason }}</span>
      </div>

      <div v-if="candidates.length > 1 && candidates[1]?.risks?.length" class="trace-row trace-risk">
        <span class="trace-index">!</span>
        <span class="trace-risk-copy text-sm leading-6">
          备选方案 <b>{{ candidates[1].name }}</b> 的主要风险：
          {{ candidates[1].risks.slice(0, 2).join('；') }}
        </span>
      </div>

      <div v-if="caseMatches?.length" class="trace-row">
        <span class="trace-index">K</span>
        <span class="text-sm leading-6 text-slate-300">
          相似案例参考：
          {{ caseMatches[0].prompt }}
          <b v-if="caseMatches[0].recommendations?.length"> → {{ caseMatches[0].recommendations.join(' / ') }}</b>
        </span>
      </div>
    </div>
  </section>
</template>
