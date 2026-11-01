"""Hypothesis-driven diagnosis graph with durable, fenced persistence.

LangGraph only routes; every durable fact is committed by the Repository
transactions built in P2. Each node commits its own step before the next one is
entered, so recovery resumes from the saved node without re-running committed
work and without re-reading content files.
"""

# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownLambdaType=false, reportUnnecessaryCast=false

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict, TypeVar, cast

from langgraph.graph import END, START, StateGraph
from pydantic import JsonValue, ValidationError

from super_ai.aiops.diagnosis_budget import (
    BudgetExpired,
    BudgetState,
    BudgetUnavailable,
    DiagnosisClock,
    DiagnosticBudgetController,
    SystemDiagnosisClock,
    TimePhase,
)
from super_ai.aiops.diagnosis_config import DiagnosisConfig
from super_ai.aiops.diagnosis_context import (
    DiagnosisContentError,
    DiagnosisContext,
    MockScenario,
    prepare_diagnosis_context,
    timestamp_ms,
)
from super_ai.aiops.diagnosis_models import (
    AssessmentOutput,
    DiagnosisBudget,
    DiagnosisResult,
    Evidence,
    Hypothesis,
    HypothesisRelation,
    HypothesisRevision,
    IncidentConclusion,
    QueryPlan,
    QueryRecord,
    UnmetRequest,
)
from super_ai.aiops.diagnosis_recovery import plan_diagnostic_recovery
from super_ai.aiops.diagnosis_reporting import ReportFacts, build_diagnosis_report
from super_ai.aiops.diagnosis_tools import (
    ClsSearchDefaults,
    DiagnosisToolbox,
    DiagnosisToolError,
    RepeatedFailureGuard,
    ToolExecution,
    build_mock_diagnosis_toolbox,
    build_mock_query_change_arguments,
    build_mock_query_metric_arguments,
    build_mock_search_log_arguments,
    build_real_diagnosis_toolbox,
    build_real_search_log_arguments,
    normalize_mock_arguments,
)
from super_ai.jobs.runtime import BackgroundJobContext
from super_ai.llm import LlmProvider
from super_ai.mcp_client import LocalMcpClient, McpClientError
from super_ai.mcp_connections import McpConnectionService
from super_ai.memory.repositories import (
    DiagnosticEvidenceWrite,
    DiagnosticExecutionScope,
    DiagnosticLeaseLost,
    DiagnosticNodeWrite,
    DiagnosticQueryWrite,
    DiagnosticReservationWrite,
    DiagnosticStateConflict,
    DiagnosticTerminalWrite,
    JsonDict,
    MemoryRepositories,
)
from super_ai.observability import emit_event

logger = logging.getLogger(__name__)

ENGINE = "hypothesis-driven-v1"
LOG_TOOL = "SearchLog"
METRIC_TOOL = "QueryMetric"
CHANGE_TOOL = "QueryChange"
LOG_WINDOW_BEFORE_MINUTES = 10
LOG_WINDOW_AFTER_MINUTES = 5
FINAL_FAILURE_NOTE = "核心执行失败，未产生可信结论。"

ModelT = TypeVar("ModelT")
NodeName = Literal[
    "prepare_context",
    "build_queries",
    "execute_queries",
    "revise_hypotheses",
    "assess_hypotheses",
    "finalize",
    "report",
]


class DiagnosisExecutionError(RuntimeError):
    """A core stage failed; the run ends through the program failure path."""


class DiagnosisOutputInvalid(DiagnosisExecutionError):
    """A structured node output stayed invalid after the single correction pass."""


class DiagnosisStreamState(TypedDict, total=False):
    """Working state mirrored into the graph; the checkpoint stays authoritative."""

    route: str
    hypotheses: list[JsonDict]
    hypothesis_relations: list[JsonDict]
    incident_conclusion: JsonDict | None
    query_plan: JsonDict | None
    unmet_requests: list[JsonDict]
    query_records: list[JsonDict]
    evidence_ids: list[str]
    unassessed_evidence_ids: list[str]
    assessment_is_current: bool


@dataclass(frozen=True, slots=True)
class _AlertContext:
    service: str = ""
    instance: str = ""
    starts_at_ms: int | None = None
    summary: str = ""


@dataclass(slots=True)
class _RoundResult:
    calls_planned: int = 0
    calls_succeeded: int = 0
    calls_failed: int = 0
    business_records: int = 0
    evidence_ids: list[str] = field(default_factory=list)


