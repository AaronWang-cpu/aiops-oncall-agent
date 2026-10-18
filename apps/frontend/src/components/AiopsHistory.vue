<script setup lang="ts">
import { Activity } from "lucide-vue-next";
import { computed, ref } from "vue";

import type { AiopsDiagnosticSummary } from "@agent-py/api-contracts";

import AsyncStatusBadge from "./AsyncStatusBadge.vue";

defineEmits<{ select: [diagnosticId: string] }>();
const props = defineProps<{ readonly activeDiagnosticId: string | null; readonly tasks: readonly AiopsDiagnosticSummary[] }>();

const COLLAPSED_COUNT = 3;
const expanded = ref(false);

const visibleTasks = computed(() =>
  expanded.value ? props.tasks : props.tasks.slice(0, COLLAPSED_COUNT)
);
const hiddenCount = computed(() => Math.max(0, props.tasks.length - COLLAPSED_COUNT));

function taskDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
</script>

<template>
  <aside class="aiops-history" aria-label="诊断历史">
    <header><p>诊断历史</p><Activity :size="16" aria-hidden="true" /></header>
    <p v-if="tasks.length === 0" class="aiops-history__empty">还没有诊断记录。</p>
    <template v-else>
      <ul>
        <li v-for="task in visibleTasks" :key="task.id"><button type="button" :aria-current="task.id === activeDiagnosticId ? 'page' : undefined" :class="{ 'aiops-history__task--active': task.id === activeDiagnosticId }" @click="$emit('select', task.id)"><span><strong>{{ task.query }}</strong><small>{{ taskDate(task.updatedAt) }}</small></span><AsyncStatusBadge :status="task.status" compact /></button></li>
      </ul>
      <button v-if="!expanded && hiddenCount > 0" class="aiops-history__toggle" type="button" @click="expanded = true">
        查看全部（还有 {{ hiddenCount }} 条）
      </button>
      <button v-else-if="expanded && hiddenCount > 0" class="aiops-history__toggle" type="button" @click="expanded = false">
        收起
      </button>
    </template>
  </aside>
</template>

<style scoped>
.aiops-history { border-top: 1px solid var(--line); min-width: 0; }
header { align-items: center; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; min-height: 3.75rem; padding: 0 0.85rem; }
header p { color: var(--text-secondary); font-size: 0.75rem; font-weight: 700; margin: 0; }
.aiops-history__empty { color: var(--text-tertiary); font-size: 0.82rem; margin: 1rem; }
ul { list-style: none; margin: 0; padding: 0.4rem; }
li button { align-items: center; color: var(--text-secondary); display: flex; gap: 0.5rem; justify-content: space-between; min-height: 3.75rem; padding: 0.5rem; text-align: left; width: 100%; }
li button:hover { background: var(--surface-hover); color: var(--text-primary); }
li button > span { display: grid; flex: 1; min-width: 0; }
strong { font-size: 0.8rem; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
small { color: var(--text-tertiary); font-size: 0.7rem; margin-top: 0.25rem; }
.aiops-history__task--active { background: var(--accent-soft); color: var(--accent-strong); }
.aiops-history__toggle { border-top: 1px solid var(--line); color: var(--accent-strong, var(--text-secondary)); cursor: pointer; font-size: 0.75rem; font-weight: 650; min-height: 2.8rem; padding: 0 0.85rem; text-align: left; width: 100%; }
.aiops-history__toggle:hover { background: var(--surface-hover); }
@media (max-width: 860px) { .aiops-history { border-bottom: 1px solid var(--line); max-height: 14rem; overflow-y: auto; } }
</style>
