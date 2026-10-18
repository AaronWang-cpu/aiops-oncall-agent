<script setup lang="ts">
import { CheckCircle2, ChevronRight, ClipboardList, FileClock, FileWarning, Loader2, XCircle } from "lucide-vue-next";
import { computed } from "vue";
import { useRouter } from "vue-router";

import type { AiopsDiagnosticSummary, SseEvent } from "@agent-py/api-contracts";

import AsyncStatusBadge from "./AsyncStatusBadge.vue";

const props = defineProps<{
  readonly task: AiopsDiagnosticSummary | null;
  readonly isRunning: boolean;
  readonly liveEvents: readonly SseEvent[];
  readonly hasReport: boolean;
}>();

const router = useRouter();

const latestEventText = computed<string | null>(() => {
  for (let i = props.liveEvents.length - 1; i >= 0; i -= 1) {
    const event = props.liveEvents[i];
    if (event === undefined) continue;
    if (event.type === "complete") return "诊断完成";
    if (event.type === "report") return `报告已生成：${event.report.title}`;
    if (event.type === "tool.call") return `工具调用 · ${event.toolCall.name}`;
    if (event.type === "reference.source") return `知识检索 · ${event.reference.title}`;
    if (event.type === "task.status") return event.task.message ?? event.task.status;
    if (event.type === "error") return `错误：${event.error.message}`;
  }
  return null;
});

const progressPercent = computed<number>(() => {
  if (!props.isRunning && props.task?.status === "succeeded") return 100;
  if (!props.isRunning) return 0;
  for (let i = props.liveEvents.length - 1; i >= 0; i -= 1) {
    const event = props.liveEvents[i];
    if (event?.type === "complete") return 100;
    if (event?.type === "report") return 90;
    if (event?.type === "task.status" && event.task.progress !== undefined) {
      return event.task.progress;
    }
    if (event?.type === "reference.source") return 65;
    if (event?.type === "tool.call") return 50;
  }
  return 10;
});

function openReport(): void {
  if (props.task === null) return;
  void router.push({ name: "aiops-report", params: { id: props.task.id } });
}
</script>

<template>
  <section class="diag-card" aria-label="当前诊断任务">
    <div v-if="task === null" class="diag-card__empty">
      <ClipboardList :size="28" aria-hidden="true" />
      <div>
        <strong>等待诊断任务</strong>
        <p>从左侧告警列表发起诊断，或在输入框输入问题后执行。</p>
      </div>
    </div>

    <template v-else>
      <header class="diag-card__header">
        <div class="diag-card__query-area">
          <p class="diag-card__label">诊断任务</p>
          <strong class="diag-card__query">{{ task.query }}</strong>
        </div>
        <AsyncStatusBadge :status="isRunning ? 'running' : task.status" />
      </header>

      <div class="diag-card__progress-area">
        <div class="diag-card__progress-bar-wrap">
          <div
            class="diag-card__progress-bar"
            :class="{ 'diag-card__progress-bar--pulse': isRunning }"
            :style="{ width: `${progressPercent}%` }"
            role="progressbar"
            :aria-valuenow="progressPercent"
            aria-valuemin="0"
            aria-valuemax="100"
          />
        </div>
        <p class="diag-card__event-text">
          <template v-if="isRunning">
            <Loader2 :size="13" class="diag-card__spinner" aria-hidden="true" />
            {{ latestEventText ?? "初始化中…" }}
          </template>
          <template v-else-if="task.status === 'succeeded'">
            <CheckCircle2 :size="13" aria-hidden="true" class="diag-card__icon-ok" />
            诊断完成
          </template>
          <template v-else-if="task.status === 'failed'">
            <XCircle :size="13" aria-hidden="true" class="diag-card__icon-fail" />
            诊断失败
          </template>
          <template v-else-if="task.status === 'accepted'">
            <FileClock :size="13" aria-hidden="true" />
            等待执行
          </template>
          <template v-else>
            <FileClock :size="13" aria-hidden="true" />
            {{ latestEventText ?? "就绪" }}
          </template>
        </p>
      </div>

      <div v-if="hasReport" class="diag-card__report-action">
        <button class="diag-card__view-report" type="button" @click="openReport">
          <ClipboardList :size="15" aria-hidden="true" />
          查看完整诊断报告
          <ChevronRight :size="15" aria-hidden="true" />
        </button>
      </div>
      <div v-else-if="task.status === 'failed'" class="diag-card__report-action diag-card__report-action--failed">
        <FileWarning :size="15" aria-hidden="true" />
        <span>诊断在报告生成前失败，请检查下方证据链后重新执行。</span>
      </div>
    </template>
  </section>
</template>

<style scoped>
.diag-card { background: var(--surface); border-bottom: 1px solid var(--line); min-width: 0; }
.diag-card__empty { align-items: center; color: var(--text-tertiary); display: flex; gap: 1rem; min-height: 8rem; padding: 1.5rem; }
.diag-card__empty svg { flex: 0 0 auto; }
.diag-card__empty strong { color: var(--text-secondary); display: block; font-size: 0.88rem; margin-bottom: 0.3rem; }
.diag-card__empty p { font-size: 0.78rem; line-height: 1.55; margin: 0; }
.diag-card__header { align-items: flex-start; display: flex; gap: 0.75rem; justify-content: space-between; padding: 1rem 1.15rem 0.85rem; }
.diag-card__query-area { flex: 1; min-width: 0; }
.diag-card__label { color: var(--text-tertiary); font-size: 0.68rem; font-weight: 700; margin: 0 0 0.3rem; }
.diag-card__query { display: block; font-size: 0.88rem; font-weight: 650; line-height: 1.45; overflow-wrap: anywhere; }
.diag-card__progress-area { padding: 0 1.15rem 1rem; }
.diag-card__progress-bar-wrap { background: var(--line); height: 4px; overflow: hidden; }
.diag-card__progress-bar { background: var(--accent); height: 100%; transition: width 0.5s ease; }
.diag-card__progress-bar--pulse { animation: diag-bar-pulse 1.5s ease-in-out infinite; }
.diag-card__event-text { align-items: center; color: var(--text-secondary); display: flex; font-size: 0.75rem; gap: 0.4rem; margin: 0.55rem 0 0; min-height: 1.4rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.diag-card__spinner { animation: diag-spin 1s linear infinite; flex: 0 0 auto; }
.diag-card__icon-ok { color: var(--status-success-text); flex: 0 0 auto; }
.diag-card__icon-fail { color: var(--status-danger-text); flex: 0 0 auto; }
.diag-card__report-action { border-top: 1px solid var(--line); padding: 0.75rem 1.15rem; }
.diag-card__view-report { align-items: center; background: var(--accent); border: none; color: #fff; cursor: pointer; display: inline-flex; font-size: 0.82rem; font-weight: 700; gap: 0.45rem; justify-content: center; min-height: 2.4rem; padding: 0.4rem 1rem; transition: filter 0.12s; width: 100%; }
.diag-card__view-report:hover { filter: brightness(1.08); }
.diag-card__report-action--failed { align-items: center; color: var(--status-danger-text); display: flex; font-size: 0.78rem; gap: 0.5rem; }
@keyframes diag-bar-pulse { 0%, 100% { opacity: 0.7; } 50% { opacity: 1; } }
@keyframes diag-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .diag-card__progress-bar { transition: none; } .diag-card__progress-bar--pulse, .diag-card__spinner { animation: none; } }
</style>
