<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from "vue";

import ActiveAlertList from "../components/ActiveAlertList.vue";
import AiopsCaseLibrary from "../components/AiopsCaseLibrary.vue";
import AiopsDiagnosticCard from "../components/AiopsDiagnosticCard.vue";
import AiopsEvidenceChain from "../components/AiopsEvidenceChain.vue";
import AiopsHistory from "../components/AiopsHistory.vue";
import AiopsReportPanel from "../components/AiopsReportPanel.vue";
import AiopsRunForm from "../components/AiopsRunForm.vue";
import AiopsTimeline from "../components/AiopsTimeline.vue";
import AppErrorState from "../components/AppErrorState.vue";
import AppLoadingState from "../components/AppLoadingState.vue";
import { useAiopsStore } from "../stores/aiops";

interface ReportDisplay {
  readonly id: string;
  readonly title: string;
  readonly content: string;
  readonly createdAt: string | null;
}

const aiops = useAiopsStore();

const isEffectivelyRunning = computed(
  () => aiops.isRunning || aiops.activeTask?.status === "running"
);

const hasReport = computed(() => {
  if ((aiops.evidenceChain?.reports ?? []).length > 0) return true;
  return aiops.liveEvents.some((event) => event.type === "report");
});

/** Prefer the persisted report; fall back to the streamed report before the chain reloads. */
const reportForPanel = computed<ReportDisplay | null>(() => {
  const persisted = aiops.evidenceChain?.reports ?? [];
  const last = persisted[persisted.length - 1];
  if (last !== undefined) {
    return {
      content: last.content,
      createdAt: last.createdAt,
      id: last.id,
      title: last.title
    };
  }
  for (let index = aiops.liveEvents.length - 1; index >= 0; index -= 1) {
    const event = aiops.liveEvents[index];
    if (event?.type !== "report") continue;
    return {
      content: event.report.content,
      createdAt: event.timestamp,
      id: event.report.id,
      title: event.report.title
    };
  }
  return null;
});

const taskFailed = computed(() => aiops.activeTask?.status === "failed");
const taskCanceled = computed(() => aiops.activeTask?.status === "cancelled");
const diagnosisMode = computed(() => aiops.activeDiagnosis?.mode ?? null);

onMounted(() => {
  void aiops.initialize().catch(() => undefined);
});

onBeforeUnmount(() => {
  aiops.reset();
});

function run(operation: () => Promise<unknown>): void {
  void operation().catch(() => undefined);
}

function selectDiagnostic(id: string): void {
  run(() => aiops.selectDiagnostic(id));
}

function startDiagnostic(query: string, alert: Record<string, unknown> | undefined): void {
  run(() => aiops.runDiagnostic(query, alert));
}

function diagnoseAlert(alert: Parameters<typeof aiops.diagnoseAlert>[0]): void {
  run(() => aiops.diagnoseAlert(alert));
}
</script>

<template>
  <section class="aiops-view" aria-label="智能诊断工作区">
    <header class="aiops-view__hero">
      <div class="aiops-view__pulse" aria-hidden="true"><span /><span /><span /></div>
      <div>
        <p>智能诊断</p>
        <h2>{{ aiops.activeTask?.query ?? "智能诊断工作区" }}</h2>
      </div>
    </header>

    <AppLoadingState v-if="aiops.isLoading && aiops.history.length === 0" label="正在加载诊断历史" />
    <AppErrorState
      v-else-if="aiops.errorMessage && aiops.history.length === 0"
      :can-retry="true"
      :message="aiops.errorMessage"
      @retry="run(aiops.initialize)"
    />
    <div v-else class="aiops-view__console">
      <aside class="aiops-view__left" aria-label="诊断输入与历史">
        <AiopsRunForm
          :disabled="aiops.isLoading"
          :is-running="aiops.isRunning"
          @cancel="run(aiops.cancelActive)"
          @run="startDiagnostic"
        />
        <ActiveAlertList
          :alerts="aiops.activeAlerts"
          :error-message="aiops.alertsErrorMessage"
          :is-loading="aiops.alertsLoading"
          @diagnose="diagnoseAlert"
          @refresh="run(aiops.refreshActiveAlerts)"
        />
        <AiopsHistory
          :active-diagnostic-id="aiops.activeDiagnosticId"
          :tasks="aiops.history"
          @select="selectDiagnostic"
        />
      </aside>

      <main class="aiops-view__center" aria-label="诊断过程与报告">
        <AiopsDiagnosticCard
          :task="aiops.activeTask"
          :is-running="isEffectivelyRunning"
          :live-events="aiops.liveEvents"
          :has-report="hasReport"
        />
        <AiopsTimeline :events="aiops.liveEvents" :is-running="isEffectivelyRunning" />
        <AiopsReportPanel
          :report="reportForPanel"
          :is-running="isEffectivelyRunning"
          :has-task="aiops.activeTask !== null"
          :task-failed="taskFailed"
          :task-canceled="taskCanceled"
          :diagnosis-mode="diagnosisMode"
        />
      </main>

      <aside class="aiops-view__right" aria-label="证据链与案例">
        <AiopsEvidenceChain :chain="aiops.evidenceChain" :diagnosis="aiops.activeDiagnosis" />
        <AiopsCaseLibrary :cases="aiops.diagnosticCases" @select="selectDiagnostic" />
      </aside>
    </div>
  </section>
