/** One schema source is used by OpenAPI and the runtime result guard. */
export interface DiagnosisSchema {
  readonly type?: string | readonly string[];
  readonly properties?: Readonly<Record<string, DiagnosisSchema>>;
  readonly required?: readonly string[];
  readonly additionalProperties?: boolean;
  readonly items?: DiagnosisSchema;
  readonly enum?: readonly string[];
  readonly oneOf?: readonly DiagnosisSchema[];
  readonly $ref?: string;
  readonly minimum?: number;
  readonly minLength?: number;
  readonly minItems?: number;
  readonly maxItems?: number;
}

const text: DiagnosisSchema = { type: "string", minLength: 1 };
const strings: DiagnosisSchema = { type: "array", items: text };
const count: DiagnosisSchema = { type: "integer", minimum: 0 };
const positive: DiagnosisSchema = { type: "integer", minimum: 1 };
const enumeration = (...values: string[]): DiagnosisSchema => ({
  type: "string", enum: values
});
const ref = (name: string): DiagnosisSchema => ({ $ref: `#/components/schemas/${name}` });
const list = (name: string): DiagnosisSchema => ({ type: "array", items: ref(name) });
const exact = (properties: Record<string, DiagnosisSchema>): DiagnosisSchema => ({
  type: "object", properties, required: Object.keys(properties), additionalProperties: false
});
const nullable = (schema: DiagnosisSchema): DiagnosisSchema => ({
  oneOf: [schema, { type: "null" }]
});
const assessment = {
  hypothesis_id: text,
  hypothesis_status: enumeration(
    "pending", "investigating", "supported", "contradicted", "blocked", "unresolved"
  ),
  assessment: text, evidence_links: list("HypothesisEvidenceLink"), gaps: list("HypothesisGap")
};
const call = {
  hypothesis_ids: strings, question: text, tool_name: text,
  arguments: { type: "object", additionalProperties: true } satisfies DiagnosisSchema
};
const request = { hypothesis_ids: strings, requirement: text };

export const DIAGNOSIS_SCHEMAS: Readonly<Record<string, DiagnosisSchema>> = {
  HypothesisEvidenceLink: exact({
    evidence_id: text, relation: enumeration("supports", "contradicts", "context"), explanation: text
  }),
  HypothesisGap: exact({ question: text, why_it_matters: text }),
  HypothesisAssessment: exact(assessment),
  DiagnosisHypothesis: exact({ ...assessment, statement: text }),
  DiagnosisEvidence: exact({
    evidence_id: text, query_id: text, kind: enumeration("log", "metric", "change"), data: {}
  }),
  DiagnosisQueryCall: exact(call),
  DiagnosisQueryRecord: exact({
    ...call, query_id: text, status: enumeration("succeeded", "failed"), status_reason: text
  }),
  HypothesisRelation: exact({
    from_hypothesis_id: text, to_hypothesis_id: text,
    relation_type: enumeration("causal_link", "competing"), explanation: text, evidence_ids: strings
  }),
  IncidentConclusion: {
    oneOf: [
      exact({
        conclusion_status: enumeration("confirmed"), root_cause: text,
        stop_reason: enumeration("root_cause_confirmed"), explanation: text
      }),
      exact({
        conclusion_status: enumeration("unconfirmed"), root_cause: { type: "null" },
        stop_reason: nullable(enumeration("budget_exhausted", "critical_data_unavailable")),
        explanation: text
      })
    ]
  },
  DiagnosisRequest: exact(request),
  DiagnosisUnmetRequest: exact({ ...request, reason: text }),
  DiagnosisNextStep: {
    oneOf: [
      exact({
        action: enumeration("build_queries", "revise_hypotheses"),
        reason: text, requests: list("DiagnosisRequest")
      }),
      exact({
        action: enumeration("finalize"), reason: text,
        requests: { ...list("DiagnosisRequest"), maxItems: 0 }
      })
    ]
  },
  DiagnosisQueryPlan: {
    oneOf: [
      exact({
        calls: { ...list("DiagnosisQueryCall"), minItems: 1 },
        unmet_requests: list("DiagnosisUnmetRequest")
      }),
      exact({
        calls: { ...list("DiagnosisQueryCall"), maxItems: 0 },
        unmet_requests: { ...list("DiagnosisUnmetRequest"), minItems: 1 }
      })
    ]
  },
  DiagnosisRevision: exact({
    new_hypotheses: { type: "array", items: exact({ statement: text }) },
    revised_hypotheses: {
      type: "array", items: exact({ hypothesis_id: text, statement: text })
    }
  }),
  DiagnosisAssessmentOutput: exact({
    hypothesis_assessments: list("HypothesisAssessment"),
    hypothesis_relations: list("HypothesisRelation"),
    incident_conclusion: ref("IncidentConclusion"), next_step: ref("DiagnosisNextStep")
  }),
  DiagnosisBudget: exact({
    rounds_used: count, tool_calls_used: count, reserved_tool_calls: count,
    unknown_tool_calls: count, internal_steps_used: count,
    max_rounds: positive, max_tool_calls: positive, max_internal_steps: positive,
    started_at: text, exploration_deadline: text, analysis_deadline: text, deadline: text
  }),
  DiagnosisResult: exact({
    engine: enumeration("hypothesis-driven-v1"), mode: enumeration("real", "mock"),
    hypotheses: list("DiagnosisHypothesis"), hypothesis_relations: list("HypothesisRelation"),
    incident_conclusion: ref("IncidentConclusion"), query_records: list("DiagnosisQueryRecord"),
    tool_evidence: list("DiagnosisEvidence"), unmet_requests: list("DiagnosisUnmetRequest"),
    unassessed_evidence_ids: strings, assessment_is_current: { type: "boolean" },
    budget: ref("DiagnosisBudget")
  })
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isJson(value: unknown): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return (value as unknown[]).every(isJson);
  return isRecord(value) && Object.values(value).every(isJson);
}

export function validatesDiagnosisSchema(
  schema: DiagnosisSchema | undefined, value: unknown
): boolean {
  if (schema === undefined) return false;
  if (schema.$ref !== undefined) {
    return validatesDiagnosisSchema(DIAGNOSIS_SCHEMAS[schema.$ref.split("/").at(-1) ?? ""], value);
  }
  if (schema.oneOf !== undefined) {
    return schema.oneOf.filter((part) => validatesDiagnosisSchema(part, value)).length === 1;
  }
  if (schema.enum !== undefined) {
    return typeof value === "string" && schema.enum.includes(value);
  }
  switch (schema.type) {
    case "null": return value === null;
    case "boolean": return typeof value === "boolean";
    case "string":
      return typeof value === "string" && value.trim().length >= (schema.minLength ?? 0);
    case "integer":
      return typeof value === "number" && Number.isInteger(value) && value >= (schema.minimum ?? 0);
    case "array":
      return Array.isArray(value)
        && value.length >= (schema.minItems ?? 0)
        && value.length <= (schema.maxItems ?? Infinity)
        && (value as unknown[]).every(
        (item) => validatesDiagnosisSchema(schema.items, item)
      );
    case "object":
      if (!isRecord(value) || !isJson(value)) return false;
      if (schema.properties === undefined) return true;
      if (!(schema.required ?? []).every((key) => Object.hasOwn(value, key))) return false;
      return Object.entries(value).every(([key, item]) =>
        schema.properties?.[key] === undefined
          ? schema.additionalProperties !== false
          : validatesDiagnosisSchema(schema.properties[key], item)
      );
    default: return isJson(value);
  }
}
