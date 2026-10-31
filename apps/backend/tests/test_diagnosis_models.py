from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from super_ai.aiops.diagnosis_models import (
    AssessmentOutput,
    DiagnosisResult,
    Evidence,
    Hypothesis,
    HypothesisRevision,
    IncidentConclusion,
    NextStep,
    QueryPlan,
    QueryRecord,
)


def _assessment() -> dict[str, object]:
    return {
        "hypothesis_assessments": [
            {
                "hypothesis_id": "H1",
                "hypothesis_status": "investigating",
                "assessment": "需要验证实际配置，不能仅凭等待症状确认原因。",
                "evidence_links": [
                    {"evidence_id": "E1", "relation": "supports", "explanation": "仅支持等待症状。"}
                ],
                "gaps": [{"question": "生效配置是否变化？", "why_it_matters": "区分容量与流量。"}],
            },
            {
                "hypothesis_id": "H2",
                "hypothesis_status": "pending",
                "assessment": "尚待取得流量证据。",
                "evidence_links": [],
                "gaps": [],
            },
        ],
        "hypothesis_relations": [],
        "incident_conclusion": {
            "conclusion_status": "unconfirmed",
            "root_cause": None,
            "stop_reason": None,
            "explanation": "当前只确认症状。",
        },
        "next_step": {
            "action": "build_queries",
            "reason": "补充判别事实。",
            "requests": [{"hypothesis_ids": ["H1", "H2"], "requirement": "查询配置与流量。"}],
        },
    }


def test_assessment_has_no_statement_and_preserves_nested_objects() -> None:
    output = AssessmentOutput.model_validate(_assessment())
    output.validate_context(hypothesis_ids={"H1", "H2"}, evidence_ids={"E1"})
    assert set(output.hypothesis_assessments[0].model_dump()) == {
        "hypothesis_id",
        "hypothesis_status",
        "assessment",
        "evidence_links",
        "gaps",
    }
    assert output.incident_conclusion.root_cause is None
    assert output.hypothesis_assessments[0].gaps[0].why_it_matters == "区分容量与流量。"


@pytest.mark.parametrize(
    ("ids", "message"),
    [
        ({"H1"}, "unknown hypothesis reference"),
        ({"H1", "H2", "H3"}, "assessment must cover all current hypotheses exactly once"),
    ],
)
def test_assessment_requires_exact_hypothesis_set(ids: set[str], message: str) -> None:
    output = AssessmentOutput.model_validate(_assessment())
    with pytest.raises(ValueError) as exc:
        output.validate_context(hypothesis_ids=ids, evidence_ids={"E1"})
    assert str(exc.value) == message


def test_assessment_rejects_duplicate_id_and_unknown_evidence() -> None:
    output = AssessmentOutput.model_validate(_assessment())
    output.hypothesis_assessments[1].hypothesis_id = "H1"
    with pytest.raises(ValueError, match="duplicate"):
        output.validate_context(hypothesis_ids={"H1", "H2"}, evidence_ids={"E1"})
    output = AssessmentOutput.model_validate(_assessment())
    with pytest.raises(ValueError, match="unknown evidence"):
        output.validate_context(hypothesis_ids={"H1", "H2"}, evidence_ids={"OTHER"})


def test_assessment_rejects_extra_statement() -> None:
    output = AssessmentOutput.model_validate(_assessment()).model_dump()
    assessments = list(AssessmentOutput.model_validate(output).hypothesis_assessments)
    extra = {**assessments[0].model_dump(), "statement": "评估节点不写解释。"}
    output["hypothesis_assessments"] = [extra, assessments[1].model_dump()]
    with pytest.raises(ValidationError, match="statement"):
        AssessmentOutput.model_validate(output)


@pytest.mark.parametrize("reverse", [False, True])
def test_competing_relationship_is_undirected_and_unique(reverse: bool) -> None:
    output = AssessmentOutput.model_validate(_assessment()).model_dump()
    relation: dict[str, object] = {
        "from_hypothesis_id": "H1",
        "to_hypothesis_id": "H2",
        "relation_type": "competing",
        "explanation": "两者可共同作用，尚须区分。",
        "evidence_ids": ["E1"],
    }
    duplicate = deepcopy(relation)
    if reverse:
        duplicate.update(from_hypothesis_id="H2", to_hypothesis_id="H1")
    output["hypothesis_relations"] = [relation, duplicate]
    with pytest.raises(ValueError, match="duplicate"):
        AssessmentOutput.model_validate(output).validate_context(
            hypothesis_ids={"H1", "H2"}, evidence_ids={"E1"}
        )


