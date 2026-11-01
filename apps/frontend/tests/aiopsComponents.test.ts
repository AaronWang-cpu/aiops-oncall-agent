// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AiopsDiagnosticEvidenceChain,
  AiopsDiagnosticStep,
  AiopsDiagnosticSummary,
  DiagnosisResult,
  SseEvent
} from "@agent-py/api-contracts";

import AiopsEvidenceChain from "../src/components/AiopsEvidenceChain.vue";
import AiopsCaseLibrary from "../src/components/AiopsCaseLibrary.vue";
import AiopsReportPanel from "../src/components/AiopsReportPanel.vue";
import AiopsRunForm from "../src/components/AiopsRunForm.vue";
import AiopsTimeline from "../src/components/AiopsTimeline.vue";

beforeEach(() => {
  setActivePinia(createPinia());
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: true, data: { items: [] } }), {
    headers: { "Content-Type": "application/json" },
    status: 200
  })));
});

describe("AIOps components", () => {
  it("validates optional alert context before creating a diagnosis", async () => {
    const wrapper = mount(AiopsRunForm, { props: { disabled: false, isRunning: false } });
    await wrapper.get('textarea[aria-label="诊断问题"]').setValue("Inspect latency");
    await wrapper.get('textarea[aria-label="告警上下文"]') .setValue("{not-json");
    await wrapper.get('button[type="submit"]').trigger("submit");

    expect(wrapper.text()).toContain("有效的 JSON 对象");
    expect(wrapper.emitted("run")).toBeUndefined();
  });

  it("renders a readable execution chain with collapsed tool summaries and no raw JSON", () => {
    const event: SseEvent = {
      id: "event_1",
      type: "tool.call",
      channel: "aiops",
      timestamp: "2026-07-10T00:00:01.000Z",
      toolCall: { id: "tool_1", name: "SearchLog", status: "completed", output: { raw: "x".repeat(400) } }
    };
    const chain: AiopsDiagnosticEvidenceChain = {
      task: diagnostic(),
      steps: [
        { id: "step_1", taskId: "diagnostic_1", sequence: 1, phase: "planner", status: "completed", payload: { noSopMatched: true, plan: [{ tool: "SearchLog", purpose: "查询告警窗口日志" }] }, createdAt: "2026-07-10T00:00:00.000Z" },
        { id: "step_2", taskId: "diagnostic_1", sequence: 2, phase: "executor", status: "completed", payload: { tool: "SearchLog", planStep: { purpose: "查询告警窗口日志" } }, createdAt: "2026-07-10T00:00:01.000Z" },
        { id: "step_3", taskId: "diagnostic_1", sequence: 3, phase: "replanner", status: "completed", payload: { decision: "report", planIndex: 1, planLength: 1, executionFailed: false }, createdAt: "2026-07-10T00:00:02.000Z" }
      ],
      toolCalls: [{
        id: "tool_1", ownerUserId: "user_1", sessionId: null, diagnosticTaskId: "diagnostic_1", toolName: "SearchLog", status: "completed", arguments: {},
        resultSummary: JSON.stringify({ recordCount: 20, records: [{ timestamp: "2026-07-10 08:00:00", level: "ERROR", service: "checkout", event: "timeout", message: "request timeout", latency_ms: 2450 }] }),
        errorMessage: null, startedAt: "2026-07-10T00:00:01.000Z", completedAt: "2026-07-10T00:00:02.000Z", durationMs: 1000, createdAt: "2026-07-10T00:00:01.000Z"
      }],
      evidence: [{ id: "evidence_1", taskId: "diagnostic_1", stepId: "step_2", toolCallId: "tool_1", kind: "log", source: "SearchLog", summary: "RAW_EVIDENCE_MARKER", payload: { raw: "RAW_PAYLOAD_MARKER" }, createdAt: "2026-07-10T00:00:01.000Z" }],
      reports: [{ id: "report_1", title: "Diagnostic report", content: "Persisted report body.", payload: {}, evidenceIds: ["evidence_1"], createdAt: "2026-07-10T00:00:02.000Z" }],
      reportEvidenceLinks: [{ id: "link_1", taskId: "diagnostic_1", reportId: "report_1", evidenceId: "evidence_1", createdAt: "2026-07-10T00:00:02.000Z" }],
      checkpoints: []
    };

    const timeline = mount(AiopsTimeline, { props: { events: [event], isRunning: true } });
    expect(timeline.text()).toContain("诊断过程");
    expect(timeline.text()).toContain("已完成");
    expect(timeline.text()).toContain("SearchLog");
    expect(timeline.text()).not.toContain("raw");
    expect(timeline.text()).not.toContain("x".repeat(400));
    const execution = mount(AiopsEvidenceChain, { props: { chain } });
    expect(execution.text()).toContain("Planner · 生成 1 步诊断计划");
    expect(execution.text()).toContain("Executor · 查询告警窗口日志");
    expect(execution.text()).toContain("Replanner · 证据汇总完成，进入报告");
    expect(execution.text()).toContain("共返回 20 条日志");
    expect(execution.text()).toContain("request timeout");
    expect(execution.findAll("details")).toHaveLength(1);
    expect(execution.get("details").attributes("open")).toBeUndefined();
    expect(execution.text()).not.toContain("recordCount");
    expect(execution.text()).not.toContain("RAW_EVIDENCE_MARKER");
    expect(execution.text()).not.toContain("RAW_PAYLOAD_MARKER");
    expect(execution.text()).not.toContain("evidence_1");
    expect(execution.text()).not.toContain("Persisted report body");
  });

  it("renders the seven-node engine steps and keeps unknown steps visible", () => {
    const steps: readonly AiopsDiagnosticStep[] = [
      persistedStep(1, "prepare_context", { mode: "mock", toolNames: ["SearchLog", "QueryMetric"], knowledgeServices: ["order-service"] }),
      persistedStep(2, "build_queries", { calls: [{ tool: "SearchLog", question: "查询告警窗口日志" }], unmetRequests: ["缺少变更数据"] }),
      persistedStep(3, "execute_queries", { planned: 1, succeeded: 1, failed: 0 }),
      persistedStep(4, "revise_hypotheses", { new: 1, revised: 0 }),
      persistedStep(5, "assess_hypotheses", { assessed: ["H1"], relations: 1, conclusion: "unconfirmed", nextAction: "finalize" }),
      persistedStep(6, "finalize", { status: "succeeded", stopReason: "budget_exhausted" }),
      persistedStep(7, "mystery_node", {})
    ];
    const wrapper = mount(AiopsEvidenceChain, { props: { chain: emptyChain(steps) } });

    expect(wrapper.text()).toContain("准备上下文 · 模拟模式，可用工具 2 项");
    expect(wrapper.text()).toContain("构建查询 · 计划 1 项查询");
    expect(wrapper.text()).toContain("查询告警窗口日志");
    expect(wrapper.text()).toContain("未满足需求：缺少变更数据");
    expect(wrapper.text()).toContain("执行查询 · 成功 1 / 计划 1");
    expect(wrapper.text()).toContain("调整假设 · 新增 1，修改 0");
    expect(wrapper.text()).toContain("评估假设 · 判断 1 项，关系 1 条");
    expect(wrapper.text()).toContain("收敛调查 · 调查完成");
    expect(wrapper.text()).toContain("停止原因：调查预算耗尽");
    expect(wrapper.text()).toContain("mystery_node · completed");
    expect(wrapper.findAll(".aiops-execution__steps li")).toHaveLength(7);
  });

  it("shows supported hypotheses with evidence, gaps and an unconfirmed conclusion", () => {
    const wrapper = mount(AiopsEvidenceChain, {
      props: { chain: emptyChain([]), diagnosis: diagnosis() }
    });

    expect(wrapper.text()).toContain("假设与判断");
    expect(wrapper.text()).toContain("有证据支持");
    expect(wrapper.text()).toContain("订单服务连接池耗尽");
    expect(wrapper.text()).toContain("支持：日志显示连接超时");
    expect(wrapper.text()).toContain("待验证：是否只有订单服务受影响");
    expect(wrapper.text()).toContain("因果关联");
    expect(wrapper.text()).toContain("连接池耗尽导致网关超时");
    expect(wrapper.text()).toContain("具体根因尚未确认");
    expect(wrapper.text()).not.toContain("事故根因已确认");
    expect(wrapper.text()).not.toContain("E1");
    expect(wrapper.findAll("details")).toHaveLength(0);
  });

  it("marks stale assessments and unassessed evidence instead of mixing them", () => {
    const wrapper = mount(AiopsEvidenceChain, {
      props: {
        chain: emptyChain([]),
        diagnosis: { ...diagnosis(), assessment_is_current: false, unassessed_evidence_ids: ["E9"] }
      }
    });

    expect(wrapper.text()).toContain("以下判断来自此前快照");
    expect(wrapper.text()).toContain("另有 1 条证据尚未纳入当前结论");
  });

  it("labels mock investigations and never marks unknown historical modes as real", () => {
    const mocked = mount(AiopsEvidenceChain, {
      props: { chain: emptyChain([]), diagnosis: { ...diagnosis(), mode: "mock" } }
    });
    expect(mocked.text()).toContain("模拟场景");

    const legacy = mount(AiopsEvidenceChain, { props: { chain: emptyChain([]) } });
    expect(legacy.text()).not.toContain("模拟场景");
    expect(legacy.text()).not.toContain("假设与判断");
    expect(legacy.text()).not.toContain("真实数据");
  });

  it("renders a persisted Markdown report as the center reading surface", () => {
    const wrapper = mount(AiopsReportPanel, {
      props: {
        report: {
          id: "report_1",
          title: "告警分析报告",
          content: "# 告警分析报告\n\n## 📋 活跃告警清单\n\n| 告警 | 级别 |\n|---|---|\n| CPU高 | 严重 |\n\n## 📊 结论\n\n需要继续核实。",
          createdAt: "2026-07-10T00:00:02.000Z"
        },
        isRunning: false,
        hasTask: true,
        taskFailed: false
      }
    });

    expect(wrapper.text()).toContain("最终诊断报告");
    expect(wrapper.text()).toContain("已沉淀");
    expect(wrapper.text()).toContain("活跃告警清单");
    expect(wrapper.find("table").exists()).toBe(true);
    expect(wrapper.find(".markdown-content--report").exists()).toBe(true);
  });

  it("keeps a failed diagnosis failed even when a fallback report exists", () => {
    const wrapper = mount(AiopsReportPanel, {
      props: {
        report: {
          id: "report_1",
          title: "诊断报告",
          content: "# 诊断报告\n\n兜底正文。",
          createdAt: "2026-07-10T00:00:02.000Z"
        },
        isRunning: false,
        hasTask: true,
        taskFailed: true
      }
    });

    expect(wrapper.text()).toContain("诊断失败");
    expect(wrapper.text()).toContain("报告内容不代表调查成功");
    expect(wrapper.text()).not.toContain("已沉淀");
    expect(wrapper.text()).toContain("兜底正文");
  });

  it("shows the mock scenario tag and the cancel note on the report panel", () => {
    const base = {
      report: {
        id: "report_1",
        title: "诊断报告",
        content: "# 诊断报告\n\n正文。",
        createdAt: "2026-07-10T00:00:02.000Z"
      },
      isRunning: false,
      hasTask: true,
      taskFailed: false
    };

    const mocked = mount(AiopsReportPanel, { props: { ...base, diagnosisMode: "mock" } });
    expect(mocked.text()).toContain("模拟场景");

    const canceled = mount(AiopsReportPanel, { props: { ...base, taskCanceled: true } });
    expect(canceled.text()).toContain("诊断任务已取消");

    const historical = mount(AiopsReportPanel, { props: base });
    expect(historical.text()).not.toContain("模拟场景");
  });

  it("explains report generation while a diagnosis is running", () => {
    const wrapper = mount(AiopsReportPanel, {
      props: { report: null, isRunning: true, hasTask: true, taskFailed: false }
    });

    expect(wrapper.text()).toContain("生成中");
    expect(wrapper.text()).toContain("正在等待诊断证据汇总");
  });

  it("labels new diagnosis phases in the live timeline without dropping them", () => {
    const events: readonly SseEvent[] = [
      { id: "t1", type: "task.status", channel: "aiops", timestamp: "2026-07-10T00:00:01.000Z", task: { id: "diagnostic_1", status: "running", message: "正在构建查询", phase: "build_queries" } },
      { id: "t2", type: "task.status", channel: "aiops", timestamp: "2026-07-10T00:00:02.000Z", task: { id: "diagnostic_1", status: "running", message: "正在评估假设", phase: "assess_hypotheses" } }
    ];
    const wrapper = mount(AiopsTimeline, { props: { events, isRunning: true } });

    expect(wrapper.text()).toContain("正在构建查询");
    expect(wrapper.text()).toContain("构建查询");
    expect(wrapper.text()).toContain("评估假设");
  });

  it("does not repeat the report body inside the timeline", () => {
    const marker = "REPORT_BODY_MARKER";
    const event: SseEvent = {
      id: "e_report",
      type: "report",
      channel: "aiops",
      timestamp: "2026-07-10T00:00:03.000Z",
      report: { id: "report_1", title: "诊断报告", content: `# 诊断报告\n\n${marker}`, format: "markdown" }
    };
    const wrapper = mount(AiopsTimeline, { props: { events: [event], isRunning: false } });

    expect(wrapper.text()).toContain("诊断报告");
    expect(wrapper.text()).not.toContain(marker);
  });

  it("lists a server-backed diagnosis case and selects its task", async () => {
    const longSummary = `# 告警分析报告\n\n${"长报告内容".repeat(80)}`;
    const wrapper = mount(AiopsCaseLibrary, {
      props: {
        cases: [{
          id: "case_1", ownerUserId: "user_1", taskId: "diagnostic_1", reportId: "report_1", documentId: "doc_1", indexTaskId: "index_1", alertName: "CheckoutLatencyHigh", service: "checkout", keywords: ["checkout", "latency"], rootCause: "", remediation: "", summary: longSummary, evidenceIds: ["evidence_1"], createdAt: "2026-07-10T00:00:00Z"
        }]
      }
    });

    expect(wrapper.text()).toContain("CheckoutLatencyHigh");
    expect(wrapper.text()).toContain("长报告内容");
    expect(wrapper.text()).not.toContain(longSummary);
    await wrapper.get(".aiops-case-library__case").trigger("click");
    expect(wrapper.emitted("select")).toEqual([["diagnostic_1"]]);
    await wrapper.get('button[title="打开生成的知识文档"]').trigger("click");
    expect(wrapper.emitted("open-document")).toEqual([["doc_1"]]);
  });
});

