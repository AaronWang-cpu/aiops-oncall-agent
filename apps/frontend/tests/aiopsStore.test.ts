import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it } from "vitest";

import type {
  AiopsDiagnosticEvidenceChain,
  AiopsDiagnosticSummary,
  DiagnosisResult,
  ErrorSseEvent,
  SseEvent
} from "@agent-py/api-contracts";

import { ApiClientError } from "../src/api/apiClient";
import type { AiopsClient } from "../src/aiops/aiopsClient";
import { setAiopsClientFactoryForTests, useAiopsStore } from "../src/stores/aiops";

const task = (overrides: Partial<AiopsDiagnosticSummary> = {}): AiopsDiagnosticSummary => ({
  id: "diagnostic_1",
  ownerUserId: "user_1",
  status: "accepted",
  query: "Investigate elevated API latency",
  inputPayload: { query: "Investigate elevated API latency", alert: {} },
  resultPayload: {},
  createdAt: "2026-07-10T00:00:00.000Z",
  updatedAt: "2026-07-10T00:00:00.000Z",
  completedAt: null,
  reports: [],
  ...overrides
});

const chain = (overrides: Partial<AiopsDiagnosticEvidenceChain> = {}): AiopsDiagnosticEvidenceChain => ({
  task: task({
    completedAt: "2026-07-10T00:00:04.000Z",
    reports: [{
      id: "report_1",
      title: "AIOps evidence-based diagnostic report",
      content: "## Finding\n\nThe API was slow.",
      payload: {},
      evidenceIds: ["evidence_1"],
      createdAt: "2026-07-10T00:00:04.000Z"
    }],
    status: "succeeded"
  }),
  steps: [{
    id: "step_1",
    taskId: "diagnostic_1",
    sequence: 1,
    phase: "planner",
    status: "completed",
    payload: {},
    createdAt: "2026-07-10T00:00:01.000Z"
  }],
  toolCalls: [{
    id: "tool_1",
    ownerUserId: "user_1",
    sessionId: null,
    diagnosticTaskId: "diagnostic_1",
    toolName: "SearchLog",
    status: "completed",
    arguments: { query: "latency" },
    resultSummary: "Found latency spike.",
    errorMessage: null,
    startedAt: "2026-07-10T00:00:01.000Z",
    completedAt: "2026-07-10T00:00:02.000Z",
    durationMs: 50,
    createdAt: "2026-07-10T00:00:01.000Z"
  }],
  evidence: [{
    id: "evidence_1",
    taskId: "diagnostic_1",
    stepId: "step_1",
    toolCallId: "tool_1",
    kind: "log",
    source: "SearchLog",
    summary: "Latency spike at 10:00.",
    payload: { matched: 1 },
    createdAt: "2026-07-10T00:00:02.000Z"
  }],
  reports: [{
    id: "report_1",
    title: "AIOps evidence-based diagnostic report",
    content: "## Finding\n\nThe API was slow.",
    payload: {},
    evidenceIds: ["evidence_1"],
    createdAt: "2026-07-10T00:00:04.000Z"
  }],
  reportEvidenceLinks: [{
    id: "link_1",
    taskId: "diagnostic_1",
    reportId: "report_1",
    evidenceId: "evidence_1",
    createdAt: "2026-07-10T00:00:04.000Z"
  }],
  checkpoints: [],
  ...overrides
});

const diagnosticResult = (): DiagnosisResult => ({
  engine: "hypothesis-driven-v1",
  mode: "mock",
  hypotheses: [],
  hypothesis_relations: [],
  incident_conclusion: {
    conclusion_status: "unconfirmed",
    root_cause: null,
    stop_reason: null,
    explanation: "仍在调查。"
  },
  query_records: [],
  tool_evidence: [],
  unmet_requests: [],
  unassessed_evidence_ids: [],
  assessment_is_current: true,
  budget: {
    rounds_used: 1,
    tool_calls_used: 1,
    reserved_tool_calls: 0,
    unknown_tool_calls: 0,
    internal_steps_used: 0,
    max_rounds: 5,
    max_tool_calls: 20,
    max_internal_steps: 2,
    started_at: "2026-07-10T00:00:00Z",
    exploration_deadline: "2026-07-10T00:06:30Z",
    analysis_deadline: "2026-07-10T00:07:30Z",
    deadline: "2026-07-10T00:08:00Z"
  }
});

