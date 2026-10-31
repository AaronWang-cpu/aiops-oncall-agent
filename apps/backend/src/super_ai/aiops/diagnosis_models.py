"""Strict business and node-output contracts for hypothesis-driven diagnosis."""

from __future__ import annotations

from collections.abc import Collection
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
HypothesisStatus = Literal[
    "pending", "investigating", "supported", "contradicted", "blocked", "unresolved"
]
EvidenceKind = Literal["log", "metric", "change"]
StopReason = Literal["root_cause_confirmed", "budget_exhausted", "critical_data_unavailable"]
DiagnosisPhase = Literal[
    "prepare_context",
    "build_queries",
    "execute_queries",
    "revise_hypotheses",
    "assess_hypotheses",
    "finalize",
    "report",
]


class DiagnosisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class EvidenceLink(DiagnosisModel):
    evidence_id: Text
    relation: Literal["supports", "contradicts", "context"]
    explanation: Text


class HypothesisGap(DiagnosisModel):
    question: Text
    why_it_matters: Text


class HypothesisAssessment(DiagnosisModel):
    hypothesis_id: Text
    hypothesis_status: HypothesisStatus
    assessment: Text
    evidence_links: list[EvidenceLink]
    gaps: list[HypothesisGap]


class Hypothesis(HypothesisAssessment):
    statement: Text


class Evidence(DiagnosisModel):
    evidence_id: Text
    query_id: Text
    kind: EvidenceKind
    data: JsonValue


class QueryCall(DiagnosisModel):
    hypothesis_ids: list[Text]
    question: Text
    tool_name: Text
    arguments: dict[str, JsonValue]


class QueryRecord(QueryCall):
    query_id: Text
    status: Literal["succeeded", "failed"]
    status_reason: Text


class HypothesisRelation(DiagnosisModel):
    from_hypothesis_id: Text
    to_hypothesis_id: Text
    relation_type: Literal["causal_link", "competing"]
    explanation: Text
    evidence_ids: list[Text]


class IncidentConclusion(DiagnosisModel):
    conclusion_status: Literal["confirmed", "unconfirmed"]
    root_cause: Text | None
    stop_reason: StopReason | None
    explanation: Text

    @model_validator(mode="after")
    def validate_confirmation(self) -> IncidentConclusion:
        if self.conclusion_status == "confirmed":
            if self.root_cause is None or self.stop_reason != "root_cause_confirmed":
                raise ValueError("confirmed requires a cause and root_cause_confirmed")
        elif self.root_cause is not None or self.stop_reason == "root_cause_confirmed":
            raise ValueError("unconfirmed cannot contain a confirmed cause")
        return self


class InvestigationRequest(DiagnosisModel):
    hypothesis_ids: list[Text]
    requirement: Text


class UnmetRequest(InvestigationRequest):
    reason: Text


class NextStep(DiagnosisModel):
    action: Literal["build_queries", "revise_hypotheses", "finalize"]
    reason: Text
    requests: list[InvestigationRequest]

    @model_validator(mode="after")
    def validate_finalization(self) -> NextStep:
        if self.action == "finalize" and self.requests:
            raise ValueError("finalize must not contain further requests")
        return self


class QueryPlan(DiagnosisModel):
    calls: list[QueryCall]
    unmet_requests: list[UnmetRequest]

    @model_validator(mode="after")
    def validate_nonempty_plan(self) -> QueryPlan:
        if not self.calls and not self.unmet_requests:
            raise ValueError("query plan must contain calls or unmet requests")
        return self

    def validate_context(
        self, *, hypothesis_ids: Collection[str], tool_names: Collection[str], max_calls: int
    ) -> None:
        if len(self.calls) > max_calls:
            raise ValueError("query plan exceeds available batch/call budget")
        for call in self.calls:
            _validate_ids(call.hypothesis_ids, hypothesis_ids, "hypothesis")
            if call.tool_name not in tool_names:
                raise ValueError("query plan references an unavailable tool")
        for request in self.unmet_requests:
            _validate_ids(request.hypothesis_ids, hypothesis_ids, "hypothesis")


class NewHypothesis(DiagnosisModel):
    statement: Text


class RevisedHypothesis(NewHypothesis):
    hypothesis_id: Text


class HypothesisRevision(DiagnosisModel):
    new_hypotheses: list[NewHypothesis]
    revised_hypotheses: list[RevisedHypothesis]

    def validate_context(self, *, hypothesis_ids: Collection[str]) -> None:
        _validate_ids(
            [item.hypothesis_id for item in self.revised_hypotheses],
            hypothesis_ids,
            "hypothesis",
        )