def test_self_relation_and_cross_task_reference_are_rejected() -> None:
    output = AssessmentOutput.model_validate(_assessment()).model_dump()
    relation: dict[str, object] = {
        "from_hypothesis_id": "H1",
        "to_hypothesis_id": "H1",
        "relation_type": "causal_link",
        "explanation": "非法自关系。",
        "evidence_ids": [],
    }
    output["hypothesis_relations"] = [relation]
    with pytest.raises(ValueError, match="duplicate"):
        AssessmentOutput.model_validate(output).validate_context(
            hypothesis_ids={"H1", "H2"}, evidence_ids={"E1"}
        )
    relation["to_hypothesis_id"] = "OTHER_TASK_H"
    with pytest.raises(ValueError, match="unknown hypothesis"):
        AssessmentOutput.model_validate(output).validate_context(
            hypothesis_ids={"H1", "H2"}, evidence_ids={"E1"}
        )


@pytest.mark.parametrize(
    ("status", "cause", "reason"),
    [
        ("confirmed", None, "root_cause_confirmed"),
        ("confirmed", "   ", "root_cause_confirmed"),
        ("confirmed", "具体原因", "budget_exhausted"),
        ("unconfirmed", "仅为疑似原因", None),
        ("unconfirmed", None, "root_cause_confirmed"),
        ("unconfirmed", None, "execution_error"),
    ],
)
def test_incident_conclusion_rejects_inconsistent_confirmation(
    status: str, cause: str | None, reason: str | None
) -> None:
    with pytest.raises(ValidationError):
        IncidentConclusion.model_validate(
            {
                "conclusion_status": status,
                "root_cause": cause,
                "stop_reason": reason,
                "explanation": "模型结构校验不代替因果语义验证。",
            }
        )


def test_final_analysis_must_finish_but_can_leave_stop_fact_to_program() -> None:
    output = AssessmentOutput.model_validate(_assessment())
    with pytest.raises(ValueError, match="final analysis"):
        output.validate_context(
            hypothesis_ids={"H1", "H2"}, evidence_ids={"E1"}, final_analysis=True
        )
    output.next_step = NextStep(action="finalize", reason="结束最后分析。", requests=[])
    with pytest.raises(ValueError, match="stopping fact"):
        output.validate_context(hypothesis_ids={"H1", "H2"}, evidence_ids={"E1"})
    output.validate_context(hypothesis_ids={"H1", "H2"}, evidence_ids={"E1"}, final_analysis=True)


def test_stopping_conclusion_cannot_request_more_queries() -> None:
    output = AssessmentOutput.model_validate(_assessment())
    output.incident_conclusion.stop_reason = "critical_data_unavailable"
    with pytest.raises(ValueError, match="requires finalize"):
        output.validate_context(hypothesis_ids={"H1", "H2"}, evidence_ids={"E1"})


def test_revision_is_incremental_and_cannot_write_assessment_fields() -> None:
    revision = HypothesisRevision.model_validate(
        {
            "new_hypotheses": [],
            "revised_hypotheses": [{"hypothesis_id": "H1", "statement": "细化。"}],
        }
    )
    revision.validate_context(hypothesis_ids={"H1"})
    with pytest.raises(ValueError):
        revision.validate_context(hypothesis_ids={"OTHER"})
    with pytest.raises(ValidationError):
        HypothesisRevision.model_validate(
            {
                "new_hypotheses": [{"statement": "新增。", "hypothesis_status": "supported"}],
                "revised_hypotheses": [],
            }
        )


