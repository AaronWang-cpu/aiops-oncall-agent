<script setup lang="ts">
import { X } from "lucide-vue-next";
import { computed } from "vue";

import type { AiopsDiagnosticEvidence } from "@agent-py/api-contracts";

const props = defineProps<{ readonly evidence: AiopsDiagnosticEvidence | null }>();
const emit = defineEmits<{ close: [] }>();

/** Large tool results are capped for reading; the operator is told what was cut. */
const ROW_LIMIT = 10;

const KIND_LABELS: Record<string, string> = {
  alert: "告警",
  change: "变更",
  knowledge_reference: "知识",
  log: "日志",
  metric: "指标",
  ticket: "工单"
};

interface Series {
  readonly metricName: string;
  readonly unit: string;
  readonly aggregation: string;
  readonly points: readonly { readonly timestamp: string; readonly value: number | null }[];
  readonly total: number;
}

const kindLabel = computed(() =>
  props.evidence === null ? "" : KIND_LABELS[props.evidence.kind] ?? props.evidence.kind
);

/** Older rows stored a JSON blob as the summary; the payload below carries the content. */
const title = computed(() => {
  const summary = (props.evidence?.summary ?? "").trim();
  if (summary.length === 0 || summary.startsWith("{") || summary.startsWith("[")) {
    return "证据原始内容";
  }
  return summary;
});

const data = computed<Record<string, unknown>>(() => {
  const payload = props.evidence?.payload ?? {};
  const inner = payload["data"];
  if (typeof inner === "object" && inner !== null && !Array.isArray(inner)) {
    return inner as Record<string, unknown>;
  }
  return payload;
});

const series = computed<readonly Series[]>(() => {
  const raw = data.value["series"];
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const row = record(item);
    const points = Array.isArray(row["points"]) ? row["points"] : [];
    return {
      aggregation: text(row["aggregation"]) || "avg",
      metricName: text(row["metric_name"]) || "未命名指标",
      points: points.map((point) => {
        const entry = record(point);
        const value = entry["value"];
        return {
          timestamp: text(entry["timestamp"]),
          value: typeof value === "number" ? value : null
        };
      }),
      total: typeof row["sampleCount"] === "number" ? row["sampleCount"] : points.length,
      unit: text(row["unit"])
    };
  });
});

const records = computed<readonly Record<string, unknown>[]>(() => {
  const raw = data.value["records"];
  return Array.isArray(raw) ? raw.map(record) : [];
});

const scalars = computed<readonly (readonly [string, string])[]>(() =>
  Object.entries(data.value)
    .filter(([key, value]) => key !== "series" && key !== "records" && isScalar(value))
    .map(([key, value]) => [key, String(value)])
);

const rawJson = computed(() => JSON.stringify(props.evidence?.payload ?? {}, null, 2));

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function isScalar(value: unknown): value is string | number | boolean {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN");
}

function recordLines(row: Record<string, unknown>): readonly string[] {
  return Object.entries(row)
    .filter(([, value]) => isScalar(value))
    .map(([key, value]) => `${key}：${String(value)}`);
}

function valueText(value: unknown): string {
  if (isScalar(value)) return String(value);
  if (Array.isArray(value)) return `${value.length} 项`;
  return "结构化内容";
}
</script>