class AiopsDiagnosticService:
    """Run one durable hypothesis-driven investigation for an owned task."""

    def __init__(
        self,
        *,
        repositories: MemoryRepositories,
        llm_provider: LlmProvider,
        config: DiagnosisConfig,
        cls_region: str,
        cls_topic_id: str,
        clock: DiagnosisClock | None = None,
        mcp_client: LocalMcpClient | None = None,
        mcp_client_provider: McpConnectionService | None = None,
    ) -> None:
        self._repositories = repositories
        self._llm_provider = llm_provider
        self._config = config
        self._cls_region = cls_region
        self._cls_topic_id = cls_topic_id
        self._clock = clock or SystemDiagnosisClock()
        self._mcp_client = mcp_client
        self._mcp_client_provider = mcp_client_provider
        if mcp_client is None and mcp_client_provider is None and config.mode == "real":
            raise ValueError("A real diagnosis requires an MCP client or provider.")

    async def run(self, context: BackgroundJobContext) -> None:
        """Execute or resume the investigation; terminals are committed atomically."""
        scope = context.execution_scope
        runtime = self._runtime_repository()
        task = await self._repositories.diagnostics.get_task(
            owner_user_id=scope.owner_user_id,
            task_id=scope.task_id,
        )
        if task is None:
            raise RuntimeError("Diagnostic task is unavailable.")
        run = self._new_run(
            context=context, scope=scope, runtime=runtime, task_input=task.input_payload,
            query=task.query,
        )
        stored = await runtime.load_state(owner_user_id=scope.owner_user_id, task_id=scope.task_id)
        if stored is not None:
            decision = plan_diagnostic_recovery(
                stored,
                clock=self._clock,
                cancelled=context.job.cancel_requested_at is not None,
            )
            if decision.next_node == "end":
                return
            run.adopt_checkpoint(decision.checkpoint)
            run.adopt_interrupted(decision.interrupted_queries)
        graph = self._build_graph(run)
        try:
            await graph.ainvoke(run.graph_state(), config={"recursion_limit": 80})
        except (BudgetExpired, BudgetUnavailable) as exc:
            run.limitation(f"预算限制提前结束：{exc.__class__.__name__}。")
            await run.finish_programmatically(stop_reason="budget_exhausted")
        except DiagnosisExecutionError as exc:
            run.limitation(FINAL_FAILURE_NOTE)
            await run.finish_programmatically(
                status="failed", stop_reason=None, failure_reason=str(exc) or None
            )
        except DiagnosticLeaseLost:
            emit_event(logger, "agent.aiops.lease_lost", diagnosticTaskId=scope.task_id)
            raise
        except Exception as exc:  # 未预期异常也必须留下一致终态
            emit_event(
                logger,
                "agent.aiops.failed",
                diagnosticTaskId=scope.task_id,
                errorCategory=exc.__class__.__name__,
            )
            run.limitation(FINAL_FAILURE_NOTE)
            await run.finish_programmatically(
                status="failed",
                stop_reason=None,
                failure_reason=f"Diagnostic execution failed: {exc.__class__.__name__}.",
            )

    async def terminate(
        self, context: BackgroundJobContext, status: Literal["failed", "cancelled"], reason: str
    ) -> None:
        """Runtime finalizer: commit a durable terminal without new model or tool calls."""
        scope = context.execution_scope
        runtime = self._runtime_repository()
        task = await self._repositories.diagnostics.get_task(
            owner_user_id=scope.owner_user_id,
            task_id=scope.task_id,
        )
        run = self._new_run(
            context=context,
            scope=scope,
            runtime=runtime,
            task_input=task.input_payload if task is not None else {},
            query=task.query if task is not None else "",
        )
        stored = await runtime.load_state(owner_user_id=scope.owner_user_id, task_id=scope.task_id)
        if stored is not None:
            decision = plan_diagnostic_recovery(stored, clock=self._clock, cancelled=True)
            run.adopt_checkpoint(decision.checkpoint)
            run.adopt_interrupted(decision.interrupted_queries)
        if status == "cancelled":
            await run.finish_programmatically(status="cancelled", cancelled=True)
            return
        await run.finish_programmatically(status="failed", stop_reason=None, failure_reason=reason)

    def _runtime_repository(self):
        repository = self._repositories.diagnosis_runtime
        if repository is None:
            raise RuntimeError("Diagnostic runtime storage is unavailable.")
        return repository

    def _new_run(
        self,
        *,
        context: BackgroundJobContext,
        scope: DiagnosticExecutionScope,
        runtime: Any,
        task_input: JsonDict,
        query: str,
    ) -> _Run:
        return _Run(
            context=context,
            scope=scope,
            runtime=runtime,
            config=self._config,
            clock=self._clock,
            llm_provider=self._llm_provider,
            cls_defaults=ClsSearchDefaults(
                region=self._cls_region, topic_id=self._cls_topic_id
            ),
            toolbox_factory=self._toolbox_for,
            alert=_dict(task_input.get("alert")),
            query=query,
        )

    async def _toolbox_for(
        self, owner_user_id: str, context: DiagnosisContext
    ) -> DiagnosisToolbox:
        if self._config.mode == "mock":
            return build_mock_diagnosis_toolbox(context)
        client = await self._diagnostic_client(owner_user_id=owner_user_id)
        return await build_real_diagnosis_toolbox(client=client)

    async def _diagnostic_client(self, *, owner_user_id: str) -> LocalMcpClient:
        timeout = float(self._config.tool_timeout_seconds)
        if self._mcp_client_provider is not None:
            return await self._mcp_client_provider.diagnostic_client_for_user(
                owner_user_id=owner_user_id, timeout_seconds=timeout
            )
        if self._mcp_client is None:
            raise McpClientError("MCP client is unavailable.")
        return self._mcp_client.diagnostic_copy(timeout_seconds=timeout)

    def _build_graph(self, run: _Run) -> Any:
        graph: Any = StateGraph(DiagnosisStreamState)
        graph.add_node("prepare_context", run.prepare_context)
        graph.add_node("build_queries", run.build_queries)
        graph.add_node("execute_queries", run.execute_queries)
        graph.add_node("revise_hypotheses", run.revise_hypotheses)
        graph.add_node("assess_hypotheses", run.assess_hypotheses)
        graph.add_node("finalize", run.finalize)
        graph.add_node("report", run.report)
        graph.add_conditional_edges(
            START,
            _state_route,
            {name: name for name in _NODE_NAMES},
        )
        graph.add_edge("prepare_context", "build_queries")
        graph.add_conditional_edges(
            "build_queries",
            _state_route,
            {
                "build_queries": "build_queries",
                "execute_queries": "execute_queries",
                "assess_hypotheses": "assess_hypotheses",
                "finalize": "finalize",
            },
        )
        graph.add_edge("execute_queries", "revise_hypotheses")
        graph.add_conditional_edges(
            "revise_hypotheses",
            _state_route,
            {"assess_hypotheses": "assess_hypotheses", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "assess_hypotheses",
            _state_route,
            {
                "build_queries": "build_queries",
                "revise_hypotheses": "revise_hypotheses",
                "finalize": "finalize",
            },
        )
        graph.add_edge("finalize", "report")
        graph.add_edge("report", END)
        return graph.compile()


_NODE_NAMES = (
    "prepare_context",
    "build_queries",
    "execute_queries",
    "revise_hypotheses",
    "assess_hypotheses",
    "finalize",
    "report",
)


def _state_route(state: DiagnosisStreamState) -> str:
    route = state.get("route")
    if route in _NODE_NAMES or route == "end":
        return str(route)
    return "prepare_context"


class ToolError(RuntimeError):
    """A single tool failure that the graph records without aborting other calls."""


class _EmptyRealToolbox:
    """Real mode without discovered tools: report the gap, never fabricate data."""

    @property
    def tool_names(self) -> frozenset[str]:
        return frozenset()

    async def execute(
        self, *, tool_name: str, arguments: Mapping[str, JsonValue], timeout_seconds: float
    ) -> ToolExecution:
        del arguments, timeout_seconds
        return ToolExecution(
            tool_name=tool_name,
            status="failed",
            status_reason="当前用户没有已启用的真实工具。",
        )


@dataclass(frozen=True, slots=True)
class _PreparedCall:
    arguments: dict[str, JsonValue]
    skipped_reason: str | None = None


@dataclass(slots=True)
class _State:
    checkpoint: JsonDict
    route: str = "prepare_context"
    working: JsonDict = field(default_factory=dict)


class _Run:
    """Per-run orchestration: budget, tools, prompts and durable commits."""

    def __init__(
        self,
        *,
        context: BackgroundJobContext,
        scope: DiagnosticExecutionScope,
        runtime: Any,
        config: DiagnosisConfig,
        clock: DiagnosisClock,
        llm_provider: LlmProvider,
        cls_defaults: ClsSearchDefaults,
        toolbox_factory: Callable[[str, DiagnosisContext], Awaitable[DiagnosisToolbox]],
        alert: JsonDict,
        query: str,
    ) -> None:
        self._context = context
        self._scope = scope
        self._runtime = runtime
        self._config = config
        self._clock = clock
        self._llm_provider = llm_provider
        self._cls_defaults = cls_defaults
        self._toolbox_factory = toolbox_factory
        self._alert_input = alert
        self._query = query
        self._controller: DiagnosticBudgetController | None = None
        self._toolbox: DiagnosisToolbox | None = None
        self._context_snapshot: DiagnosisContext | None = None
        self._guard = RepeatedFailureGuard()
        self._commit_lock = asyncio.Lock()
        self.state = _State(checkpoint={})

    # ---------- checkpoint plumbing ----------

    def seed_checkpoint(self, *, mode: Literal["real", "mock"]) -> None:
        controller = DiagnosticBudgetController.start(self._config, clock=self._clock)
        checkpoint: JsonDict = {
            "input": {"alert": dict(self._alert_input), "query": self._query},
            "runtime": {
                "engine": ENGINE,
                "mode": mode,
                "next_node": "prepare_context",
                "revision": 0,
                "phase": "prepare_context",
                "round_index": 0,
                "nodes": [],
                "operations": {},
                "tool_names": [],
                "report_fallback": False,
                "budget_stop": False,
                **controller.snapshot().model_dump(mode="json"),
            },
            "working_state": {
                "hypotheses": [],
                "hypothesis_relations": [],
                "incident_conclusion": None,
                "query_plan": None,
                "unmet_requests": [],
                "query_records": [],
                "evidence_ids": [],
                "unassessed_evidence_ids": [],
                "assessment_is_current": True,
                "initialization_failed": False,
                "data_unavailable": False,
                "limitations": [],
            },
            "last_valid_assessment": None,
        }
        self.state.checkpoint = checkpoint
        self.state.working = _dict(checkpoint["working_state"])
        self._controller = controller

    def adopt_checkpoint(self, checkpoint: JsonDict) -> None:
        self.state.checkpoint = checkpoint
        self.state.working = _dict(checkpoint.get("working_state"))
        runtime = _dict(checkpoint.get("runtime"))
        self.state.route = str(runtime.get("next_node") or "prepare_context")
        self._controller = (
            DiagnosticBudgetController(_budget_state(runtime), clock=self._clock)
            if "budget" in runtime
            else None
        )

    def adopt_interrupted(self, queries: Sequence[QueryRecord]) -> None:
        records = [*self._query_records(), *queries]
        self._patch_working(query_records=[record.model_dump(mode="json") for record in records])
        if queries:
            self.limitation("服务中断：调用结果未提交，未重放这些请求。")

    def graph_state(self) -> DiagnosisStreamState:
        return {**cast(DiagnosisStreamState, self.state.working), "route": self.state.route}

    def _node_return(self) -> DiagnosisStreamState:
        return {
            **cast(DiagnosisStreamState, self.state.working),
            "route": self.state.route,
        }

    # ---------- accessors ----------

    @property
    def _runtime_state(self) -> JsonDict:
        return _dict(self.state.checkpoint.get("runtime"))

    def _budget(self) -> DiagnosticBudgetController:
        if self._controller is None:
            raise DiagnosisExecutionError("Diagnostic budget is not initialised.")
        return self._controller

    def _toolbox_ref(self) -> DiagnosisToolbox:
        if self._toolbox is None:
            raise DiagnosisExecutionError("Diagnostic tools are not initialised.")
        return self._toolbox

    def _context_ref(self) -> DiagnosisContext:
        if self._context_snapshot is None:
            raise DiagnosisExecutionError("Diagnostic context is not initialised.")
        return self._context_snapshot

    def limitation(self, text: str) -> None:
        limitations = _list(self.state.working.get("limitations"))
        if text not in limitations:
            limitations.append(text)
        self.state.working["limitations"] = limitations

    def _hypotheses(self) -> list[Hypothesis]:
        return [
            Hypothesis.model_validate(item) for item in _list(self.state.working.get("hypotheses"))
        ]

    def _relations(self) -> list[HypothesisRelation]:
        return [
            HypothesisRelation.model_validate(item)
            for item in _list(self.state.working.get("hypothesis_relations"))
        ]

    def _conclusion(self) -> IncidentConclusion | None:
        raw = self.state.working.get("incident_conclusion")
        return IncidentConclusion.model_validate(raw) if raw is not None else None

    def _query_records(self) -> list[QueryRecord]:
        return [
            QueryRecord.model_validate(item)
            for item in _list(self.state.working.get("query_records"))
        ]

    def _evidence_ids(self) -> list[str]:
        return [str(item) for item in _list(self.state.working.get("evidence_ids"))]

    def _next_action(self) -> str:
        return str(self.state.working.get("next_action") or "build_queries")

    def _scenario(self) -> MockScenario | None:
        """Prefer the prepared snapshot; fall back to the persisted context."""
        if self._context_snapshot is not None:
            return self._context_snapshot.scenario
        raw = _dict(_dict(self._runtime_state.get("context")).get("scenario"))
        return MockScenario.model_validate(raw) if raw else None

    def _alert(self) -> _AlertContext:
        scenario = self._scenario()
        alert = _dict(_dict(self.state.checkpoint.get("input")).get("alert"))
        primary = _alert_context(alert)
        if primary.service and (primary.starts_at_ms is not None or scenario is None):
            return _AlertContext(
                service=primary.service,
                instance=primary.instance or (scenario.alert.instance if scenario else ""),
                starts_at_ms=primary.starts_at_ms
                or (timestamp_ms(scenario.alert.starts_at) if scenario else None),
                summary=primary.summary or (scenario.alert.summary if scenario else ""),
            )
        if scenario is not None:
            return _AlertContext(
                service=scenario.alert.service,
                instance=scenario.alert.instance,
                starts_at_ms=timestamp_ms(scenario.alert.starts_at),
                summary=scenario.alert.summary,
            )
        return primary

    def _revision(self) -> int:
        return _int(self._runtime_state.get("revision"), default=0)

    def _patch_runtime(self, **values: object) -> None:
        runtime = dict(self._runtime_state)
        runtime.update(values)
        self.state.checkpoint = {**self.state.checkpoint, "runtime": runtime}

    def _patch_working(self, **values: object) -> None:
        working = dict(self.state.working)
        working.update(values)
        self.state.working = working
        self.state.checkpoint = {**self.state.checkpoint, "working_state": working}

    def _sync_budget(self) -> None:
        self._patch_runtime(**self._budget().snapshot().model_dump(mode="json"))

    # ---------- durable commits ----------

    async def _commit_node(
        self,
        *,
        node: str,
        operation_id: str,
        phase: str,
        payload: JsonDict,
        events: list[JsonDict],
        result_payload: JsonDict | None = None,
    ) -> None:
        self._sync_budget()
        self._patch_runtime(next_node=node, phase=phase)
        if operation_id not in _list(self._runtime_state.get("nodes")):
            nodes = [*_list(self._runtime_state.get("nodes")), operation_id]
            self._patch_runtime(nodes=nodes)
        self._patch_working(
            hypotheses=[item.model_dump(mode="json") for item in self._hypotheses()],
            hypothesis_relations=[item.model_dump(mode="json") for item in self._relations()],
            query_records=[item.model_dump(mode="json") for item in self._query_records()],
        )
        result = await self._runtime.commit_diagnostic_node(
            scope=self._scope,
            write=DiagnosticNodeWrite(
                operation_id=operation_id,
                expected_revision=self._revision(),
                checkpoint=self.state.checkpoint,
                phase=phase,
                payload=payload,
                events=events,
                result_payload=result_payload,
            ),
        )
        self._adopt(result.checkpoint)

    async def _reserve(
        self,
        *,
        operation_id: str,
        kind: Literal["model", "tool"],
        phase: TimePhase,
        stage: Literal["reserve", "dispatch"],
        query: JsonDict | None = None,
        events: list[JsonDict] | None = None,
    ) -> None:
        self._sync_budget()
        result = await self._runtime.reserve_diagnostic_operation(
            scope=self._scope,
            write=DiagnosticReservationWrite(
                operation_id=operation_id,
                expected_revision=self._revision(),
                checkpoint=self.state.checkpoint,
                kind=kind,
                phase=phase,
                query=query,
                events=events,
                stage=stage,
            ),
        )
        self._adopt(result.checkpoint)

    def _adopt(self, checkpoint: JsonDict) -> None:
        self.state.checkpoint = checkpoint
        self.state.working = _dict(checkpoint.get("working_state"))
        runtime = _dict(checkpoint.get("runtime"))
        if self._controller is not None:
            self._controller.state = _budget_state(runtime)

    async def _guard_boundaries(self, *, phase: TimePhase) -> None:
        await self._context.raise_if_lease_lost()
        await self._context.raise_if_cancelled()
        if self._budget().remaining(phase) <= 0:
            raise BudgetExpired(phase)

    # ---------- model access ----------

    async def _invoke_model(self, *, phase: TimePhase, prompt: str) -> str:
        timeout = self._budget().timeout(phase, float(self._config.model_timeout_seconds))
        model = self._llm_provider.create_diagnostic_model(timeout_seconds=timeout)
        response = await asyncio.wait_for(model.ainvoke(prompt), timeout=timeout)
        return _model_text(response)

    async def _structured_output(
        self,
        *,
        node: str,
        phase: TimePhase,
        operation_id: str,
        prompt: str,
        parse: Callable[[str], tuple[ModelT | None, str | None]],
    ) -> ModelT:
        """Reserve one model intent, allow a single structured correction, then stop."""
        await self._reserve(operation_id=operation_id, kind="model", phase=phase, stage="reserve")
        try:
            text = await self._invoke_model(phase=phase, prompt=prompt)
        except (asyncio.TimeoutError, BudgetExpired) as exc:
            raise DiagnosisExecutionError(f"{node} model request timed out.") from exc
        except Exception as exc:
            raise DiagnosisExecutionError(
                f"{node} model request failed: {exc.__class__.__name__}."
            ) from exc
        value, error = parse(text)
        if value is not None:
            return value
        correction_prompt = (
            f"{prompt}\n\n上一次输出不符合结构要求：{error}\n"
            "只返回修正后的 JSON，不要解释，也不要新增字段。"
        )
        emit_event(logger, "agent.aiops.output_corrected", node=node)
        try:
            corrected = await self._invoke_model(phase=phase, prompt=correction_prompt)
        except (asyncio.TimeoutError, BudgetExpired) as exc:
            raise DiagnosisExecutionError(f"{node} correction timed out.") from exc
        except Exception as exc:
            raise DiagnosisExecutionError(
                f"{node} correction failed: {exc.__class__.__name__}."
            ) from exc
        value, error = parse(corrected)
        if value is None:
            raise DiagnosisOutputInvalid(f"{node} output stayed invalid: {error}")
        return value

    # ---------- nodes ----------

    async def prepare_context(self, state: DiagnosisStreamState) -> DiagnosisStreamState:
        del state
        await self._context.raise_if_lease_lost()
        await self._context.raise_if_cancelled()
        if not self.state.checkpoint.get("runtime"):
            self.seed_checkpoint(mode=self._config.mode)
        try:
            context = prepare_diagnosis_context(self._config)
        except DiagnosisContentError as exc:
            self.limitation(f"内容准备失败：{exc}")
            self._patch_working(initialization_failed=True)
            self.state.route = "finalize"
            return self._node_return()
        self._context_snapshot = context
        try:
            toolbox = await self._toolbox_factory(self._scope.owner_user_id, context)
        except McpClientError as exc:
            emit_event(logger, "agent.aiops.tool_unavailable", errorCategory=str(exc))
            toolbox = _EmptyRealToolbox()
        self._toolbox = toolbox
        if not toolbox.tool_names:
            self.limitation("当前模式没有可用工具，只能回报能力缺口。")
        self._patch_runtime(
            mode=context.mode,
            tool_names=sorted(toolbox.tool_names),
            context=context.model_dump(mode="json"),
        )
        await self._commit_node(
            node="prepare_context",
            operation_id="prepare_context",
            phase="prepare_context",
            payload={
                "mode": context.mode,
                "toolNames": sorted(toolbox.tool_names),
                "knowledgeServices": sorted(context.knowledge.services),
            },
            events=[
                _task_status_event(
                    self._scope.task_id,
                    "running",
                    "已固定本次调查内容与可用工具，开始构建查询。",
                    10,
                    "prepare_context",
                )
            ],
        )
        self.state.route = "build_queries"
        return self._node_return()

    async def build_queries(self, state: DiagnosisStreamState) -> DiagnosisStreamState:
        del state
        await self._guard_boundaries(phase="exploration")
        budget = self._budget()
        if not budget.can_query():
            self._patch_working(next_action="finalize")
            self.state.route = "finalize"
            return self._node_return()
        round_index = _int(self._runtime_state.get("round_index"), default=0) + 1
        self._patch_runtime(round_index=round_index, phase="build_queries")
        operation_id = f"build_queries:{round_index}"
        available = _list(self._runtime_state.get("tool_names"))
        remaining_calls = (
            budget.state.budget.max_tool_calls
            - budget.state.budget.tool_calls_used
            - budget.state.budget.unknown_tool_calls
        )
        max_calls = max(0, min(self._config.max_calls_per_batch, remaining_calls))
        prompt = self._build_queries_prompt(available=available, max_calls=max_calls)
        plan = await self._structured_output(
            node="build_queries",
            phase="exploration",
            operation_id=operation_id,
            prompt=prompt,
            parse=lambda text: self._parse_query_plan(text, max_calls=max_calls),
        )
        if not plan.calls:
            if self._budget().state.budget.internal_steps_used >= self._config.max_internal_steps:
                self.limitation("可执行查询为空且内部往返额度已用尽。")
                self._patch_working(next_action="finalize")
                self.state.route = "finalize"
                return self._node_return()
            self._record_plan(plan)
            self._consume_internal_step()
            await self._commit_node(
                node="build_queries",
                operation_id=operation_id,
                phase="build_queries",
                payload={"calls": 0, "unmetRequests": len(plan.unmet_requests)},
                events=[
                    _task_status_event(
                        self._scope.task_id,
                        "running",
                        "本轮没有可执行查询，回流确认替代路径。",
                        20 + round_index,
                        "build_queries",
                    )
                ],
            )
            self.state.route = "build_queries"
            return self._node_return()
        self._record_plan(plan)
        await self._commit_node(
            node="build_queries",
            operation_id=operation_id,
            phase="build_queries",
            payload={
                "calls": [
                    {"tool": call.tool_name, "question": call.question} for call in plan.calls
                ],
                "unmetRequests": [item.requirement for item in plan.unmet_requests],
            },
            events=[
                _task_status_event(
                    self._scope.task_id,
                    "running",
                    f"已构建 {len(plan.calls)} 个查询，准备执行。",
                    20 + round_index,
                    "build_queries",
                )
            ],
        )
        self.state.route = "execute_queries"
        return self._node_return()

    async def execute_queries(self, state: DiagnosisStreamState) -> DiagnosisStreamState:
        del state
        plan = self._current_plan()
        if plan is None or not plan.calls:
            self.state.route = "assess_hypotheses" if self._hypotheses() else "finalize"
            return self._node_return()
        await self._guard_boundaries(phase="exploration")
        round_index = _int(self._runtime_state.get("round_index"), default=1)
        batch_id = f"batch:{round_index}"
        first_round = not self._hypotheses()
        timeout = self._budget().timeout("exploration", float(self._config.tool_timeout_seconds))
        semaphore = asyncio.Semaphore(self._concurrency(len(plan.calls)))
        outcome = _RoundResult(calls_planned=len(plan.calls))

        async def run_call(index: int, call: Any) -> None:
            query_id = f"call:{round_index}:{index}"
            async with semaphore:
                async with self._commit_lock:
                    prepared = await self._begin_call(
                        query_id=query_id, batch_id=batch_id, call=call
                    )
                if prepared.skipped_reason is not None:
                    outcome.calls_failed += 1
                    self.limitation(prepared.skipped_reason)
                    return
                execution = await self._run_tool(
                    call=call, arguments=prepared.arguments, timeout_seconds=timeout
                )
                async with self._commit_lock:
                    await self._commit_call_outcome(
                        query_id=query_id,
                        call=call,
                        execution=execution,
                        arguments=prepared.arguments,
                    )
            if execution.status == "succeeded":
                outcome.calls_succeeded += 1
                outcome.business_records += 1 if _has_business_records(execution.data) else 0
            else:
                outcome.calls_failed += 1

        await asyncio.gather(*(run_call(index, call) for index, call in enumerate(plan.calls)))
        self._finish_new_batch(batch_id)
        if first_round and outcome.calls_succeeded == 0:
            self.limitation("首轮所有查询均失败，未能取得任何现场事实。")
            self._patch_working(initialization_failed=True, data_unavailable=True)
        elif first_round and outcome.business_records == 0:
            self.limitation("首轮查询均未返回业务记录，未能取得现场事实。")
            self._patch_working(initialization_failed=True)
        await self._commit_node(
            node="execute_queries",
            operation_id=f"execute_queries:{round_index}",
            phase="execute_queries",
            payload={
                "planned": outcome.calls_planned,
                "succeeded": outcome.calls_succeeded,
                "failed": outcome.calls_failed,
            },
            events=[
                _task_status_event(
                    self._scope.task_id,
                    "running",
                    f"本轮完成 {outcome.calls_succeeded} 个成功查询。",
                    30 + round_index,
                    "execute_queries",
                )
            ],
        )
        if bool(self.state.working.get("initialization_failed")):
            self._patch_working(next_action="finalize")
            self.state.route = "finalize"
            return self._node_return()
        self.state.route = "revise_hypotheses"
        return self._node_return()

    async def revise_hypotheses(self, state: DiagnosisStreamState) -> DiagnosisStreamState:
        del state
        await self._guard_boundaries(phase="exploration")
        try:
            self._budget().consume_internal_step()
        except BudgetUnavailable:
            self.limitation("内部往返额度已用尽，无法继续细化假设。")
            self._budget_stop()
            self.state.route = "finalize"
            return self._node_return()
        round_index = _int(self._runtime_state.get("round_index"), default=1)
        operation_id = f"revise_hypotheses:{round_index}"
        current = self._hypotheses()
        prompt = self._revise_prompt(current)
        revision = await self._structured_output(
            node="revise_hypotheses",
            phase="exploration",
            operation_id=operation_id,
            prompt=prompt,
            parse=lambda text: self._parse_revision(text),
        )
        if not revision.new_hypotheses and not revision.revised_hypotheses:
            if not current:
                self.limitation("已返回现场数据，但没有形成任何有依据的初始假设。")
                self._patch_working(initialization_failed=True)
                await self._commit_node(
                    node="revise_hypotheses",
                    operation_id=operation_id,
                    phase="revise_hypotheses",
                    payload={"new": 0, "revised": 0, "initializationFailed": True},
                    events=[],
                )
                self.state.route = "finalize"
                return self._node_return()
            await self._commit_node(
                node="revise_hypotheses",
                operation_id=operation_id,
                phase="revise_hypotheses",
                payload={"new": 0, "revised": 0},
                events=[],
            )
            self.state.route = "assess_hypotheses"
            return self._node_return()
        applied_new, applied_revised = self._apply_revision(revision)
        await self._commit_node(
            node="revise_hypotheses",
            operation_id=operation_id,
            phase="revise_hypotheses",
            payload={"new": applied_new, "revised": applied_revised},
            events=[
                _task_status_event(
                    self._scope.task_id,
                    "running",
                    f"假设更新：新增 {len(applied_new)} 个，细化 {len(applied_revised)} 个。",
                    40 + round_index,
                    "revise_hypotheses",
                )
            ],
        )
        self.state.route = "assess_hypotheses"
        return self._node_return()

    async def assess_hypotheses(self, state: DiagnosisStreamState) -> DiagnosisStreamState:
        del state
        final_analysis = self._is_final_analysis()
        phase: TimePhase = "analysis" if final_analysis else "exploration"
        await self._guard_boundaries(phase=phase)
        round_index = _int(self._runtime_state.get("round_index"), default=1)
        operation_id = f"assess_hypotheses:{round_index}"
        prompt = self._assess_prompt(final_analysis=final_analysis)
        assessment = await self._structured_output(
            node="assess_hypotheses",
            phase=phase,
            operation_id=operation_id,
            prompt=prompt,
            parse=lambda text: self._parse_assessment(
                text, final_analysis=final_analysis, operation_id=operation_id
            ),
        )
        self._apply_assessment(assessment)
        self._record_last_valid_assessment()
        await self._commit_node(
            node="assess_hypotheses",
            operation_id=operation_id,
            phase="assess_hypotheses",
            payload={
                "assessed": [item.hypothesis_id for item in assessment.hypothesis_assessments],
                "relations": len(assessment.hypothesis_relations),
                "conclusion": assessment.incident_conclusion.conclusion_status,
                "nextAction": assessment.next_step.action,
                "finalAnalysis": final_analysis,
            },
            events=[
                _task_status_event(
                    self._scope.task_id,
                    "running",
                    f"评估完成：{assessment.incident_conclusion.explanation[:60]}",
                    60 + round_index,
                    "assess_hypotheses",
                    diagnosis=self._public_diagnosis(),
                )
            ],
            result_payload=self._result_payload(),
        )
        action = assessment.next_step.action
        if final_analysis and action != "finalize":
            self.limitation("最后分析阶段只能收尾，已按程序收尾。")
            action = "finalize"
        if action == "build_queries" and not self._budget().can_query():
            self.limitation("预算或时间已不允许新查询，转为收尾。")
            action = "finalize"
            self._budget_stop()
        self._patch_working(next_action=action)
        self.state.route = action
        return self._node_return()

    async def finalize(self, state: DiagnosisStreamState) -> DiagnosisStreamState:
        del state
        await self._context.raise_if_lease_lost()
        working = dict(self.state.working)
        hypotheses = self._hypotheses()
        frozen = [
            hypothesis.model_copy(
                update={
                    "hypothesis_status": (
                        "unresolved"
                        if hypothesis.hypothesis_status in {"pending", "investigating", "blocked"}
                        else hypothesis.hypothesis_status
                    )
                }
            )
            for hypothesis in hypotheses
        ]
        working["hypotheses"] = [item.model_dump(mode="json") for item in frozen]
        self.state.working = working
        conclusion = self._conclusion()
        status: Literal["succeeded", "failed"] = "succeeded"
        stop_reason: (
            Literal["root_cause_confirmed", "budget_exhausted", "critical_data_unavailable"] | None
        ) = None
        if conclusion is not None and conclusion.conclusion_status == "confirmed":
            stop_reason = "root_cause_confirmed"
        elif bool(working.get("initialization_failed")):
            status = "failed"
            self.limitation("初始化未完成：现场数据不足以形成可评估的假设。")
        elif bool(working.get("data_unavailable")):
            stop_reason = "critical_data_unavailable"
        else:
            stop_reason = "budget_exhausted"
        if (
            conclusion is not None
            and conclusion.conclusion_status == "confirmed"
            and status == "failed"
        ):
            status = "succeeded"
        if conclusion is None:
            conclusion = IncidentConclusion(
                conclusion_status="unconfirmed",
                root_cause=None,
                stop_reason=stop_reason,
                explanation="本次调查结束，未确认事故根本原因。",
            )
        elif conclusion.stop_reason != stop_reason:
            conclusion = conclusion.model_copy(
                update={
                    "stop_reason": stop_reason,
                    "root_cause": conclusion.root_cause
                    if conclusion.conclusion_status == "confirmed"
                    else None,
                }
            )
        working["incident_conclusion"] = conclusion.model_dump(mode="json")
        self.state.working = working
        self._patch_working(final_status=status)
        await self._commit_node(
            node="finalize",
            operation_id="finalize",
            phase="finalize",
            payload={"status": status, "stopReason": stop_reason},
            events=[
                _task_status_event(
                    self._scope.task_id,
                    "running",
                    "调查已收尾，正在生成报告。",
                    90,
                    "finalize",
                    diagnosis=self._public_diagnosis(),
                )
            ],
            result_payload=self._result_payload(),
        )
        self.state.route = "report"
        return self._node_return()

    async def report(self, state: DiagnosisStreamState) -> DiagnosisStreamState:
        del state
        await self._context.raise_if_lease_lost()
        model_body = await self._report_model_body()
        facts = self._report_facts()
        report = build_diagnosis_report(facts=facts, model_body=model_body)
        if report.body_source == "program" and model_body is not None:
            self.limitation("报告模型正文与结论不一致，已改用程序兜底正文。")
        status = str(self.state.working.get("final_status") or "succeeded")
        await self._finish(
            status=cast(Literal["succeeded", "failed", "cancelled"], status),
            title=report.title,
            content=report.content,
        )
        self.state.route = "end"
        return self._node_return()

    # ---------- query execution helpers ----------

    async def _begin_call(self, *, query_id: str, batch_id: str, call: Any) -> _PreparedCall:
        """Reserve and dispatch one call; the external request happens outside the lock."""
        arguments = _json_arguments(call.arguments)
        query: JsonDict = {
            "query_id": query_id,
            "hypothesis_ids": [str(item) for item in call.hypothesis_ids],
            "question": call.question,
            "tool_name": call.tool_name,
            "arguments": arguments,
        }
        try:
            self._guard.check(tool_name=call.tool_name, arguments=arguments)
        except DiagnosisToolError as exc:
            return _PreparedCall(arguments=arguments, skipped_reason=str(exc))
        self._budget().reserve_call(query_id=query_id, batch_id=batch_id)
        await self._reserve(
            operation_id=query_id, kind="tool", phase="exploration", stage="reserve", query=query
        )
        self._budget().mark_dispatched(query_id)
        await self._reserve(
            operation_id=query_id,
            kind="tool",
            phase="exploration",
            stage="dispatch",
            query=query,
            events=[_tool_event(query_id, call.tool_name, "started", arguments)],
        )
        return _PreparedCall(arguments=arguments)

    async def _run_tool(
        self, *, call: Any, arguments: dict[str, JsonValue], timeout_seconds: float
    ) -> ToolExecution:
        try:
            return await self._toolbox_ref().execute(
                tool_name=call.tool_name,
                arguments=arguments,
                timeout_seconds=timeout_seconds,
            )
        except DiagnosisToolError as exc:
            return ToolExecution(call.tool_name, "failed", str(exc))
        except (asyncio.TimeoutError, BudgetExpired):
            return ToolExecution(call.tool_name, "failed", "工具调用超时。")
        except Exception as exc:
            return ToolExecution(
                call.tool_name, "failed", f"工具调用失败：{exc.__class__.__name__}。"
            )

    async def _commit_call_outcome(
        self,
        *,
        query_id: str,
        call: Any,
        execution: ToolExecution,
        arguments: dict[str, JsonValue],
    ) -> None:
        succeeded = execution.status == "succeeded"
        has_records = succeeded and _has_business_records(execution.data)
        status_reason = (
            "工具已返回记录。"
            if has_records
            else ("工具无匹配记录。" if succeeded else execution.status_reason)
        )
        record = QueryRecord(
            query_id=query_id,
            hypothesis_ids=[str(item) for item in call.hypothesis_ids],
            question=call.question,
            tool_name=call.tool_name,
            arguments=arguments,
            status="succeeded" if succeeded else "failed",
            status_reason=status_reason,
        )
        evidence: list[DiagnosticEvidenceWrite] = []
        if has_records:
            evidence_id = f"evidence:{query_id}"
            evidence.append(
                DiagnosticEvidenceWrite(
                    evidence_id=evidence_id,
                    kind=_evidence_kind(call.tool_name),
                    source=call.tool_name,
                    summary=status_reason,
                    payload={"data": cast(JsonValue, execution.data)},
                )
            )
            working = self.state.working
            self._patch_working(
                evidence_ids=[*self._evidence_ids(), evidence_id],
                unassessed_evidence_ids=[
                    *[str(item) for item in _list(working.get("unassessed_evidence_ids"))],
                    evidence_id,
                ],
                assessment_is_current=False,
            )
        self._budget().complete_call(query_id)
        if not succeeded:
            self._guard.record_failure(tool_name=call.tool_name, arguments=arguments)
        self._sync_budget()
        self._patch_working(
            query_records=[
                record.model_dump(mode="json") for record in [*self._query_records(), record]
            ]
        )
        result = await self._runtime.commit_diagnostic_query(
            scope=self._scope,
            write=DiagnosticQueryWrite(
                operation_id=query_id,
                expected_revision=self._revision(),
                checkpoint=self.state.checkpoint,
                query=record.model_dump(mode="json"),
                evidence=evidence,
                events=[
                    _tool_event(
                        query_id, call.tool_name, "completed" if succeeded else "failed", None
                    )
                ],
            ),
        )
        self._adopt(result.checkpoint)

    def _finish_new_batch(self, batch_id: str) -> None:
        try:
            self._budget().finish_batch(batch_id)
        except BudgetUnavailable:
            emit_event(logger, "agent.aiops.batch_open", batchId=batch_id)

    def _consume_internal_step(self) -> None:
        self._budget().consume_internal_step()

    def _budget_stop(self) -> None:
        self._patch_runtime(budget_stop=True)

    def _concurrency(self, planned: int) -> int:
        budget = self._budget()
        remaining_calls = (
            budget.state.budget.max_tool_calls
            - budget.state.budget.tool_calls_used
            - budget.state.budget.unknown_tool_calls
        )
        limit = max(
            1,
            min(
                self._config.max_concurrent_calls,
                self._config.max_calls_per_batch,
                planned,
                max(1, remaining_calls),
            ),
        )
        if budget.remaining("exploration") < float(self._config.tool_timeout_seconds):
            return 1
        return limit

    def _is_final_analysis(self) -> bool:
        budget = self._budget()
        if budget.remaining("exploration") <= 0:
            return True
        counters = budget.state.budget
        return (
            counters.rounds_used >= counters.max_rounds
            or counters.tool_calls_used + counters.unknown_tool_calls >= counters.max_tool_calls
        )

    def _current_plan(self) -> QueryPlan | None:
        raw = self.state.working.get("query_plan")
        return QueryPlan.model_validate(raw) if raw is not None else None

    def _record_plan(self, plan: QueryPlan) -> None:
        self._patch_working(
            query_plan=plan.model_dump(mode="json"),
            unmet_requests=[item.model_dump(mode="json") for item in plan.unmet_requests],
        )

    # ---------- application logic ----------

    def _apply_revision(self, revision: HypothesisRevision) -> tuple[list[str], list[str]]:
        hypotheses = self._hypotheses()
        by_id = {item.hypothesis_id: item for item in hypotheses}
        applied_new: list[str] = []
        applied_revised: list[str] = []
        for item in revision.revised_hypotheses:
            existing = by_id.get(item.hypothesis_id)
            if existing is None:
                continue
            by_id[item.hypothesis_id] = existing.model_copy(
                update={
                    "statement": item.statement,
                    "hypothesis_status": "pending",
                    "assessment": "解释已在本次调查中细化，等待依据现有证据重新评估。",
                    "evidence_links": [],
                    "gaps": [],
                }
            )
            applied_revised.append(item.hypothesis_id)
        next_index = (
            max((_identifier_number(item.hypothesis_id) for item in hypotheses), default=0) + 1
        )
        for offset, item in enumerate(revision.new_hypotheses):
            hypothesis_id = f"H{next_index + offset}"
            by_id[hypothesis_id] = Hypothesis(
                hypothesis_id=hypothesis_id,
                statement=item.statement,
                hypothesis_status="pending",
                assessment="本次调查新增的解释，等待依据现有证据评估。",
                evidence_links=[],
                gaps=[],
            )
            applied_new.append(hypothesis_id)
        if applied_revised:
            self._patch_working(hypothesis_relations=[], incident_conclusion=None)
            self.limitation("解释被细化，原有关联与事故结论已失效并等待重新评估。")
        self._patch_working(
            hypotheses=[
                by_id[key].model_dump(mode="json")
                for key in sorted(by_id, key=lambda value: (_identifier_number(value), value))
            ],
            assessment_is_current=False,
        )
        return applied_new, applied_revised

    def _apply_assessment(self, assessment: AssessmentOutput) -> None:
        hypotheses = {item.hypothesis_id: item for item in self._hypotheses()}
        for update in assessment.hypothesis_assessments:
            existing = hypotheses.get(update.hypothesis_id)
            if existing is None:
                continue
            hypotheses[update.hypothesis_id] = existing.model_copy(
                update={
                    "hypothesis_status": update.hypothesis_status,
                    "assessment": update.assessment,
                    "evidence_links": update.evidence_links,
                    "gaps": update.gaps,
                }
            )
        self._patch_working(
            hypotheses=[
                item.model_dump(mode="json")
                for item in sorted(
                    hypotheses.values(),
                    key=lambda value: (
                        _identifier_number(value.hypothesis_id),
                        value.hypothesis_id,
                    ),
                )
            ],
            hypothesis_relations=[
                item.model_dump(mode="json") for item in assessment.hypothesis_relations
            ],
            incident_conclusion=assessment.incident_conclusion.model_dump(mode="json"),
            assessment_is_current=True,
            unassessed_evidence_ids=[],
        )

    def _record_last_valid_assessment(self) -> None:
        self.state.checkpoint = {
            **self.state.checkpoint,
            "last_valid_assessment": {
                "hypotheses": _list(self.state.working.get("hypotheses")),
                "hypothesis_relations": _list(self.state.working.get("hypothesis_relations")),
                "incident_conclusion": self.state.working.get("incident_conclusion"),
                "analyzed_evidence_ids": self._evidence_ids(),
                "recorded_at": self._clock.now().isoformat(),
            },
        }

    def _public_diagnosis(self) -> JsonDict:
        """Typed public projection; raw payloads stay in the evidence chain."""
        conclusion = self._conclusion()
        working = self.state.working
        records = self._query_records()
        by_query = {record.query_id: record for record in records}
        evidence: list[Evidence] = []
        for evidence_id in self._evidence_ids():
            query_id = _query_id_for_evidence(evidence_id, records)
            record = by_query.get(query_id)
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    query_id=query_id,
                    kind=cast(
                        Literal["log", "metric", "change"],
                        _evidence_kind(record.tool_name) if record is not None else "log",
                    ),
                    data=None,
                )
            )
        result = DiagnosisResult(
            engine=ENGINE,
            mode=cast(Literal["real", "mock"], str(self._runtime_state.get("mode") or "real")),
            hypotheses=self._hypotheses(),
            hypothesis_relations=self._relations(),
            incident_conclusion=conclusion
            if conclusion is not None
            else IncidentConclusion(
                conclusion_status="unconfirmed",
                root_cause=None,
                stop_reason=None,
                explanation="调查尚未形成结论。",
            ),
            query_records=records,
            tool_evidence=evidence,
            unmet_requests=_unmet_requests(working),
            unassessed_evidence_ids=[
                str(item) for item in _list(working.get("unassessed_evidence_ids"))
            ],
            assessment_is_current=bool(working.get("assessment_is_current", True)),
            budget=_budget_model(self._runtime_state),
        )
        return result.model_dump(mode="json")

    def _result_payload(self) -> JsonDict:
        return {
            "engine": ENGINE,
            "mode": str(self._runtime_state.get("mode") or "real"),
            "diagnosis": self._public_diagnosis(),
        }

    def _report_facts(self) -> ReportFacts:
        runtime = self._runtime_state
        working = self.state.working
        return ReportFacts(
            mode=cast(Literal["real", "mock"], str(runtime.get("mode") or "real")),
            conclusion=self._conclusion(),
            hypotheses=tuple(self._hypotheses()),
            relations=tuple(self._relations()),
            query_records=tuple(self._query_records()),
            unmet_requests=tuple(_unmet_requests(working)),
            unassessed_evidence_ids=tuple(
                str(item) for item in _list(working.get("unassessed_evidence_ids"))
            ),
            assessment_is_current=bool(working.get("assessment_is_current", True)),
            alert={"service": self._alert().service},
            limitations=tuple(str(item) for item in _list(working.get("limitations"))),
            generated_at=self._clock.now().isoformat(),
        )

    async def _report_model_body(self) -> str | None:
        try:
            if self._budget().remaining("report") <= 0:
                self.limitation("报告阶段时间不足，使用程序兜底正文。")
                return None
            return await self._invoke_model(phase="report", prompt=self._report_prompt())
        except Exception as exc:
            emit_event(logger, "agent.aiops.report_fallback", errorCategory=exc.__class__.__name__)
            self.limitation("报告模型未能返回有效正文，已使用程序兜底正文。")
            return None

    async def _finish(
        self,
        *,
        status: Literal["succeeded", "failed", "cancelled"],
        title: str,
        content: str,
        failure_reason: str | None = None,
        cancelled: bool = False,
    ) -> None:
        del cancelled
        self._sync_budget()
        self._patch_working(
            hypotheses=[item.model_dump(mode="json") for item in self._hypotheses()],
            hypothesis_relations=[item.model_dump(mode="json") for item in self._relations()],
            query_records=[item.model_dump(mode="json") for item in self._query_records()],
        )
        self._patch_runtime(next_node="end", final_status=status)
        result = await self._runtime.finish_diagnostic_job(
            scope=self._scope,
            write=DiagnosticTerminalWrite(
                operation_id="finish:final",
                expected_revision=self._revision(),
                checkpoint=self.state.checkpoint,
                status=status,
                title=title,
                content=content,
                result_payload=self._result_payload(),
                evidence_ids=self._evidence_ids(),
                error_message=failure_reason,
            ),
        )
        self._adopt(result.checkpoint)

    async def finish_programmatically(
        self,
        *,
        status: Literal["succeeded", "failed", "cancelled"] = "succeeded",
        stop_reason: Literal[
            "root_cause_confirmed", "budget_exhausted", "critical_data_unavailable"
        ]
        | None = None,
        failure_reason: str | None = None,
        cancelled: bool = False,
    ) -> None:
        """Program-only terminal path used by finalize, cancel and failure handling."""
        try:
            if not self.state.checkpoint.get("runtime"):
                self.seed_checkpoint(mode=self._config.mode)
            working = dict(self.state.working)
            hypotheses = [
                hypothesis.model_copy(
                    update={
                        "hypothesis_status": (
                            "unresolved"
                            if hypothesis.hypothesis_status
                            in {"pending", "investigating", "blocked"}
                            else hypothesis.hypothesis_status
                        )
                    }
                )
                for hypothesis in self._hypotheses()
            ]
            working["hypotheses"] = [item.model_dump(mode="json") for item in hypotheses]
            if status != "cancelled":
                conclusion = self._conclusion()
                if conclusion is None:
                    conclusion = IncidentConclusion(
                        conclusion_status="unconfirmed",
                        root_cause=None,
                        stop_reason=stop_reason,
                        explanation=(
                            "本次调查结束，未确认事故根本原因。"
                            if status == "succeeded"
                            else "核心执行失败，未产生可信结论。"
                        ),
                    )
                elif conclusion.stop_reason != stop_reason:
                    conclusion = conclusion.model_copy(
                        update={
                            "stop_reason": stop_reason,
                            "root_cause": conclusion.root_cause
                            if conclusion.conclusion_status == "confirmed"
                            else None,
                        }
                    )
                working["incident_conclusion"] = conclusion.model_dump(mode="json")
            self.state.working = working
            facts = self._report_facts()
            report = build_diagnosis_report(facts=facts, model_body=None)
            await self._finish(
                status=status,
                title=report.title,
                content=report.content,
                failure_reason=failure_reason,
                cancelled=cancelled,
            )
        except DiagnosticLeaseLost:
            raise
        except DiagnosticStateConflict:
            # Another worker already committed a terminal for this investigation.
            emit_event(
                logger, "agent.aiops.terminal_conflict", diagnosticTaskId=self._scope.task_id
            )

    # ---------- prompts and parsing ----------

    def _tool_schema_hint(self) -> str:
        names = sorted(str(item) for item in _list(self._runtime_state.get("tool_names")))
        alert = self._alert()
        window = "未知"
        if alert.starts_at_ms is not None:
            start, end = _log_window(alert.starts_at_ms)
            window = f"from_ms={start}, to_ms={end}"
        return (
            f"可用工具：{json.dumps(names, ensure_ascii=False)}\n"
            f"告警服务：{alert.service or '未知'}；窗口：{window}\n"
            "工具参数契约：\n"
            f"- {LOG_TOOL}: service, instance?, levels?, from_ms, to_ms, limit\n"
            f"- {METRIC_TOOL}: service, metric_names, from_ms, to_ms, labels?, aggregation?\n"
            f"- {CHANGE_TOOL}: services, from_ms, to_ms, change_type?"
        )

    def _evidence_digest(self) -> str:
        records = self._query_records()
        if not records:
            return "（尚无现场查询记录）"
        lines: list[str] = []
        for record in records:
            lines.append(
                f"- {record.query_id} [{record.status}] {record.tool_name} "
                f"问题：{record.question} 说明：{record.status_reason}"
            )
        return "\n".join(lines)

    def _build_queries_prompt(self, *, available: Sequence[object], max_calls: int) -> str:
        hypotheses = self._hypotheses()
        assessment_digest = (
            "\n".join(
                f"- {item.hypothesis_id} [{item.hypothesis_status}] {item.statement} / 缺口："
                + ("；".join(gap.question for gap in item.gaps) or "无")
                for item in hypotheses
            )
            or "（尚未形成假设，首轮只做现场采证）"
        )
        unmet = _list(self.state.working.get("unmet_requests"))
        unmet_text = "\n".join(f"- {_dict(item).get('requirement')}" for item in unmet) or "（无）"
        return (
            "你是 AIOps 调查的执行计划器。只输出 JSON，字段为 calls 与 unmet_requests。\n"
            "calls 每项字段：hypothesis_ids（数组，首轮可为空）、question、tool_name、"
            "arguments。\n"
            "unmet_requests 每项字段：hypothesis_ids、requirement、reason。\n"
            f"最多 {max_calls} 个 calls；calls 与 unmet_requests 不能同时为空。\n"
            f"{self._tool_schema_hint()}\n"
            f"当前假设与缺口：\n{assessment_digest}\n"
            f"尚未满足的信息需求：\n{unmet_text}\n"
            f"已有查询记录：\n{self._evidence_digest()}\n"
            "要求：只为能解释告警的缺口补充必要事实；相同失败参数不要重复请求；"
            "无法用现有工具满足的需求写入 unmet_requests，不要编造替代数据。"
        )

    def _revise_prompt(self, current: Sequence[Hypothesis]) -> str:
        listed = (
            "\n".join(f"- {item.hypothesis_id}: {item.statement}" for item in current) or "（无）"
        )
        return (
            "你是 AIOps 调查的假设调整器。只输出 JSON，字段为 new_hypotheses 与 "
            "revised_hypotheses。\n"
            "new_hypotheses 每项只有 statement；revised_hypotheses 每项有 hypothesis_id "
            "与 statement。\n"
            "revised 表示细化同一解释（保留 ID）；更换或新增不同原因必须放入 "
            "new_hypotheses。\n"
            "不得写入未在证据中出现的事实，也不得重复已有解释。\n"
            f"当前假设：\n{listed}\n"
            f"已有查询记录：\n{self._evidence_digest()}\n"
            "若现有数据不足以形成有依据的解释，两个数组都可以为空。"
        )

    def _assess_prompt(self, *, final_analysis: bool) -> str:
        hypotheses = (
            "\n".join(
                f"- {item.hypothesis_id} [{item.hypothesis_status}] {item.statement}"
                for item in self._hypotheses()
            )
            or "（当前没有假设）"
        )
        phase_note = (
            "当前是最后分析：next_step.action 必须是 finalize 且 requests 为空。"
            if final_analysis
            else "如需更多事实选择 build_queries；只需调整解释选择 revise_hypotheses；"
            "结束选择 finalize。"
        )
        return (
            "你是 AIOps 调查的评估器。只输出 JSON，字段为 hypothesis_assessments、"
            "hypothesis_relations、incident_conclusion、next_step。\n"
            "hypothesis_assessments 必须覆盖全部当前假设且各一次，字段为 hypothesis_id、"
            "hypothesis_status、assessment、evidence_links、gaps。\n"
            "hypothesis_relations 每项为 from_hypothesis_id、to_hypothesis_id、relation_type"
            "（causal_link 或 competing）、explanation、evidence_ids。\n"
            "incident_conclusion 为 conclusion_status、root_cause、stop_reason、explanation；"
            "confirmed 必须给出具体 root_cause 且 stop_reason=root_cause_confirmed，"
            "unconfirmed 的 root_cause 必须为 null。\n"
            "next_step 为 action、reason、requests（每项 hypothesis_ids 与 requirement）。\n"
            f"{phase_note}\n"
            "确认根因必须同时具备具体原因、对象/时间/机制证据、无关键反证或主要未决竞争解释；"
            "工具成功、单个 supported 或数值评分都不能作为确认依据。\n"
            f"当前假设：\n{hypotheses}\n"
            f"已有查询记录：\n{self._evidence_digest()}\n"
            f"本轮可用证据 ID：{json.dumps(self._evidence_ids(), ensure_ascii=False)}"
        )

    def _report_prompt(self) -> str:
        facts = self._report_facts()
        conclusion = facts.conclusion
        hypotheses = json.dumps(
            [item.model_dump(mode="json") for item in facts.hypotheses], ensure_ascii=False
        )
        unmet = json.dumps(
            [item.model_dump(mode="json") for item in facts.unmet_requests], ensure_ascii=False
        )
        return (
            "你是 AIOps 报告撰写者。只输出中文 Markdown 正文，必须包含以下四个二级标题"
            "且顺序一致：\n"
            "## 诊断结论\n## 原因与证据\n## 调查结果与局限\n## 后续建议\n"
            "不要输出代码围栏，不要新增未经证实的因果链，不要声称已执行处置。\n"
            f"程序记录的结论状态：{conclusion.conclusion_status if conclusion else 'unconfirmed'}；"
            f"根因：{conclusion.root_cause if conclusion and conclusion.root_cause else '未确认'}\n"
            f"假设：{hypotheses}\n"
            f"查询记录：{self._evidence_digest()}\n"
            f"未满足需求：{unmet}\n"
            f"已知局限：{json.dumps(list(facts.limitations), ensure_ascii=False)}"
        )

    def _parse_query_plan(
        self, text: str, *, max_calls: int
    ) -> tuple[QueryPlan | None, str | None]:
        payload, error = _json_object(text)
        if payload is None:
            return None, error
        try:
            plan = QueryPlan.model_validate(payload)
        except ValidationError as exc:
            return None, _safe_validation_error(exc)
        try:
            plan.validate_context(
                hypothesis_ids=[item.hypothesis_id for item in self._hypotheses()],
                tool_names=[str(item) for item in _list(self._runtime_state.get("tool_names"))],
                max_calls=max_calls,
            )
            materialized = [
                call.model_copy(
                    update={
                        "arguments": _materialize_arguments(
                            call=call,
                            alert=self._alert(),
                            config=self._config,
                            cls_defaults=self._cls_defaults,
                        )
                    }
                )
                for call in plan.calls
            ]
        except (ValueError, DiagnosisToolError) as exc:
            return None, str(exc)[:200] or "查询计划不符合约束。"
        return plan.model_copy(update={"calls": materialized}), None

    def _parse_revision(self, text: str) -> tuple[HypothesisRevision | None, str | None]:
        payload, error = _json_object(text)
        if payload is None:
            return None, error
        try:
            revision = HypothesisRevision.model_validate(payload)
            revision.validate_context(
                hypothesis_ids=[item.hypothesis_id for item in self._hypotheses()]
            )
        except ValidationError as exc:
            return None, _safe_validation_error(exc)
        except ValueError as exc:
            return None, str(exc)[:200]
        return revision, None

    def _parse_assessment(
        self, text: str, *, final_analysis: bool, operation_id: str
    ) -> tuple[AssessmentOutput | None, str | None]:
        del operation_id
        payload, error = _json_object(text)
        if payload is None:
            return None, error
        try:
            assessment = AssessmentOutput.model_validate(payload)
            assessment.validate_context(
                hypothesis_ids=[item.hypothesis_id for item in self._hypotheses()],
                evidence_ids=self._evidence_ids(),
                final_analysis=final_analysis,
            )
        except ValidationError as exc:
            return None, _safe_validation_error(exc)
        except ValueError as exc:
            return None, str(exc)[:200]
        return assessment, None


