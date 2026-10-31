import { DIAGNOSIS_SCHEMAS, validatesDiagnosisSchema } from "./diagnosis-schema";

export const DIAGNOSIS_PHASES = [
  "prepare_context", "build_queries", "execute_queries", "revise_hypotheses",
  "assess_hypotheses", "finalize", "report"
] as const;
export type DiagnosisPhase = (typeof DIAGNOSIS_PHASES)[number];
export type DiagnosisJsonValue =
  | null | boolean | number | string | readonly DiagnosisJsonValue[]
  | { readonly [key: string]: DiagnosisJsonValue };
export type HypothesisStatus =
  | "pending" | "investigating" | "supported" | "contradicted" | "blocked" | "unresolved";
export type DiagnosisStopReason =
  | "root_cause_confirmed" | "budget_exhausted" | "critical_data_unavailable";

export interface HypothesisEvidenceLink {
  readonly evidence_id: string;
  readonly relation: "supports" | "contradicts" | "context";
  readonly explanation: string;
}
export interface HypothesisGap {
  readonly question: string;
  readonly why_it_matters: string;
}
export interface HypothesisAssessment {
  readonly hypothesis_id: string;
  readonly hypothesis_status: HypothesisStatus;
  readonly assessment: string;
  readonly evidence_links: readonly HypothesisEvidenceLink[];
  readonly gaps: readonly HypothesisGap[];
}
export interface DiagnosisHypothesis extends HypothesisAssessment {
  readonly statement: string;
}
export interface DiagnosisEvidence {
  readonly evidence_id: string;
  readonly query_id: string;
  readonly kind: "log" | "metric" | "change";
  readonly data: DiagnosisJsonValue;
}
export interface DiagnosisQueryCall {
  readonly hypothesis_ids: readonly string[];
  readonly question: string;
  readonly tool_name: string;
  readonly arguments: Readonly<Record<string, DiagnosisJsonValue>>;
}
export interface DiagnosisQueryRecord extends DiagnosisQueryCall {
  readonly query_id: string;
  readonly status: "succeeded" | "failed";
  readonly status_reason: string;
}
export interface HypothesisRelation {
  readonly from_hypothesis_id: string;
  readonly to_hypothesis_id: string;
  readonly relation_type: "causal_link" | "competing";
  readonly explanation: string;
  readonly evidence_ids: readonly string[];
}
export interface IncidentConclusion {
  readonly conclusion_status: "confirmed" | "unconfirmed";
  readonly root_cause: string | null;
  readonly stop_reason: DiagnosisStopReason | null;
  readonly explanation: string;
}
export interface DiagnosisRequest {
  readonly hypothesis_ids: readonly string[];
  readonly requirement: string;
}
export interface DiagnosisUnmetRequest extends DiagnosisRequest {
  readonly reason: string;
}
export interface DiagnosisNextStep {
  readonly action: "build_queries" | "revise_hypotheses" | "finalize";
  readonly reason: string;
  readonly requests: readonly DiagnosisRequest[];
}
export interface DiagnosisQueryPlan {
  readonly calls: readonly DiagnosisQueryCall[];
  readonly unmet_requests: readonly DiagnosisUnmetRequest[];
}
export interface DiagnosisRevision {
  readonly new_hypotheses: readonly { readonly statement: string }[];
  readonly revised_hypotheses:
    readonly { readonly hypothesis_id: string; readonly statement: string }[];
}
export interface DiagnosisAssessmentOutput {
  readonly hypothesis_assessments: readonly HypothesisAssessment[];
  readonly hypothesis_relations: readonly HypothesisRelation[];
  readonly incident_conclusion: IncidentConclusion;
  readonly next_step: DiagnosisNextStep;
}
export interface DiagnosisBudget {
  readonly rounds_used: number;
  readonly tool_calls_used: number;
  readonly reserved_tool_calls: number;
  readonly unknown_tool_calls: number;
  readonly internal_steps_used: number;
  readonly max_rounds: number;
  readonly max_tool_calls: number;
  readonly max_internal_steps: number;
  readonly started_at: string;
  readonly exploration_deadline: string;
  readonly analysis_deadline: string;
  readonly deadline: string;
}
export interface DiagnosisResult {
  readonly engine: "hypothesis-driven-v1";
  readonly mode: "real" | "mock";
  readonly hypotheses: readonly DiagnosisHypothesis[];
  readonly hypothesis_relations: readonly HypothesisRelation[];
  readonly incident_conclusion: IncidentConclusion;
  readonly query_records: readonly DiagnosisQueryRecord[];
  readonly tool_evidence: readonly DiagnosisEvidence[];
  readonly unmet_requests: readonly DiagnosisUnmetRequest[];
  readonly unassessed_evidence_ids: readonly string[];
  readonly assessment_is_current: boolean;
  readonly budget: DiagnosisBudget;
}

export function isDiagnosisResult(value: unknown): value is DiagnosisResult {
  return validatesDiagnosisSchema(DIAGNOSIS_SCHEMAS["DiagnosisResult"], value);
}
