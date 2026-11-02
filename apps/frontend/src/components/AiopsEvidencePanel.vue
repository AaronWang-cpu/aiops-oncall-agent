<script setup lang="ts">
import { Database } from "lucide-vue-next";
import { computed } from "vue";

import type { AiopsDiagnosticEvidence, AiopsEvidenceKind } from "@agent-py/api-contracts";

const props = defineProps<{
  readonly evidence: readonly AiopsDiagnosticEvidence[];
  readonly unassessedIds: readonly string[];
}>();

const emit = defineEmits<{ "open-evidence": [evidenceId: string] }>();

const KIND_LABELS: Record<string, string> = {
  alert: "告警",
  change: "变更",
  knowledge_reference: "知识",
  log: "日志",
  metric: "指标",
  ticket: "工单"
};

const KIND_ORDER: readonly string[] = ["log", "metric", "change", "alert", "ticket", "knowledge_reference"];

const groups = computed(() =>
  KIND_ORDER.map((kind) => ({
    kind,
    label: KIND_LABELS[kind] ?? kind,
    items: props.evidence.filter((item) => item.kind === kind)
  })).filter((group) => group.items.length > 0)
);

function formatTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN");
}

function isUnassessed(item: AiopsDiagnosticEvidence): boolean {
  return props.unassessedIds.includes(item.id);
}

/** Older rows stored a JSON blob as the summary; show a label instead of dumping it. */
function readableSummary(item: AiopsDiagnosticEvidence): string {
  const summary = item.summary.trim();
  if (summary.startsWith("{") || summary.startsWith("[")) {
    return `${item.source || item.id} 的结构化返回`;
  }
  return summary || item.source || item.id;
}

function kindLabel(kind: AiopsEvidenceKind): string {
  return KIND_LABELS[kind] ?? kind;
}
</script>

<template>
  <section class="aiops-evidence" aria-label="现场证据">
    <header>
      <h4><Database :size="15" aria-hidden="true" />现场证据</h4>
      <span>{{ evidence.length }} 条</span>
    </header>

    <p v-if="evidence.length === 0" class="aiops-evidence__empty">
      本次调查还没有采集到证据。工具返回的完整结果会保存在这里。
    </p>
    <template v-else>
      <div v-for="group in groups" :key="group.kind" class="aiops-evidence__group">
        <p class="aiops-evidence__group-title">{{ group.label }} · {{ group.items.length }} 条</p>
        <ul>
          <li v-for="item in group.items" :key="item.id">
            <button type="button" :aria-label="`查看证据 ${item.id}`" @click="emit('open-evidence', item.id)">
              <span class="aiops-evidence__kind" :class="`aiops-evidence__kind--${item.kind}`">{{ kindLabel(item.kind) }}</span>
              <span class="aiops-evidence__body">
                <strong>{{ readableSummary(item) }}</strong>
                <small>{{ item.source || "未知来源" }} · {{ formatTime(item.createdAt) }}</small>
              </span>
              <span v-if="isUnassessed(item)" class="aiops-evidence__pending">未纳入结论</span>
            </button>
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>

<style scoped>
.aiops-evidence { display: grid; gap: 0.65rem; min-width: 0; }
header { align-items: center; display: flex; justify-content: space-between; }
h4 { align-items: center; display: flex; font-size: 0.82rem; gap: 0.35rem; margin: 0; }
header > span { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 650; }
.aiops-evidence__empty { color: var(--text-tertiary); font-size: 0.78rem; line-height: 1.5; margin: 0; }
.aiops-evidence__group { display: grid; gap: 0.35rem; }
.aiops-evidence__group-title { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 700; margin: 0; }
ul { display: grid; gap: 0.3rem; list-style: none; margin: 0; padding: 0; }
li { min-width: 0; }
button { align-items: center; background: transparent; border: 1px solid var(--line); cursor: pointer; display: grid; gap: 0.5rem; grid-template-columns: auto minmax(0, 1fr) auto; padding: 0.5rem 0.55rem; text-align: left; width: 100%; }
button:hover { background: var(--surface-hover); border-color: var(--line-strong); }
.aiops-evidence__kind { border: 1px solid var(--line-strong); color: var(--text-secondary); font-size: 0.66rem; font-weight: 700; padding: 0.05rem 0.3rem; }
.aiops-evidence__kind--metric { border-color: var(--accent-strong); color: var(--accent-strong); }
.aiops-evidence__kind--change { border-color: var(--status-warning-text, #8a5a00); color: var(--status-warning-text, #8a5a00); }
.aiops-evidence__body { display: grid; gap: 0.15rem; min-width: 0; }
.aiops-evidence__body strong { font-size: 0.78rem; line-height: 1.45; overflow-wrap: anywhere; }
.aiops-evidence__body small { color: var(--text-tertiary); font-size: 0.7rem; overflow-wrap: anywhere; }
.aiops-evidence__pending { color: var(--status-warning-text, #8a5a00); font-size: 0.68rem; font-weight: 650; }
</style>
