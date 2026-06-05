<script setup lang="ts">
/**
 * 后端返回的候选架构展示模型。
 *
 * match_score 已在后端完成综合排序计算，前端只负责按分值展示进度和排序结果。
 * rule_engine_note 用于暴露规则引擎的二次校验结论，帮助用户理解候选方案不是单纯依赖 LLM 生成。
 */
export interface Candidate {
  name: string
  match_score: number
  match_reasons?: string[]
  risks?: string[]
  rule_engine_note?: string
}

defineProps<{ candidates: Candidate[] }>()

// 前端固定突出前三个候选方案，符合报告中 Top 3 架构推荐的验收和对比场景。
const rankLabels = ['首选', '备选', '补充']
const rankClasses = ['candidate-primary', 'candidate-secondary', 'candidate-tertiary']

/**
 * 提取适合卡片标题展示的架构名称。
 *
 * Args:
 *   name: 后端可能带有英文缩写或补充说明的完整候选架构名称。
 * Returns:
 *   去除括号说明后的短名称，避免卡片标题在三列布局中被辅助信息挤占。
 */
function shortName(name: string) {
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
      <!-- 这里只展示前三名，避免低匹配候选稀释用户对推荐结论和风险提示的关注。 -->
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

        <!-- 规则引擎备注优先展示，用来解释加分、降权或兜底推荐等影响排序的业务判断。 -->
        <p v-if="candidate.rule_engine_note" class="rule-engine-note mb-3 rounded border border-amber-300/20 bg-amber-300/10 px-3 py-2 text-xs">
          {{ candidate.rule_engine_note }}
        </p>

        <div v-if="candidate.match_reasons?.length" class="space-y-2">
          <p class="text-xs font-semibold text-slate-400">推荐理由</p>
          <ul class="space-y-2">
            <!-- 卡片内只保留最关键的两条理由，完整解释由报告正文承接，保证三列对比时信息密度可控。 -->
            <li v-for="reason in candidate.match_reasons.slice(0, 2)" :key="reason" class="flex gap-2 text-xs leading-5 text-slate-300">
              <span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-300" />
              <span>{{ reason }}</span>
            </li>
          </ul>
        </div>

        <div v-if="candidate.risks?.length" class="mt-4 space-y-2">
          <p class="text-xs font-semibold text-slate-400">风险提示</p>
          <ul class="space-y-2">
            <!-- 风险同样做数量约束，优先呈现会影响选型决策的主要边界条件。 -->
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
