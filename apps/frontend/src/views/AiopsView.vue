<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from "vue";
import { useRouter } from "vue-router";

import ActiveAlertList from "../components/ActiveAlertList.vue";
import AiopsCaseLibrary from "../components/AiopsCaseLibrary.vue";
import AiopsDiagnosticCard from "../components/AiopsDiagnosticCard.vue";
import AiopsEvidenceChain from "../components/AiopsEvidenceChain.vue";
import AiopsHistory from "../components/AiopsHistory.vue";
import AiopsRunForm from "../components/AiopsRunForm.vue";
import AppErrorState from "../components/AppErrorState.vue";
import AppLoadingState from "../components/AppLoadingState.vue";
import { useAiopsStore } from "../stores/aiops";

const aiops = useAiopsStore();
const router = useRouter();

const hasReport = computed(() => {
  const reports = aiops.evidenceChain?.reports ?? [];
  if (reports.length > 0) return true;
  return aiops.liveEvents.some((e) => e.type === "report");
});

const isEffectivelyRunning = computed(
  () => aiops.isRunning || aiops.activeTask?.status === "running"
);

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

function openCaseDocument(documentId: string): void {
  void router.push({ name: "knowledge", query: { documentId } });
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

      <main class="aiops-view__right" aria-label="诊断详情">
        <AiopsDiagnosticCard
          :task="aiops.activeTask"
          :is-running="isEffectivelyRunning"
          :live-events="aiops.liveEvents"
          :has-report="hasReport"
        />
        <AiopsEvidenceChain :chain="aiops.evidenceChain" />
        <AiopsCaseLibrary
          :cases="aiops.diagnosticCases"
          @open-document="openCaseDocument"
          @select="selectDiagnostic"
        />
      </main>
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
.aiops-view__console { display: grid; grid-template-columns: minmax(18rem, 0.72fr) minmax(0, 1fr); min-height: 0; overflow: hidden; }
.aiops-view__left { border-right: 1px solid var(--line); min-height: 0; min-width: 0; overflow-y: auto; overscroll-behavior: contain; }
.aiops-view__right { display: flex; flex-direction: column; gap: 0; min-height: 0; min-width: 0; overflow-y: auto; overscroll-behavior: contain; }
@keyframes aiops-pulse { 0%, 100% { opacity: 0.28; transform: translateY(0); } 50% { opacity: 1; transform: translateY(-0.18rem); } }
@media (prefers-reduced-motion: reduce) { .aiops-view__pulse span { animation: none; } }
@media (max-width: 1024px) { .aiops-view__console { grid-template-columns: minmax(16rem, 0.8fr) minmax(0, 1fr); } }
@media (max-width: 860px) { .aiops-view { min-height: auto; } .aiops-view__hero { grid-template-columns: auto minmax(0, 1fr); } .aiops-view__console { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr); } .aiops-view__left { border-right: 0; border-bottom: 1px solid var(--line); max-height: 50vh; } }
</style>
