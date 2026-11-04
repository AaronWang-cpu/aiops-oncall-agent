"""P4：假设驱动诊断图、预算、报告与终态闭环。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from super_ai.aiops.diagnosis_config import DiagnosisConfig
from super_ai.aiops.diagnosis_tools import DEFAULT_LOG_LIMIT, MAX_LOG_LIMIT
from super_ai.aiops.diagnostics import AiopsDiagnosticService
from super_ai.jobs.runtime import BackgroundJobContext
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.models import (
    AgentToolCallAuditModel,
    BackgroundJobEventModel,
    BackgroundJobModel,
    DiagnosticEvidenceModel,
    DiagnosticReportModel,
    DiagnosticStepModel,
    ReportEvidenceLinkModel,
)
from super_ai.memory.repositories import BackgroundJobRepository, MemoryRepositories
from super_ai.memory.sqlite import create_sqlite_memory_repositories

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = BACKEND_ROOT / "src" / "super_ai" / "aiops" / "mock_scenarios"
OWNER = "user-a"

PLAN_CALLS: list[dict[str, object]] = [
    {
        "hypothesis_ids": [],
        "question": "订单服务窗口内有哪些错误日志？",
        "tool_name": "SearchLog",
        "arguments": {"service": "order-service"},
    },
    {
        "hypothesis_ids": [],
        "question": "连接池使用率如何变化？",
        "tool_name": "QueryMetric",
        "arguments": {
            "service": "order-service",
            "metric_names": ["order_db_connection_pool_usage"],
        },
    },
    {
        "hypothesis_ids": [],
        "question": "窗口内有哪些变更？",
        "tool_name": "QueryChange",
        "arguments": {"services": ["order-service"]},
    },
]

CONFIRMED_ASSESSMENT: dict[str, object] = {
    "hypothesis_assessments": [
        {
            "hypothesis_id": "H1",
            "hypothesis_status": "supported",
            "assessment": "日志与指标同时显示连接池耗尽，订单接口因此报错。",
            "evidence_links": [
                {
                    "evidence_id": "evidence:task-graph:call:1:0",
                    "relation": "supports",
                    "explanation": "错误日志显示等待连接超时。",
                }
            ],
            "gaps": [],
        },
        {
            "hypothesis_id": "H2",
            "hypothesis_status": "supported",
            "assessment": "变更记录显示连接池上限被下调到 20，是耗尽的直接机制。",
            "evidence_links": [
                {
                    "evidence_id": "evidence:task-graph:call:1:2",
                    "relation": "supports",
                    "explanation": "变更明细给出上限调整前后取值。",
                }
            ],
            "gaps": [],
        },
    ],
    "hypothesis_relations": [
        {
            "from_hypothesis_id": "H2",
            "to_hypothesis_id": "H1",
            "relation_type": "causal_link",
            "explanation": "上限下调导致连接池耗尽。",
            "evidence_ids": ["evidence:task-graph:call:1:1"],
        }
    ],
    "incident_conclusion": {
        "conclusion_status": "confirmed",
        "root_cause": "配置变更把连接池上限从 100 下调到 20，导致订单库连接耗尽",
        "stop_reason": "root_cause_confirmed",
        "explanation": "变更、指标与日志共同指向同一机制，没有关键反证。",
    },
    "next_step": {"action": "finalize", "reason": "根因已确认。", "requests": []},
}

REPORT_BODY = """## 诊断结论

已确认根本原因：连接池上限下调导致订单库连接耗尽。

## 原因与证据

连接池使用率在告警前达到上限，同时配置变更把最大连接数从 100 降到 20。

## 调查结果与局限

本轮查询成功返回日志、指标与变更记录，未发现关键反证。

## 后续建议