</template>

<style scoped>
.aiops-view { background: var(--surface-raised); display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100%; min-height: 0; overflow: hidden; }
.aiops-view__hero { align-items: center; border-bottom: 1px solid var(--line); display: grid; gap: 0.9rem; grid-template-columns: auto minmax(0, 1fr); min-height: 4.6rem; padding: 0.85rem clamp(1rem, 2.6vw, 1.8rem); }
.aiops-view__hero p { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 760; margin: 0 0 0.22rem; }
.aiops-view__hero h2 { font-size: clamp(0.98rem, 1.2vw, 1.15rem); font-weight: 720; letter-spacing: 0; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.aiops-view__pulse { align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: 0.5rem; display: inline-flex; gap: 0.22rem; height: 2.45rem; justify-content: center; width: 2.45rem; }
.aiops-view__pulse span { animation: aiops-pulse 1.1s ease-in-out infinite; background: var(--accent); border-radius: 999px; display: block; height: 0.38rem; opacity: 0.35; width: 0.38rem; }
.aiops-view__pulse span:nth-child(2) { animation-delay: 120ms; }
.aiops-view__pulse span:nth-child(3) { animation-delay: 240ms; }
.aiops-view__console { display: grid; grid-template-columns: minmax(17rem, 0.66fr) minmax(0, 1.5fr) minmax(19rem, 0.9fr); min-height: 0; overflow: hidden; }
.aiops-view__left { border-right: 1px solid var(--line); min-height: 0; min-width: 0; overflow-y: auto; overscroll-behavior: contain; }
.aiops-view__center { border-right: 1px solid var(--line); display: grid; grid-template-rows: auto minmax(0, 1fr) minmax(8rem, 0.42fr); min-height: 0; min-width: 0; overflow: hidden; }
.aiops-view__right { display: flex; flex-direction: column; gap: 0; min-height: 0; min-width: 0; overflow-y: auto; overscroll-behavior: contain; }
@keyframes aiops-pulse { 0%, 100% { opacity: 0.28; transform: translateY(0); } 50% { opacity: 1; transform: translateY(-0.18rem); } }
@media (prefers-reduced-motion: reduce) { .aiops-view__pulse span { animation: none; } }
@media (max-width: 1180px) { .aiops-view__console { grid-template-columns: minmax(15rem, 0.72fr) minmax(0, 1.28fr); } .aiops-view__right { display: none; } }
@media (max-width: 1024px) {
  .aiops-view { height: auto; min-height: 0; }
  .aiops-view__console { grid-template-columns: minmax(0, 1fr); overflow-y: auto; }
  .aiops-view__left { border-bottom: 1px solid var(--line); border-right: 0; overflow: visible; }
  .aiops-view__center { border-bottom: 1px solid var(--line); border-right: 0; grid-template-rows: auto auto auto; }
  .aiops-view__right { display: flex; overflow: visible; }
}
</style>
