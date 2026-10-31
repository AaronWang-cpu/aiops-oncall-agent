"""SQLite-leased durable worker runtime for local background work."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, TypeAlias
from uuid import uuid4

from super_ai.memory.repositories import (
    BackgroundJobRecord,
    BackgroundJobRepository,
    DiagnosticExecutionScope,
    DiagnosticLeaseLost,
    JsonDict,
)
from super_ai.observability import emit_event

logger = logging.getLogger(__name__)
JobHandler: TypeAlias = Callable[["BackgroundJobContext"], Awaitable[None]]
JobTerminationHandler: TypeAlias = Callable[
    ["BackgroundJobContext", Literal["failed", "cancelled"], str],
    Awaitable[None],
]


class JobCancelled(RuntimeError):
    """Cooperative cancellation requested at a safe handler boundary."""


@dataclass(frozen=True, slots=True)
class BackgroundJobContext:
    """Narrow handler context backed by the durable repository."""

    job: BackgroundJobRecord
    repository: BackgroundJobRepository

    @property
    def worker_id(self) -> str:
        if self.job.lease_owner is None:
            raise DiagnosticLeaseLost("Background job has no claimed worker.")
        return self.job.lease_owner

    @property
    def execution_scope(self) -> DiagnosticExecutionScope:
        return DiagnosticExecutionScope(
            owner_user_id=self.job.owner_user_id,
            task_id=self.job.resource_id,
            job_id=self.job.id,
            worker_id=self.worker_id,
            attempt=self.job.attempt,
        )

    async def append_event(self, payload: JsonDict) -> None:
        await self.repository.append_event(
            owner_user_id=self.job.owner_user_id,
            job_id=self.job.id,
            payload=payload,
            worker_id=self.worker_id,
            attempt=self.job.attempt,
        )

    async def raise_if_lease_lost(self) -> BackgroundJobRecord:
        current = await self.repository.get(
            owner_user_id=self.job.owner_user_id,
            job_id=self.job.id,
        )
        if (
            current is None
            or current.status != "running"
            or current.lease_owner != self.worker_id
            or current.attempt != self.job.attempt
            or current.lease_expires_at is None
            or current.lease_expires_at <= _utc_now()
        ):
            raise DiagnosticLeaseLost("Background job lease is no longer valid.")
        return current

    async def raise_if_cancelled(self) -> None:
        current = await self.raise_if_lease_lost()
        if current.cancel_requested_at is not None:
            raise JobCancelled("Background job cancellation was requested.")


class BackgroundJobRuntime:
    """Run registered handlers using renewable SQLite leases."""

    def __init__(
        self,
        repository: BackgroundJobRepository,
        *,
        concurrency: int = 2,
        lease_seconds: int = 30,
        poll_seconds: float = 0.2,
    ) -> None:
        self._repository = repository
        self._concurrency = max(1, concurrency)
        self._lease_seconds = max(6, lease_seconds)
        self._poll_seconds = max(0.05, poll_seconds)
        self._handlers: dict[str, JobHandler] = {}
        self._termination_handlers: dict[str, JobTerminationHandler] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        self._runtime_id = f"runtime_{uuid4().hex}"

    def register(
        self,
        kind: str,
        handler: JobHandler,
        *,
        on_termination: JobTerminationHandler | None = None,
    ) -> None:
        if kind in self._handlers:
            raise ValueError(f"Background job handler already registered: {kind}")
        if on_termination is not None and kind != "aiops_diagnosis":
            raise ValueError("Atomic termination hooks are reserved for diagnostic jobs.")
        self._handlers[kind] = handler
        if on_termination is not None:
            self._termination_handlers[kind] = on_termination

    async def start(self) -> None:
        if self._workers:
            return
        self._stopping.clear()
        self._workers = [
            asyncio.create_task(self._worker_loop(index), name=f"background-worker-{index}")
            for index in range(self._concurrency)
        ]

    async def stop(self) -> None:
        self._stopping.set()
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    async def _worker_loop(self, index: int) -> None:
        worker_id = f"{self._runtime_id}:{index}"
        while not self._stopping.is_set():
            now = _utc_now()
            job = await self._repository.claim_next(
                worker_id=worker_id,
                lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                now=now,
            )
            if job is None:
                await asyncio.sleep(self._poll_seconds)
                continue
            await self._execute(job, worker_id)

    async def _execute(self, job: BackgroundJobRecord, worker_id: str) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            await self._repository.handle_failure(
                job_id=job.id,
                worker_id=worker_id,
                error_message=f"No handler is registered for job kind: {job.kind}",
                retry_at=_utc_now(),
                attempt=job.attempt,
            )
            return

        emit_event(logger, "background.job.started", jobId=job.id, kind=job.kind)
        context = BackgroundJobContext(job=job, repository=self._repository)
        lease_lost = asyncio.Event()
        execution: asyncio.Task[None] | None = None
        heartbeat: asyncio.Task[None] | None = None
        try:
            await context.raise_if_cancelled()
            execution = asyncio.create_task(
                _run_handler(handler, context), name=f"job-handler-{job.id}"
            )
            heartbeat = asyncio.create_task(self._heartbeat(job, worker_id, execution, lease_lost))
            await asyncio.wait_for(execution, timeout=job.timeout_seconds)
            if await self._diagnostic_terminal_committed(job):
                return
            await context.raise_if_cancelled()
        except asyncio.CancelledError:
            if not lease_lost.is_set():
                raise
            emit_event(logger, "background.job.lease_lost", jobId=job.id, kind=job.kind)
        except DiagnosticLeaseLost:
            emit_event(logger, "background.job.lease_lost", jobId=job.id, kind=job.kind)
        except JobCancelled:
            if await self._diagnostic_terminal_committed(job):
                return
            if await self._terminate_diagnostic(context, "cancelled", "User cancelled diagnosis."):
                return
            await self._repository.mark_cancelled(
                job_id=job.id,
                worker_id=worker_id,
                attempt=job.attempt,
            )
            emit_event(logger, "background.job.cancelled", jobId=job.id, kind=job.kind)
        except Exception as exc:
            if await self._diagnostic_terminal_committed(job):
                return
            if await self._terminate_diagnostic(
                context,
                "failed",
                f"Diagnostic execution failed: {exc.__class__.__name__}.",
            ):
                return
            retry_at = _utc_now() + timedelta(seconds=min(30, 2**job.attempt))
            updated = await self._repository.handle_failure(
                job_id=job.id,
                worker_id=worker_id,
                error_message=_safe_error(exc),
                retry_at=retry_at,
                attempt=job.attempt,
            )
            emit_event(
                logger,
                "background.job.failed",
                jobId=job.id,
                kind=job.kind,
                final=updated is not None and updated.status == "failed",
                errorCategory=exc.__class__.__name__,
            )
        else:
            if await self._terminate_diagnostic(
                context,
                "failed",
                "Diagnostic handler returned without a durable terminal.",
            ):
                return
            await self._repository.mark_succeeded(
                job_id=job.id,
                worker_id=worker_id,
                attempt=job.attempt,
            )
            emit_event(logger, "background.job.completed", jobId=job.id, kind=job.kind)
        finally:
            if execution is not None and not execution.done():
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)

    async def _diagnostic_terminal_committed(self, job: BackgroundJobRecord) -> bool:
        if job.kind != "aiops_diagnosis":
            return False
        current = await self._repository.get(owner_user_id=job.owner_user_id, job_id=job.id)
        return current is not None and current.status in {"succeeded", "failed", "cancelled"}

    async def _terminate_diagnostic(
        self,
        context: BackgroundJobContext,
        status: Literal["failed", "cancelled"],
        reason: str,
    ) -> bool:
        finalizer = self._termination_handlers.get(context.job.kind)
        if finalizer is None:
            return False
        try:
            await context.raise_if_lease_lost()
            await finalizer(context, status, reason)
            if not await self._diagnostic_terminal_committed(context.job):
                raise RuntimeError("Diagnostic finalizer did not commit a terminal.")
        except DiagnosticLeaseLost:
            emit_event(logger, "background.job.lease_lost", jobId=context.job.id)
        except Exception as exc:
            # Leave the leased job recoverable rather than publish an isolated job terminal.
            emit_event(
                logger,
                "background.job.terminal_pending",
                jobId=context.job.id,
                errorCategory=exc.__class__.__name__,
            )
        return True

    async def _heartbeat(
        self,
        job: BackgroundJobRecord,
        worker_id: str,
        execution: asyncio.Task[None],
        lease_lost: asyncio.Event,
    ) -> None:
        interval = self._lease_seconds / 3
        while not self._stopping.is_set():
            await asyncio.sleep(interval)
            try:
                renewed = await self._repository.renew_lease(
                    job_id=job.id,
                    worker_id=worker_id,
                    attempt=job.attempt,
                    lease_expires_at=_utc_now() + timedelta(seconds=self._lease_seconds),
                )
            except Exception:
                logger.warning("Background job lease renewal failed; stopping local execution.")
                renewed = False
            if not renewed:
                lease_lost.set()
                execution.cancel()
                return


async def _run_handler(handler: JobHandler, context: BackgroundJobContext) -> None:
    await handler(context)


def _safe_error(error: Exception) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return "Background job timed out."
    text = str(error).strip()
    return (text or error.__class__.__name__)[:1000]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
