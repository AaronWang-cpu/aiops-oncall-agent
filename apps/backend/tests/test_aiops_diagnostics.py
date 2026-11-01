"""AIOps 诊断的 HTTP/SSE 契约、案例库权限与证据作用域回归。

旧 SOP-first 图的行为已由假设驱动诊断替换，相关断言迁移到
`test_diagnosis_graph.py`（图闭环）与 `test_diagnosis_tools.py`（参数与筛选）。
本文件保留仍然适用的 API、所有权和存储作用域断言。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.aiops.diagnosis_config import DiagnosisConfig
from super_ai.aiops.diagnostics import AiopsDiagnosticService
from super_ai.api.app import AiopsDiagnosticRunner, create_app
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.repositories import TenantScopeError
from super_ai.memory.sqlite import create_sqlite_memory_repositories

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = BACKEND_ROOT / "src" / "super_ai" / "aiops" / "mock_scenarios"

PLAN: dict[str, object] = {
    "calls": [
        {
            "hypothesis_ids": [],
            "question": "订单服务窗口内有哪些错误日志？",
            "tool_name": "SearchLog",
            "arguments": {"service": "order-service"},
        }
    ],
    "unmet_requests": [],
}

REVISION: dict[str, object] = {
    "new_hypotheses": [{"statement": "订单服务连接池耗尽导致接口报错"}],
    "revised_hypotheses": [],
}

ASSESSMENT: dict[str, object] = {
    "hypothesis_assessments": [
        {
            "hypothesis_id": "H1",
            "hypothesis_status": "supported",
            "assessment": "错误日志显示连接等待超时。",
            "evidence_links": [],
            "gaps": [],
        }
    ],
    "hypothesis_relations": [],
    "incident_conclusion": {
        "conclusion_status": "unconfirmed",
        "root_cause": None,
        "stop_reason": "budget_exhausted",
        "explanation": "证据支持症状，但未解释耗尽机制。",
    },
    "next_step": {"action": "finalize", "reason": "已有结论。", "requests": []},
}

REPORT_BODY = """## 诊断结论

本次调查未确认事故根本原因。

## 原因与证据

日志显示连接等待超时。

## 调查结果与局限

未取得能解释耗尽机制的证据。

## 后续建议

