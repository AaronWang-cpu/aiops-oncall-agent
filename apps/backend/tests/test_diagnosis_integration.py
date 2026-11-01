"""P6：贯通 Mock 场景、真实传输替身、任务/job/SSE 与前端回载的联合验收。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.aiops.diagnosis_config import DiagnosisConfig
from super_ai.aiops.diagnostics import AiopsDiagnosticService
from super_ai.api.app import AiopsDiagnosticRunner, create_app
from super_ai.jobs.runtime import BackgroundJobContext
from super_ai.mcp_client import (
    LocalMcpClient,
    McpClientError,
    McpServerConnection,
    McpToolDefinition,
)
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.repositories import MemoryRepositories
from super_ai.memory.sqlite import create_sqlite_memory_repositories

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = BACKEND_ROOT / "src" / "super_ai" / "aiops" / "mock_scenarios"
OWNER = "user-a"

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

MOCK_PLAN: list[dict[str, object]] = [
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

MOCK_REVISION: dict[str, object] = {
    "new_hypotheses": [
        {"statement": "order-service 数据库连接池耗尽导致订单接口报错"},
        {"statement": "连接池上限被下调是耗尽的直接机制"},
    ],
    "revised_hypotheses": [],
}

MOCK_ASSESSMENT: dict[str, object] = {
    "hypothesis_assessments": [
        {
            "hypothesis_id": "H1",
            "hypothesis_status": "supported",
            "assessment": "日志与指标同时显示连接池耗尽，订单接口因此报错。",
            "evidence_links": [
                {
                    "evidence_id": "evidence:call:1:0",
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
                    "evidence_id": "evidence:call:1:2",
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
            "evidence_ids": ["evidence:call:1:1"],
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

REPORT_HEADINGS = (
    "# 诊断报告",
    "## 诊断结论",
    "## 原因与证据",
    "## 调查结果与局限",
    "## 后续建议",
)

REAL_PLAN: list[dict[str, object]] = [
    {
        "hypothesis_ids": [],
        "question": "订单服务窗口内有哪些错误日志？",
        "tool_name": "SearchLog",
        "arguments": {"service": "order-service"},
    }
]

REAL_ASSESSMENT: dict[str, object] = {
    "hypothesis_assessments": [
        {
            "hypothesis_id": "H1",
            "hypothesis_status": "supported",
            "assessment": "真实 CLS 日志显示等待连接超时。",
            "evidence_links": [
                {
                    "evidence_id": "evidence:call:1:0",
                    "relation": "supports",
                    "explanation": "日志给出等待连接超时。",
                }
            ],
            "gaps": [],
        }
    ],
    "hypothesis_relations": [],
    "incident_conclusion": {
        "conclusion_status": "confirmed",
        "root_cause": "连接池等待超时导致订单接口错误",
        "stop_reason": "root_cause_confirmed",
        "explanation": "真实日志给出直接机制。",
    },
    "next_step": {"action": "finalize", "reason": "根因已确认。", "requests": []},
}


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

    def reply(self, prompt: str) -> str:
        self.calls.append(prompt)
        for marker, queue in (
            ("执行计划器", self.plan),
            ("假设调整器", self.revise),
            ("评估器", self.assess),
            ("报告撰写者", self.report),
        ):
            if marker in prompt:
                if not queue:
                    raise AssertionError(f"no scripted reply left for {marker}")
                return queue.pop(0)
        raise AssertionError("unexpected diagnostic prompt")


class ScriptedLlmProvider:
    def __init__(self, script: ModelScript) -> None:
        self.script = script

    def create_diagnostic_model(self, *, timeout_seconds: float) -> ScriptedChatModel:
        del timeout_seconds
        return ScriptedChatModel(self.script)


class ToolCallDouble(LocalMcpClient):
    """Replace only the transport boundary; count the real calls actually issued."""

    def __init__(
        self, *, fail: bool = False, error_message: str = "MCP server unavailable"
    ) -> None:
        super().__init__(
            connections=[
                McpServerConnection(
                    name="cls",
                    url="http://mcp.test/sse",
                    timeout_seconds=30,
                    retries=1,
                )
            ]
        )
        self._fail = fail
        self._error_message = error_message
        self.calls: list[str] = []

    async def discover_tools(self) -> list[McpToolDefinition]:
        return [McpToolDefinition("SearchLog", "search cls logs", {"type": "object"}, "cls")]

    async def call_discovered_tool(
        self,
        definition: McpToolDefinition,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> Any:
        del arguments, timeout_seconds
        self.calls.append(definition.name)
        if self._fail:
            raise McpClientError(self._error_message)
        return {
            "recordCount": 2,
            "records": [
                {
                    "timestamp": "2026-03-18T09:12:30Z",
                    "level": "ERROR",
                    "service": "order-service",
                    "message": "waiting for connection timeout",
                },
                {
                    "timestamp": "2026-03-18T09:13:00Z",
                    "level": "ERROR",
                    "service": "order-service",
                    "message": "connection pool exhausted",
                },
            ],
        }


class ToolClientProvider:
    def __init__(self, client: LocalMcpClient) -> None:
        self._client = client

    async def diagnostic_client_for_user(
        self, *, owner_user_id: str, timeout_seconds: float
    ) -> LocalMcpClient:
        del owner_user_id, timeout_seconds
        return self._client


@pytest.fixture
def migrated_url(tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'integration.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url


def _plan(calls: list[dict[str, object]]) -> str:
    return json.dumps({"calls": calls, "unmet_requests": []})


def _mock_config() -> DiagnosisConfig:
    return DiagnosisConfig(
        mode="mock",
        mockScenarioPath=str(SCENARIO_DIR / "order-pool-exhaustion.json"),
        maxRounds=2,
        maxToolCalls=6,
        investigationSeconds=300,
        finalAnalysisSeconds=60,
        reportSeconds=30,
        totalSeconds=390,
    )


def _real_config() -> DiagnosisConfig:
    return DiagnosisConfig(
        mode="real",
        mockScenarioPath="",
        projectKnowledgePath="",
        maxRounds=2,
        maxToolCalls=6,
        investigationSeconds=300,
        finalAnalysisSeconds=60,
        reportSeconds=30,
        totalSeconds=390,
    )


def _mock_script() -> ModelScript:
    return ModelScript(
        plan=[_plan(MOCK_PLAN)],
        revise=[json.dumps(MOCK_REVISION)],
        assess=[json.dumps(MOCK_ASSESSMENT)],
        report=[REPORT_BODY],
    )


def _real_script() -> ModelScript:
    revision = {
        "new_hypotheses": [{"statement": "连接等待超时导致报错"}],
        "revised_hypotheses": [],
    }
    return ModelScript(
        plan=[_plan(REAL_PLAN)],
        revise=[json.dumps(revision)],
        assess=[json.dumps(REAL_ASSESSMENT)],
        report=[REPORT_BODY],
    )


def _real_failure_script() -> ModelScript:
    """A real outage before any records: the program must not invent a hypothesis."""
    return ModelScript(
        plan=[_plan(REAL_PLAN)],
        revise=[],
        assess=[],
        report=[REPORT_BODY],
    )


def _mock_service(repositories: MemoryRepositories, script: ModelScript) -> AiopsDiagnosticService:
    return AiopsDiagnosticService(
        repositories=repositories,
        llm_provider=cast(Any, ScriptedLlmProvider(script)),
        config=_mock_config(),
        cls_region="ap-guangzhou",
        cls_topic_id="topic-1",
    )


def _real_service(
    repositories: MemoryRepositories, script: ModelScript, double: ToolCallDouble
) -> AiopsDiagnosticService:
    return AiopsDiagnosticService(
        repositories=repositories,
        llm_provider=cast(Any, ScriptedLlmProvider(script)),
        config=_real_config(),
        cls_region="ap-guangzhou",
        cls_topic_id="topic-1",
        mcp_client_provider=cast(Any, ToolClientProvider(double)),
    )


async def _claimed_context(
    repositories: MemoryRepositories, *, job_id: str, task_id: str, query: str
) -> BackgroundJobContext:
    assert repositories.background_jobs is not None
    await repositories.diagnostics.create_task(
        owner_user_id=OWNER,
        task_id=task_id,
        status="queued",
        query=query,
        input_payload={"alert": {}},
    )
    await repositories.background_jobs.enqueue(
        owner_user_id=OWNER,
        job_id=job_id,
        kind="aiops_diagnosis",
        resource_type="aiops_diagnostic",
        resource_id=task_id,
        payload={"diagnosticId": task_id},
        max_attempts=1,
    )
    claimed = await repositories.background_jobs.claim_next(
        worker_id="worker-integration",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    assert claimed is not None
    return BackgroundJobContext(job=claimed, repository=repositories.background_jobs)


async def _register(client: httpx.AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "displayName": email.split("@")[0],
            "password": "correct horse battery staple",
        },
    )
    return cast(dict[str, Any], response.json()["data"])


def _auth_headers(token: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sse_frames(body: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    event_name = ""
    event_id = ""
    for line in body.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("id: "):
            event_id = line.removeprefix("id: ")
        elif line.startswith("data: "):
            payload = cast(dict[str, Any], json.loads(line.removeprefix("data: ")))
            frames.append({"event": event_name, "id": event_id, "payload": payload})
    return frames


async def _wait_terminal(
    client: httpx.AsyncClient, headers: dict[str, str], diagnostic_id: str
) -> dict[str, Any]:
    for _ in range(100):
        response = await client.get(
            f"/aiops/diagnostics/{diagnostic_id}/evidence-chain", headers=headers
        )
        assert response.status_code == 200
        data = cast(dict[str, Any], response.json()["data"])
        if cast(dict[str, Any], data["task"])["status"] in TERMINAL_STATUSES:
            return data
        await asyncio.sleep(0.02)
    raise AssertionError("diagnosis did not reach a terminal state")


@pytest.mark.asyncio
async def test_api_mock_diagnosis_delivers_the_frontend_contract(
    migrated_url: str,
) -> None:
    engine = create_memory_engine(migrated_url)
    try:
        sessions = create_memory_session_factory(engine)
        repositories = create_sqlite_memory_repositories(sessions)
        script = _mock_script()
        runner = _mock_service(repositories, script)
        app = create_app(
            database_url=migrated_url,
            session_factory=sessions,
            aiops_diagnostic_runner=cast(AiopsDiagnosticRunner, runner),
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            owner = await _register(client, "integration-owner@example.com")
            headers = _auth_headers(owner["accessToken"])
            created = await client.post(
                "/aiops/diagnostics",
                headers=headers,
                json={"query": "订单接口错误率升高", "alert": {"service": "order-service"}},
            )
            assert created.status_code == 202
            diagnostic_id = created.json()["data"]["id"]

            stream = await client.post(
                f"/aiops/diagnostics/{diagnostic_id}:stream", headers=headers
            )
            chain = await _wait_terminal(client, headers, diagnostic_id)
            events_before = len(script.calls)
            replay = await client.post(
                f"/aiops/diagnostics/{diagnostic_id}:stream", headers=headers
            )

        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        frames = _sse_frames(stream.text)
        assert [frame["event"] for frame in frames][-3:] == [
            "report",
            "task.status",
            "complete",
        ]
        assert all(frame["id"] == frame["payload"]["id"] for frame in frames)

        task = cast(dict[str, Any], chain["task"])
        assert task["status"] == "succeeded"
        diagnosis = cast(dict[str, Any], task["resultPayload"]["diagnosis"])
        assert set(diagnosis) == {
            "engine",
            "mode",
            "hypotheses",
            "hypothesis_relations",
            "incident_conclusion",
            "query_records",
            "tool_evidence",
            "unmet_requests",
            "unassessed_evidence_ids",
            "assessment_is_current",
            "budget",
        }
        assert diagnosis["engine"] == "hypothesis-driven-v1"
        assert diagnosis["mode"] == "mock"
        assert cast(dict[str, Any], diagnosis["incident_conclusion"])["conclusion_status"] == (
            "confirmed"
        )
        assert len(cast(list[object], diagnosis["query_records"])) == 3

        phases = [step["phase"] for step in cast(list[dict[str, Any]], chain["steps"])]
        assert set(phases) >= {
            "prepare_context",
            "build_queries",
            "execute_queries",
            "revise_hypotheses",
            "assess_hypotheses",
            "finalize",
        }
        tool_calls = cast(list[dict[str, Any]], chain["toolCalls"])
        assert [tool["status"] for tool in tool_calls] == ["completed"] * 3
        reports = cast(list[dict[str, Any]], chain["reports"])
        assert len(reports) == 1
        for heading in REPORT_HEADINGS:
            assert heading in cast(str, reports[0]["content"])

        # 重复订阅只重放已持久事件，不重新运行诊断。
        assert _sse_frames(replay.text) == frames
        assert len(script.calls) == events_before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_mode_diagnosis_uses_transport_double_without_retry(
    migrated_url: str,
) -> None:
    engine = create_memory_engine(migrated_url)
    try:
        sessions = create_memory_session_factory(engine)
        repositories = create_sqlite_memory_repositories(sessions)
        double = ToolCallDouble()
        script = _real_script()
        service = _real_service(repositories, script, double)
        context = await _claimed_context(
            repositories, job_id="job-real", task_id="task-real", query="订单接口错误率升高"
        )

        await service.run(context)

        task = await repositories.diagnostics.get_task(owner_user_id=OWNER, task_id="task-real")
        assert task is not None and task.status == "succeeded"
        assert double.calls == ["SearchLog"]
        diagnosis = cast(dict[str, Any], task.result_payload["diagnosis"])
        assert diagnosis["mode"] == "real"
        records = cast(list[dict[str, Any]], diagnosis["query_records"])
        assert [record["status"] for record in records] == ["succeeded"]
        evidence = cast(list[dict[str, Any]], diagnosis["tool_evidence"])
        assert evidence and evidence[0]["kind"] == "log"
        jobs = repositories.background_jobs
        assert jobs is not None
        stored = await jobs.list_events(owner_user_id=OWNER, job_id="job-real")
        report = cast(dict[str, Any], stored[-3].payload["report"])
        assert "模拟场景" not in cast(str, report["content"])
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_mode_records_failed_tool_without_mock_fallback(
    migrated_url: str,
) -> None:
    engine = create_memory_engine(migrated_url)
    try:
        sessions = create_memory_session_factory(engine)
        repositories = create_sqlite_memory_repositories(sessions)
        double = ToolCallDouble(fail=True)
        script = _real_failure_script()
        service = _real_service(repositories, script, double)
        context = await _claimed_context(
            repositories,
            job_id="job-real-failed",
            task_id="task-real-failed",
            query="订单接口错误率升高",
        )

        await service.run(context)

        task = await repositories.diagnostics.get_task(
            owner_user_id=OWNER, task_id="task-real-failed"
        )
        assert task is not None and task.status == "failed"
        assert double.calls == ["SearchLog"]
        diagnosis = cast(dict[str, Any], task.result_payload["diagnosis"])
        assert diagnosis["mode"] == "real"
        records = cast(list[dict[str, Any]], diagnosis["query_records"])
        assert [record["status"] for record in records] == ["failed"]
        # 真实失败绝不回退 Mock：不写入模拟证据，也不伪造模拟假设或根因。
        assert cast(list[object], diagnosis["tool_evidence"]) == []
        assert cast(list[object], diagnosis["hypotheses"]) == []
        conclusion = cast(dict[str, Any], diagnosis["incident_conclusion"])
        assert conclusion["conclusion_status"] == "unconfirmed"
        assert conclusion["root_cause"] is None
        assert "order-pool-exhaustion" not in json.dumps(diagnosis)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_api_queued_cancel_does_not_start_the_diagnosis(
    migrated_url: str,
) -> None:
    engine = create_memory_engine(migrated_url)
    try:
        sessions = create_memory_session_factory(engine)
        repositories = create_sqlite_memory_repositories(sessions)
        script = _mock_script()
        runner = _mock_service(repositories, script)
        app = create_app(
            database_url=migrated_url,
            session_factory=sessions,
            aiops_diagnostic_runner=cast(AiopsDiagnosticRunner, runner),
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            owner = await _register(client, "integration-cancel@example.com")
            headers = _auth_headers(owner["accessToken"])
            owner_id = cast(str, owner["user"]["id"])
            await repositories.diagnostics.create_task(
                owner_user_id=owner_id,
                task_id="task-cancel",
                status="queued",
                query="订单接口错误率升高",
                input_payload={"alert": {}},
            )
            jobs = repositories.background_jobs
            assert jobs is not None
            job = await jobs.enqueue(
                owner_user_id=owner_id,
                job_id="job-cancel",
                kind="aiops_diagnosis",
                resource_type="aiops_diagnostic",
                resource_id="task-cancel",
                payload={"diagnosticId": "task-cancel"},
                max_attempts=1,
            )

            cancelled = await client.post(f"/background-jobs/{job.id}:cancel", headers=headers)

        assert cancelled.status_code == 200
        assert cancelled.json()["data"]["status"] == "cancelled"
        # 取消不加载外部资源：不调用模型，也不产出假设。
        assert script.calls == []
        task = await repositories.diagnostics.get_task(
            owner_user_id=owner_id, task_id="task-cancel"
        )
        assert task is not None and task.status == "cancelled"
        reports = await repositories.diagnostics.list_reports(
            owner_user_id=owner_id, task_id="task-cancel"
        )
        assert len(reports) == 1
        assert "取消" in reports[0].content
        assert "取消" in reports[0].title
        # 取消不产出调查投影，也不伪造假设或根因。
        assert "diagnosis" not in task.result_payload
    finally:
        await engine.dispose()


def _two_run_script() -> ModelScript:
    """Enough scripted replies for two independent mock diagnoses."""
    return ModelScript(
        plan=[_plan(MOCK_PLAN)] * 2,
        revise=[json.dumps(MOCK_REVISION)] * 2,
        assess=[json.dumps(MOCK_ASSESSMENT)] * 2,
        report=[REPORT_BODY] * 2,
    )


@pytest.mark.asyncio
async def test_cross_owner_stream_cursor_and_chain_are_denied(
    migrated_url: str,
) -> None:
    engine = create_memory_engine(migrated_url)
    try:
        sessions = create_memory_session_factory(engine)
        repositories = create_sqlite_memory_repositories(sessions)
        runner = _mock_service(repositories, _two_run_script())
        app = create_app(
            database_url=migrated_url,
            session_factory=sessions,
            aiops_diagnostic_runner=cast(AiopsDiagnosticRunner, runner),
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            owner = await _register(client, "isolation-owner@example.com")
            other = await _register(client, "isolation-other@example.com")
            owner_headers = _auth_headers(owner["accessToken"])
            other_headers = _auth_headers(other["accessToken"])
            owner_created = await client.post(
                "/aiops/diagnostics",
                headers=owner_headers,
                json={"query": "订单接口错误率升高", "alert": {}},
            )
            other_created = await client.post(
                "/aiops/diagnostics",
                headers=other_headers,
                json={"query": "支付网关超时", "alert": {}},
            )
            owner_id = cast(str, owner_created.json()["data"]["id"])
            other_id = cast(str, other_created.json()["data"]["id"])
            owner_stream = await client.post(
                f"/aiops/diagnostics/{owner_id}:stream", headers=owner_headers
            )
            owner_cursor = _sse_frames(owner_stream.text)[0]["id"]

            denied_stream = await client.post(
                f"/aiops/diagnostics/{owner_id}:stream", headers=other_headers
            )
            foreign_cursor = await client.post(
                f"/aiops/diagnostics/{other_id}:stream",
                headers={**other_headers, "Last-Event-ID": owner_cursor},
            )
            denied_chain = await client.get(
                f"/aiops/diagnostics/{owner_id}/evidence-chain", headers=other_headers
            )

        assert denied_stream.status_code == 403
        # 游标必须属于同一 user 与同一 job：他人事件 ID 不能作用于自己的任务。
        assert foreign_cursor.status_code == 404
        assert denied_chain.status_code == 403
        assert owner_id not in denied_stream.text
        assert owner_id not in foreign_cursor.text
        assert owner_id not in denied_chain.text
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_events_and_report_never_expose_credentials(migrated_url: str) -> None:
    engine = create_memory_engine(migrated_url)
    secret_token = "sk-live-abcdef123456"
    secret_id = "AKIDabcdef123456"
    try:
        sessions = create_memory_session_factory(engine)
        repositories = create_sqlite_memory_repositories(sessions)
        double = ToolCallDouble(
            fail=True,
            error_message=f"CLS rejected Authorization {secret_token} with {secret_id}",
        )
        service = _real_service(repositories, _real_failure_script(), double)
        context = await _claimed_context(
            repositories,
            job_id="job-redaction",
            task_id="task-redaction",
            query="订单接口错误率升高",
        )

        await service.run(context)

        task = await repositories.diagnostics.get_task(
            owner_user_id=OWNER, task_id="task-redaction"
        )
        assert task is not None
        records = cast(
            list[dict[str, Any]],
            cast(dict[str, Any], task.result_payload["diagnosis"])["query_records"],
        )
        assert "[redacted]" in cast(str, records[0]["status_reason"])

        jobs = repositories.background_jobs
        assert jobs is not None
        events = await jobs.list_events(owner_user_id=OWNER, job_id="job-redaction")
        serialized = json.dumps(task.result_payload) + json.dumps(
            [event.payload for event in events]
        )
        for secret in (secret_token, secret_id):
            assert secret not in serialized
        assert "[redacted]" in serialized
    finally:
        await engine.dispose()