# ---------- module helpers ----------


def _materialize_arguments(
    *,
    call: Any,
    alert: _AlertContext,
    config: DiagnosisConfig,
    cls_defaults: ClsSearchDefaults,
) -> dict[str, JsonValue]:
    """Fill program-owned parameters; unknown keys stay invalid."""
    raw = _json_arguments(call.arguments)
    if config.mode == "mock":
        normalized = normalize_mock_arguments(tool_name=call.tool_name, arguments=raw)
        if call.tool_name == LOG_TOOL:
            base: dict[str, JsonValue] = build_mock_search_log_arguments(
                service=str(normalized.get("service") or alert.service or "unknown"),
                alert_starts_at_ms=alert.starts_at_ms or 0,
            )
        elif call.tool_name == METRIC_TOOL:
            base = build_mock_query_metric_arguments(
                service=str(normalized.get("service") or alert.service or "unknown"),
                alert_starts_at_ms=alert.starts_at_ms or 0,
                metric_names=cast(Sequence[str] | None, normalized.get("metric_names")),
                labels=cast(Mapping[str, str] | None, normalized.get("labels")),
            )
        elif call.tool_name == CHANGE_TOOL:
            base = build_mock_query_change_arguments(
                alert_service=alert.service or "unknown",
                alert_starts_at_ms=alert.starts_at_ms or 0,
                services=cast(Sequence[str] | None, normalized.get("services")),
            )
        else:
            raise DiagnosisToolError(f"unsupported mock tool: {call.tool_name}")
        merged = dict(base)
        for key, value in normalized.items():
            merged[key] = value
        return merged
    if call.tool_name == LOG_TOOL:
        return dict(
            build_real_search_log_arguments(
                defaults=cls_defaults,
                service=str(raw.get("service") or alert.service or "unknown"),
                alert_starts_at_ms=alert.starts_at_ms or 0,
                query=str(raw.get("Query") or raw.get("query") or "") or None,
            )
        )
    return raw


