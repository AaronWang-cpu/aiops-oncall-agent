"""Short, fenced SQLite transactions for durable diagnostic graph transitions."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from hashlib import sha256
from typing import cast

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from super_ai.aiops.diagnosis_budget import BudgetState
from super_ai.aiops.diagnosis_models import DiagnosisResult, IncidentConclusion, QueryRecord
from super_ai.error_catalog import ERROR_DEFINITIONS
from super_ai.memory.models import (
    AgentToolCallAuditModel,
    BackgroundJobEventModel,
    BackgroundJobModel,
    DiagnosticEvidenceModel,
    DiagnosticReportModel,
    DiagnosticStepModel,
    DiagnosticTaskModel,
    GraphCheckpointModel,
    ReportEvidenceLinkModel,
    utc_now,
)
from super_ai.memory.repositories import (
    DiagnosticCommitResult,
    DiagnosticExecutionScope,
    DiagnosticLeaseLost,
    DiagnosticNodeWrite,
    DiagnosticQueryWrite,
    DiagnosticReservationWrite,
    DiagnosticStateConflict,
    DiagnosticTerminalWrite,
    JsonDict,
    TenantScopeError,
)

NAMESPACE = "hypothesis-driven-v1"
Mutation = Callable[[AsyncSession, DiagnosticTaskModel, BackgroundJobModel], Awaitable[None]]


class SQLiteDiagnosticRuntimeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_state(self, *, owner_user_id: str, task_id: str) -> JsonDict | None:
        async with self._session_factory() as session:
            task = await session.get(DiagnosticTaskModel, task_id)
            if task is None or task.owner_user_id != owner_user_id:
                return None
            row = await session.get(GraphCheckpointModel, _id(task_id, "current"))
            return _copy(row.checkpoint_payload) if row is not None else None

    async def load_evidence(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        evidence_ids: list[str],
    ) -> list[JsonDict]:
        if len(set(evidence_ids)) != len(evidence_ids):
            raise DiagnosticStateConflict("Evidence references must be unique.")
        async with self._session_factory() as session:
            task = await session.get(DiagnosticTaskModel, task_id)
            if task is None or task.owner_user_id != owner_user_id:
                raise TenantScopeError("Diagnostic task is not accessible.")
            result: list[JsonDict] = []
            for evidence_id in evidence_ids:
                row = await session.get(DiagnosticEvidenceModel, evidence_id)
                if (
                    row is None
                    or row.owner_user_id != owner_user_id
                    or row.task_id != task_id
                    or row.tool_call_id is None
                    or row.kind not in {"log", "metric", "change"}
                ):
                    raise TenantScopeError("Evidence is not accessible in this investigation.")
                result.append(
                    {
                        "evidence_id": row.id,
                        "query_id": row.tool_call_id,
                        "kind": row.kind,
                        "data": _copy(row.payload),
                    }
                )
        return result

    async def reserve_diagnostic_operation(
        self, *, scope: DiagnosticExecutionScope, write: DiagnosticReservationWrite
    ) -> DiagnosticCommitResult:
        checkpoint = _copy(write.checkpoint)

        async def mutate(
            session: AsyncSession, task: DiagnosticTaskModel, job: BackgroundJobModel
        ) -> None:
            if job.cancel_requested_at is not None:
                raise DiagnosticStateConflict("Cancellation prevents new diagnostic operations.")
            if write.kind == "tool":
                if write.query is None:
                    raise ValueError("Tool reservation requires query context.")
                query = write.query
                if _string(query, "query_id") != write.operation_id:
                    raise ValueError("Reservation identity does not match the query.")
                _check_budget(write.checkpoint, required=True)
                if write.stage == "dispatch":
                    audit = await session.get(AgentToolCallAuditModel, write.operation_id)
                    if (
                        audit is None
                        or audit.owner_user_id != scope.owner_user_id
                        or audit.diagnostic_task_id != scope.task_id
                        or audit.tool_name != _string(query, "tool_name")
                        or audit.arguments != _dict(query.get("arguments"))
                        or audit.status != "started"
                    ):
                        raise DiagnosticStateConflict(
                            "Dispatch does not match its reserved intent."
                        )
                else:
                    session.add(
                        AgentToolCallAuditModel(
                            id=write.operation_id,
                            owner_user_id=scope.owner_user_id,
                            chat_session_id=None,
                            diagnostic_task_id=scope.task_id,
                            tool_name=_string(query, "tool_name"),
                            status="started",
                            arguments=_dict(query.get("arguments")),
                            result_summary=None,
                            error_message=None,
                            started_at=utc_now(),
                            completed_at=None,
                            duration_ms=None,
                        )
                    )
            runtime = _dict(checkpoint.get("runtime"))
            operations = _dict(runtime.get("operations", {}))
            if write.stage == "dispatch":
                operation = _dict(operations.get(write.operation_id))
                if operation.get("status") != "reserved":
                    raise DiagnosticStateConflict("Operation is not available for dispatch.")
                operation["status"] = "dispatched"
            else:
                if write.operation_id in operations:
                    raise DiagnosticStateConflict("Operation identity was already reserved.")
                operation: JsonDict = {
                    "kind": write.kind,
                    "phase": write.phase,
                    "status": "reserved",
                    "query": _copy(write.query) if write.query is not None else None,
                }
            operations[write.operation_id] = operation
            runtime["operations"] = operations
            checkpoint["runtime"] = runtime
            await _append_events(session, job, write.events or [])
            task.status = "running"

        return await self._apply(
            scope=scope,
            key=f"{write.stage}:{write.operation_id}",
            expected_revision=write.expected_revision,
            checkpoint=checkpoint,
            fingerprint={
                "kind": write.kind,
                "phase": write.phase,
                "query": write.query,
                "events": write.events,
                "stage": write.stage,
            },
            mutate=mutate,
        )

    async def commit_diagnostic_query(
        self, *, scope: DiagnosticExecutionScope, write: DiagnosticQueryWrite
    ) -> DiagnosticCommitResult:
        QueryRecord.model_validate(write.query)
        checkpoint = _copy(write.checkpoint)

        async def mutate(
            session: AsyncSession, task: DiagnosticTaskModel, job: BackgroundJobModel
        ) -> None:
            audit = await session.get(AgentToolCallAuditModel, write.operation_id)
            if (
                audit is None
                or audit.owner_user_id != scope.owner_user_id
                or audit.diagnostic_task_id != scope.task_id
            ):
                raise TenantScopeError("Query audit is not accessible in this diagnosis.")
            query = write.query
            runtime = _dict(checkpoint.get("runtime"))
            operations = _dict(runtime.get("operations", {}))
            operation = _dict(operations.get(write.operation_id))
            reserved_query = _dict(operation.get("query"))
            if (
                _string(query, "query_id") != audit.id
                or _string(query, "tool_name") != audit.tool_name
                or _dict(query.get("arguments")) != audit.arguments
                or any(
                    query.get(key) != reserved_query.get(key)
                    for key in (
                        "hypothesis_ids",
                        "question",
                        "tool_name",
                        "arguments",
                    )
                )
            ):
                raise DiagnosticStateConflict("Query result does not match its reserved call.")
            status = _string(query, "status")
            if status not in {"succeeded", "failed"}:
                raise ValueError("Query records only accept terminal execution statuses.")
            audit.status = "completed" if status == "succeeded" else "failed"
            completed_at = utc_now()
            audit.completed_at = completed_at
            audit.duration_ms = max(
                0, int((completed_at - _utc(audit.started_at)).total_seconds() * 1000)
            )
            audit.error_message = _string(query, "status_reason") if status == "failed" else None
            audit.result_summary = json.dumps(
                {"evidenceIds": [item.evidence_id for item in write.evidence]},
                ensure_ascii=False,
            )
            for item in write.evidence:
                if item.kind not in {"log", "metric", "change"}:
                    raise ValueError("Tool evidence must be log, metric or change.")
                session.add(
                    DiagnosticEvidenceModel(
                        id=item.evidence_id,
                        owner_user_id=scope.owner_user_id,
                        task_id=scope.task_id,
                        step_id=None,
                        tool_call_id=audit.id,
                        kind=item.kind,
                        source=item.source,
                        summary=item.summary,
                        payload=_copy(item.payload),
                    )
                )
            if write.result_payload is not None:
                task.result_payload = _copy(write.result_payload)
            operation["status"] = "completed"
            operation["query"] = _copy(query)
            operation["evidence_ids"] = [item.evidence_id for item in write.evidence]
            operations[write.operation_id] = operation
            runtime["operations"] = operations
            checkpoint["runtime"] = runtime
            await _append_events(session, job, write.events)

        return await self._apply(
            scope=scope,
            key=f"query:{write.operation_id}",
            expected_revision=write.expected_revision,
            checkpoint=checkpoint,
            fingerprint={
                "query": write.query,
                "evidence": [
                    {
                        "id": item.evidence_id,
                        "kind": item.kind,
                        "payload": item.payload,
                        "source": item.source,
                        "summary": item.summary,
                    }
                    for item in write.evidence
                ],
                "events": write.events,
                "result_payload": write.result_payload,
            },
            mutate=mutate,
        )

    async def commit_diagnostic_node(
        self, *, scope: DiagnosticExecutionScope, write: DiagnosticNodeWrite
    ) -> DiagnosticCommitResult:
        checkpoint = _copy(write.checkpoint)

        async def mutate(
            session: AsyncSession, task: DiagnosticTaskModel, job: BackgroundJobModel
        ) -> None:
            sequence = (
                int(
                    await session.scalar(
                        select(func.max(DiagnosticStepModel.sequence)).where(
                            DiagnosticStepModel.task_id == scope.task_id
                        )
                    )
                    or 0
                )
                + 1
            )
            session.add(
                DiagnosticStepModel(
                    id=_id(scope.task_id, f"step:{write.operation_id}"),
                    owner_user_id=scope.owner_user_id,
                    task_id=scope.task_id,
                    sequence=sequence,
                    phase=write.phase,
                    status="completed",
                    payload=_copy(write.payload),
                )
            )
            if write.result_payload is not None:
                task.result_payload = _copy(write.result_payload)
            task.status = "running"
            runtime = _dict(checkpoint.get("runtime"))
            operations = _dict(runtime.get("operations", {}))
            if write.operation_id in operations:
                operation = _dict(operations[write.operation_id])
                if operation.get("kind") != "model":
                    raise DiagnosticStateConflict("A node cannot finish a tool operation.")
                operation["status"] = "completed"
                operations[write.operation_id] = operation
                runtime["operations"] = operations
                checkpoint["runtime"] = runtime
            await _append_events(session, job, write.events)

        return await self._apply(
            scope=scope,
            key=f"node:{write.operation_id}",
            expected_revision=write.expected_revision,
            checkpoint=checkpoint,
            fingerprint={
                "phase": write.phase,
                "payload": write.payload,
                "events": write.events,
                "result_payload": write.result_payload,
            },
            mutate=mutate,
        )

    async def finish_diagnostic_job(
        self, *, scope: DiagnosticExecutionScope, write: DiagnosticTerminalWrite
    ) -> DiagnosticCommitResult:
        checkpoint = _copy(write.checkpoint)

        async def mutate(
            session: AsyncSession, task: DiagnosticTaskModel, job: BackgroundJobModel
        ) -> None:
            status = "cancelled" if job.cancel_requested_at is not None else write.status
            content = write.content
            title = write.title
            if status == "cancelled" and write.status != "cancelled":
                title = "诊断已取消"
                content = (
                    "# 诊断报告\n\n## 诊断结论\n\n用户取消了本次调查，未执行任何处置。\n\n"
                    "## 原因与证据\n\n请查看已保存的查询及有效判断，不将未评估内容视作结论。\n\n"
                    "## 调查结果与局限\n\n取消前已取得的数据予以保留。\n\n"
                    "## 后续建议\n\n确认继续调查后新建任务。\n"
                )
            now = utc_now()
            task.status = status
            task.completed_at = now
            task.result_payload = _copy(write.result_payload)
            task.result_payload = {**task.result_payload, "executionStatus": status}
            if status == "cancelled" and "diagnosis" in task.result_payload:
                diagnosis = DiagnosisResult.model_validate(task.result_payload["diagnosis"])
                for hypothesis in diagnosis.hypotheses:
                    if hypothesis.hypothesis_status in {"pending", "investigating", "blocked"}:
                        hypothesis.hypothesis_status = "unresolved"
                if not diagnosis.assessment_is_current:
                    diagnosis.incident_conclusion = IncidentConclusion(
                        conclusion_status="unconfirmed",
                        root_cause=None,
                        stop_reason=None,
                        explanation="用户取消调查，最新内容尚未完成验证。",
                    )
                task.result_payload = {
                    **task.result_payload,
                    "diagnosis": diagnosis.model_dump(mode="json"),
                }
            runtime = _dict(checkpoint.get("runtime"))
            runtime["final_status"] = status
            runtime["next_node"] = "end"
            checkpoint["runtime"] = runtime
            job.status = status
            job.completed_at = now
            job.updated_at = now
            job.error_message = write.error_message if status == "failed" else None
            job.lease_owner = None
            job.lease_expires_at = None
            report_id = _id(scope.task_id, "report:final")
            session.add(
                DiagnosticReportModel(
                    id=report_id,
                    owner_user_id=scope.owner_user_id,
                    task_id=scope.task_id,
                    title=title,
                    content=content,
                    payload={
                        "format": "markdown",
                        "diagnosis": task.result_payload.get("diagnosis"),
                    },
                )
            )
            for evidence_id in write.evidence_ids:
                evidence = await session.get(DiagnosticEvidenceModel, evidence_id)
                if (
                    evidence is None
                    or evidence.owner_user_id != scope.owner_user_id
                    or evidence.task_id != scope.task_id
                ):
                    raise TenantScopeError("Report evidence belongs to another investigation.")
                session.add(
                    ReportEvidenceLinkModel(
                        id=_id(scope.task_id, f"link:{evidence_id}"),
                        owner_user_id=scope.owner_user_id,
                        task_id=scope.task_id,
                        report_id=report_id,
                        evidence_id=evidence_id,
                    )
                )
            events: list[JsonDict] = [
                {
                    "type": "report",
                    "report": {
                        "id": report_id,
                        "title": title,
                        "content": content,
                        "format": "markdown",
                    },
                }
            ]
            if status == "failed":
                category, http_status, message = ERROR_DEFINITIONS["SYSTEM_UNAVAILABLE"]
                events.append(
                    {
                        "type": "error",
                        "error": {
                            "code": "SYSTEM_UNAVAILABLE",
                            "category": category,
                            "httpStatus": http_status,
                            "message": message,
                        },
                    }
                )
            events.extend(
                [
                    {
                        "type": "task.status",
                        "task": {
                            "id": task.id,
                            "status": status,
                            "phase": "report",
                            "progress": 100,
                            "message": "诊断已结束。"
                            if status == "succeeded"
                            else "请查看调查局限。",
                        },
                    },
                    {
                        "type": "complete",
                        "result": _task_payload(
                            task,
                            report_id,
                            title,
                            content,
                            write.evidence_ids,
                        ),
                    },
                ]
            )
            await _append_events(session, job, events)

        return await self._apply(
            scope=scope,
            key=f"finish:{write.operation_id}",
            expected_revision=write.expected_revision,
            checkpoint=checkpoint,
            fingerprint={
                "status": write.status,
                "title": write.title,
                "content": write.content,
                "result_payload": write.result_payload,
                "evidence_ids": write.evidence_ids,
                "error_message": write.error_message,
            },
            mutate=mutate,
        )

    async def _apply(
        self,
        *,
        scope: DiagnosticExecutionScope,
        key: str,
        expected_revision: int,
        checkpoint: JsonDict,
        fingerprint: JsonDict,
        mutate: Mutation,
    ) -> DiagnosticCommitResult:
        fingerprint_text = json.dumps(
            {**fingerprint, "checkpoint": checkpoint, "expected_revision": expected_revision},
            sort_keys=True,
            allow_nan=False,
        )
        digest = sha256(fingerprint_text.encode("utf-8")).hexdigest()
        candidate = _copy(checkpoint)
        async with self._session_factory() as session, session.begin():
            # SQLite has no row-level FOR UPDATE. Acquire the writer lock before reading.
            await session.execute(text("BEGIN IMMEDIATE"))
            task = await session.get(DiagnosticTaskModel, scope.task_id)
            job = await session.get(BackgroundJobModel, scope.job_id)
            if (
                task is None
                or job is None
                or task.owner_user_id != scope.owner_user_id
                or job.owner_user_id != scope.owner_user_id
                or job.resource_type != "aiops_diagnostic"
                or job.resource_id != task.id
            ):
                raise TenantScopeError("Diagnostic task and job are not accessible.")
            current = await session.get(GraphCheckpointModel, _id(scope.task_id, "current"))
            existing = await session.get(GraphCheckpointModel, _id(scope.task_id, key))
            if existing is not None:
                if existing.metadata_json.get("fingerprint") != digest or current is None:
                    raise DiagnosticStateConflict("Operation identity has incompatible content.")
                return DiagnosticCommitResult(_copy(current.checkpoint_payload), True)
            now = utc_now()
            if (
                job.status != "running"
                or task.status in {"succeeded", "failed", "cancelled"}
                or job.lease_owner != scope.worker_id
                or job.attempt != scope.attempt
                or job.lease_expires_at is None
                or _utc(job.lease_expires_at) <= now
            ):
                raise DiagnosticLeaseLost("Diagnostic lease is no longer valid.")
            previous = _copy(current.checkpoint_payload) if current is not None else None
            revision = _revision(previous) if previous is not None else 0
            if expected_revision != revision:
                raise DiagnosticStateConflict("Diagnostic checkpoint has advanced.")
            _check_budget(candidate)
            if previous is not None:
                _check_fixed_budget(previous, candidate)
            await mutate(session, task, job)
            # finish may adjust its captured checkpoint when cancellation wins the race.
            candidate = _copy(checkpoint)
            runtime = _dict(candidate.get("runtime"))
            runtime["revision"] = revision + 1
            candidate["runtime"] = runtime
            task.updated_at = now
            if current is None:
                current = _checkpoint(scope, "current", candidate, {"active": True})
                session.add(current)
            else:
                current.checkpoint_payload = _copy(candidate)
            session.add(_checkpoint(scope, key, candidate, {"fingerprint": digest}))
            await session.flush()
        return DiagnosticCommitResult(candidate, False)


async def cancel_queued_diagnosis(session: AsyncSession, job: BackgroundJobModel) -> None:
    """Join the caller's locked cancellation transaction without loading external resources."""
    task = await session.get(DiagnosticTaskModel, job.resource_id)
    if task is None or task.owner_user_id != job.owner_user_id:
        raise TenantScopeError("Diagnostic task is not accessible.")
    now = utc_now()
    task.status = "cancelled"
    task.completed_at = now
    task.updated_at = now
    task.result_payload = {**_copy(task.result_payload), "executionStatus": "cancelled"}
    report_id = _id(task.id, "report:final")
    title = "诊断已取消"
    content = (
        "# 诊断报告\n\n## 诊断结论\n\n用户在执行前取消了任务，未确认事故根因。\n\n"
        "## 原因与证据\n\n尚未调用外部工具，没有现场查询结果。\n\n"
        "## 调查结果与局限\n\n未开始调查，也未执行处置。\n\n"
        "## 后续建议\n\n需要继续调查时，请显式创建新任务。\n"
    )
    session.add(
        DiagnosticReportModel(
            id=report_id,
            owner_user_id=task.owner_user_id,
            task_id=task.id,
            title=title,
            content=content,
            payload={"format": "markdown"},
        )
    )
    await _append_events(
        session,
        job,
        [
            {
                "type": "report",
                "report": {
                    "id": report_id,
                    "title": title,
                    "content": content,
                    "format": "markdown",
                },
            },
            {
                "type": "task.status",
                "task": {
                    "id": task.id,
                    "status": "cancelled",
                    "phase": "report",
                    "progress": 100,
                    "message": "任务在执行前已取消。",
                },
            },
            {"type": "complete", "result": _task_payload(task, report_id, title, content, [])},
        ],
    )