需补齐机制证据后再判断。
"""


@dataclass
class ModelScript:
    plan: list[str] = field(default_factory=lambda: [json.dumps(PLAN)])
    revise: list[str] = field(default_factory=lambda: [json.dumps(REVISION)])
    assess: list[str] = field(default_factory=lambda: [json.dumps(ASSESSMENT)])
    report: list[str] = field(default_factory=lambda: [REPORT_BODY])

    def reply(self, prompt: str) -> str:
        for marker, queue in (
            ("执行计划器", self.plan),
            ("假设调整器", self.revise),
            ("评估器", self.assess),
            ("报告撰写者", self.report),
        ):
            if marker in prompt:
                return queue.pop(0) if queue else REPORT_BODY
        raise AssertionError("unexpected diagnostic prompt")


class ScriptedModel:
    def __init__(self, script: ModelScript) -> None:
        self._script = script

    async def ainvoke(self, input: object) -> object:
        return self._script.reply(str(input))


class ScriptedLlmProvider:
    def __init__(self) -> None:
        self.script = ModelScript()

    def create_diagnostic_model(self, *, timeout_seconds: float) -> ScriptedModel:
        del timeout_seconds
        return ScriptedModel(self.script)


def _mock_service(repositories: Any) -> AiopsDiagnosticService:
    return AiopsDiagnosticService(
        repositories=repositories,
        llm_provider=cast(Any, ScriptedLlmProvider()),
        config=DiagnosisConfig(
            mode="mock",
            mockScenarioPath=str(SCENARIO_DIR / "order-pool-exhaustion.json"),
        ),
        cls_region="ap-guangzhou",
        cls_topic_id="topic-1",
    )


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'aiops.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url


@pytest.mark.asyncio
async def test_aiops_stream_requires_task_owner(migrated_database_url: str) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        sessions = create_memory_session_factory(engine)
        repositories = create_sqlite_memory_repositories(sessions)
        runner = _mock_service(repositories)
        app = create_app(
            database_url=migrated_database_url,
            session_factory=sessions,
            aiops_diagnostic_runner=cast(AiopsDiagnosticRunner, runner),
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            owner = await _register(client, "owner@example.com")
            other = await _register(client, "other@example.com")
            create_response = await client.post(
                "/aiops/diagnostics",
                headers=_auth_headers(owner["accessToken"]),
                json={"query": "Inspect order errors", "alert": {}},
            )
            diagnostic_id = create_response.json()["data"]["id"]
            denied = await client.post(
                f"/aiops/diagnostics/{diagnostic_id}:stream",
                headers=_auth_headers(other["accessToken"]),
            )
            stream = await client.post(
                f"/aiops/diagnostics/{diagnostic_id}:stream",
                headers=_auth_headers(owner["accessToken"]),
            )
            history = await client.get(
                "/aiops/diagnostics",
                headers=_auth_headers(owner["accessToken"]),
            )
            owner_chain = await client.get(
                f"/aiops/diagnostics/{diagnostic_id}/evidence-chain",
                headers=_auth_headers(owner["accessToken"]),
            )
            denied_chain = await client.get(
                f"/aiops/diagnostics/{diagnostic_id}/evidence-chain",
                headers=_auth_headers(other["accessToken"]),
            )

        assert create_response.status_code == 202
        assert denied.status_code == 403
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        frames = _sse_frames(stream.text)
        assert [frame["event"] for frame in frames][-3:] == [
            "report",
            "task.status",
            "complete",
        ]
        assert all(frame["id"].startswith("diagnostic_") for frame in frames)
        assert all(frame["payload"]["id"] == frame["id"] for frame in frames)
        assert history.status_code == 200
        assert [item["id"] for item in history.json()["data"]["items"]] == [diagnostic_id]
        assert owner_chain.status_code == 200
        assert owner_chain.json()["data"]["task"]["id"] == diagnostic_id
        assert denied_chain.status_code == 403
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_aiops_stream_resumes_from_persisted_event_id(migrated_database_url: str) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        sessions = create_memory_session_factory(engine)
        repositories = create_sqlite_memory_repositories(sessions)
        runner = _mock_service(repositories)
        app = create_app(
            database_url=migrated_database_url,
            session_factory=sessions,
            aiops_diagnostic_runner=cast(AiopsDiagnosticRunner, runner),
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            owner = await _register(client, "resume@example.com")
            create_response = await client.post(
                "/aiops/diagnostics",
                headers=_auth_headers(owner["accessToken"]),
                json={"query": "Inspect order errors", "alert": {}},
            )
            diagnostic_id = create_response.json()["data"]["id"]
            full = await client.post(
                f"/aiops/diagnostics/{diagnostic_id}:stream",
                headers=_auth_headers(owner["accessToken"]),
            )
            frames = _sse_frames(full.text)
            cursor = frames[0]["id"]
            resume_headers = {**_auth_headers(owner["accessToken"]), "Last-Event-ID": cursor}
            unknown_headers = {
                **_auth_headers(owner["accessToken"]),
                "Last-Event-ID": "diagnostic_unknown_cursor",
            }
            resumed = await client.post(
                f"/aiops/diagnostics/{diagnostic_id}:stream",
                headers=resume_headers,
            )
            unknown_cursor = await client.post(
                f"/aiops/diagnostics/{diagnostic_id}:stream",
                headers=unknown_headers,
            )

        resumed_frames = _sse_frames(resumed.text)
        assert resumed.status_code == 200
        assert resumed_frames
        assert [frame["id"] for frame in resumed_frames] == [frame["id"] for frame in frames[1:]]
        assert unknown_cursor.status_code == 404
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_diagnosis_case_api_lists_only_owner_cases_and_denies_direct_access(
    migrated_database_url: str,
) -> None:
    app = create_app(database_url=migrated_database_url)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = await _register(client, "case-owner@example.com")
        other = await _register(client, "case-other@example.com")
        repositories = app.state.memory_repositories
        task = await repositories.diagnostics.create_task(
            owner_user_id=owner["user"]["id"],
            task_id="diagnostic-case-owner",
            status="succeeded",
            query="Investigate checkout timeout",
        )
        report = await repositories.diagnostics.add_report(
            owner_user_id=owner["user"]["id"],
            report_id="report-case-owner",
            task_id=task.id,
            title="Checkout timeout report",
            content="Evidence-backed report.",
        )
        document = await repositories.documents.create_document(
            owner_user_id=owner["user"]["id"],
            document_id="document-case-owner",
            knowledge_base_id=f"kb_{owner['user']['id']}",
            filename="checkout-case.md",
            size_bytes=22,
            mime_type="text/markdown",
            content_hash="sha256:case-owner",
            metadata={"knowledgeType": "diagnostic-case"},
        )
        index_task = await repositories.document_index_tasks.create_task(
            owner_user_id=owner["user"]["id"],
            task_id="index-case-owner",
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
        )
        case = await repositories.diagnostics.create_case(
            owner_user_id=owner["user"]["id"],
            case_id="case-owner",
            task_id=task.id,
            report_id=report.id,
            document_id=document.id,
            index_task_id=index_task.id,
            alert_name="CheckoutTimeout",
            service="checkout",
            keywords=["checkout", "timeout"],
            root_cause="",
            remediation="",
            summary="Evidence-backed report.",
            evidence_ids=[],
        )
        owner_list = await client.get(
            "/aiops/diagnostic-cases",
            headers=_auth_headers(owner["accessToken"]),
        )
        owner_detail = await client.get(
            f"/aiops/diagnostic-cases/{case.id}",
            headers=_auth_headers(owner["accessToken"]),
        )
        denied_detail = await client.get(
            f"/aiops/diagnostic-cases/{case.id}",
            headers=_auth_headers(other["accessToken"]),
        )

    assert owner_list.status_code == 200
    assert [item["id"] for item in owner_list.json()["data"]["items"]] == [case.id]
    assert owner_detail.status_code == 200
    assert owner_detail.json()["data"]["id"] == case.id
    assert denied_detail.status_code == 403
    assert case.id not in denied_detail.text


@pytest.mark.asyncio
async def test_diagnostic_evidence_repository_rejects_cross_tenant_step(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task_a = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-owner-a",
            status="accepted",
            query="Owner A",
        )
        task_b = await repositories.diagnostics.create_task(
            owner_user_id="user-b",
            task_id="diagnostic-owner-b",
            status="accepted",
            query="Owner B",
        )
        step_a = await repositories.diagnostics.create_step(
            owner_user_id="user-a",
            step_id="step-owner-a",
            task_id=task_a.id,
            sequence=1,
            phase="planner",
            status="completed",
        )

        with pytest.raises(TenantScopeError):
            await repositories.diagnostics.create_evidence(
                owner_user_id="user-b",
                evidence_id="evidence-cross-tenant",
                task_id=task_b.id,
                step_id=step_a.id,
                kind="ticket",
                source="ticket-system",
                summary="Must not be written.",
            )
    finally:
        await engine.dispose()


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