def _has_business_records(data: JsonValue) -> bool:
    if data is None:
        return False
    if isinstance(data, list):
        return bool(data)
    if isinstance(data, dict):
        for key in ("recordCount", "seriesCount"):
            value = data.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value > 0
        return bool(data)
    return bool(data)


def _evidence_kind(tool_name: str) -> str:
    if tool_name == METRIC_TOOL:
        return "metric"
    if tool_name == CHANGE_TOOL:
        return "change"
    return "log"


def _alert_context(alert: JsonDict) -> _AlertContext:
    labels = alert.get("labels")
    label_map = labels if isinstance(labels, Mapping) else {}
    service = str(
        alert.get("service") or label_map.get("service") or alert.get("alertname") or ""
    ).strip()
    instance = str(alert.get("instance") or label_map.get("instance") or "").strip()
    starts_at = str(alert.get("startsAt") or alert.get("starts_at") or "").strip()
    starts_at_ms: int | None = None
    if starts_at:
        try:
            starts_at_ms = timestamp_ms(starts_at)
        except ValueError:
            starts_at_ms = None
    return _AlertContext(
        service=service,
        instance=instance,
        starts_at_ms=starts_at_ms,
        summary=str(alert.get("summary") or "").strip(),
    )


def _log_window(starts_at_ms: int) -> tuple[int, int]:
    return (
        starts_at_ms - LOG_WINDOW_BEFORE_MINUTES * 60 * 1000,
        starts_at_ms + LOG_WINDOW_AFTER_MINUTES * 60 * 1000,
    )