def _checkpoint(
    scope: DiagnosticExecutionScope, key: str, payload: JsonDict, metadata: JsonDict
) -> GraphCheckpointModel:
    return GraphCheckpointModel(
        id=_id(scope.task_id, key),
        owner_user_id=scope.owner_user_id,
        task_id=scope.task_id,
        thread_id=scope.task_id,
        checkpoint_ns=NAMESPACE,
        checkpoint_id=key,
        checkpoint_payload=_copy(payload),
        metadata_json=metadata,
    )


async def _append_events(
    session: AsyncSession, job: BackgroundJobModel, events: list[JsonDict]
) -> None:
    sequence = int(
        await session.scalar(
            select(func.max(BackgroundJobEventModel.sequence)).where(
                BackgroundJobEventModel.job_id == job.id
            )
        )
        or 0
    )
    for event in events:
        sequence += 1
        identity = _id(job.id, f"event:{sequence}")
        payload = {
            **_copy(event),
            "id": identity,
            "channel": "aiops",
            "timestamp": utc_now().isoformat(),
        }
        session.add(
            BackgroundJobEventModel(
                id=identity,
                job_id=job.id,
                owner_user_id=job.owner_user_id,
                sequence=sequence,
                payload=payload,
                created_at=utc_now(),
            )
        )