function diagnostic(): AiopsDiagnosticSummary {
  return {
    id: "diagnostic_1",
    ownerUserId: "user_1",
    status: "succeeded",
    query: "Inspect latency",
    inputPayload: {},
    resultPayload: {},
    createdAt: "2026-07-10T00:00:00.000Z",
    updatedAt: "2026-07-10T00:00:02.000Z",
    completedAt: "2026-07-10T00:00:02.000Z",
    reports: []
  };
}

function persistedStep(
  sequence: number,
  phase: string,
  payload: Record<string, unknown>
): AiopsDiagnosticStep {
  return {
    id: `step_${sequence}`,
    taskId: "diagnostic_1",
    sequence,
    phase,
    status: "completed",
    payload,
    createdAt: "2026-07-10T00:00:00.000Z"
  };
}

function emptyChain(steps: readonly AiopsDiagnosticStep[]): AiopsDiagnosticEvidenceChain {
  return {
    task: diagnostic(),
    steps,
    toolCalls: [],
    evidence: [],
    reports: [],
    reportEvidenceLinks: [],
    checkpoints: []
  };
}

function diagnosis(): DiagnosisResult {
  return {
    engine: "hypothesis-driven-v1",
    mode: "mock",
    hypotheses: [
      {
        hypothesis_id: "H1",
        statement: "订单服务连接池耗尽",
        hypothesis_status: "supported",
        assessment: "日志与指标同时显示连接超时。",
        evidence_links: [{ evidence_id: "E1", relation: "supports", explanation: "日志显示连接超时" }],
        gaps: [{ question: "是否只有订单服务受影响", why_it_matters: "确认影响范围" }]
      },
      {
        hypothesis_id: "H2",
        statement: "网关自身发布导致超时",
        hypothesis_status: "contradicted",
        assessment: "网关版本未变化。",
        evidence_links: [],
        gaps: []
      }
    ],
    hypothesis_relations: [{
      from_hypothesis_id: "H1",
      to_hypothesis_id: "H2",
      relation_type: "causal_link",
      explanation: "连接池耗尽导致网关超时",
      evidence_ids: ["E1"]
    }],
    incident_conclusion: {
      conclusion_status: "unconfirmed",
      root_cause: null,
      stop_reason: null,
      explanation: "尚需确认影响范围。"
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
  };
}