def _unmet_requests(working: JsonDict) -> list[UnmetRequest]:
    return [UnmetRequest.model_validate(item) for item in _list(working.get("unmet_requests"))]


def _query_id_for_evidence(evidence_id: str, records: Sequence[QueryRecord]) -> str:
    for record in records:
        if evidence_id == f"evidence:{record.query_id}":
            return record.query_id
    return f"unknown:{evidence_id}"


def _json_arguments(value: object) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], dict(_dict(value)))


def _budget_state(runtime: JsonDict) -> BudgetState:
    return BudgetState.model_validate(
        {
            name: runtime[name]
            for name in ("budget", "calls", "batches", "remaining_seconds", "saved_at")
            if name in runtime
        }
    )


def _budget_model(runtime: JsonDict) -> DiagnosisBudget:
    return DiagnosisBudget.model_validate(_dict(runtime.get("budget")))


def _identifier_number(value: str) -> int:
    match = re.fullmatch(r"H(\d+)", value)
    return int(match.group(1)) if match else 0


def _json_object(text: str) -> tuple[JsonDict | None, str | None]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\n?", "", candidate)
        candidate = re.sub(r"\n?```$", "", candidate.strip())
    match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
    if match is None:
        return None, "输出中没有 JSON 对象。"
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, "输出不是合法 JSON。"
    if not isinstance(parsed, Mapping):
        return None, "输出不是 JSON 对象。"
    return dict(cast(Mapping[str, object], parsed)), None


