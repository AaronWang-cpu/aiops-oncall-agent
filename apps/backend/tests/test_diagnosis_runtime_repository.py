from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from super_ai.aiops.diagnosis_budget import BudgetState, DiagnosticBudgetController
from super_ai.aiops.diagnosis_config import DiagnosisConfig
from super_ai.aiops.diagnosis_recovery import plan_diagnostic_recovery
from super_ai.api.app import create_app
from super_ai.jobs.runtime import BackgroundJobContext, BackgroundJobRuntime, JobCancelled
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.diagnosis_sqlite import SQLiteDiagnosticRuntimeRepository
from super_ai.memory.extended_sqlite import SQLiteBackgroundJobRepository
from super_ai.memory.models import (
    AgentToolCallAuditModel,
    BackgroundJobEventModel,
    BackgroundJobModel,
    DiagnosticEvidenceModel,
    DiagnosticReportModel,
    DiagnosticStepModel,
    GraphCheckpointModel,
    ReportEvidenceLinkModel,
)
from super_ai.memory.repositories import (
    BackgroundJobRecord,
    DiagnosticEvidenceWrite,
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
from super_ai.memory.sqlite import SQLiteDiagnosticMemoryRepository


@dataclass
class Database:
    sessions: async_sessionmaker[AsyncSession]
    runtime: SQLiteDiagnosticRuntimeRepository
    diagnostics: SQLiteDiagnosticMemoryRepository
    jobs: SQLiteBackgroundJobRepository
    scope: DiagnosticExecutionScope


@pytest.fixture
def migrated_url(tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'diagnosis.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url


@pytest.fixture
async def database(migrated_url: str) -> AsyncIterator[Database]:
    engine = create_memory_engine(migrated_url)
    sessions = create_memory_session_factory(engine)
    diagnostics = SQLiteDiagnosticMemoryRepository(sessions)
    jobs = SQLiteBackgroundJobRepository(sessions)
    await diagnostics.create_task(
        owner_user_id="user-a",
        task_id="task-a",
        status="queued",
        query="Investigate latency",
    )
    await jobs.enqueue(
        owner_user_id="user-a",
        job_id="job-a",
        kind="aiops_diagnosis",
        resource_type="aiops_diagnostic",
        resource_id="task-a",
        max_attempts=1,
    )
    claimed = await jobs.claim_next(
        worker_id="worker-a",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    assert claimed is not None
    try:
        yield Database(
            sessions,
            SQLiteDiagnosticRuntimeRepository(sessions),
            diagnostics,
            jobs,
            DiagnosticExecutionScope("user-a", "task-a", "job-a", "worker-a", claimed.attempt),
        )
    finally:
        await engine.dispose()


def checkpoint() -> JsonDict:
    budget = DiagnosticBudgetController.start(DiagnosisConfig()).state.budget
    return {
        "runtime": {"revision": 0, "next_node": "build_queries", "budget": budget.model_dump()},
        "working_state": {"evidence_ids": []},
        "last_valid_assessment": None,
    }


def node(state: JsonDict, *, revision: int = 0, identity: str = "prepare") -> DiagnosticNodeWrite:
    return DiagnosticNodeWrite(
        operation_id=identity,
        expected_revision=revision,
        checkpoint=state,
        phase="prepare_context",
        payload={"mode": "mock"},
        events=[{"type": "task.status", "task": {"id": "task-a", "status": "running"}}],
    )


def reservation(state: JsonDict, *, revision: int = 0) -> DiagnosticReservationWrite:
    query: JsonDict = {
        "query_id": "Q1",
        "hypothesis_ids": [],
        "question": "Inspect service logs",
        "tool_name": "SearchLog",
        "arguments": {"service": "checkout"},
    }
    return DiagnosticReservationWrite(
        operation_id="Q1",
        expected_revision=revision,
        checkpoint=state,
        kind="tool",
        phase="execute_queries",
        query=query,
    )


def query_result(state: JsonDict, *, revision: int = 1) -> DiagnosticQueryWrite:
    query: JsonDict = {
        "query_id": "Q1",
        "hypothesis_ids": [],
        "question": "Inspect service logs",
        "tool_name": "SearchLog",
        "arguments": {"service": "checkout"},
        "status": "succeeded",
        "status_reason": "Returned logs",
    }
    return DiagnosticQueryWrite(
        operation_id="Q1",
        expected_revision=revision,
        checkpoint=state,
        query=query,
        evidence=[
            DiagnosticEvidenceWrite(
                "E1",
                "log",
                "SearchLog",
                "One record",
                {"records": [{"message": "pool exhausted"}]},
            )
        ],
        events=[{"type": "tool.call", "toolCall": {"id": "Q1", "status": "completed"}}],
    )


def terminal(
    state: JsonDict,
    *,
    revision: int = 0,
    status: Literal["failed", "succeeded", "cancelled"] = "failed",
    evidence_ids: list[str] | None = None,
) -> DiagnosticTerminalWrite:
    return DiagnosticTerminalWrite(
        operation_id="final",
        expected_revision=revision,
        checkpoint=state,
        status=status,
        title="Investigation",
        content="# Report\n\nEvidence only.",
        result_payload={"partial": True},
        evidence_ids=evidence_ids or [],
        error_message="Sanitized failure" if status == "failed" else None,
    )


async def count(database: Database, table: type[object]) -> int:
    async with database.sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(table)) or 0)


async def install_failure(database: Database, table: str) -> None:
    async with database.sessions() as session, session.begin():
        await session.execute(
            text(
                f"CREATE TRIGGER fail_insert BEFORE INSERT ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'injected persistence failure'); END"
            )
        )


async def remove_failure(database: Database) -> None:
    async with database.sessions() as session, session.begin():
        await session.execute(text("DROP TRIGGER fail_insert"))


@pytest.mark.asyncio
async def test_node_is_atomic_and_idempotent(database: Database) -> None:
    write = node(checkpoint())
    first = await database.runtime.commit_diagnostic_node(scope=database.scope, write=write)
    replay = await database.runtime.commit_diagnostic_node(scope=database.scope, write=write)
    assert not first.already_committed
    assert replay.already_committed
    assert replay.checkpoint == first.checkpoint
    assert await count(database, DiagnosticStepModel) == 1
    assert await count(database, BackgroundJobEventModel) == 1
    assert await count(database, GraphCheckpointModel) == 2
    assert await database.runtime.load_state(owner_user_id="user-b", task_id="task-a") is None
    with pytest.raises(DiagnosticStateConflict, match="incompatible content"):
        await database.runtime.commit_diagnostic_node(
            scope=database.scope,
            write=replace(write, events=[]),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table",
    [
        "aiops_diagnostic_steps",
        "background_job_events",
        "aiops_graph_checkpoints",
    ],
)
async def test_node_failure_rolls_back_every_artifact(database: Database, table: str) -> None:
    await install_failure(database, table)
    with pytest.raises(Exception, match="injected persistence failure"):
        await database.runtime.commit_diagnostic_node(
            scope=database.scope, write=node(checkpoint())
        )
    assert await count(database, DiagnosticStepModel) == 0
    assert await count(database, BackgroundJobEventModel) == 0
    assert await count(database, GraphCheckpointModel) == 0
    task = await database.diagnostics.get_task(owner_user_id="user-a", task_id="task-a")
    assert task is not None and task.status == "queued"
    await remove_failure(database)
    await database.runtime.commit_diagnostic_node(scope=database.scope, write=node(checkpoint()))
    assert await count(database, DiagnosticStepModel) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("table", ["tool_call_audits", "aiops_graph_checkpoints"])
async def test_reservation_failure_does_not_leave_intent(database: Database, table: str) -> None:
    await install_failure(database, table)
    with pytest.raises(Exception, match="injected persistence failure"):
        await database.runtime.reserve_diagnostic_operation(
            scope=database.scope,
            write=reservation(checkpoint()),
        )
    assert await count(database, AgentToolCallAuditModel) == 0
    assert await count(database, GraphCheckpointModel) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table",
    [
        "aiops_diagnostic_evidence",
        "background_job_events",
        "aiops_graph_checkpoints",
    ],
)
async def test_query_failure_preserves_reservation_and_rolls_back_result(
    database: Database,
    table: str,
) -> None:
    reserved = await database.runtime.reserve_diagnostic_operation(
        scope=database.scope,
        write=reservation(checkpoint()),
    )
    await install_failure(database, table)
    write = query_result(reserved.checkpoint)
    with pytest.raises(Exception, match="injected persistence failure"):
        await database.runtime.commit_diagnostic_query(scope=database.scope, write=write)
    async with database.sessions() as session:
        audit = await session.get(AgentToolCallAuditModel, "Q1")
        assert audit is not None and audit.status == "started" and audit.completed_at is None
    assert await count(database, DiagnosticEvidenceModel) == 0
    assert await count(database, BackgroundJobEventModel) == 0
    assert (
        await database.runtime.load_state(
            owner_user_id="user-a",
            task_id="task-a",
        )
        == reserved.checkpoint
    )
    await remove_failure(database)
    first = await database.runtime.commit_diagnostic_query(scope=database.scope, write=write)
    replay = await database.runtime.commit_diagnostic_query(scope=database.scope, write=write)
    assert replay.already_committed and replay.checkpoint == first.checkpoint
    assert await count(database, DiagnosticEvidenceModel) == 1
    assert await count(database, BackgroundJobEventModel) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table",
    [
        "aiops_diagnostic_reports",
        "aiops_report_evidence_links",
        "background_job_events",
        "aiops_graph_checkpoints",
    ],
)
async def test_terminal_failure_rolls_back_status_report_links_and_events(
    database: Database,
    table: str,
) -> None:
    reserved = await database.runtime.reserve_diagnostic_operation(
        scope=database.scope,
        write=reservation(checkpoint()),
    )
    result = await database.runtime.commit_diagnostic_query(
        scope=database.scope,
        write=query_result(reserved.checkpoint),
    )
    await install_failure(database, table)
    write = terminal(result.checkpoint, revision=2, evidence_ids=["E1"])
    with pytest.raises(Exception, match="injected persistence failure"):
        await database.runtime.finish_diagnostic_job(scope=database.scope, write=write)
    task = await database.diagnostics.get_task(owner_user_id="user-a", task_id="task-a")
    job = await database.jobs.get(owner_user_id="user-a", job_id="job-a")
    assert task is not None and task.status == "running" and task.completed_at is None
    assert job is not None and job.status == "running" and job.lease_owner == "worker-a"
    assert await count(database, DiagnosticReportModel) == 0
    assert await count(database, ReportEvidenceLinkModel) == 0
    assert await count(database, BackgroundJobEventModel) == 1
    await remove_failure(database)
    committed = await database.runtime.finish_diagnostic_job(scope=database.scope, write=write)
    replay = await database.runtime.finish_diagnostic_job(scope=database.scope, write=write)
    assert replay.already_committed and replay.checkpoint == committed.checkpoint
    events = await database.jobs.list_events(owner_user_id="user-a", job_id="job-a")
    assert [item.payload["type"] for item in events] == [
        "tool.call",
        "report",
        "error",
        "task.status",
        "complete",
    ]
    assert all(item.payload["id"] == item.id for item in events)
    complete = events[-1].payload["result"]
    assert isinstance(complete, dict)
    assert complete["reports"][0]["evidenceIds"] == ["E1"]
    assert complete["status"] == "failed"
    assert await count(database, DiagnosticReportModel) == 1
    assert await count(database, ReportEvidenceLinkModel) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope",
    [
        DiagnosticExecutionScope("user-b", "task-a", "job-a", "worker-a", 1),
        DiagnosticExecutionScope("user-a", "task-a", "other-job", "worker-a", 1),
    ],
)
async def test_foreign_owner_or_job_cannot_write(
    database: Database,
    scope: DiagnosticExecutionScope,
) -> None:
    with pytest.raises(TenantScopeError):
        await database.runtime.commit_diagnostic_node(scope=scope, write=node(checkpoint()))
    assert await count(database, DiagnosticStepModel) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["worker", "attempt", "expiry"])
