<script setup lang="ts">
// 推荐组合方案组件：用前两名候选架构生成可答辩说明的组合建议。
import type { Candidate } from './CandidateCards.vue'

defineProps<{ candidates: Candidate[] }>()

function shortName(name: string) {
  // 保留架构中文短名，减少组合文案中的视觉噪音。
  return name.replace(/\s*\(.+?\)/g, '').trim()
}
</script>

<template>
  <section v-if="candidates.length >= 2" class="combo-panel animate-in">
    <div>
      <p class="text-xs font-semibold uppercase tracking-[0.16em] text-indigo-200">Combination</p>
      <h3 class="mt-1 text-lg font-bold text-white">推荐组合方案</h3>
      <p class="combo-copy mt-3 leading-7">
        以 <b class="combo-primary-arch">{{ shortName(candidates[0].name) }}</b> 作为核心架构，
        搭配 <b class="combo-secondary-arch">{{ shortName(candidates[1].name) }}</b> 处理专项能力。
        这种组合能兼顾主流程稳定性与局部扩展弹性，适合在答辩中说明架构演进路径。
      </p>
    </div>
  </section>
</template>

