"""Classify durable recovery boundaries without invoking a model or external tool."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import cast

from super_ai.aiops.diagnosis_budget import (
    BudgetState,
    DiagnosisClock,
    DiagnosticBudgetController,
)
from super_ai.aiops.diagnosis_models import QueryRecord
from super_ai.memory.repositories import JsonDict

NODES = {
    "prepare_context",
    "build_queries",
    "execute_queries",
    "revise_hypotheses",
    "assess_hypotheses",
    "finalize",
    "report",
    "end",
}


@dataclass(frozen=True, slots=True)
class DiagnosticRecoveryDecision:
    checkpoint: JsonDict
    interrupted_queries: tuple[QueryRecord, ...]
    failure_reason: str | None
    report_fallback: bool

    @property
    def next_node(self) -> str:
        return str(_mapping(self.checkpoint["runtime"])["next_node"])


def plan_diagnostic_recovery(
    checkpoint: JsonDict,
    *,
    clock: DiagnosisClock | None = None,
    cancelled: bool = False,
) -> DiagnosticRecoveryDecision:
    candidate = deepcopy(checkpoint)
    runtime = _mapping(candidate["runtime"])
    next_node = runtime.get("next_node")
    if not isinstance(next_node, str) or next_node not in NODES:
        raise ValueError("Invalid persisted diagnostic recovery node.")
    if next_node == "end":
        return DiagnosticRecoveryDecision(candidate, (), None, True)

    controller: DiagnosticBudgetController | None = None
    if "budget" in runtime:
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
                if name in runtime
            }
        )
        controller = DiagnosticBudgetController(state, clock=clock)
        controller.recover_interrupted()
        runtime.update(controller.snapshot().model_dump(mode="json"))

    interrupted: list[QueryRecord] = []
    failure: str | None = None
    fallback = False
    operations = _mapping(runtime.get("operations", {}))
    for operation_id, raw_operation in operations.items():
        operation = _mapping(raw_operation)
        if operation.get("status") not in {"reserved", "dispatched", "interrupted", "unknown"}:
            continue
        if operation.get("kind") == "tool":
            unknown = operation.get("status") in {"reserved", "unknown"}
            reason = (
                "Service interruption: dispatch is unknown; "
                "reservation retained, call not replayed."
                if unknown
                else "Service interruption: dispatched call has no committed outcome; "
                "call not replayed."
            )
            interrupted.append(
                QueryRecord.model_validate(
                    {
                        **_mapping(operation["query"]),
                        "query_id": operation_id,
                        "status": "failed",
                        "status_reason": reason,
                    }
                )
            )
            operation["status"] = "unknown" if unknown else "interrupted"
        elif operation.get("kind") == "model":
            operation["status"] = "interrupted"
            if operation.get("phase") == "report":
                fallback = True
                runtime["next_node"] = "report"
            else:
                failure = "A core diagnostic model request was interrupted before valid commit."
                runtime["next_node"] = "finalize"
        else:
            raise ValueError("Invalid persisted diagnostic operation kind.")
        operations[operation_id] = operation

    if failure is not None:
        runtime["final_status"] = "failed"
        runtime["failure_reason"] = failure
        runtime["next_node"] = "finalize"
    if cancelled:
        runtime["final_status"] = "cancelled"
        runtime["next_node"] = "finalize"
        fallback = True
    if controller is not None and not cancelled and failure is None:
        if controller.remaining("analysis") <= 0:
            runtime["next_node"] = "report" if runtime["next_node"] == "report" else "finalize"
            fallback = fallback or controller.remaining("report") <= 0
            runtime["budget_stop"] = True
        elif controller.remaining("exploration") <= 0 and next_node not in {"finalize", "report"}:
            working = _mapping(candidate.get("working_state", {}))
            runtime["next_node"] = "assess_hypotheses" if working.get("hypotheses") else "finalize"
            runtime["budget_stop"] = True
    runtime["operations"] = operations
    runtime["report_fallback"] = fallback
    candidate["runtime"] = runtime
    return DiagnosticRecoveryDecision(candidate, tuple(interrupted), failure, fallback)


def _mapping(value: object) -> JsonDict:
    if not isinstance(value, Mapping):
        raise ValueError("Persisted diagnostic state must contain JSON objects.")
    return dict(cast(Mapping[str, object], value))
