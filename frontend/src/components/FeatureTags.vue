<script setup lang="ts">
// 特征标签组件：展示需求解析 Agent 提取出的关键词和关键非功能需求。
defineProps<{ features: string[] }>()
</script>

<template>
  <section class="glass p-5 animate-in">
    <div class="mb-4 flex items-end justify-between gap-3">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-200">Feature Extraction</p>
        <h3 class="mt-1 text-lg font-bold text-white">语义理解与特征提取</h3>
      </div>
      <span class="rounded border border-cyan-300/20 bg-cyan-300/10 px-2 py-1 text-xs text-cyan-100">
        {{ features.length }} 项
      </span>
    </div>

    <div class="flex flex-wrap gap-2">
      <span
        v-for="feature in features"
        :key="feature"
        class="feature-chip"
      >
        {{ feature }}
      </span>
    </div>
  </section>
</template>