def _safe_validation_error(exc: ValidationError) -> str:
    fields = sorted({".".join(str(part) for part in error["loc"]) for error in exc.errors()})
    return "结构校验失败，字段：" + ", ".join(fields)[:200]


def _model_text(response: object) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text", "")) if isinstance(item, Mapping) else str(item)
            for item in content
        )
    return str(content)


def _task_status_event(
    task_id: str,
    status: str,
    message: str,
    progress: int,
    phase: str,
    diagnosis: JsonDict | None = None,
) -> JsonDict:
    task: JsonDict = {
        "id": task_id,
        "status": status,
        "message": message,
        "progress": progress,
        "phase": phase,
    }
    if diagnosis is not None:
        task["diagnosis"] = diagnosis
    return {"type": "task.status", "task": task}


def _tool_event(
    audit_id: str,
    name: str,
    status: Literal["started", "completed", "failed"],
    payload: object,
) -> JsonDict:
    key = "input" if status == "started" else "output"
    return {
        "type": "tool.call",
        "toolCall": {
            "id": audit_id,
            "name": name,
            "status": status,
            key: _safe_value(payload),
        },
    }


def _safe_value(value: object) -> object:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError):
        return str(value)[:200]


def _dict(value: object) -> JsonDict:
    if not isinstance(value, Mapping):
        return {}
    return dict(cast(Mapping[str, object], value))


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _int(value: object, *, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


__all__ = [
    "AiopsDiagnosticService",
    "DiagnosisExecutionError",
    "DiagnosisOutputInvalid",
]