const events: readonly SseEvent[] = [
  {
    id: "event_1",
    type: "task.status",
    channel: "aiops",
    timestamp: "2026-07-10T00:00:01.000Z",
    task: { id: "diagnostic_1", status: "running", progress: 15, message: "Planner: retrieving SOP evidence." }
  },
  {
    id: "event_2",
    type: "tool.call",
    channel: "aiops",
    timestamp: "2026-07-10T00:00:02.000Z",
    toolCall: { id: "tool_1", name: "SearchLog", status: "completed", output: { matches: 1 } }
  },
  {
    id: "event_3",
    type: "reference.source",
    channel: "aiops",
    timestamp: "2026-07-10T00:00:02.000Z",
    reference: { id: "reference_1", title: "Latency runbook", sourceType: "knowledge-base", score: 0.92 }
  },
  {
    id: "event_4",
    type: "report",
    channel: "aiops",
    timestamp: "2026-07-10T00:00:04.000Z",
    report: { id: "report_1", title: "AIOps evidence-based diagnostic report", content: "## Finding\n\nThe API was slow.", format: "markdown" }
  },
  { id: "event_5", type: "complete", channel: "aiops", timestamp: "2026-07-10T00:00:04.000Z" }
];

const streamError: ErrorSseEvent = {
  id: "event_error",
  type: "error",
  channel: "aiops",
  timestamp: "2026-07-10T00:00:02.000Z",
  error: { code: "SYSTEM_UNAVAILABLE", category: "system", httpStatus: 503, message: "CLS unavailable." }
};

afterEach(() => setAiopsClientFactoryForTests(null));

describe("AIOps store", () => {
  it("creates a diagnostic, projects shared SSE events, and reconciles its persisted evidence chain", async () => {
    setAiopsClientFactoryForTests(() => fakeFactory());
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.initialize();
    await store.runDiagnostic("Investigate elevated API latency", { severity: "high" });

    expect(store.activeDiagnosticId).toBe("diagnostic_1");
    expect(store.liveEvents.map((event) => event.type)).toEqual(events.map((event) => event.type));
    expect(store.evidenceChain?.reports[0]?.evidenceIds).toEqual(["evidence_1"]);
    expect(store.isRunning).toBe(false);
  });

  it("loads the selected persisted evidence chain from the server-backed history", async () => {
    setAiopsClientFactoryForTests(() => fakeFactory());
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.initialize();
    await store.selectDiagnostic("diagnostic_1");

    expect(store.history[0]).toMatchObject({ id: "diagnostic_1", status: "succeeded" });
    expect(store.evidenceChain?.evidence[0]?.summary).toContain("Latency spike");
  });

  it("surfaces a streamed diagnostic error without inventing a completed report", async () => {
    setAiopsClientFactoryForTests(() => fakeFactory({ streamed: [[streamError]] }));
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.runDiagnostic("Inspect logs");

    expect(store.errorMessage).toBe("服务暂时不可用，请稍后重试。");
    expect(store.liveEvents).toEqual([streamError]);
  });

  it("resumes an incomplete stream from the saved cursor and drops replayed events", async () => {
    const calls: StreamCall[] = [];
    const replay: readonly SseEvent[] = [
      events[0]!,
      events[3]!,
      { id: "event_6", type: "task.status", channel: "aiops", timestamp: "2026-07-10T00:00:04.000Z", task: { id: "diagnostic_1", status: "succeeded" } },
      { id: "event_7", type: "complete", channel: "aiops", timestamp: "2026-07-10T00:00:04.000Z" }
    ];
    setAiopsClientFactoryForTests(() => fakeFactory({
      calls,
      chains: [chain({ task: task({ status: "running" }) }), chain()],
      streamed: [[events[0]!, streamError], replay]
    }));
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.runDiagnostic("Inspect logs");

    expect(calls).toEqual([
      { diagnosticId: "diagnostic_1" },
      { diagnosticId: "diagnostic_1", lastEventId: "event_error" }
    ]);
    expect(store.liveEvents.map((event) => event.id)).toEqual([
      "event_1", "event_error", "event_4", "event_6", "event_7"
    ]);
    expect(store.lastEventId).toBe("event_7");
    expect(store.activeTask?.status).toBe("succeeded");
    expect(store.isRunning).toBe(false);
  });

  it("keeps consuming after a streamed error and reflects the final failed state", async () => {
    const failed: readonly SseEvent[] = [
      streamError,
      events[3]!,
      { id: "event_8", type: "task.status", channel: "aiops", timestamp: "2026-07-10T00:00:04.000Z", task: { id: "diagnostic_1", status: "failed" } },
      { id: "event_9", type: "complete", channel: "aiops", timestamp: "2026-07-10T00:00:05.000Z" }
    ];
    setAiopsClientFactoryForTests(() => fakeFactory({
      chains: [chain({ task: task({ status: "failed", completedAt: "2026-07-10T00:00:05.000Z" }) })],
      streamed: [failed]
    }));
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.runDiagnostic("Inspect logs");

    expect(store.liveEvents.map((event) => event.type)).toEqual([
      "error", "report", "task.status", "complete"
    ]);
    expect(store.activeTask?.status).toBe("failed");
    expect(store.evidenceChain?.task.status).toBe("failed");
    expect(store.isRunning).toBe(false);
  });

  it("does not treat an EOF without complete as success", async () => {
    setAiopsClientFactoryForTests(() => fakeFactory({
      chains: [chain({ task: task({ status: "failed", completedAt: "2026-07-10T00:00:05.000Z" }) })],
      streamed: [[events[0]!]]
    }));
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.runDiagnostic("Inspect logs");

    expect(store.liveEvents.some((event) => event.type === "complete")).toBe(false);
    expect(store.activeTask?.status).toBe("failed");
    expect(store.evidenceChain?.task.status).toBe("failed");
    expect(store.isRunning).toBe(false);
  });

  it("does not present a stale success when the persisted reload fails", async () => {
    setAiopsClientFactoryForTests(() => fakeFactory({ failChain: true }));
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.runDiagnostic("Inspect logs");

    expect(store.evidenceChain).toBeNull();
    expect(store.activeTask?.status).not.toBe("succeeded");
    expect(store.errorMessage).not.toBeNull();
    expect(store.isRunning).toBe(false);
  });

  it("projects the typed diagnosis result and leaves legacy payloads without one", async () => {
    setAiopsClientFactoryForTests(() => fakeFactory({
      chains: [chain({ task: task({ resultPayload: { diagnosis: diagnosticResult() }, status: "succeeded" }) })]
    }));
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.selectDiagnostic("diagnostic_1");
    expect(store.activeDiagnosis?.engine).toBe("hypothesis-driven-v1");

    setAiopsClientFactoryForTests(() => fakeFactory());
    setActivePinia(createPinia());
    const legacy = useAiopsStore();
    await legacy.selectDiagnostic("diagnostic_1");
    expect(legacy.activeDiagnosis).toBeNull();
  });
});

