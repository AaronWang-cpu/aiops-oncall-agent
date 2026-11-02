<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import ActiveAlertList from "../components/ActiveAlertList.vue";
import AiopsCaseLibrary from "../components/AiopsCaseLibrary.vue";
import AiopsConclusionPanel from "../components/AiopsConclusionPanel.vue";
import AiopsDiagnosticCard from "../components/AiopsDiagnosticCard.vue";
import AiopsEvidenceDrawer from "../components/AiopsEvidenceDrawer.vue";
import AiopsEvidencePanel from "../components/AiopsEvidencePanel.vue";
import AiopsExecutionChain from "../components/AiopsExecutionChain.vue";
import AiopsHistory from "../components/AiopsHistory.vue";
import AiopsLedgerPanel from "../components/AiopsLedgerPanel.vue";
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

const TABS = [
  { id: "conclusion", label: "结论与假设" },
  { id: "evidence", label: "现场证据" },
  { id: "ledger", label: "调查账本" }
] as const;

const aiops = useAiopsStore();
const activeTab = ref<(typeof TABS)[number]["id"]>("conclusion");
const selectedEvidenceId = ref<string | null>(null);

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

function startDiagnostic(query: string, alert: Record<string, unknown> | undefined): void {
  run(() => aiops.runDiagnostic(query, alert));
}

function diagnoseAlert(alert: Parameters<typeof aiops.diagnoseAlert>[0]): void {
  run(() => aiops.diagnoseAlert(alert));
}

/** Evidence referenced from a hypothesis opens the evidence tab behind the drawer. */
function openEvidence(evidenceId: string): void {
  selectedEvidenceId.value = evidenceId;
  activeTab.value = "evidence";
}
</script>

<template>
  <section class="aiops-workbench" aria-label="智能诊断工作区">
    <header class="aiops-workbench__command">
      <AiopsRunForm
        :disabled="aiops.isLoading"
        :is-running="aiops.isRunning"
        @cancel="run(aiops.cancelActive)"
        @run="startDiagnostic"
      />
    </header>

    <AppLoadingState v-if="aiops.isLoading && aiops.history.length === 0" label="正在加载诊断历史" />
    <AppErrorState
      v-else-if="aiops.errorMessage && aiops.history.length === 0"
      :can-retry="true"
      :message="aiops.errorMessage"
      @retry="run(aiops.initialize)"
    />
    <div v-else class="aiops-workbench__grid">
      <aside class="aiops-workbench__sources" aria-label="告警、历史与案例">
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
        <AiopsCaseLibrary :cases="aiops.diagnosticCases" @select="selectDiagnostic" />
      </aside>

      <main class="aiops-workbench__primary" aria-label="诊断过程与报告">
        <AiopsDiagnosticCard
          :task="aiops.activeTask"
          :is-running="isEffectivelyRunning"
          :live-events="aiops.liveEvents"
          :has-report="hasReport"
        />
        <AiopsTimeline :events="aiops.liveEvents" :is-running="isEffectivelyRunning" />
        <AiopsExecutionChain
          :chain="aiops.evidenceChain"
          @open-evidence="openEvidence"
        />
        <AiopsReportPanel
          :report="reportForPanel"
          :is-running="isEffectivelyRunning"
          :has-task="aiops.activeTask !== null"
          :task-failed="taskFailed"
          :task-canceled="taskCanceled"
          :diagnosis-mode="aiops.activeDiagnosis?.mode ?? null"
        />
      </main>

      <aside class="aiops-workbench__inspector" aria-label="结论、证据与账本">
        <nav class="aiops-workbench__tabs" aria-label="检查器视图">
          <button
            v-for="tab in TABS"
            :key="tab.id"
            type="button"
            :class="{ 'aiops-workbench__tab--active': activeTab === tab.id }"
            :aria-current="activeTab === tab.id ? 'true' : undefined"
            @click="activeTab = tab.id"
          >
            {{ tab.label }}
          </button>
        </nav>
        <div class="aiops-workbench__panel">
          <AiopsConclusionPanel
            v-if="activeTab === 'conclusion'"
            :diagnosis="aiops.activeDiagnosis"
            :task-status="aiops.activeTask?.status ?? null"
            @open-evidence="openEvidence"
          />
          <AiopsEvidencePanel
            v-else-if="activeTab === 'evidence'"
            :evidence="aiops.evidenceChain?.evidence ?? []"
            :unassessed-ids="aiops.activeDiagnosis?.unassessed_evidence_ids ?? []"
            @open-evidence="openEvidence"
          />
          <AiopsLedgerPanel
            v-else
            :budget="aiops.activeDiagnosis?.budget ?? null"
            :query-records="aiops.activeDiagnosis?.query_records ?? []"
          />
        </div>
      </aside>
    </div>

    <AiopsEvidenceDrawer :evidence="selectedEvidence" @close="selectedEvidenceId = null" />
  </section>
</template>

<style scoped>
.aiops-workbench { background: var(--surface-raised); display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100%; min-height: 0; overflow: hidden; }
.aiops-workbench__command { border-bottom: 1px solid var(--line); min-width: 0; }
.aiops-workbench__grid { display: grid; grid-template-columns: minmax(15rem, 0.82fr) minmax(0, 1.6fr) minmax(18rem, 1fr); min-height: 0; overflow: hidden; }
.aiops-workbench__sources { border-right: 1px solid var(--line); display: flex; flex-direction: column; min-height: 0; min-width: 0; overflow-y: auto; overscroll-behavior: contain; }
.aiops-workbench__primary { border-right: 1px solid var(--line); display: grid; grid-template-rows: auto minmax(0, 1fr) auto minmax(8rem, 0.42fr); min-height: 0; min-width: 0; overflow: hidden; }
.aiops-workbench__inspector { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 0; min-width: 0; }
.aiops-workbench__tabs { border-bottom: 1px solid var(--line); display: flex; gap: 0.25rem; padding: 0.5rem 0.7rem; }
.aiops-workbench__tabs button { background: transparent; border: 1px solid transparent; color: var(--text-secondary); cursor: pointer; font-family: inherit; font-size: 0.74rem; font-weight: 630; min-height: 2rem; padding: 0 0.55rem; }
.aiops-workbench__tabs button:hover { background: var(--surface-hover); }
.aiops-workbench__tabs .aiops-workbench__tab--active { background: var(--surface-hover); border-color: var(--line-strong); color: var(--text-primary); font-weight: 700; }
.aiops-workbench__panel { min-height: 0; min-width: 0; overflow-y: auto; overscroll-behavior: contain; padding: 1rem 1.1rem 1.4rem; }
@media (max-width: 1280px) {
  .aiops-workbench__grid { grid-template-columns: minmax(14rem, 0.8fr) minmax(0, 1.4fr); }
  .aiops-workbench__inspector { border-top: 1px solid var(--line); grid-column: 1 / -1; max-height: 24rem; }
}
@media (max-width: 1024px) {
  .aiops-workbench { height: auto; min-height: 0; }
  .aiops-workbench__grid { grid-template-columns: minmax(0, 1fr); overflow-y: auto; }
  .aiops-workbench__sources { border-bottom: 1px solid var(--line); border-right: 0; overflow: visible; }
  .aiops-workbench__primary { border-bottom: 1px solid var(--line); border-right: 0; grid-template-rows: auto auto auto auto; }
  .aiops-workbench__inspector { max-height: none; overflow: visible; }
  .aiops-workbench__panel { overflow: visible; }
}
</style>