def _check_budget(checkpoint: JsonDict, *, required: bool = False) -> None:
    runtime = _dict(checkpoint.get("runtime"))
    raw = runtime.get("budget")
    if raw is None and not required:
        return
    budget = _dict(raw)
    if "calls" in runtime or "batches" in runtime:
        BudgetState.model_validate(
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
    used = _integer(budget, "tool_calls_used")
    reserved = _integer(budget, "reserved_tool_calls")
    unknown = _integer(budget, "unknown_tool_calls")
    if used + reserved + unknown > _integer(budget, "max_tool_calls"):
        raise DiagnosticStateConflict("Tool budget would be exceeded.")
    if _integer(budget, "rounds_used") > _integer(budget, "max_rounds"):
        raise DiagnosticStateConflict("Round budget would be exceeded.")
    if _integer(budget, "internal_steps_used") > _integer(budget, "max_internal_steps"):
        raise DiagnosticStateConflict("Internal budget would be exceeded.")


def _check_fixed_budget(previous: JsonDict, candidate: JsonDict) -> None:
    old = _dict(previous.get("runtime")).get("budget")
    if old is None:
        return
    before = _dict(old)
    after = _dict(_dict(candidate.get("runtime")).get("budget"))
    for name in (
        "max_rounds",
        "max_tool_calls",
        "max_internal_steps",
        "started_at",
        "exploration_deadline",
        "analysis_deadline",
        "deadline",
    ):
        if before.get(name) != after.get(name):
            raise DiagnosticStateConflict("Recovery cannot reset configured budgets or deadlines.")
    for name in ("rounds_used", "tool_calls_used"):
        if _integer(after, name) < _integer(before, name):
            raise DiagnosticStateConflict("Confirmed execution counts cannot decrease.")


def _revision(checkpoint: JsonDict) -> int:
    return _integer(_dict(checkpoint.get("runtime")), "revision")


def _integer(value: JsonDict, key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result < 0:
        raise ValueError(f"Expected nonnegative integer execution field: {key}")
    return result


def _string(value: JsonDict, key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"Expected nonempty execution field: {key}")
    return result


def _dict(value: object) -> JsonDict:
    if not isinstance(value, Mapping):
        raise ValueError("Expected diagnostic JSON object.")
    return dict(cast(Mapping[str, object], value))


def _copy(value: Mapping[str, object]) -> JsonDict:
    return _dict(json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))


def _id(parent: str, key: str) -> str:
    return "diagnostic_" + sha256(f"{parent}:{key}".encode()).hexdigest()[:40]


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _task_payload(
    task: DiagnosticTaskModel,
    report_id: str,
    title: str,
    content: str,
    evidence_ids: list[str],
) -> JsonDict:
    return {
        "id": task.id,
        "ownerUserId": task.owner_user_id,
        "status": task.status,
        "query": task.query,
        "inputPayload": _copy(task.input_payload),
        "resultPayload": _copy(task.result_payload),
        "createdAt": _utc(task.created_at).isoformat(),
        "updatedAt": utc_now().isoformat(),
        "completedAt": _utc(task.completed_at).isoformat() if task.completed_at else None,
        "reports": [
            {
                "id": report_id,
                "title": title,
                "content": content,
                "payload": {
                    "format": "markdown",
                    "diagnosis": task.result_payload.get("diagnosis"),
                },
                "evidenceIds": evidence_ids,
                "createdAt": utc_now().isoformat(),
            }
        ],
    }
