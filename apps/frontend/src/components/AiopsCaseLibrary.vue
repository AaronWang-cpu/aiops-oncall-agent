<script setup lang="ts">
import { BookOpenCheck, ChevronDown, FolderOpen } from "lucide-vue-next";
import { ref } from "vue";

import type { AiopsDiagnosticCase } from "@agent-py/api-contracts";

defineEmits<{ select: [taskId: string]; "open-document": [documentId: string] }>();
defineProps<{ readonly cases: readonly AiopsDiagnosticCase[] }>();

const collapsed = ref(true);

function caseSummary(summary: string): string {
  const plainText = summary
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/[`*_>|-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return plainText.length > 180 ? `${plainText.slice(0, 177)}...` : plainText;
}
</script>

<template>
  <section class="aiops-case-library" aria-label="诊断案例库">
    <button class="aiops-case-library__collapse-header" type="button" :aria-expanded="!collapsed" @click="collapsed = !collapsed">
      <div class="aiops-case-library__collapse-title">
        <BookOpenCheck :size="16" aria-hidden="true" />
        <div>
          <p>案例库</p>
          <h3>已归档的诊断案例</h3>
        </div>
      </div>
      <ChevronDown :size="16" class="aiops-case-library__collapse-chevron" :class="{ 'aiops-case-library__collapse-chevron--open': !collapsed }" aria-hidden="true" />
    </button>
    <div v-show="!collapsed" class="aiops-case-library__body">
      <p v-if="cases.length === 0">已完成的诊断会自动保存到这里。</p>
      <ul v-else><li v-for="item in cases" :key="item.id"><button class="aiops-case-library__case" type="button" @click="$emit('select', item.taskId)"><strong>{{ item.alertName || item.service || '诊断案例' }}</strong><small>{{ item.service || '未提供服务名称' }} · {{ item.keywords.join(', ') || '未提取关键词' }}</small><span>{{ caseSummary(item.summary) }}</span></button><button class="aiops-case-library__document" type="button" title="打开生成的知识文档" :aria-label="`打开 ${item.alertName || item.service || '诊断案例'} 生成的知识文档`" @click="$emit('open-document', item.documentId)"><FolderOpen :size="16" aria-hidden="true" /></button></li></ul>
    </div>
  </section>
</template>

<style scoped>
.aiops-case-library { border-top: 1px solid var(--line); min-width: 0; }
.aiops-case-library__collapse-header { align-items: center; background: transparent; border: none; cursor: pointer; display: flex; justify-content: space-between; min-height: 3.75rem; padding: 0 1.2rem; transition: background 0.12s; width: 100%; }
.aiops-case-library__collapse-header:hover { background: var(--surface-hover); }
.aiops-case-library__collapse-title { align-items: center; display: flex; gap: 0.65rem; }
.aiops-case-library__collapse-title p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 700; margin: 0 0 0.2rem; text-align: left; }
h3 { font-size: 0.9rem; font-weight: 680; margin: 0; text-align: left; }
.aiops-case-library__collapse-chevron { color: var(--text-tertiary); flex: 0 0 auto; transition: transform 0.18s; }
.aiops-case-library__collapse-chevron--open { transform: rotate(180deg); }
.aiops-case-library__body { padding: 0.5rem 1.2rem 1.2rem; }
.aiops-case-library__body > p { color: var(--text-tertiary); font-size: 0.8rem; margin: 0.5rem 0 0; }
ul { display: grid; gap: 0.35rem; list-style: none; margin: 0.5rem 0 0; padding: 0; }
li { align-items: center; display: grid; gap: 0.45rem; grid-template-columns: minmax(0, 1fr) 2rem; }
.aiops-case-library__case { display: grid; gap: 0.2rem; min-width: 0; padding: 0.55rem 0; text-align: left; width: 100%; }
.aiops-case-library__case:hover strong { color: var(--accent-strong); text-decoration: underline; }
.aiops-case-library__document { align-items: center; border: 1px solid transparent; color: var(--text-secondary); display: inline-flex; height: 2rem; justify-content: center; width: 2rem; }
.aiops-case-library__document:hover { background: var(--surface-hover); border-color: var(--line); color: var(--accent-strong); }
strong { font-size: 0.8rem; font-weight: 680; }
small, span { color: var(--text-tertiary); font-size: 0.72rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
span { color: var(--text-secondary); }
@media (prefers-reduced-motion: reduce) { .aiops-case-library__collapse-chevron { transition: none; } }
</style>