先核对该配置变更并评估回滚，本报告不执行任何处置。
"""


class ScriptedChatModel:
    def __init__(self, script: ModelScript) -> None:
        self._script = script

    async def ainvoke(self, input: object) -> object:
        return self._script.reply(str(input))


@dataclass
class ModelScript:
    """Reply per node by prompt marker; records every invocation."""

    plan: list[str] = field(default_factory=lambda: list[str]())
    revise: list[str] = field(default_factory=lambda: list[str]())
    assess: list[str] = field(default_factory=lambda: list[str]())
    report: list[str] = field(default_factory=lambda: list[str]())
    calls: list[str] = field(default_factory=lambda: list[str]())
    interrupt_on: str | None = None

    def reply(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.interrupt_on is not None and self.interrupt_on in prompt:
            raise asyncio.CancelledError
        if "执行计划器" in prompt:
            return self._next(self.plan, "plan")
        if "假设调整器" in prompt:
            return self._next(self.revise, "revise")
        if "评估器" in prompt:
            return self._next(self.assess, "assess")
        if "报告撰写者" in prompt:
            return self._next(self.report, "report")
        raise AssertionError("unexpected diagnostic prompt")

    def _next(self, queue: list[str], label: str) -> str:
        if not queue:
            raise AssertionError(f"no scripted {label} reply left")
        return queue.pop(0)


class ScriptedLlmProvider:
    def __init__(self, script: ModelScript) -> None:
        self.script = script
        self.models: list[str] = []

    def create_diagnostic_model(self, *, timeout_seconds: float) -> ScriptedChatModel:
        self.models.append(f"{timeout_seconds:.0f}")
        return ScriptedChatModel(self.script)

    def create_chat_model(self) -> ScriptedChatModel:  # pragma: no cover - not used here
        raise AssertionError("chat model is not part of diagnosis")

    def create_embedding_model(self) -> object:  # pragma: no cover - not used here
        raise AssertionError("embedding model is not part of diagnosis")

    def create_rerank_model(self) -> object:  # pragma: no cover - not used here
        raise AssertionError("rerank model is not part of diagnosis")

    async def check_readiness(self) -> object:  # pragma: no cover - not used here
        return {"ok": True}


@dataclass
class Harness:
    repositories: MemoryRepositories
    jobs: BackgroundJobRepository
    service: AiopsDiagnosticService
    context: BackgroundJobContext
    script: ModelScript
    provider: ScriptedLlmProvider
    sessions: Any


@pytest.fixture
def migrated_url(tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'graph.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url


def _config(
    *,
    mode: Literal["real", "mock"] = "mock",
    scenario: str = "order-pool-exhaustion.json",
    knowledge: Path | None = None,
) -> DiagnosisConfig:
    return DiagnosisConfig(
        mode=mode,
        mockScenarioPath=str(SCENARIO_DIR / scenario),
        projectKnowledgePath="" if knowledge is None else str(knowledge),
        maxRounds=2,
        maxToolCalls=6,
        investigationSeconds=300,
        finalAnalysisSeconds=60,
        reportSeconds=30,
        totalSeconds=390,
    )


async def _harness(
    migrated_url: str,
    script: ModelScript,
    *,
    mode: Literal["real", "mock"] = "mock",
    scenario: str = "order-pool-exhaustion.json",
    knowledge: Path | None = None,
) -> Harness:
    engine = create_memory_engine(migrated_url)
    sessions = create_memory_session_factory(engine)
    repositories = create_sqlite_memory_repositories(sessions)
    assert repositories.background_jobs is not None
    job_id = "job-graph"
    await repositories.diagnostics.create_task(
        owner_user_id=OWNER,
        task_id="task-graph",
        status="queued",
        query="订单接口错误率升高",
        input_payload={"alert": {}},
    )
    await repositories.background_jobs.enqueue(
        owner_user_id=OWNER,
        job_id=job_id,
        kind="aiops_diagnosis",
        resource_type="aiops_diagnostic",
        resource_id="task-graph",
        payload={"diagnosticId": "task-graph"},
        max_attempts=1,
    )
    claimed = await repositories.background_jobs.claim_next(
        worker_id="worker-graph",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    assert claimed is not None
    provider = ScriptedLlmProvider(script)
    service = AiopsDiagnosticService(
        repositories=repositories,
        llm_provider=cast(Any, provider),
        config=_config(mode=mode, scenario=scenario, knowledge=knowledge),
        cls_region="ap-guangzhou",
        cls_topic_id="topic-1",
    )
    return Harness(
        repositories=repositories,
        jobs=repositories.background_jobs,
        service=service,
        context=BackgroundJobContext(job=claimed, repository=repositories.background_jobs),
        script=script,
        provider=provider,
        sessions=sessions,
    )


def _plan(calls: list[dict[str, object]], unmet: list[dict[str, object]] | None = None) -> str:
    return json.dumps({"calls": calls, "unmet_requests": unmet or []})


def _script() -> ModelScript:
    return ModelScript(
        plan=[_plan(PLAN_CALLS)],
        revise=[
            json.dumps(
                {
                    "new_hypotheses": [
                        {"statement": "order-service 数据库连接池耗尽导致订单接口报错"},
                        {"statement": "连接池上限被下调是耗尽的直接机制"},
                    ],
                    "revised_hypotheses": [],
                }
            )
        ],
        assess=[json.dumps(CONFIRMED_ASSESSMENT)],
        report=[REPORT_BODY],
    )


async def _events(jobs: BackgroundJobRepository, job_id: str) -> list[dict[str, object]]:
    stored = await jobs.list_events(owner_user_id=OWNER, job_id=job_id)
    return [item.payload for item in stored]


async def _count(sessions: Any, model: type[Any]) -> int:
    async with sessions() as session:
        rows = await session.scalars(select(model))
        return len(list(rows))


@pytest.mark.asyncio
async def test_graph_collects_evidence_then_confirms_root_cause(migrated_url: str) -> None:
    harness = await _harness(migrated_url, _script())

    await harness.service.run(harness.context)

    task = await harness.repositories.diagnostics.get_task(
        owner_user_id=OWNER, task_id="task-graph"
    )
    assert task is not None
    assert task.status == "succeeded"
    diagnosis = cast(dict[str, object], task.result_payload["diagnosis"])
    hypotheses = cast(list[dict[str, object]], diagnosis["hypotheses"])
    assert [item["hypothesis_id"] for item in hypotheses] == ["H1", "H2"]
    conclusion = cast(dict[str, object], diagnosis["incident_conclusion"])
    assert conclusion["conclusion_status"] == "confirmed"
    assert conclusion["stop_reason"] == "root_cause_confirmed"
    records = cast(list[dict[str, object]], diagnosis["query_records"])
    assert len(records) == 3
    assert {record["status"] for record in records} == {"succeeded"}
    assert diagnosis["assessment_is_current"] is True
    assert cast(list[object], diagnosis["unassessed_evidence_ids"]) == []

    session_factory = harness.sessions
    assert await _count(session_factory, DiagnosticEvidenceModel) == 3
    assert await _count(session_factory, ReportEvidenceLinkModel) == 3
    assert await _count(session_factory, DiagnosticReportModel) == 1
    assert await _count(session_factory, DiagnosticStepModel) >= 6
    async with session_factory() as session:
        audits = list(await session.scalars(select(AgentToolCallAuditModel)))
    assert [audit.status for audit in audits] == ["completed", "completed", "completed"]

    events = await _events(harness.jobs, "job-graph")
    assert events[-1]["type"] == "complete"
    assert [event["type"] for event in events][-3:] == ["report", "task.status", "complete"]
    assert all(str(event.get("id", "")).startswith("diagnostic_") for event in events)
    report = cast(dict[str, object], events[-3]["report"])
    content = str(report["content"])
    for heading in (
        "# 诊断报告",
        "## 诊断结论",
        "## 原因与证据",
        "## 调查结果与局限",
        "## 后续建议",
    ):
        assert heading in content
    assert report["format"] == "markdown"
    assert "```" not in content


@pytest.mark.asyncio
async def test_graph_reports_unconfirmed_when_first_round_has_no_records(
    migrated_url: str,
) -> None:
    script = _script()
    script.plan = [
        _plan(
            [
                {
                    "hypothesis_ids": [],
                    "question": "不存在的服务有日志吗？",
                    "tool_name": "SearchLog",
                    "arguments": {"service": "unknown-service"},
                }
            ]
        )
    ]
    script.revise = []
    script.assess = []
    harness = await _harness(migrated_url, script)

    await harness.service.run(harness.context)

    task = await harness.repositories.diagnostics.get_task(
        owner_user_id=OWNER, task_id="task-graph"
    )
    assert task is not None
    assert task.status == "failed"
    conclusion = cast(
        dict[str, object],
        cast(dict[str, object], task.result_payload["diagnosis"])["incident_conclusion"],
    )
    assert conclusion["conclusion_status"] == "unconfirmed"
    assert conclusion["root_cause"] is None
    assert conclusion["stop_reason"] is None
    events = await _events(harness.jobs, "job-graph")
    assert [event["type"] for event in events][-4:] == [
        "report",
        "error",
        "task.status",
        "complete",
    ]
    report = cast(dict[str, object], events[-4]["report"])
    assert "未确认" in str(report["content"])
    # 未发起真实业务调用也不生成假设。
    assert not script.revise
    assert await _count(harness.sessions, DiagnosticReportModel) == 1


@pytest.mark.asyncio
async def test_graph_corrects_one_invalid_plan_output(migrated_url: str) -> None:
    script = _script()
    script.plan = ["这不是 JSON", _plan(PLAN_CALLS)]
    harness = await _harness(migrated_url, script)

    await harness.service.run(harness.context)

    task = await harness.repositories.diagnostics.get_task(
        owner_user_id=OWNER, task_id="task-graph"
    )
    assert task is not None and task.status == "succeeded"
    plan_calls = [prompt for prompt in script.calls if "执行计划器" in prompt]
    assert len(plan_calls) == 2
    assert "不符合结构要求" in plan_calls[1]


@pytest.mark.asyncio
async def test_graph_fails_after_repeated_invalid_plan_output(migrated_url: str) -> None:
    script = _script()
    script.plan = ["不是 JSON", "仍不是 JSON"]
    script.revise = []
    script.assess = []
    harness = await _harness(migrated_url, script)

    await harness.service.run(harness.context)

    task = await harness.repositories.diagnostics.get_task(
        owner_user_id=OWNER, task_id="task-graph"
    )
    assert task is not None and task.status == "failed"
    assert len([prompt for prompt in script.calls if "执行计划器" in prompt]) == 2


@pytest.mark.asyncio
async def test_resume_after_terminal_does_not_rerun_or_duplicate(migrated_url: str) -> None:
    harness = await _harness(migrated_url, _script())
    await harness.service.run(harness.context)
    before = await _events(harness.jobs, "job-graph")
    scripted_calls = len(harness.script.calls)

    await harness.service.run(harness.context)

    assert len(harness.script.calls) == scripted_calls
    assert await _events(harness.jobs, "job-graph") == before
    assert await _count(harness.sessions, DiagnosticReportModel) == 1


@pytest.mark.asyncio
async def test_finalizer_commits_cancelled_terminal_without_model_calls(
    migrated_url: str,
) -> None:
    script = _script()
    harness = await _harness(migrated_url, script)

    await harness.service.terminate(harness.context, "cancelled", "User cancelled diagnosis.")

    assert harness.script.calls == []
    task = await harness.repositories.diagnostics.get_task(
        owner_user_id=OWNER, task_id="task-graph"
    )
    assert task is not None and task.status == "cancelled"
    events = await _events(harness.jobs, "job-graph")
    assert [event["type"] for event in events] == ["report", "task.status", "complete"]
    job = await harness.jobs.get(owner_user_id=OWNER, job_id="job-graph")
    assert job is not None and job.status == "cancelled" and job.lease_owner is None
    async with harness.sessions() as session:
        stored = await session.get(BackgroundJobModel, "job-graph")
        assert stored is not None and stored.lease_expires_at is None
        sequences = [
            item.sequence for item in await session.scalars(select(BackgroundJobEventModel))
        ]
    assert sequences == sorted(sequences)


@pytest.mark.asyncio
async def test_mock_mode_marks_report_and_diagnosis_as_simulated(migrated_url: str) -> None:
    harness = await _harness(migrated_url, _script())

    await harness.service.run(harness.context)

    task = await harness.repositories.diagnostics.get_task(
        owner_user_id=OWNER, task_id="task-graph"
    )
    assert task is not None
    assert cast(dict[str, object], task.result_payload["diagnosis"])["mode"] == "mock"
    events = await _events(harness.jobs, "job-graph")
    final = cast(dict[str, object], events[-1]["result"])
    reports = cast(list[dict[str, object]], final["reports"])
    assert "模拟场景" in str(reports[0]["content"])


@pytest.mark.asyncio
async def test_query_planner_prompt_exposes_the_fixed_metric_catalog(migrated_url: str) -> None:
    harness = await _harness(migrated_url, _script())

    await harness.service.run(harness.context)

    plan_prompts = [prompt for prompt in harness.script.calls if "执行计划器" in prompt]
    assert plan_prompts
    assert "order_db_connection_pool_usage" in plan_prompts[0]
    assert "只能从这个白名单中选择" in plan_prompts[0]


@pytest.mark.asyncio
async def test_query_planner_prompt_states_the_log_limit_range(migrated_url: str) -> None:
    """The planner passed limit=200 until the contract carried the accepted range."""
    harness = await _harness(migrated_url, _script())

    await harness.service.run(harness.context)

    plan_prompts = [prompt for prompt in harness.script.calls if "执行计划器" in prompt]
    assert plan_prompts
    assert f"limit（1~{MAX_LOG_LIMIT} 的整数，默认 {DEFAULT_LOG_LIMIT}）" in plan_prompts[0]


@pytest.mark.asyncio
async def test_prompts_carry_project_knowledge_as_background(
    migrated_url: str, tmp_path: Path
) -> None:
    """Operator knowledge must reach the prompts, labelled as context rather than evidence."""
    knowledge = tmp_path / "knowledge.yaml"
    knowledge.write_text(
        "project_overview: 订单平台共用一套 MySQL 订单库。\n"
        "services:\n"
        "  order-service:\n"
        "    description: 负责订单创建与查询，连接池上限 20。\n",
        encoding="utf-8",
    )
    harness = await _harness(migrated_url, _script(), knowledge=knowledge)

    await harness.service.run(harness.context)

    marked = [
        prompt
        for prompt in harness.script.calls
        if "执行计划器" in prompt or "假设调整器" in prompt or "评估器" in prompt
    ]
    assert marked
    for prompt in marked:
        assert "项目背景（用于理解服务职责与术语，不构成证据）" in prompt
        assert "订单平台共用一套 MySQL 订单库。" in prompt
        assert "负责订单创建与查询，连接池上限 20。" in prompt


@pytest.mark.asyncio
async def test_prompts_stay_free_of_the_knowledge_block_without_knowledge(
    migrated_url: str,
) -> None:
    harness = await _harness(migrated_url, _script())

    await harness.service.run(harness.context)

    assert all("项目背景" not in prompt for prompt in harness.script.calls)


@pytest.mark.asyncio
async def test_hypothesis_prompts_carry_the_tool_records(migrated_url: str) -> None:
    """A summary alone cannot be the only evidence: the model must read the records."""
    harness = await _harness(migrated_url, _script())

    await harness.service.run(harness.context)

    revise_prompts = [prompt for prompt in harness.script.calls if "假设调整器" in prompt]
    assess_prompts = [prompt for prompt in harness.script.calls if "评估器" in prompt]
    assert revise_prompts and assess_prompts
    for prompt in (revise_prompts[0], assess_prompts[0]):
        assert "证据内容：" in prompt
        assert "HikariPool-1" in prompt
        assert "maximumPoolSize" in prompt
        assert "order_db_connection_pool_usage" in prompt


@pytest.mark.asyncio
async def test_assessment_prompt_states_the_stop_reason_contract(migrated_url: str) -> None:
    """The model invented stop reasons until the prompt listed the allowed values."""
    harness = await _harness(migrated_url, _script())

    await harness.service.run(harness.context)

    assess_prompts = [prompt for prompt in harness.script.calls if "评估器" in prompt]
    assert assess_prompts
    prompt = assess_prompts[0]
    assert "root_cause_confirmed、budget_exhausted、critical_data_unavailable 或 null" in prompt
    assert "调查继续（next_step.action 不是 finalize）时必须为 null" in prompt


@pytest.mark.asyncio
async def test_assessment_prompt_states_the_hypothesis_status_contract(migrated_url: str) -> None:
    """An unlisted status enum makes the model invent values and fails the whole node."""
    harness = await _harness(migrated_url, _script())

    await harness.service.run(harness.context)

    assess_prompts = [prompt for prompt in harness.script.calls if "评估器" in prompt]
    assert assess_prompts
    assert (
        "hypothesis_status 只能取 pending、investigating、supported、contradicted、"
        "blocked、unresolved。" in assess_prompts[0]
    )


@pytest.mark.asyncio
async def test_resume_after_interrupted_model_intent_fails_without_retry(
    migrated_url: str,
) -> None:
    """Design 7: an interrupted core model intent ends as an execution failure, never replayed."""
    interrupted = _script()
    interrupted.interrupt_on = "假设调整器"
    harness = await _harness(migrated_url, interrupted)

    with pytest.raises(asyncio.CancelledError):
        await harness.service.run(harness.context)

    resumed = ModelScript(revise=_script().revise, assess=_script().assess, report=_script().report)
    harness.provider.script = resumed
    await harness.service.run(harness.context)

    assert resumed.calls == []
    task = await harness.repositories.diagnostics.get_task(
        owner_user_id=OWNER, task_id="task-graph"
    )
    assert task is not None and task.status == "failed"
    conclusion = cast(
        dict[str, object],
        cast(dict[str, object], task.result_payload["diagnosis"])["incident_conclusion"],
    )
    assert conclusion["conclusion_status"] == "unconfirmed"
    events = await _events(harness.jobs, "job-graph")
    assert [event["type"] for event in events][-4:] == [
        "report",
        "error",
        "task.status",
        "complete",
    ]


@pytest.mark.asyncio
async def test_diagnostic_model_uses_the_configured_model_timeout(migrated_url: str) -> None:
    harness = await _harness(migrated_url, _script())

    await harness.service.run(harness.context)

    assert harness.provider.models
    assert set(harness.provider.models) == {f"{_config().model_timeout_seconds:.0f}"}