def test_business_field_sets_are_exact_and_execution_has_only_terminal_status() -> None:
    hypothesis = Hypothesis(
        hypothesis_id="H1",
        statement="有待验证的具体原因。",
        hypothesis_status="pending",
        assessment="待评估。",
        evidence_links=[],
        gaps=[],
    )
    assert len(hypothesis.model_dump()) == 6
    evidence = Evidence(evidence_id="E1", query_id="Q1", kind="change", data={"records": []})
    assert set(evidence.model_dump()) == {"evidence_id", "query_id", "kind", "data"}
    record: dict[str, object] = {
        "query_id": "Q1",
        "hypothesis_ids": [],
        "question": "查什么。",
        "tool_name": "SearchLog",
        "arguments": {},
        "status": "succeeded",
        "status_reason": "空结果亦是成功。",
    }
    assert len(QueryRecord.model_validate(record).model_dump()) == 7
    for status in ("planned", "running", "cancelled"):
        with pytest.raises(ValidationError):
            QueryRecord.model_validate({**record, "status": status})
    with pytest.raises(ValidationError, match="locator"):
        Evidence.model_validate({**evidence.model_dump(), "locator": "row1"})


def test_query_plan_requires_information_and_obeys_available_budget() -> None:
    with pytest.raises(ValidationError):
        QueryPlan(calls=[], unmet_requests=[])
    plan = QueryPlan.model_validate(
        {
            "calls": [
                {
                    "hypothesis_ids": [],
                    "question": "先采证。",
                    "tool_name": "SearchLog",
                    "arguments": {},
                }
            ],
            "unmet_requests": [],
        }
    )
    plan.validate_context(hypothesis_ids=[], tool_names={"SearchLog"}, max_calls=1)
    with pytest.raises(ValueError, match="unavailable tool"):
        plan.validate_context(hypothesis_ids=[], tool_names=[], max_calls=1)
    with pytest.raises(ValueError, match="budget"):
        plan.validate_context(hypothesis_ids=[], tool_names={"SearchLog"}, max_calls=0)
    unmet = QueryPlan.model_validate(
        {
            "calls": [],
            "unmet_requests": [
                {"hypothesis_ids": [], "requirement": "获取配置。", "reason": "无工具。"}
            ],
        }
    )
    unmet.validate_context(hypothesis_ids=[], tool_names=[], max_calls=0)


def test_finalize_does_not_contain_requests() -> None:
    with pytest.raises(ValidationError):
        NextStep.model_validate(
            {
                "action": "finalize",
                "reason": "已停止。",
                "requests": [{"hypothesis_ids": [], "requirement": "不应补查。"}],
            }
        )


def test_public_result_has_exact_fields_and_resolves_actual_queries() -> None:
    payload: dict[str, object] = {
        "engine": "hypothesis-driven-v1",
        "mode": "mock",
        "hypotheses": [],
        "hypothesis_relations": [],
        "incident_conclusion": {
            "conclusion_status": "unconfirmed",
            "root_cause": None,
            "stop_reason": None,
            "explanation": "尚在调查。",
        },
        "query_records": [
            {
                "query_id": "Q1",
                "hypothesis_ids": [],
                "question": "日志。",
                "tool_name": "SearchLog",
                "arguments": {},
                "status": "succeeded",
                "status_reason": "已获取。",
            }
        ],
        "tool_evidence": [
            {"evidence_id": "E1", "query_id": "Q1", "kind": "log", "data": {"records": []}}
        ],
        "unmet_requests": [],
        "unassessed_evidence_ids": ["E1"],
        "assessment_is_current": False,
        "budget": {
            "rounds_used": 1,
            "tool_calls_used": 1,
            "reserved_tool_calls": 0,
            "unknown_tool_calls": 0,
            "internal_steps_used": 0,
            "max_rounds": 5,
            "max_tool_calls": 20,
            "max_internal_steps": 2,
            "started_at": "2026-10-31T00:00:00Z",
            "exploration_deadline": "2026-10-31T00:06:30Z",
            "analysis_deadline": "2026-10-31T00:07:30Z",
            "deadline": "2026-10-31T00:08:00Z",
        },
    }
    result = DiagnosisResult.model_validate(payload)
    result.validate_references()
    assert len(result.model_dump()) == 11
    result.tool_evidence[0].query_id = "OTHER"
    with pytest.raises(ValueError, match="unknown query"):
        result.validate_references()
    with pytest.raises(ValidationError, match="confidence"):
        DiagnosisResult.model_validate({**payload, "confidence": 0.9})
