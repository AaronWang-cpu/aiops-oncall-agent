from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from super_ai.aiops.diagnosis_budget import BudgetState, DiagnosticBudgetController
from super_ai.aiops.diagnosis_config import DiagnosisConfig
from super_ai.aiops.diagnosis_recovery import plan_diagnostic_recovery
from super_ai.memory.repositories import JsonDict


class FakeClock:
    def __init__(self) -> None:
        self.wall = datetime(2026, 10, 31, tzinfo=timezone.utc)
        self.tick = 0.0

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.tick

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.tick += seconds


def initial_state(clock: FakeClock) -> JsonDict:
    budget = DiagnosticBudgetController.start(DiagnosisConfig(), clock=clock)
    return {
        "runtime": {
            **budget.snapshot().model_dump(mode="json"),
            "revision": 3,
            "next_node": "build_queries",
            "operations": {},
        },
        "working_state": {"hypotheses": [], "evidence_ids": []},
        "last_valid_assessment": None,
    }


@pytest.mark.parametrize(
    "phase",
    [
        "build_queries",
        "revise_hypotheses",
        "assess_hypotheses",
    ],
)
def test_interrupted_core_model_goes_to_program_failure_without_replay(phase: str) -> None:
    clock = FakeClock()
    checkpoint = initial_state(clock)
    runtime = cast(JsonDict, checkpoint["runtime"])
    runtime["operations"] = {"M1": {"kind": "model", "phase": phase, "status": "reserved"}}
    runtime["next_node"] = phase
    decision = plan_diagnostic_recovery(checkpoint, clock=clock)
    assert decision.next_node == "finalize"
    assert decision.failure_reason is not None
    assert cast(JsonDict, decision.checkpoint["runtime"])["final_status"] == "failed"
    assert decision.interrupted_queries == ()
    assert cast(JsonDict, checkpoint["runtime"])["next_node"] == phase


def test_interrupted_report_goes_directly_to_fallback_without_failure() -> None:
    clock = FakeClock()
    checkpoint = initial_state(clock)
    runtime = cast(JsonDict, checkpoint["runtime"])
    runtime["operations"] = {"R1": {"kind": "model", "phase": "report", "status": "dispatched"}}
    runtime["next_node"] = "report"
    runtime["final_status"] = "succeeded"
    decision = plan_diagnostic_recovery(checkpoint, clock=clock)
    assert decision.next_node == "report"
    assert decision.report_fallback
    assert decision.failure_reason is None
    assert cast(JsonDict, decision.checkpoint["runtime"])["final_status"] == "succeeded"


@pytest.mark.parametrize("dispatched", [False, True])
def test_interrupted_tool_is_not_replayed_or_refunded(dispatched: bool) -> None:
    clock = FakeClock()
    budget = DiagnosticBudgetController.start(DiagnosisConfig(), clock=clock)
    budget.reserve_call(query_id="Q1", batch_id="B1")
    if dispatched:
        budget.mark_dispatched("Q1")
    query: JsonDict = {
        "query_id": "Q1",
        "hypothesis_ids": [],
        "question": "Inspect checkout logs",
        "tool_name": "SearchLog",
        "arguments": {"service": "checkout"},
    }
    checkpoint: JsonDict = {
        "runtime": {
            **budget.snapshot().model_dump(mode="json"),
            "revision": 2,
            "next_node": "execute_queries",
            "operations": {
                "Q1": {
                    "kind": "tool",
                    "phase": "execute_queries",
                    "query": query,
                    "status": "dispatched" if dispatched else "reserved",
                }
            },
        },
        "working_state": {"hypotheses": [], "evidence_ids": []},
        "last_valid_assessment": None,
    }
    clock.advance(10)
    decision = plan_diagnostic_recovery(checkpoint, clock=clock)
    assert decision.next_node == "execute_queries"
    assert len(decision.interrupted_queries) == 1
    assert decision.interrupted_queries[0].status == "failed"
    assert "not replayed" in decision.interrupted_queries[0].status_reason
    runtime = cast(JsonDict, decision.checkpoint["runtime"])
    state = BudgetState.model_validate(
        {
            name: runtime[name]
            for name in (
                "budget",
                "calls",
                "batches",
                "remaining_seconds",
                "saved_at",
            )
        }
    )
    assert state.budget.reserved_tool_calls == 0
    assert state.budget.tool_calls_used == int(dispatched)
    assert state.budget.unknown_tool_calls == int(not dispatched)
    assert state.budget.rounds_used == int(dispatched)
    assert state.budget.deadline == budget.state.budget.deadline
    assert state.remaining_seconds["exploration"] == 380


@pytest.mark.parametrize(
    "node",
    [
        "build_queries",
        "execute_queries",
        "revise_hypotheses",
        "assess_hypotheses",
        "report",
    ],
)
def test_valid_committed_node_and_assessment_are_restored(node: str) -> None:
    clock = FakeClock()
    checkpoint = initial_state(clock)
    runtime = cast(JsonDict, checkpoint["runtime"])
    runtime["next_node"] = node
    runtime["operations"] = {"M1": {"kind": "model", "phase": node, "status": "completed"}}
    checkpoint["last_valid_assessment"] = {"hypothesis_relations": [], "step_sequence": 3}
    decision = plan_diagnostic_recovery(checkpoint, clock=clock)
    assert decision.next_node == node
    assert decision.failure_reason is None
    assert decision.interrupted_queries == ()
    assert decision.checkpoint["last_valid_assessment"] == checkpoint["last_valid_assessment"]


@pytest.mark.parametrize(
    "seconds,expected,fallback",
    [
        (390, "assess_hypotheses", False),
        (450, "finalize", False),
        (480, "finalize", True),
    ],
)
def test_recovery_uses_original_phase_deadlines(
    seconds: int,
    expected: str,
    fallback: bool,
) -> None:
    clock = FakeClock()
    checkpoint = initial_state(clock)
    checkpoint["working_state"] = {"hypotheses": [{"hypothesis_id": "H1"}]}
    clock.advance(seconds)
    decision = plan_diagnostic_recovery(checkpoint, clock=clock)
    assert decision.next_node == expected
    assert decision.report_fallback == fallback
    assert cast(JsonDict, decision.checkpoint["runtime"])["budget_stop"] is True


def test_cancelled_recovery_goes_to_program_finalize() -> None:
    clock = FakeClock()
    checkpoint = initial_state(clock)
    decision = plan_diagnostic_recovery(checkpoint, clock=clock, cancelled=True)
    assert decision.next_node == "finalize"
    assert decision.report_fallback
    assert cast(JsonDict, decision.checkpoint["runtime"])["final_status"] == "cancelled"


def test_terminal_recovery_has_no_more_work() -> None:
    clock = FakeClock()
    checkpoint = initial_state(clock)
    cast(JsonDict, checkpoint["runtime"])["next_node"] = "end"
    decision = plan_diagnostic_recovery(checkpoint, clock=clock)
    assert decision.checkpoint == checkpoint
    assert decision.interrupted_queries == ()
    assert decision.next_node == "end"


def test_invalid_node_is_not_guessed() -> None:
    clock = FakeClock()
    checkpoint = initial_state(clock)
    cast(JsonDict, checkpoint["runtime"])["next_node"] = "old-unknown-node"
    with pytest.raises(ValueError, match="Invalid persisted"):
        plan_diagnostic_recovery(checkpoint, clock=clock)