class AssessmentOutput(DiagnosisModel):
    hypothesis_assessments: list[HypothesisAssessment]
    hypothesis_relations: list[HypothesisRelation]
    incident_conclusion: IncidentConclusion
    next_step: NextStep

    def validate_context(
        self,
        *,
        hypothesis_ids: Collection[str],
        evidence_ids: Collection[str],
        final_analysis: bool = False,
    ) -> None:
        assessed = [item.hypothesis_id for item in self.hypothesis_assessments]
        _validate_ids(assessed, hypothesis_ids, "hypothesis")
        if set(assessed) != set(hypothesis_ids):
            raise ValueError("assessment must cover all current hypotheses exactly once")
        for item in self.hypothesis_assessments:
            _validate_ids(
                [link.evidence_id for link in item.evidence_links], evidence_ids, "evidence"
            )
        relations: set[tuple[str, str, str]] = set()
        for relation in self.hypothesis_relations:
            _validate_ids(
                [relation.from_hypothesis_id, relation.to_hypothesis_id],
                hypothesis_ids,
                "hypothesis",
            )
            _validate_ids(relation.evidence_ids, evidence_ids, "evidence")
            ends = (relation.from_hypothesis_id, relation.to_hypothesis_id)
            if relation.relation_type == "competing":
                ends = tuple(sorted(ends))
            key = (relation.relation_type, ends[0], ends[1])
            if key in relations:
                raise ValueError("duplicate hypothesis relationship")
            relations.add(key)
        for request in self.next_step.requests:
            _validate_ids(request.hypothesis_ids, hypothesis_ids, "hypothesis")
        stopped = self.incident_conclusion.stop_reason is not None
        if stopped and self.next_step.action != "finalize":
            raise ValueError("a stopping conclusion requires finalize")
        if not stopped and self.next_step.action == "finalize" and not final_analysis:
            raise ValueError("normal finalize requires a stopping fact")
        if final_analysis and self.next_step.action != "finalize":
            raise ValueError("final analysis may not request further investigation")


class DiagnosisBudget(DiagnosisModel):
    rounds_used: Annotated[int, Field(ge=0)]
    tool_calls_used: Annotated[int, Field(ge=0)]
    reserved_tool_calls: Annotated[int, Field(ge=0)]
    unknown_tool_calls: Annotated[int, Field(ge=0)]
    internal_steps_used: Annotated[int, Field(ge=0)]
    max_rounds: Annotated[int, Field(gt=0)]
    max_tool_calls: Annotated[int, Field(gt=0)]
    max_internal_steps: Annotated[int, Field(gt=0)]
    started_at: Text
    exploration_deadline: Text
    analysis_deadline: Text
    deadline: Text


class DiagnosisResult(DiagnosisModel):
    engine: Literal["hypothesis-driven-v1"]
    mode: Literal["real", "mock"]
    hypotheses: list[Hypothesis]
    hypothesis_relations: list[HypothesisRelation]
    incident_conclusion: IncidentConclusion
    query_records: list[QueryRecord]
    tool_evidence: list[Evidence]
    unmet_requests: list[UnmetRequest]
    unassessed_evidence_ids: list[Text]
    assessment_is_current: bool
    budget: DiagnosisBudget

    def validate_references(self) -> None:
        hypotheses = [item.hypothesis_id for item in self.hypotheses]
        queries = [item.query_id for item in self.query_records]
        evidence = [item.evidence_id for item in self.tool_evidence]
        for values, kind in (
            (hypotheses, "hypothesis"),
            (queries, "query"),
            (evidence, "evidence"),
        ):
            _validate_ids(values, values, kind)
        for item in self.tool_evidence:
            _validate_ids([item.query_id], queries, "query")
        for query in self.query_records:
            _validate_ids(query.hypothesis_ids, hypotheses, "hypothesis")
        for request in self.unmet_requests:
            _validate_ids(request.hypothesis_ids, hypotheses, "hypothesis")
        _validate_ids(self.unassessed_evidence_ids, evidence, "evidence")
        assessment = AssessmentOutput(
            hypothesis_assessments=[
                HypothesisAssessment.model_validate(item.model_dump(exclude={"statement"}))
                for item in self.hypotheses
            ],
            hypothesis_relations=self.hypothesis_relations,
            incident_conclusion=self.incident_conclusion,
            next_step=NextStep(action="finalize", reason="公开调查状态。", requests=[]),
        )
        assessment.validate_context(
            hypothesis_ids=hypotheses, evidence_ids=evidence, final_analysis=True
        )


def _validate_ids(values: Collection[str], allowed: Collection[str], kind: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {kind} reference")
    if not set(values).issubset(allowed):
        raise ValueError(f"unknown {kind} reference")