async def test_stale_worker_is_fenced(database: Database, change: str) -> None:
    async with database.sessions() as session, session.begin():
        job = await session.get(BackgroundJobModel, "job-a")
        assert job is not None
        if change == "worker":
            job.lease_owner = "worker-b"
        elif change == "attempt":
            job.attempt += 1
        else:
            job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(DiagnosticLeaseLost):
        await database.runtime.commit_diagnostic_node(
            scope=database.scope, write=node(checkpoint())
        )
    assert await count(database, DiagnosticStepModel) == 0


@pytest.mark.asyncio
async def test_concurrent_writes_never_overwrite_newer_state(database: Database) -> None:
    state = checkpoint()
    results = await asyncio.gather(
        database.runtime.commit_diagnostic_node(
            scope=database.scope, write=node(state, identity="a")
        ),
        database.runtime.commit_diagnostic_node(
            scope=database.scope, write=node(state, identity="b")
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(item, DiagnosticStateConflict) for item in results) == 1
    assert sum(not isinstance(item, BaseException) for item in results) == 1
    assert await count(database, DiagnosticStepModel) == 1
    assert await count(database, BackgroundJobEventModel) == 1


@pytest.mark.asyncio
async def test_recovery_cannot_reset_deadline_or_actual_count(database: Database) -> None:
    first = await database.runtime.commit_diagnostic_node(
        scope=database.scope,
        write=node(checkpoint()),
    )
    state = checkpoint()
    with pytest.raises(DiagnosticStateConflict, match="cannot reset"):
        await database.runtime.commit_diagnostic_node(
            scope=database.scope,
            write=node(state, revision=1, identity="second"),
        )
    assert (
        await database.runtime.load_state(
            owner_user_id="user-a",
            task_id="task-a",
        )
        == first.checkpoint
    )


class ObservableRuntime(BackgroundJobRuntime):
    async def execute_claimed(self, job: BackgroundJobRecord) -> None:
        assert job.lease_owner is not None
        await self._execute(job, job.lease_owner)


class CountingJobRepository(SQLiteBackgroundJobRepository):
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(sessions)
        self.terminal_calls: list[str] = []
        self.reject_renewal = False

    async def mark_succeeded(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt: int | None = None,
    ) -> BackgroundJobRecord | None:
        self.terminal_calls.append("succeeded")
        return await super().mark_succeeded(job_id=job_id, worker_id=worker_id, attempt=attempt)

    async def mark_cancelled(
        self,
        *,
        job_id: str,
        worker_id: str,
        attempt: int | None = None,
    ) -> BackgroundJobRecord | None:
        self.terminal_calls.append("cancelled")
        return await super().mark_cancelled(job_id=job_id, worker_id=worker_id, attempt=attempt)

    async def handle_failure(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_message: str,
        retry_at: datetime,
        attempt: int | None = None,
    ) -> BackgroundJobRecord | None:
        self.terminal_calls.append("failure")
        return await super().handle_failure(
            job_id=job_id,
            worker_id=worker_id,
            error_message=error_message,
            retry_at=retry_at,
            attempt=attempt,
        )

    async def renew_lease(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_expires_at: datetime,
        attempt: int | None = None,
    ) -> bool:
        if self.reject_renewal:
            return False
        return await super().renew_lease(
            job_id=job_id,
            worker_id=worker_id,
            lease_expires_at=lease_expires_at,
            attempt=attempt,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
@pytest.mark.parametrize("after", ["return", "error", "cancel"])
async def test_runtime_never_overwrites_atomic_diagnostic_terminal(
    database: Database,
    status: Literal["succeeded", "failed", "cancelled"],
    after: str,
) -> None:
    jobs = CountingJobRepository(database.sessions)
    runtime = ObservableRuntime(jobs)
    job = await jobs.get(owner_user_id="user-a", job_id="job-a")
    assert job is not None

    async def handler(context: BackgroundJobContext) -> None:
        assert context.worker_id == "worker-a"
        assert context.execution_scope == database.scope
        await database.runtime.finish_diagnostic_job(
            scope=context.execution_scope,
            write=terminal(checkpoint(), status=status),
        )
        if after == "error":
            raise RuntimeError("Error after durable terminal")
        if after == "cancel":
            raise JobCancelled("Cancellation after durable terminal")

    runtime.register("aiops_diagnosis", handler)
    await runtime.execute_claimed(job)
    updated = await jobs.get(owner_user_id="user-a", job_id="job-a")
    assert updated is not None and updated.status == status
    assert jobs.terminal_calls == []
    assert await count(database, DiagnosticReportModel) == 1


@pytest.mark.asyncio
async def test_heartbeat_loss_stops_handler_without_writing_terminal(database: Database) -> None:
    jobs = CountingJobRepository(database.sessions)
    jobs.reject_renewal = True
    runtime = ObservableRuntime(jobs, lease_seconds=6)
    cancelled = asyncio.Event()
    job = await jobs.get(owner_user_id="user-a", job_id="job-a")
    assert job is not None

    async def handler(context: BackgroundJobContext) -> None:
        await context.raise_if_cancelled()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    runtime.register("aiops_diagnosis", handler)
    await asyncio.wait_for(runtime.execute_claimed(job), timeout=4)
    assert cancelled.is_set()
    assert jobs.terminal_calls == []
    updated = await jobs.get(owner_user_id="user-a", job_id="job-a")
    assert updated is not None and updated.status == "running"


@pytest.mark.asyncio
async def test_two_workers_only_one_claims_and_same_id_new_attempt_is_fenced(
    database: Database,
) -> None:
    async with database.sessions() as session, session.begin():
        job = await session.get(BackgroundJobModel, "job-a")
        assert job is not None
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    claims = await asyncio.gather(
        database.jobs.claim_next(worker_id="worker-a", lease_expires_at=expiry),
        database.jobs.claim_next(worker_id="worker-b", lease_expires_at=expiry),
    )
    winners = [job for job in claims if job is not None]
    assert len(winners) == 1
    assert winners[0].attempt == 2
    assert not await database.jobs.renew_lease(
        job_id="job-a",
        worker_id="worker-a",
        attempt=1,
        lease_expires_at=expiry,
    )
    assert (
        await database.jobs.mark_succeeded(
            job_id="job-a",
            worker_id="worker-a",
            attempt=1,
        )
        is None
    )
    with pytest.raises(DiagnosticLeaseLost):
        await database.jobs.append_event(
            owner_user_id="user-a",
            job_id="job-a",
            worker_id="worker-a",
            attempt=1,
            payload={"type": "task.status"},
        )
    with pytest.raises(DiagnosticLeaseLost):
        await database.runtime.reserve_diagnostic_operation(
            scope=database.scope,
            write=reservation(checkpoint()),
        )
    assert await count(database, AgentToolCallAuditModel) == 0


@pytest.mark.asyncio
async def test_cancel_before_finish_wins_and_terminal_cancel_is_rejected(
    database: Database,
) -> None:
    requested = await database.jobs.request_cancel(owner_user_id="user-a", job_id="job-a")
    assert requested is not None and requested.cancel_requested_at is not None
    with pytest.raises(DiagnosticStateConflict, match="Cancellation prevents"):
        await database.runtime.reserve_diagnostic_operation(
            scope=database.scope,
            write=reservation(checkpoint()),
        )
    await database.runtime.finish_diagnostic_job(
        scope=database.scope,
        write=terminal(checkpoint(), status="succeeded"),
    )
    task = await database.diagnostics.get_task(owner_user_id="user-a", task_id="task-a")
    job = await database.jobs.get(owner_user_id="user-a", job_id="job-a")
    assert task is not None and task.status == "cancelled"
    assert job is not None and job.status == "cancelled"
    assert await database.jobs.request_cancel(owner_user_id="user-a", job_id="job-a") is None
    events = await database.jobs.list_events(owner_user_id="user-a", job_id="job-a")
    assert [item.payload["type"] for item in events] == ["report", "task.status", "complete"]
    assert await count(database, DiagnosticReportModel) == 1


@pytest.mark.asyncio
async def test_terminal_before_cancel_is_never_overwritten(database: Database) -> None:
    await database.runtime.finish_diagnostic_job(
        scope=database.scope,
        write=terminal(checkpoint(), status="succeeded"),
    )
    assert await database.jobs.request_cancel(owner_user_id="user-a", job_id="job-a") is None
    task = await database.diagnostics.get_task(owner_user_id="user-a", task_id="task-a")
    assert task is not None and task.status == "succeeded"


@pytest.mark.asyncio
async def test_explicit_retry_creates_new_task_and_keeps_original_report(
    database: Database,
) -> None:
    await database.runtime.finish_diagnostic_job(
        scope=database.scope,
        write=terminal(checkpoint()),
    )
    assert (
        await database.jobs.retry(
            owner_user_id="user-b",
            source_job_id="job-a",
            new_job_id="foreign-retry",
        )
        is None
    )
    retried = await database.jobs.retry(
        owner_user_id="user-a",
        source_job_id="job-a",
        new_job_id="job-retry",
    )
    assert retried is not None and retried.resource_id != "task-a"
    assert retried.retry_of_job_id == "job-a"
    assert retried.payload["diagnosticId"] == retried.resource_id
    original = await database.diagnostics.get_task(owner_user_id="user-a", task_id="task-a")
    new_task = await database.diagnostics.get_task(
        owner_user_id="user-a",
        task_id=retried.resource_id,
    )
    assert original is not None and original.status == "failed"
    assert new_task is not None and new_task.status == "queued"
    assert new_task.query == original.query and new_task.input_payload == original.input_payload
    assert new_task.result_payload == {} and new_task.completed_at is None
    assert await count(database, DiagnosticReportModel) == 1


@pytest.mark.asyncio
async def test_queued_cancel_is_atomic_and_does_not_start_handler(database: Database) -> None:
    await database.diagnostics.create_task(
        owner_user_id="user-a",
        task_id="queued-task",
        status="queued",
        query="Queued",
    )
    await database.jobs.enqueue(
        owner_user_id="user-a",
        job_id="queued-job",
        kind="aiops_diagnosis",
        resource_type="aiops_diagnostic",
        resource_id="queued-task",
    )
    await install_failure(database, "background_job_events")
    with pytest.raises(Exception, match="injected persistence failure"):
        await database.jobs.request_cancel(owner_user_id="user-a", job_id="queued-job")
    queued = await database.jobs.get(owner_user_id="user-a", job_id="queued-job")
    assert queued is not None and queued.status == "queued" and queued.started_at is None
    assert await count(database, DiagnosticReportModel) == 0
    await remove_failure(database)
    cancelled = await database.jobs.request_cancel(owner_user_id="user-a", job_id="queued-job")
    assert cancelled is not None and cancelled.status == "cancelled"
    task = await database.diagnostics.get_task(owner_user_id="user-a", task_id="queued-task")
    assert task is not None and task.status == "cancelled"
    assert (
        await database.jobs.claim_next(
            worker_id="worker-c",
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        is None
    )
    assert await count(database, AgentToolCallAuditModel) == 0
    events = await database.jobs.list_events(owner_user_id="user-a", job_id="queued-job")
    assert [item.payload["type"] for item in events] == ["report", "task.status", "complete"]


@pytest.mark.asyncio
async def test_persisted_intent_dispatch_and_full_evidence_restore(database: Database) -> None:
    controller = DiagnosticBudgetController.start(DiagnosisConfig())
    controller.reserve_call(query_id="Q1", batch_id="B1")
    state: JsonDict = {
        "runtime": {
            **controller.snapshot().model_dump(mode="json"),
            "revision": 0,
            "next_node": "execute_queries",
        },
        "working_state": {"evidence_ids": []},
        "last_valid_assessment": None,
    }
    reserve_write = reservation(state)
    reserved = await database.runtime.reserve_diagnostic_operation(
        scope=database.scope,
        write=reserve_write,
    )
    replay = await database.runtime.reserve_diagnostic_operation(
        scope=database.scope,
        write=reserve_write,
    )
    assert replay.already_committed
    runtime = reserved.checkpoint["runtime"]
    assert isinstance(runtime, dict)
    assert runtime["operations"]["Q1"]["status"] == "reserved"
    controller.mark_dispatched("Q1")
    dispatched_state: JsonDict = {
        **reserved.checkpoint,
        "runtime": {**runtime, **controller.snapshot().model_dump(mode="json")},
    }
    dispatched = await database.runtime.reserve_diagnostic_operation(
        scope=database.scope,
        write=replace(reservation(dispatched_state, revision=1), stage="dispatch"),
    )
    restored = await database.runtime.load_state(owner_user_id="user-a", task_id="task-a")
    assert restored is not None
    assert restored == dispatched.checkpoint
    assert isinstance(restored["runtime"], dict)
    persisted_runtime = cast(JsonDict, restored["runtime"])
    persisted_budget = BudgetState.model_validate(
        {
            name: persisted_runtime[name]
            for name in (
                "budget",
                "calls",
                "batches",
                "remaining_seconds",
                "saved_at",
            )
        }
    )
    assert persisted_budget.budget.tool_calls_used == 1
    assert persisted_budget.budget.rounds_used == 1
    recovered = DiagnosticBudgetController(persisted_budget)
    assert recovered.recover_interrupted() == ["Q1"]
    assert recovered.state.budget.tool_calls_used == 1
    controller.complete_call("Q1")
    completed_state: JsonDict = {
        **dispatched.checkpoint,
        "runtime": {**persisted_runtime, **controller.snapshot().model_dump(mode="json")},
        "working_state": {"evidence_ids": ["E1"]},
    }
    completed = await database.runtime.commit_diagnostic_query(
        scope=database.scope,
        write=query_result(completed_state, revision=2),
    )
    assert "pool exhausted" not in str(completed.checkpoint)
    evidence = await database.runtime.load_evidence(
        owner_user_id="user-a",
        task_id="task-a",
        evidence_ids=["E1"],
    )
    assert evidence == [
        {
            "evidence_id": "E1",
            "query_id": "Q1",
            "kind": "log",
            "data": {"records": [{"message": "pool exhausted"}]},
        }
    ]
    with pytest.raises(TenantScopeError):
        await database.runtime.load_evidence(
            owner_user_id="user-b",
            task_id="task-a",
            evidence_ids=["E1"],
        )
    with pytest.raises(TenantScopeError):
        await database.runtime.load_evidence(
            owner_user_id="user-a",
            task_id="task-a",
            evidence_ids=["foreign-evidence"],
        )


@pytest.mark.asyncio
async def test_model_intent_is_completed_only_with_node_commit(database: Database) -> None:
    write = DiagnosticReservationWrite(
        operation_id="assess-1",
        expected_revision=0,
        checkpoint=checkpoint(),
        kind="model",
        phase="assess_hypotheses",
    )
    reserved = await database.runtime.reserve_diagnostic_operation(
        scope=database.scope, write=write
    )
    state = reserved.checkpoint
    runtime = state["runtime"]
    assert isinstance(runtime, dict)
    assert runtime["operations"]["assess-1"]["status"] == "reserved"
    await install_failure(database, "background_job_events")
    node_write = replace(
        node(state, revision=1, identity="assess-1"),
        phase="assess_hypotheses",
    )
    with pytest.raises(Exception, match="injected persistence failure"):
        await database.runtime.commit_diagnostic_node(scope=database.scope, write=node_write)
    assert await database.runtime.load_state(owner_user_id="user-a", task_id="task-a") == state
    await remove_failure(database)
    committed = await database.runtime.commit_diagnostic_node(
        scope=database.scope, write=node_write
    )
    assert isinstance(committed.checkpoint["runtime"], dict)
    assert committed.checkpoint["runtime"]["operations"]["assess-1"]["status"] == "completed"


@pytest.mark.asyncio
async def test_background_api_cancel_retry_and_owner_scope(
    database: Database,
    migrated_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_external_worker_start(self: BackgroundJobRuntime) -> None:
        return None

    monkeypatch.setattr(BackgroundJobRuntime, "start", no_external_worker_start)
    app = create_app(database_url=migrated_url)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        auth = await client.post(
            "/auth/register",
            json={
                "email": "diagnosis-owner@example.test",
                "displayName": "Owner",
                "password": "correct horse battery staple",
            },
        )
        other_auth = await client.post(
            "/auth/register",
            json={
                "email": "diagnosis-other@example.test",
                "displayName": "Other",
                "password": "correct horse battery staple",
            },
        )
        assert auth.status_code == other_auth.status_code == 201
        owner_id = str(auth.json()["data"]["user"]["id"])
        headers = {"Authorization": f"Bearer {auth.json()['data']['accessToken']}"}
        other_headers = {"Authorization": f"Bearer {other_auth.json()['data']['accessToken']}"}
        await database.diagnostics.create_task(
            owner_user_id=owner_id,
            task_id="api-task",
            status="queued",
            query="API diagnostic",
        )
        await database.jobs.enqueue(
            owner_user_id=owner_id,
            job_id="api-job",
            kind="aiops_diagnosis",
            resource_type="aiops_diagnostic",
            resource_id="api-task",
            max_attempts=1,
        )
        foreign_cancel = await client.post(
            "/background-jobs/api-job:cancel",
            headers=other_headers,
        )
        foreign_retry = await client.post(
            "/background-jobs/api-job:retry",
            headers=other_headers,
        )
        assert foreign_cancel.status_code == foreign_retry.status_code == 403
        cancelled = await client.post("/background-jobs/api-job:cancel", headers=headers)
        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["status"] == "cancelled"
        cancel_again = await client.post("/background-jobs/api-job:cancel", headers=headers)
        assert cancel_again.status_code == 409
        retried = await client.post("/background-jobs/api-job:retry", headers=headers)
        assert retried.status_code == 202
        new_task_id = str(retried.json()["data"]["resourceId"])
        assert new_task_id != "api-task"
        original = await client.get("/aiops/diagnostics/api-task", headers=headers)
        fresh = await client.get(f"/aiops/diagnostics/{new_task_id}", headers=headers)
        assert original.status_code == fresh.status_code == 200
        assert original.json()["data"]["status"] == "cancelled"
        assert len(original.json()["data"]["reports"]) == 1
        assert fresh.json()["data"]["status"] == "queued"
        assert fresh.json()["data"]["reports"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["return", "error", "cancel", "timeout"])
async def test_diagnostic_runtime_uses_atomic_finalizer_instead_of_job_only_finish(
    database: Database,
    mode: str,
) -> None:
    jobs = CountingJobRepository(database.sessions)
    runtime = ObservableRuntime(jobs)
    job = await jobs.get(owner_user_id="user-a", job_id="job-a")
    assert job is not None
    if mode == "timeout":
        job = replace(job, timeout_seconds=1)
    reasons: list[str] = []

    async def handler(context: BackgroundJobContext) -> None:
        await context.raise_if_cancelled()
        if mode == "error":
            raise RuntimeError("secret-value-must-not-appear")
        if mode == "cancel":
            raise JobCancelled("Cancellation")
        if mode == "timeout":
            await asyncio.Event().wait()

    async def finalize(
        context: BackgroundJobContext,
        status: Literal["failed", "cancelled"],
        reason: str,
    ) -> None:
        reasons.append(reason)
        await database.runtime.finish_diagnostic_job(
            scope=context.execution_scope,
            write=terminal(checkpoint(), status=status),
        )

    runtime.register("aiops_diagnosis", handler, on_termination=finalize)
    await runtime.execute_claimed(job)
    updated = await jobs.get(owner_user_id="user-a", job_id="job-a")
    assert updated is not None
    assert updated.status == ("cancelled" if mode == "cancel" else "failed")
    assert jobs.terminal_calls == []
    assert len(reasons) == 1
    assert "secret-value" not in reasons[0]
    assert await count(database, DiagnosticReportModel) == 1


@pytest.mark.asyncio
async def test_failed_finalizer_leaves_job_recoverable_without_success(database: Database) -> None:
    jobs = CountingJobRepository(database.sessions)
    runtime = ObservableRuntime(jobs)
    job = await jobs.get(owner_user_id="user-a", job_id="job-a")
    assert job is not None

    async def handler(context: BackgroundJobContext) -> None:
        await context.raise_if_cancelled()

    async def unavailable_finalizer(
        context: BackgroundJobContext,
        status: Literal["failed", "cancelled"],
        reason: str,
    ) -> None:
        await context.raise_if_lease_lost()
        raise RuntimeError("Database unavailable")

    runtime.register("aiops_diagnosis", handler, on_termination=unavailable_finalizer)
    await runtime.execute_claimed(job)
    updated = await jobs.get(owner_user_id="user-a", job_id="job-a")
    assert updated is not None and updated.status == "running"
    assert jobs.terminal_calls == []
    assert await count(database, DiagnosticReportModel) == 0
    assert await count(database, BackgroundJobEventModel) == 0


@pytest.mark.asyncio
async def test_assessment_invalidation_and_last_valid_snapshot_commit_together(
    database: Database,
) -> None:
    state = checkpoint()
    previous: JsonDict = {
        "hypotheses": [{"hypothesis_id": "H1", "statement": "Original explanation"}],
        "hypothesis_relations": [{"from_hypothesis_id": "H1", "to_hypothesis_id": "H2"}],
        "incident_conclusion": {"conclusion_status": "unconfirmed"},
    }
    state["last_valid_assessment"] = previous
    state["working_state"] = previous
    first = await database.runtime.commit_diagnostic_node(
        scope=database.scope,
        write=node(state),
    )
    revised: JsonDict = {
        **first.checkpoint,
        "working_state": {
            "hypotheses": [{"hypothesis_id": "H1", "statement": "Refined explanation"}],
            "hypothesis_relations": [],
            "incident_conclusion": None,
        },
    }
    second = await database.runtime.commit_diagnostic_node(
        scope=database.scope,
        write=replace(node(revised, revision=1, identity="revise-1"), phase="revise_hypotheses"),
    )
    restored = await database.runtime.load_state(owner_user_id="user-a", task_id="task-a")
    assert restored == second.checkpoint
    assert restored is not None
    assert restored["last_valid_assessment"] == previous
    working = cast(JsonDict, restored["working_state"])
    assert working["hypothesis_relations"] == []
    assert working["incident_conclusion"] is None
    assert "Refined explanation" in str(working["hypotheses"])


@pytest.mark.asyncio
async def test_unknown_reserved_call_recovers_once_without_replay(database: Database) -> None:
    controller = DiagnosticBudgetController.start(DiagnosisConfig())
    controller.reserve_call(query_id="Q1", batch_id="B1")
    state: JsonDict = {
        "runtime": {
            **controller.snapshot().model_dump(mode="json"),
            "revision": 0,
            "next_node": "execute_queries",
        },
        "working_state": {"hypotheses": [], "evidence_ids": []},
        "last_valid_assessment": None,
    }
    reserved = await database.runtime.reserve_diagnostic_operation(
        scope=database.scope,
        write=reservation(state),
    )
    async with database.sessions() as session, session.begin():
        job = await session.get(BackgroundJobModel, "job-a")
        assert job is not None
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    resumed = await database.jobs.claim_next(
        worker_id="worker-b",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    assert resumed is not None and resumed.attempt == 2
    scope = replace(database.scope, worker_id="worker-b", attempt=2)
    decision = plan_diagnostic_recovery(reserved.checkpoint)
    assert len(decision.interrupted_queries) == 1
    committed = await database.runtime.commit_diagnostic_query(
        scope=scope,
        write=DiagnosticQueryWrite(
            operation_id="Q1",
            expected_revision=1,
            checkpoint=decision.checkpoint,
            query=decision.interrupted_queries[0].model_dump(mode="json"),
            evidence=[],
            events=[],
        ),
    )
    runtime = cast(JsonDict, committed.checkpoint["runtime"])
    budget = cast(JsonDict, runtime["budget"])
    assert budget["tool_calls_used"] == budget["rounds_used"] == 0
    assert budget["unknown_tool_calls"] == 1
    assert await count(database, AgentToolCallAuditModel) == 1
    assert plan_diagnostic_recovery(committed.checkpoint).interrupted_queries == ()


@pytest.mark.asyncio
async def test_cancellation_retains_failed_query_partial_evidence(database: Database) -> None:
    reserved = await database.runtime.reserve_diagnostic_operation(
        scope=database.scope,
        write=reservation(checkpoint()),
    )
    write = query_result(reserved.checkpoint)
    write = replace(
        write,
        query={**write.query, "status": "failed", "status_reason": "Partial response"},
    )
    result = await database.runtime.commit_diagnostic_query(scope=database.scope, write=write)
    await database.jobs.request_cancel(owner_user_id="user-a", job_id="job-a")
    await database.runtime.finish_diagnostic_job(
        scope=database.scope,
        write=terminal(result.checkpoint, revision=2, status="succeeded", evidence_ids=["E1"]),
    )
    evidence = await database.runtime.load_evidence(
        owner_user_id="user-a",
        task_id="task-a",
        evidence_ids=["E1"],
    )
    assert evidence[0]["data"] == {"records": [{"message": "pool exhausted"}]}
    task = await database.diagnostics.get_task(owner_user_id="user-a", task_id="task-a")
    assert task is not None and task.status == "cancelled"
    assert task.result_payload["partial"] is True
    assert await count(database, ReportEvidenceLinkModel) == 1