<template>
  <div v-if="evidence" class="aiops-drawer" role="dialog" aria-label="证据详情">
    <button class="aiops-drawer__backdrop" type="button" aria-label="关闭证据详情" @click="emit('close')" />
    <aside class="aiops-drawer__panel">
      <header>
        <div>
          <p><span class="aiops-drawer__kind">{{ kindLabel }}</span>{{ evidence.source || evidence.id }}</p>
          <h3>{{ title }}</h3>
        </div>
        <button type="button" aria-label="关闭证据详情" title="关闭" @click="emit('close')"><X :size="17" aria-hidden="true" /></button>
      </header>

      <div class="aiops-drawer__body">
        <p class="aiops-drawer__meta">{{ formatTime(evidence.createdAt) }} · {{ evidence.id }}</p>

        <template v-if="series.length">
          <section v-for="(item, index) in series" :key="index">
            <h4>{{ item.metricName }}<span v-if="item.unit">（{{ item.unit }}）</span> · {{ item.aggregation }} · {{ item.total }} 点</h4>
            <table>
              <thead><tr><th>时间</th><th>数值</th></tr></thead>
              <tbody>
                <tr v-for="(point, pointIndex) in item.points.slice(0, ROW_LIMIT)" :key="pointIndex">
                  <td>{{ point.timestamp }}</td>
                  <td>{{ point.value === null ? "不可用" : point.value }}</td>
                </tr>
              </tbody>
            </table>
            <p v-if="item.total > item.points.slice(0, ROW_LIMIT).length" class="aiops-drawer__cut">
              共 {{ item.total }} 点，此处显示前 {{ item.points.slice(0, ROW_LIMIT).length }} 点，其余未显示。
            </p>
          </section>
        </template>

        <template v-else-if="records.length">
          <section v-for="(row, index) in records.slice(0, ROW_LIMIT)" :key="index">
            <p v-for="line in recordLines(row)" :key="line" class="aiops-drawer__record">{{ line }}</p>
          </section>
          <p v-if="records.length > ROW_LIMIT" class="aiops-drawer__cut">
            共 {{ records.length }} 条记录，此处显示前 {{ ROW_LIMIT }} 条，其余未显示。
          </p>
        </template>

        <template v-else-if="scalars.length">
          <section>
            <p v-for="([key, value]) in scalars" :key="key" class="aiops-drawer__record">{{ key }}：{{ value }}</p>
          </section>
        </template>

        <section v-else>
          <p v-for="([key, value]) in Object.entries(data)" :key="key" class="aiops-drawer__record">{{ key }}：{{ valueText(value) }}</p>
        </section>

        <details class="aiops-drawer__raw">
          <summary>原始返回内容</summary>
          <pre>{{ rawJson }}</pre>
        </details>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.aiops-drawer { inset: 0; position: fixed; z-index: 30; }
.aiops-drawer__backdrop { background: rgb(20 21 24 / 28%); border: none; cursor: pointer; inset: 0; position: absolute; width: 100%; }
.aiops-drawer__panel { background: var(--surface-raised); border-left: 1px solid var(--line); display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100%; max-width: min(34rem, 92vw); position: absolute; right: 0; top: 0; width: 100%; }
header { align-items: start; border-bottom: 1px solid var(--line); display: flex; gap: 0.75rem; justify-content: space-between; padding: 1rem 1.1rem; }
header p { align-items: center; color: var(--text-tertiary); display: flex; font-size: 0.72rem; gap: 0.4rem; margin: 0 0 0.3rem; overflow-wrap: anywhere; }
header h3 { font-size: 0.92rem; font-weight: 690; margin: 0; overflow-wrap: anywhere; }
header button { align-items: center; background: transparent; border: 1px solid var(--line); color: var(--text-secondary); cursor: pointer; display: inline-flex; height: 1.9rem; justify-content: center; width: 1.9rem; }
header button:hover { background: var(--surface-hover); }
.aiops-drawer__kind { border: 1px solid var(--line-strong); color: var(--text-secondary); font-size: 0.66rem; font-weight: 700; padding: 0.05rem 0.3rem; }
.aiops-drawer__body { display: grid; gap: 0.8rem; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 1rem 1.1rem 1.6rem; }
.aiops-drawer__meta { color: var(--text-tertiary); font-size: 0.72rem; margin: 0; overflow-wrap: anywhere; }
section { display: grid; gap: 0.3rem; min-width: 0; }
h4 { font-size: 0.78rem; font-weight: 680; margin: 0; overflow-wrap: anywhere; }
table { border-collapse: collapse; font-size: 0.74rem; width: 100%; }
th, td { border-bottom: 1px solid var(--line); padding: 0.25rem 0.35rem; text-align: left; }
th { color: var(--text-tertiary); font-weight: 650; }
td { overflow-wrap: anywhere; }
.aiops-drawer__record { font-size: 0.76rem; line-height: 1.5; margin: 0; overflow-wrap: anywhere; }
.aiops-drawer__cut { color: var(--text-tertiary); font-size: 0.72rem; margin: 0; }
.aiops-drawer__raw summary { color: var(--text-tertiary); cursor: pointer; font-size: 0.72rem; }
pre { background: var(--surface-hover); font-size: 0.7rem; line-height: 1.5; margin: 0.4rem 0 0; max-height: 18rem; overflow: auto; padding: 0.5rem; white-space: pre-wrap; }
</style>
