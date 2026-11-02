<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import ActiveAlertList from "../components/ActiveAlertList.vue";
import AiopsConclusionPanel from "../components/AiopsConclusionPanel.vue";
import AiopsDiagnosticCard from "../components/AiopsDiagnosticCard.vue";
import AiopsEvidenceDrawer from "../components/AiopsEvidenceDrawer.vue";
import AiopsEvidencePanel from "../components/AiopsEvidencePanel.vue";
import AiopsExecutionChain from "../components/AiopsExecutionChain.vue";
import AiopsHistory from "../components/AiopsHistory.vue";
import AiopsReportPanel from "../components/AiopsReportPanel.vue";
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
const selectedEvidenceId = ref<string | null>(null);

const isEffectivelyRunning = computed(
  () => aiops.isRunning || aiops.activeTask?.status === "running"
);

const hasSelection = computed(
  () => aiops.activeTask !== null || aiops.evidenceChain !== null
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

const selectedEvidence = computed(
  () =>
    (aiops.evidenceChain?.evidence ?? []).find((item) => item.id === selectedEvidenceId.value) ??
    null
);

const taskFailed = computed(() => aiops.activeTask?.status === "failed");
const taskCanceled = computed(() => aiops.activeTask?.status === "cancelled");

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

function diagnoseAlert(alert: Parameters<typeof aiops.diagnoseAlert>[0]): void {
  run(() => aiops.diagnoseAlert(alert));
}

function openEvidence(evidenceId: string): void {
  selectedEvidenceId.value = evidenceId;
}
</script>

<template>
  <section class="aiops-workbench" aria-label="AIOps 诊断台">
    <aside class="aiops-workbench__sources" aria-label="活跃告警与诊断历史">
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

    <div class="aiops-workbench__primary" aria-label="诊断结论与过程">
      <AppLoadingState v-if="aiops.isLoading && !hasSelection" label="正在加载诊断历史" />
      <AppErrorState
        v-else-if="aiops.errorMessage && !hasSelection"
        :can-retry="true"
        :message="aiops.errorMessage"
        @retry="run(aiops.initialize)"
      />
      <p v-else-if="!hasSelection" class="aiops-workbench__hint">
        在左侧选择一条活跃告警并点击「诊断」，或打开一条历史诊断，这里会显示结论与假设、现场证据、执行链和最终报告。
      </p>
      <template v-else>
        <AiopsDiagnosticCard
          :task="aiops.activeTask"
          :is-running="isEffectivelyRunning"
          :live-events="aiops.liveEvents"
          :has-report="hasReport"
        />
        <AiopsTimeline :events="aiops.liveEvents" :is-running="isEffectivelyRunning" />
        <AiopsConclusionPanel
          :diagnosis="aiops.activeDiagnosis"
          :task-status="aiops.activeTask?.status ?? null"
          @open-evidence="openEvidence"
        />
        <AiopsEvidencePanel
          :evidence="aiops.evidenceChain?.evidence ?? []"
          :unassessed-ids="aiops.activeDiagnosis?.unassessed_evidence_ids ?? []"
          @open-evidence="openEvidence"
        />
        <AiopsExecutionChain :chain="aiops.evidenceChain" @open-evidence="openEvidence" />
        <AiopsReportPanel
          :report="reportForPanel"
          :is-running="isEffectivelyRunning"
          :has-task="aiops.activeTask !== null"
          :task-failed="taskFailed"
          :task-canceled="taskCanceled"
          :diagnosis-mode="aiops.activeDiagnosis?.mode ?? null"
        />
      </template>
    </div>

    <AiopsEvidenceDrawer :evidence="selectedEvidence" @close="selectedEvidenceId = null" />
  </section>
</template>

<style scoped>
.aiops-workbench { background: var(--surface-raised); display: grid; grid-template-columns: minmax(16rem, 19rem) minmax(0, 1fr); height: 100%; min-height: 0; overflow: hidden; }
.aiops-workbench__sources { border-right: 1px solid var(--line); display: flex; flex-direction: column; min-height: 0; min-width: 0; overflow-y: auto; overscroll-behavior: contain; }
.aiops-workbench__primary { display: flex; flex-direction: column; min-height: 0; min-width: 0; overflow-y: auto; overscroll-behavior: contain; padding-bottom: 1.6rem; }
.aiops-workbench__hint { color: var(--text-tertiary); font-size: 0.82rem; line-height: 1.7; margin: 0; max-width: 40rem; padding: 1.8rem 1.3rem; }
@media (max-width: 1024px) {
  .aiops-workbench { grid-template-columns: minmax(0, 1fr); height: auto; min-height: 0; overflow: visible; }
  .aiops-workbench__sources { border-bottom: 1px solid var(--line); border-right: 0; overflow: visible; }
  .aiops-workbench__primary { overflow: visible; }
}
</style>
