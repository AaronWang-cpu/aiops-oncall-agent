import { describe, expect, it } from "vitest";
import {
  DIAGNOSIS_PHASES, OPENAPI_CONTRACT, isDiagnosisResult,
  type DiagnosisResult, type AiopsDiagnosticSummary, type TaskStatusSseEvent
} from "../src";
import { DIAGNOSIS_SCHEMAS, validatesDiagnosisSchema } from "../src/diagnosis-schema";

function result(): DiagnosisResult {
  return {
    engine: "hypothesis-driven-v1", mode: "mock",
    hypotheses: [{
      hypothesis_id: "H1", statement: "连接配置变化有待验证。", hypothesis_status: "investigating",
      assessment: "症状不能证明原因。",
      evidence_links: [{ evidence_id: "E1", relation: "context", explanation: "时间相关。" }],
      gaps: [{ question: "实际配置？", why_it_matters: "验证机制。" }]
    }],
    hypothesis_relations: [],
    incident_conclusion: {
      conclusion_status: "unconfirmed", root_cause: null,
      stop_reason: null, explanation: "仍在调查。"
    },
    query_records: [{
      query_id: "Q1", hypothesis_ids: [], question: "查询日志。", tool_name: "SearchLog",
      arguments: { labels: { service: "payment" } }, status: "succeeded", status_reason: "返回数据。"
    }],
    tool_evidence: [{
      evidence_id: "E1", query_id: "Q1", kind: "change",
      data: { records: [{ field: "pool_size", before: 100, after: 20 }], error: null }
    }],
    unmet_requests: [], unassessed_evidence_ids: [], assessment_is_current: true,
    budget: {
      rounds_used: 1, tool_calls_used: 1, reserved_tool_calls: 0, unknown_tool_calls: 0,
      internal_steps_used: 0, max_rounds: 5, max_tool_calls: 20, max_internal_steps: 2,
      started_at: "2026-10-31T00:00:00Z", exploration_deadline: "2026-10-31T00:06:30Z",
      analysis_deadline: "2026-10-31T00:07:30Z", deadline: "2026-10-31T00:08:00Z"
    }
  };
}

describe("hypothesis-driven diagnosis contracts", () => {
  it("accepts exact business fields, nested JSON and nullable conclusions", () => {
    expect(isDiagnosisResult(result())).toBe(true);
    expect(Object.keys(result().hypotheses[0] ?? {})).toHaveLength(6);
    expect(Object.keys(result().tool_evidence[0] ?? {})).toHaveLength(4);
    expect(Object.keys(result().query_records[0] ?? {})).toHaveLength(7);
    expect(Object.keys(result().incident_conclusion)).toHaveLength(4);
    expect(isDiagnosisResult({ ...result(), hypotheses: [], query_records: [], tool_evidence: [] }))
      .toBe(true);
  });

  it.each(["scope", "locator", "confidence", "source"])("rejects extra hypothesis %s", (field) => {
    expect(isDiagnosisResult({
      ...result(), hypotheses: [{ ...result().hypotheses[0], [field]: "not-a-business-field" }]
    })).toBe(false);
  });

  it("rejects extra nested fields and invalid enums", () => {
    expect(isDiagnosisResult({
      ...result(), tool_evidence: [{ ...result().tool_evidence[0], locator: "row1" }]
    })).toBe(false);
    expect(isDiagnosisResult({
      ...result(), query_records: [{ ...result().query_records[0], status: "running" }]
    })).toBe(false);
    expect(isDiagnosisResult({ ...result(), mode: "auto" })).toBe(false);
    expect(isDiagnosisResult({ ...result(), budget: { ...result().budget, rounds_used: true } }))
      .toBe(false);
    expect(isDiagnosisResult({
      ...result(), tool_evidence: [{ ...result().tool_evidence[0], data: { value: Infinity } }]
    })).toBe(false);
  });

  it("cannot use suspected causes or execution errors as a confirmed conclusion", () => {
    for (const conclusion of [
      { conclusion_status: "unconfirmed", root_cause: "疑似原因", stop_reason: null },
      { conclusion_status: "confirmed", root_cause: null, stop_reason: "root_cause_confirmed" },
      { conclusion_status: "confirmed", root_cause: "配置降低", stop_reason: "budget_exhausted" },
      { conclusion_status: "unconfirmed", root_cause: null, stop_reason: "execution_error" }
    ]) {
      expect(isDiagnosisResult({
        ...result(), incident_conclusion: { ...conclusion, explanation: "不可用。" }
      })).toBe(false);
    }
    expect(isDiagnosisResult({
      ...result(), incident_conclusion: {
        conclusion_status: "confirmed", root_cause: "已验证配置导致容量降低。",
        stop_reason: "root_cause_confirmed", explanation: "有完整机制证据。"
      }
    })).toBe(true);
  });

  it("allows only actionable or explicitly unmet query plans", () => {
    const schema = DIAGNOSIS_SCHEMAS["DiagnosisQueryPlan"];
    expect(validatesDiagnosisSchema(schema, { calls: [], unmet_requests: [] })).toBe(false);
    expect(validatesDiagnosisSchema(schema, {
      calls: [],
      unmet_requests: [{ hypothesis_ids: [], requirement: "实际配置。", reason: "工具缺失。" }]
    })).toBe(true);
    expect(validatesDiagnosisSchema(schema, {
      calls: [{ hypothesis_ids: [], question: "日志。", tool_name: "SearchLog", arguments: {} }],
      unmet_requests: []
    })).toBe(true);
    expect(validatesDiagnosisSchema(DIAGNOSIS_SCHEMAS["DiagnosisNextStep"], {
      action: "finalize", reason: "已停止。",
      requests: [{ hypothesis_ids: [], requirement: "仍需查询。" }]
    })).toBe(false);
  });

  it("keeps old result payloads and chat progress events valid", () => {
    const payload: AiopsDiagnosticSummary["resultPayload"] = { legacy: true };
    expect(payload.diagnosis).toBeUndefined();
    expect(isDiagnosisResult(payload)).toBe(false);
    const event: TaskStatusSseEvent = {
      id: "e1", type: "task.status", channel: "chat", timestamp: "now",
      task: { id: "chat1", status: "running" }
    };
    expect(event.task.phase).toBeUndefined();
  });

  it("describes authenticated paths, cursor and all seven phases without changing event types", () => {
    const operation = OPENAPI_CONTRACT.paths["/aiops/diagnostics/{diagnosticId}:stream"]?.post;
    expect(operation?.security).toEqual([{ bearerAuth: [] }]);
    expect(operation?.responses).toHaveProperty("401");
    expect(operation?.responses).toHaveProperty("403");
    expect(operation?.parameters).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: "Last-Event-ID", in: "header", required: false })
    ]));
    expect(DIAGNOSIS_PHASES).toHaveLength(7);
    const schemas = OPENAPI_CONTRACT.components.schemas;
    expect(schemas.AiopsDiagnosticResponse.required).not.toContain("diagnosis");
    expect(schemas.AiopsDiagnosticEvidence.properties.kind.enum).toContain("change");
    expect(schemas.TaskStatusEvent.properties.task.properties.phase.enum).toEqual(DIAGNOSIS_PHASES);
    expect(schemas.DiagnosisResult).toEqual(DIAGNOSIS_SCHEMAS["DiagnosisResult"]);
  });
});
