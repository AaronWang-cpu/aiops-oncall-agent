from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from super_ai.aiops.diagnosis_budget import (
    BudgetExpired,
    BudgetUnavailable,
    DiagnosticBudgetController,
)
from super_ai.aiops.diagnosis_config import DiagnosisConfig


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


def test_fifth_batch_allows_all_calls_but_no_sixth_batch() -> None:
    budget = DiagnosticBudgetController.start(DiagnosisConfig(), clock=FakeClock())
    for batch in range(5):
        for call in range(4):
            query_id = f"Q{batch}-{call}"
            budget.reserve_call(query_id=query_id, batch_id=f"B{batch}")
            budget.mark_dispatched(query_id)
            budget.complete_call(query_id)
        budget.finish_batch(f"B{batch}")
    assert budget.state.budget.rounds_used == 5
    assert budget.state.budget.tool_calls_used == 20
    assert budget.state.budget.reserved_tool_calls == 0
    assert not budget.can_query()
    with pytest.raises(BudgetUnavailable, match="Tool-call budget exhausted"):
        budget.reserve_call(query_id="Q21", batch_id="B6")
    assert budget.timeout("analysis", 60) == 60


def test_recovery_preserves_known_counts_and_unknown_occupancy() -> None:
    budget = DiagnosticBudgetController.start(DiagnosisConfig(), clock=FakeClock())
    budget.reserve_call(query_id="Q1", batch_id="B1")
    budget.mark_dispatched("Q1")
    budget.reserve_call(query_id="Q2", batch_id="B1")
    assert budget.recover_interrupted() == ["Q1", "Q2"]
    assert budget.state.calls["Q1"].status == "interrupted"
    assert budget.state.calls["Q2"].status == "unknown"
    assert budget.state.budget.tool_calls_used == 1
    assert budget.state.budget.rounds_used == 1
    assert budget.state.budget.unknown_tool_calls == 1
    assert budget.state.budget.reserved_tool_calls == 0
    assert budget.recover_interrupted() == []
    budget.finish_batch("B1")
    with pytest.raises(BudgetUnavailable, match="already been allocated"):
        budget.reserve_call(query_id="Q1", batch_id="B2")
    with pytest.raises(BudgetUnavailable, match="cannot release"):
        budget.release_unstarted("Q2", confirmed_not_sent=True)


def test_unknown_only_batches_conservatively_occupy_rounds() -> None:
    budget = DiagnosticBudgetController.start(DiagnosisConfig(), clock=FakeClock())
    for index in range(5):
        budget.reserve_call(query_id=f"Q{index}", batch_id=f"B{index}")
        budget.recover_interrupted()
    assert budget.state.budget.tool_calls_used == 0
    assert budget.state.budget.rounds_used == 0
    assert budget.state.budget.unknown_tool_calls == 5
    assert not budget.can_query()
    with pytest.raises(BudgetUnavailable, match="Round budget exhausted"):
        budget.reserve_call(query_id="Q6", batch_id="B6")


def test_only_proven_unsent_calls_release_reservation() -> None:
    budget = DiagnosticBudgetController.start(DiagnosisConfig(), clock=FakeClock())
    budget.reserve_call(query_id="Q1", batch_id="B1")
    with pytest.raises(BudgetUnavailable, match="cannot release"):
        budget.release_unstarted("Q1", confirmed_not_sent=False)
    budget.release_unstarted("Q1", confirmed_not_sent=True)
    assert budget.state.budget.reserved_tool_calls == 0
    assert budget.state.budget.rounds_used == 0
    assert budget.state.batches == {}
    budget.reserve_call(query_id="Q2", batch_id="B1")
    budget.mark_dispatched("Q2")
    with pytest.raises(BudgetUnavailable, match="cannot release"):
        budget.release_unstarted("Q2", confirmed_not_sent=True)
    budget.complete_call("Q2")
    budget.finish_batch("B1")
    assert budget.state.budget.tool_calls_used == 1


@pytest.mark.parametrize(
    "elapsed,phase", [(390, "exploration"), (450, "analysis"), (480, "report")]
)
def test_deadlines_stop_new_work(elapsed: int, phase: str) -> None:
    clock = FakeClock()
    budget = DiagnosticBudgetController.start(DiagnosisConfig(), clock=clock)
    clock.advance(elapsed)
    if phase == "exploration":
        assert not budget.can_query()
        with pytest.raises(BudgetExpired):
            budget.reserve_call(query_id="Q1", batch_id="B1")
        assert budget.timeout("analysis", 60) == 60
    elif phase == "analysis":
        with pytest.raises(BudgetExpired):
            budget.timeout("analysis", 60)
        assert budget.timeout("report", 60) == 30
    else:
        with pytest.raises(BudgetExpired):
            budget.timeout("report", 60)


def test_restore_deducts_downtime_and_caps_clock_rollback() -> None:
    clock = FakeClock()
    budget = DiagnosticBudgetController.start(DiagnosisConfig(), clock=clock)
    clock.advance(375)
    assert budget.timeout("exploration", 60) == 15
    snapshot = budget.snapshot()
    clock.advance(10)
    restored = DiagnosticBudgetController(snapshot, clock=clock)
    assert restored.remaining("exploration") == 5
    assert restored.state.budget.deadline == budget.state.budget.deadline
    clock.wall -= timedelta(hours=1)
    clock.tick += 5
    assert restored.remaining("exploration") == 0
    assert restored.remaining("analysis") == 60


def test_snapshot_is_independent_and_failure_never_refunds_calls() -> None:
    clock = FakeClock()
    budget = DiagnosticBudgetController.start(DiagnosisConfig(), clock=clock)
    budget.reserve_call(query_id="Q1", batch_id="B1")
    snapshot = budget.snapshot()
    budget.mark_dispatched("Q1")
    budget.complete_call("Q1")
    budget.finish_batch("B1")
    assert snapshot.calls["Q1"].status == "reserved"
    assert snapshot.budget.tool_calls_used == 0
    assert budget.state.budget.tool_calls_used == 1


def test_internal_budget_does_not_disable_queries_and_resets_after_batch() -> None:
    budget = DiagnosticBudgetController.start(DiagnosisConfig(), clock=FakeClock())
    budget.consume_internal_step()
    budget.consume_internal_step()
    with pytest.raises(BudgetUnavailable, match="Internal-step budget exhausted"):
        budget.consume_internal_step()
    assert budget.can_query()
    budget.reserve_call(query_id="Q1", batch_id="B1")
    budget.mark_dispatched("Q1")
    budget.complete_call("Q1")
    budget.finish_batch("B1")
    assert budget.state.budget.internal_steps_used == 0
    budget.consume_internal_step()
