<script setup lang="ts">
import { ListChecks } from "lucide-vue-next";
import { computed } from "vue";

import type { DiagnosisBudget, DiagnosisQueryRecord } from "@agent-py/api-contracts";

const props = defineProps<{
  readonly budget: DiagnosisBudget | null;
  readonly queryRecords: readonly DiagnosisQueryRecord[];
}>();

interface Usage {
  readonly label: string;
  readonly used: number;
  readonly limit: number;
}

const usages = computed<readonly Usage[]>(() => {
  const budget = props.budget;
  if (budget === null) return [];
  return [
    { label: "查询轮次", used: budget.rounds_used, limit: budget.max_rounds },
    { label: "工具调用", used: budget.tool_calls_used, limit: budget.max_tool_calls },
    { label: "内部往返", used: budget.internal_steps_used, limit: budget.max_internal_steps }
  ];
});

const succeededCount = computed(
  () => props.queryRecords.filter((record) => record.status === "succeeded").length
);

function percent(usage: Usage): number {
  if (usage.limit <= 0) return 0;
  return Math.min(100, Math.round((usage.used / usage.limit) * 100));
}

function formatTime(value: string | undefined): string {
  if (value === undefined || value.length === 0) return "未提供";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleTimeString("zh-CN");
}

function argumentText(record: DiagnosisQueryRecord): string {
  return JSON.stringify(record.arguments);
}
</script>

<template>
  <section class="aiops-ledger" aria-label="调查预算与查询账本">
    <header>
      <h4><ListChecks :size="15" aria-hidden="true" />调查账本</h4>
      <span v-if="budget">{{ queryRecords.length }} 次查询 · 成功 {{ succeededCount }}</span>
    </header>

    <p v-if="budget === null" class="aiops-ledger__empty">诊断开始后这里显示额度消耗与每次查询的明细。</p>
    <template v-else>
      <ul class="aiops-ledger__usage">
        <li v-for="usage in usages" :key="usage.label">
          <span>{{ usage.label }}</span>
          <span class="aiops-ledger__bar"><i :style="{ width: `${percent(usage)}%` }" /></span>
          <strong>{{ usage.used }} / {{ usage.limit }}</strong>
        </li>
      </ul>
      <p v-if="budget.reserved_tool_calls > 0 || budget.unknown_tool_calls > 0" class="aiops-ledger__note">
        预留调用 {{ budget.reserved_tool_calls }} 次，未知工具调用 {{ budget.unknown_tool_calls }} 次（已计入额度）。
      </p>
      <p class="aiops-ledger__note">
        探索截止 {{ formatTime(budget.exploration_deadline) }} · 分析截止 {{ formatTime(budget.analysis_deadline) }} · 总截止 {{ formatTime(budget.deadline) }}
      </p>
    </template>

    <h4 class="aiops-ledger__section-title">查询账本</h4>
    <p v-if="queryRecords.length === 0" class="aiops-ledger__empty">本次调查还没有执行查询。</p>
    <ol v-else class="aiops-ledger__queries">
      <li v-for="(record, index) in queryRecords" :key="record.query_id">
        <div class="aiops-ledger__query-head">
          <span class="aiops-ledger__index">{{ index + 1 }}</span>
          <strong>{{ record.question }}</strong>
          <span class="aiops-ledger__status" :class="`aiops-ledger__status--${record.status}`">
            {{ record.status === "succeeded" ? "成功" : "失败" }}
          </span>
        </div>
        <p class="aiops-ledger__meta">{{ record.tool_name }}<template v-if="record.hypothesis_ids.length"> · 关联 {{ record.hypothesis_ids.join("、") }}</template></p>
        <p v-if="record.status_reason" class="aiops-ledger__reason">{{ record.status_reason }}</p>
        <details>
          <summary>查询参数</summary>
          <p class="aiops-ledger__arguments">{{ argumentText(record) }}</p>
        </details>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.aiops-ledger { display: grid; gap: 0.65rem; min-width: 0; }
header { align-items: center; display: flex; justify-content: space-between; }
h4 { align-items: center; display: flex; font-size: 0.82rem; gap: 0.35rem; margin: 0; }
header > span { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 650; }
.aiops-ledger__section-title { border-top: 1px solid var(--line); color: var(--text-secondary); padding-top: 0.7rem; }
.aiops-ledger__empty { color: var(--text-tertiary); font-size: 0.78rem; line-height: 1.5; margin: 0; }
.aiops-ledger__usage { display: grid; gap: 0.4rem; list-style: none; margin: 0; padding: 0; }
.aiops-ledger__usage li { align-items: center; display: grid; font-size: 0.74rem; gap: 0.5rem; grid-template-columns: 4.6rem minmax(0, 1fr) 4.4rem; }
.aiops-ledger__usage li > strong { font-size: 0.74rem; text-align: right; }
.aiops-ledger__bar { background: var(--line); display: block; height: 0.32rem; min-width: 0; }
.aiops-ledger__bar i { background: var(--accent); display: block; height: 100%; }
.aiops-ledger__note { color: var(--text-tertiary); font-size: 0.72rem; line-height: 1.5; margin: 0; overflow-wrap: anywhere; }
.aiops-ledger__queries { display: grid; gap: 0.6rem; list-style: none; margin: 0; padding: 0; }
.aiops-ledger__queries > li { border-left: 2px solid var(--line-strong); display: grid; gap: 0.25rem; padding-left: 0.55rem; }
.aiops-ledger__query-head { align-items: start; display: grid; gap: 0.4rem; grid-template-columns: auto minmax(0, 1fr) auto; }
.aiops-ledger__index { background: var(--surface-hover); border: 1px solid var(--line); font-size: 0.68rem; font-weight: 700; min-width: 1.25rem; text-align: center; }
.aiops-ledger__query-head strong { font-size: 0.78rem; line-height: 1.45; overflow-wrap: anywhere; }
.aiops-ledger__status { border: 1px solid var(--line-strong); font-size: 0.68rem; font-weight: 700; padding: 0.05rem 0.3rem; }
.aiops-ledger__status--succeeded { border-color: var(--status-success-text); color: var(--status-success-text); }
.aiops-ledger__status--failed { border-color: var(--status-danger-text); color: var(--status-danger-text); }
.aiops-ledger__meta { color: var(--text-tertiary); font-size: 0.72rem; margin: 0; overflow-wrap: anywhere; }
.aiops-ledger__reason { color: var(--status-danger-text); font-size: 0.72rem; line-height: 1.5; margin: 0; overflow-wrap: anywhere; }
details { min-width: 0; }
summary { color: var(--text-tertiary); cursor: pointer; font-size: 0.72rem; }
.aiops-ledger__arguments { background: var(--surface-hover); color: var(--text-secondary); font-size: 0.7rem; line-height: 1.5; margin: 0.35rem 0 0; overflow-wrap: anywhere; padding: 0.4rem 0.5rem; white-space: pre-wrap; }
</style>
