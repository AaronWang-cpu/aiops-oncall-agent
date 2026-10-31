"""Persistable call accounting and non-renewable diagnosis phase deadlines."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Literal, Protocol

from pydantic import Field, model_validator

from super_ai.aiops.diagnosis_config import DiagnosisConfig
from super_ai.aiops.diagnosis_models import DiagnosisBudget, DiagnosisModel

logger = logging.getLogger(__name__)
TimePhase = Literal["exploration", "analysis", "report"]
CallState = Literal["reserved", "dispatched", "completed", "interrupted", "unknown", "released"]
BatchState = Literal["reserved", "dispatched", "completed", "unknown"]


class BudgetExpired(RuntimeError):
    """No time remains for the requested phase."""


class BudgetUnavailable(RuntimeError):
    """No valid call, round or internal-step allocation remains."""


class DiagnosisClock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class SystemDiagnosisClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return monotonic()


class CallAllocation(DiagnosisModel):
    batch_id: str
    status: CallState


class BudgetState(DiagnosisModel):
    budget: DiagnosisBudget
    calls: dict[str, CallAllocation] = Field(default_factory=dict)
    batches: dict[str, BatchState] = Field(default_factory=dict)
    remaining_seconds: dict[TimePhase, float] = Field(
        default_factory=lambda: dict[TimePhase, float]()
    )
    saved_at: str = ""

    @model_validator(mode="after")
    def validate_allocations(self) -> BudgetState:
        used = sum(
            call.status in {"dispatched", "completed", "interrupted"}
            for call in self.calls.values()
        )
        reserved = sum(call.status == "reserved" for call in self.calls.values())
        unknown = sum(call.status == "unknown" for call in self.calls.values())
        rounds = sum(status in {"dispatched", "completed"} for status in self.batches.values())
        occupied_rounds = rounds + sum(
            status in {"reserved", "unknown"} for status in self.batches.values()
        )
        if (
            used != self.budget.tool_calls_used
            or reserved != self.budget.reserved_tool_calls
            or unknown != self.budget.unknown_tool_calls
            or rounds != self.budget.rounds_used
            or used + reserved + unknown > self.budget.max_tool_calls
            or occupied_rounds > self.budget.max_rounds
        ):
            raise ValueError("Persisted call allocations and budget counters disagree.")
        if any(
            call.batch_id not in self.batches and call.status != "released"
            for call in self.calls.values()
        ):
            raise ValueError("Call allocation refers to an unknown batch.")
        if any(seconds < 0 for seconds in self.remaining_seconds.values()):
            raise ValueError("Persisted phase time cannot be negative.")
        return self


class DiagnosticBudgetController:
    def __init__(self, state: BudgetState, *, clock: DiagnosisClock | None = None) -> None:
        self.state = state
        self.clock = clock or SystemDiagnosisClock()
        self._baseline_time = self.clock.now()
        self._baseline_tick = self.clock.monotonic()
        self._remaining: dict[TimePhase, float] = {}
        self._clock_warning_emitted = False
        downtime = (
            max(0.0, (self._baseline_time - _date(state.saved_at)).total_seconds())
            if state.saved_at
            else 0.0
        )
        for phase, deadline in self._deadlines().items():
            remaining = max(0.0, (_date(deadline) - self._baseline_time).total_seconds())
            saved_remaining = state.remaining_seconds.get(phase)
            self._remaining[phase] = (
                min(remaining, max(0.0, saved_remaining - downtime))
                if saved_remaining is not None
                else remaining
            )

    @classmethod
    def start(
        cls, config: DiagnosisConfig, *, clock: DiagnosisClock | None = None
    ) -> DiagnosticBudgetController:
        selected_clock = clock or SystemDiagnosisClock()
        started = selected_clock.now()
        exploration = started + timedelta(seconds=config.investigation_seconds)
        analysis = exploration + timedelta(seconds=config.final_analysis_seconds)
        end = analysis + timedelta(seconds=config.report_seconds)
        state = BudgetState(
            budget=DiagnosisBudget(
                rounds_used=0,
                tool_calls_used=0,
                reserved_tool_calls=0,
                unknown_tool_calls=0,
                internal_steps_used=0,
                max_rounds=config.max_rounds,
                max_tool_calls=config.max_tool_calls,
                max_internal_steps=config.max_internal_steps,
                started_at=started.isoformat(),
                exploration_deadline=exploration.isoformat(),
                analysis_deadline=analysis.isoformat(),
                deadline=end.isoformat(),
            )
        )
        return cls(state, clock=selected_clock)

    def remaining(self, phase: TimePhase) -> float:
        elapsed = max(0.0, self.clock.monotonic() - self._baseline_tick)
        wall_elapsed = (self.clock.now() - self._baseline_time).total_seconds()
        if abs(wall_elapsed - elapsed) > 5 and not self._clock_warning_emitted:
            logger.warning("Diagnostic clock changed; persisted time limits will not be renewed.")
            self._clock_warning_emitted = True
        wall_remaining = (_date(self._deadlines()[phase]) - self.clock.now()).total_seconds()
        return max(0.0, min(wall_remaining, self._remaining[phase] - elapsed))

    def timeout(self, phase: TimePhase, limit_seconds: float) -> float:
        remaining = self.remaining(phase)
        if remaining <= 0:
            raise BudgetExpired(phase)
        return min(remaining, limit_seconds)

    def can_query(self) -> bool:
        budget = self.state.budget
        occupied = budget.tool_calls_used + budget.reserved_tool_calls + budget.unknown_tool_calls
        return (
            self.remaining("exploration") > 0
            and occupied < budget.max_tool_calls
            and self._round_occupancy() < budget.max_rounds
        )

    def reserve_call(self, *, query_id: str, batch_id: str) -> None:
        if query_id in self.state.calls:
            raise BudgetUnavailable("Call identity has already been allocated.")
        self.timeout("exploration", 1.0)
        budget = self.state.budget
        if (
            budget.tool_calls_used + budget.reserved_tool_calls + budget.unknown_tool_calls
            >= budget.max_tool_calls
        ):
            raise BudgetUnavailable("Tool-call budget exhausted.")
        if batch_id not in self.state.batches:
            if self._round_occupancy() >= budget.max_rounds:
                raise BudgetUnavailable("Round budget exhausted.")
            self.state.batches[batch_id] = "reserved"
        elif self.state.batches[batch_id] not in {"reserved", "dispatched"}:
            raise BudgetUnavailable("A closed batch cannot dispatch new calls.")
        self.state.calls[query_id] = CallAllocation(batch_id=batch_id, status="reserved")
        budget.reserved_tool_calls += 1

    def mark_dispatched(self, query_id: str) -> None:
        call = self.state.calls[query_id]
        if call.status != "reserved":
            raise BudgetUnavailable("Only a reserved call can be dispatched.")
        self.timeout("exploration", 1.0)
        call.status = "dispatched"
        self.state.budget.reserved_tool_calls -= 1
        self.state.budget.tool_calls_used += 1
        if self.state.batches[call.batch_id] == "reserved":
            self.state.batches[call.batch_id] = "dispatched"
            self.state.budget.rounds_used += 1

    def complete_call(self, query_id: str) -> None:
        call = self.state.calls[query_id]
        if call.status != "dispatched":
            raise BudgetUnavailable("A query outcome requires a dispatched call.")
        call.status = "completed"

    def release_unstarted(self, query_id: str, *, confirmed_not_sent: bool) -> None:
        call = self.state.calls[query_id]
        if not confirmed_not_sent or call.status != "reserved":
            raise BudgetUnavailable("Unknown or dispatched calls cannot release budget.")
        call.status = "released"
        self.state.budget.reserved_tool_calls -= 1
        self._close_empty_batch(call.batch_id)

    def recover_interrupted(self) -> list[str]:
        interrupted: list[str] = []
        for query_id, call in self.state.calls.items():
            if call.status not in {"reserved", "dispatched"}:
                continue
            if call.status == "reserved":
                self.state.budget.reserved_tool_calls -= 1
                self.state.budget.unknown_tool_calls += 1
                call.status = "unknown"
            else:
                call.status = "interrupted"
            interrupted.append(query_id)
        for batch_id in self.state.batches:
            calls = [call for call in self.state.calls.values() if call.batch_id == batch_id]
            if any(call.status in {"completed", "interrupted"} for call in calls):
                continue
            if any(call.status == "unknown" for call in calls):
                self.state.batches[batch_id] = "unknown"
        return interrupted

    def finish_batch(self, batch_id: str) -> None:
        calls = [call for call in self.state.calls.values() if call.batch_id == batch_id]
        if any(call.status in {"reserved", "dispatched"} for call in calls):
            raise BudgetUnavailable("Batch still has uncommitted outcomes.")
        if any(call.status in {"completed", "interrupted"} for call in calls):
            self.state.batches[batch_id] = "completed"
            self.state.budget.internal_steps_used = 0
        else:
            self._close_empty_batch(batch_id)

    def consume_internal_step(self) -> None:
        self.timeout("analysis", 1.0)
        budget = self.state.budget
        if budget.internal_steps_used >= budget.max_internal_steps:
            raise BudgetUnavailable("Internal-step budget exhausted.")
        budget.internal_steps_used += 1

    def snapshot(self) -> BudgetState:
        self.state.remaining_seconds = {phase: self.remaining(phase) for phase in self._deadlines()}
        self.state.saved_at = self.clock.now().isoformat()
        return self.state.model_copy(deep=True)

    def _round_occupancy(self) -> int:
        return self.state.budget.rounds_used + sum(
            status in {"reserved", "unknown"} for status in self.state.batches.values()
        )

    def _close_empty_batch(self, batch_id: str) -> None:
        calls = [call for call in self.state.calls.values() if call.batch_id == batch_id]
        if calls and all(call.status == "released" for call in calls):
            self.state.batches.pop(batch_id, None)

    def _deadlines(self) -> dict[TimePhase, str]:
        budget = self.state.budget
        return {
            "exploration": budget.exploration_deadline,
            "analysis": budget.analysis_deadline,
            "report": budget.deadline,
        }


def _date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Persisted diagnosis deadlines must have an explicit timezone.")
    return parsed.astimezone(timezone.utc)
