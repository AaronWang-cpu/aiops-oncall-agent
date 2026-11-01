import { computed, ref, shallowRef } from "vue";
import { defineStore } from "pinia";

import type {
  ActiveAlert,
  AiopsDiagnosticCase,
  AiopsDiagnosticEvidenceChain,
  AiopsDiagnosticSummary,
  CreateAiopsDiagnosticRequest,
  DiagnosisResult,
  SseEvent
} from "@agent-py/api-contracts";
import { isDiagnosisResult } from "@agent-py/api-contracts";

import { ApiClientError } from "../api/apiClient";
import { createAiopsClient, type AiopsClient } from "../aiops/aiopsClient";
import { useFeedbackStore } from "./feedback";
import { toUserFacingError } from "../ui/userFacingError";

let clientFactory: () => AiopsClient = createAiopsClient;

/** The subscription is retried once when it ends without a terminal `complete` event. */
const DIAGNOSTIC_STREAM_ATTEMPTS = 2;

export function setAiopsClientFactoryForTests(factory: (() => AiopsClient) | null): void {
  clientFactory = factory ?? createAiopsClient;
}

function isTerminalStatus(status: string): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

export const useAiopsStore = defineStore("aiops", () => {
  const client = clientFactory();
  const history = shallowRef<readonly AiopsDiagnosticSummary[]>([]);
  const activeAlerts = ref<readonly ActiveAlert[]>([]);
  const diagnosticCases = ref<readonly AiopsDiagnosticCase[]>([]);
  const alertsErrorMessage = ref<string | null>(null);
  const alertsLoading = ref(false);
  const activeDiagnosticId = ref<string | null>(null);
  const activeTask = shallowRef<AiopsDiagnosticSummary | null>(null);
  const evidenceChain = shallowRef<AiopsDiagnosticEvidenceChain | null>(null);
  const liveEvents = shallowRef<readonly SseEvent[]>([]);
  const lastEventId = ref<string | null>(null);
  const isLoading = ref(false);
  const isRunning = ref(false);
  const errorMessage = ref<string | null>(null);
  const savedCaseDocumentId = ref<string | null>(null);

  /**
   * The new investigation projection. Live `task.status` events take precedence while the
   * run is streaming; the persisted chain wins once it has been reloaded.
   */
  const activeDiagnosis = computed<DiagnosisResult | null>(() => {
    const persisted = evidenceChain.value?.task.resultPayload.diagnosis;
    if (persisted !== undefined && isDiagnosisResult(persisted)) return persisted;
    for (let index = liveEvents.value.length - 1; index >= 0; index -= 1) {
      const event = liveEvents.value[index];
      if (event?.type !== "task.status") continue;
      const streamed = event.task.diagnosis;
      if (streamed !== undefined && isDiagnosisResult(streamed)) return streamed;
    }
    return null;
  });

  function reportError(error: unknown): void {
    const message = toUserFacingError(error);
    errorMessage.value = message;
    useFeedbackStore().showError(message);
  }

  function upsertHistory(task: AiopsDiagnosticSummary): void {
    history.value = [task, ...history.value.filter((item) => item.id !== task.id)]
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  }

  function applyChain(chain: AiopsDiagnosticEvidenceChain): void {
    evidenceChain.value = chain;
    activeDiagnosticId.value = chain.task.id;
    activeTask.value = chain.task;
    upsertHistory(chain.task);
  }

  async function reloadHistory(): Promise<void> {
    history.value = (await client.listDiagnostics()).items;
  }

  async function reloadActiveAlerts(): Promise<void> {
    alertsLoading.value = true;
    alertsErrorMessage.value = null;
    try {
      activeAlerts.value = (await client.listActiveAlerts()).items;
    } catch (error) {
      activeAlerts.value = [];
      alertsErrorMessage.value = "暂时无法获取活跃告警。";
    } finally {
      alertsLoading.value = false;
    }
  }

  async function reloadDiagnosticCases(): Promise<void> {
    diagnosticCases.value = (await client.listDiagnosticCases()).items;
  }

  async function loadEvidenceChain(diagnosticId: string): Promise<void> {
    applyChain(await client.getEvidenceChain(diagnosticId));
  }

  /**
   * Consume one subscription pass. Already-seen event IDs are dropped so a replay after
   * reconnecting never duplicates history, and `error` events do not abort the stream.
   * Also records the newest event ID as the resume cursor.
   */
  async function streamOnce(diagnosticId: string): Promise<boolean> {
    const seen = new Set(liveEvents.value.map((event) => event.id));
    let sawComplete = false;
    const cursor = lastEventId.value;
    for await (const event of client.streamDiagnostic(
      diagnosticId,
      cursor === null ? undefined : { lastEventId: cursor }
    )) {
      lastEventId.value = event.id;
      if (seen.has(event.id)) continue;
      seen.add(event.id);
      liveEvents.value = [...liveEvents.value, event];
      if (event.type === "error") {
        reportError(new ApiClientError(event.error));
      }
      if (event.type === "task.status" && activeTask.value?.id === event.task.id) {
        const status = event.task.status;
        if (status !== "queued") {
          activeTask.value = { ...activeTask.value, status };
        }
      }
      if (event.type === "complete") sawComplete = true;
    }
    return sawComplete;
  }

  /**
   * Stream the diagnosis and, when the connection ends without `complete`, reload the
   * persisted state. A still-running task is retried once from the saved cursor; an
   * incomplete stream is never treated as success.
   */
  async function streamWithRecovery(diagnosticId: string): Promise<void> {
    for (let attempt = 0; attempt < DIAGNOSTIC_STREAM_ATTEMPTS; attempt += 1) {
      let sawComplete = false;
      try {
        sawComplete = await streamOnce(diagnosticId);
      } catch (error) {
        reportError(error);
      }
      if (sawComplete) return;
      try {
        const chain = await client.getEvidenceChain(diagnosticId);
        applyChain(chain);
        if (isTerminalStatus(chain.task.status)) return;
      } catch (error) {
        reportError(error);
        return;
      }
    }
  }

  async function refreshCollections(): Promise<void> {
    await Promise.all([
      reloadHistory().catch((error: unknown) => reportError(error)),
      reloadDiagnosticCases().catch((error: unknown) => reportError(error))
    ]);
  }

  /** Reload the persisted chain after a run, dropping a stale success if the reload fails. */
  async function reloadAfterRun(diagnosticId: string): Promise<void> {
    try {
      await loadEvidenceChain(diagnosticId);
    } catch (error) {
      evidenceChain.value = null;
      reportError(error);
    }
    await refreshCollections();
  }

  async function reconcileAfterFailure(): Promise<void> {
    const diagnosticId = activeDiagnosticId.value;
    if (diagnosticId === null) return;
    try {
      await loadEvidenceChain(diagnosticId);
    } catch (error) {
      evidenceChain.value = null;
      reportError(error);
    }
    await refreshCollections();
  }

  function reset(): void {
    history.value = [];
    activeAlerts.value = [];
    diagnosticCases.value = [];
    alertsErrorMessage.value = null;
    alertsLoading.value = false;
    activeDiagnosticId.value = null;
    activeTask.value = null;
    evidenceChain.value = null;
    liveEvents.value = [];
    lastEventId.value = null;
    isLoading.value = false;
    isRunning.value = false;
    errorMessage.value = null;
    savedCaseDocumentId.value = null;
  }

  async function runDiagnostic(
    query: string,
    alert?: Record<string, unknown>,
  ): Promise<void> {
    const request: CreateAiopsDiagnosticRequest = {
      query,
      ...(alert === undefined ? {} : { alert })
    };
    isRunning.value = true;
    errorMessage.value = null;
    liveEvents.value = [];
    lastEventId.value = null;
    evidenceChain.value = null;
    try {
      const created = await client.createDiagnostic(request);
      activeDiagnosticId.value = created.id;
      activeTask.value = created;
      upsertHistory(created);
      await streamWithRecovery(created.id);
      await reloadAfterRun(created.id);
    } catch (error) {
      reportError(error);
      await reconcileAfterFailure();
    } finally {
      isRunning.value = false;
    }
  }

  async function diagnoseAlert(alert: ActiveAlert): Promise<void> {
    const query = `排查活跃告警：${alert.alertName}，服务：${alert.service}，级别：${alert.severity}。${alert.summary}`;
    await runDiagnostic(query, {
      ...alert.context,
      alertSource: alert.source,
      alertName: alert.alertName,
      service: alert.service,
      severity: alert.severity,
      status: alert.status,
      startsAt: alert.startsAt
    });
  }

  return {
    activeDiagnosticId,
    activeAlerts,
    activeDiagnosis,
    activeTask,
    diagnosticCases,
    alertsErrorMessage,
    alertsLoading,
    errorMessage,
    evidenceChain,
    history,
    isLoading,
    isRunning,
    lastEventId,
    liveEvents,
    savedCaseDocumentId,
    initialize: async (): Promise<void> => {
      isLoading.value = true;
      errorMessage.value = null;
      try {
        await reloadHistory();
      } catch (error) {
        reset();
        reportError(error);
        throw error;
      } finally {
        isLoading.value = false;
      }
      await Promise.all([reloadActiveAlerts(), reloadDiagnosticCases().catch(() => undefined)]);
    },
    selectDiagnostic: async (diagnosticId: string): Promise<void> => {
      isLoading.value = true;
      errorMessage.value = null;
      liveEvents.value = [];
      lastEventId.value = null;
      try {
        await loadEvidenceChain(diagnosticId);
      } catch (error) {
        evidenceChain.value = null;
        activeTask.value = null;
        reportError(error);
        throw error;
      } finally {
        isLoading.value = false;
      }
    },
    diagnoseAlert,
    refreshActiveAlerts: reloadActiveAlerts,
    refreshDiagnosticCases: reloadDiagnosticCases,
    runDiagnostic,
    cancelActive: async (): Promise<void> => {
      const jobId = activeTask.value?.backgroundJob?.id;
      if (jobId === undefined || client.cancelBackgroundJob === undefined) return;
      try {
        await client.cancelBackgroundJob(jobId);
        isRunning.value = false;
        await Promise.all([reloadHistory(), loadEvidenceChain(activeTask.value!.id)]);
      } catch (error) {
        reportError(error);
        throw error;
      }
    },
    saveActiveCase: async (): Promise<void> => {
      if (activeDiagnosticId.value === null) return;
      try {
        const saved = await client.saveDiagnosticCase(activeDiagnosticId.value);
        savedCaseDocumentId.value = saved.document.id;
      } catch (error) {
        reportError(error);
        throw error;
      }
    },
    reset
  };
});