interface StreamCall {
  readonly diagnosticId: string;
  readonly lastEventId?: string;
}

interface FakeOptions {
  readonly streamed?: readonly (readonly SseEvent[])[];
  readonly chains?: readonly AiopsDiagnosticEvidenceChain[];
  readonly failChain?: boolean;
  readonly calls?: StreamCall[];
}

function fakeFactory(options: FakeOptions = {}): AiopsClient {
  let streamIndex = 0;
  let chainIndex = 0;
  return {
    createDiagnostic: async () => task(),
    getEvidenceChain: async () => {
      if (options.failChain === true) {
        throw new ApiClientError({
          code: "SYSTEM_INTERNAL_ERROR",
          category: "system",
          httpStatus: 500,
          message: "无法加载证据链。"
        }, 500);
      }
      const chains = options.chains ?? [chain()];
      const item = chains[Math.min(chainIndex, chains.length - 1)];
      chainIndex += 1;
      if (item === undefined) throw new Error("missing chain fixture");
      return item;
    },
    listActiveAlerts: async () => ({ items: [] }),
    listDiagnosticCases: async () => ({ items: [] }),
    listDiagnostics: async () => ({ items: [task()] }),
    saveDiagnosticCase: async () => ({
      document: {
        id: "doc_case_1", knowledgeBaseId: "kb_1", ownerUserId: "user_1", filename: "case.md", sizeBytes: 1, mimeType: "text/markdown", contentHash: "sha256:case", status: "ready", indexStatus: "pending", uploadedAt: "2026-07-10T00:00:00Z", updatedAt: "2026-07-10T00:00:00Z"
      },
      task: { id: "index_case_1", ownerUserId: "user_1", knowledgeBaseId: "kb_1", documentId: "doc_case_1", status: "pending", failureReason: null, retryOfTaskId: null, createdAt: "2026-07-10T00:00:00Z", updatedAt: "2026-07-10T00:00:00Z", startedAt: null, completedAt: null },
      scheduled: true as const
    }),
    streamDiagnostic: async function* (
      diagnosticId: string,
      streamOptions?: { readonly lastEventId?: string }
    ): AsyncIterable<SseEvent> {
      options.calls?.push({
        diagnosticId,
        ...(streamOptions?.lastEventId === undefined ? {} : { lastEventId: streamOptions.lastEventId })
      });
      const passes = options.streamed ?? [events];
      const pass = passes[Math.min(streamIndex, passes.length - 1)] ?? [];
      streamIndex += 1;
      for (const event of pass) yield event;
    }
  };
}
