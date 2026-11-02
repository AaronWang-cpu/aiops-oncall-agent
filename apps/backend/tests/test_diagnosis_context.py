"""P3：固定知识/场景快照的加载、路径解析与恢复行为。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from super_ai.aiops.diagnosis_config import DiagnosisConfig
from super_ai.aiops.diagnosis_context import (
    DiagnosisContentError,
    ProjectKnowledge,
    prepare_diagnosis_context,
    resolve_content_path,
    restore_diagnosis_context,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
SCENARIO_DIR = BACKEND_ROOT / "src" / "super_ai" / "aiops" / "mock_scenarios"
KNOWLEDGE_TEMPLATE = REPOSITORY_ROOT / "config" / "aiops-project-knowledge.template.yaml"
FORBIDDEN_ANSWER_KEYS = {
    "expected_root_cause",
    "expectedRootCause",
    "root_cause",
    "rootCause",
    "answer",
    "score",
    "golden",
    "grading",
}


def _mock_config(scenario_name: str) -> DiagnosisConfig:
    return DiagnosisConfig(mode="mock", mockScenarioPath=str(SCENARIO_DIR / scenario_name))


def test_missing_knowledge_path_allows_empty_knowledge() -> None:
    context = prepare_diagnosis_context(DiagnosisConfig())

    assert context.mode == "real"
    assert context.knowledge == ProjectKnowledge()
    assert context.knowledge.project_overview == ""
    assert context.knowledge.services == {}
    assert context.scenario is None


def test_relative_knowledge_path_resolves_against_repository_root(tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "config"
    knowledge_dir.mkdir()
    (knowledge_dir / "knowledge.yaml").write_text(
        "project_overview: 本地订单平台\nservices:\n  order-service:\n    description: 订单服务\n",
        encoding="utf-8",
    )
    config = DiagnosisConfig(projectKnowledgePath="config/knowledge.yaml")

    context = prepare_diagnosis_context(config, repository_root=tmp_path)

    assert context.knowledge.project_overview == "本地订单平台"
    assert context.knowledge.services["order-service"].description == "订单服务"


def test_absolute_knowledge_path_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "knowledge.yaml"
    path.write_text("project_overview: 绝对路径知识\n", encoding="utf-8")

    context = prepare_diagnosis_context(
        DiagnosisConfig(projectKnowledgePath=str(path)),
        repository_root=tmp_path,
    )

    assert context.knowledge.project_overview == "绝对路径知识"
    assert resolve_content_path(str(path), repository_root=tmp_path) == path


@pytest.mark.parametrize(
    "content",
    [
        "- 只是一个列表\n",
        "unknown_section: 1\n",
        "project_overview: [unclosed\n",
    ],
)
def test_explicit_invalid_knowledge_fails_preparation(tmp_path: Path, content: str) -> None:
    path = tmp_path / "knowledge.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(DiagnosisContentError):
        prepare_diagnosis_context(
            DiagnosisConfig(projectKnowledgePath=str(path)),
            repository_root=tmp_path,
        )


def test_explicit_missing_knowledge_fails_without_silent_empty(tmp_path: Path) -> None:
    with pytest.raises(DiagnosisContentError):
        prepare_diagnosis_context(
            DiagnosisConfig(projectKnowledgePath="config/absent-knowledge.yaml"),
            repository_root=tmp_path,
        )


def test_knowledge_error_message_does_not_leak_paths_or_content(tmp_path: Path) -> None:
    path = tmp_path / "private-knowledge.yaml"
    path.write_text("project_overview: 内部机密平台代号\nservices: [oops\n", encoding="utf-8")

    with pytest.raises(DiagnosisContentError) as exc_info:
        prepare_diagnosis_context(
            DiagnosisConfig(projectKnowledgePath=str(path)),
            repository_root=tmp_path,
        )

    message = str(exc_info.value)
    assert "机密" not in message
    assert str(path) not in message


def test_knowledge_snapshot_survives_file_change_and_restore(tmp_path: Path) -> None:
    path = tmp_path / "knowledge.yaml"
    path.write_text("project_overview: 初始快照\n", encoding="utf-8")
    config = DiagnosisConfig(projectKnowledgePath=str(path))
    context = prepare_diagnosis_context(config, repository_root=tmp_path)

    path.write_text("project_overview: 被修改后的内容\n", encoding="utf-8")
    path.unlink()
    restored = restore_diagnosis_context(context.model_dump())

    assert context.knowledge.project_overview == "初始快照"
    assert restored.knowledge.project_overview == "初始快照"


def test_knowledge_is_not_assigned_an_evidence_identity(tmp_path: Path) -> None:
    path = tmp_path / "knowledge.yaml"
    path.write_text("project_overview: 背景知识\n", encoding="utf-8")

    context = prepare_diagnosis_context(
        DiagnosisConfig(projectKnowledgePath=str(path)),
        repository_root=tmp_path,
    )
    snapshot = context.model_dump()

    assert set(snapshot) == {"mode", "knowledge", "metrics", "dependencies", "scenario"}
    assert "evidence_id" not in json.dumps(snapshot["knowledge"], ensure_ascii=False)


def test_context_snapshot_carries_fixed_catalogs() -> None:
    context = prepare_diagnosis_context(DiagnosisConfig())

    assert context.metrics["order-service"]
    assert "mysql-order" in context.dependencies["order-service"]
    metric = context.metrics["order-service"][0]
    assert set(metric.model_dump()) == {
        "name",
        "description",
        "unit",
        "labels",
        "recommended_aggregation",
    }


def test_mock_context_requires_scenario_and_real_context_rejects_one(tmp_path: Path) -> None:
    context = prepare_diagnosis_context(_mock_config("order-pool-exhaustion.json"))
    assert context.scenario is not None

    with pytest.raises(ValueError, match="only mock context"):
        restore_diagnosis_context(
            {**context.model_dump(), "mode": "real"},
        )


def test_missing_mock_scenario_file_fails_preparation() -> None:
    with pytest.raises(DiagnosisContentError):
        prepare_diagnosis_context(_mock_config("absent-scenario.json"))


@pytest.mark.parametrize(
    "scenario_name",
    [
        "order-pool-exhaustion.json",
        "payment-gateway-timeout-with-distractors.json",
        "checkout-peak-incident.json",
    ],
)
def test_scenario_snapshot_is_factual_and_timezone_aware(scenario_name: str) -> None:
    context = prepare_diagnosis_context(_mock_config(scenario_name))
    scenario = context.scenario
    assert scenario is not None

    for alert in scenario.alerts:
        assert alert.starts_at.endswith("Z")
        assert alert.name and alert.service and alert.severity
    assert scenario.logs and scenario.metrics and scenario.changes
    for record in [*scenario.logs, *scenario.metrics, *scenario.changes]:
        assert record.timestamp.endswith("Z")
        assert record.service
    for metric in scenario.metrics:
        assert metric.value == pytest.approx(float(metric.value))
        catalog_names = {item.name for item in context.metrics[metric.service]}
        assert metric.metric_name in catalog_names


@pytest.mark.parametrize(
    "scenario_name",
    [
        "order-pool-exhaustion.json",
        "payment-gateway-timeout-with-distractors.json",
        "checkout-peak-incident.json",
    ],
)
def test_scenario_files_contain_no_answers_or_eval_assets(scenario_name: str) -> None:
    text = (SCENARIO_DIR / scenario_name).read_text(encoding="utf-8")
    payload = json.loads(text)

    assert FORBIDDEN_ANSWER_KEYS.isdisjoint(_all_keys(payload))
    assert "eval_fixtures" not in text
    assert "eval_results" not in text


def test_scenario_keeps_alerts_as_an_addressable_list() -> None:
    payload = json.loads((SCENARIO_DIR / "order-pool-exhaustion.json").read_text(encoding="utf-8"))

    assert set(payload) == {"alerts", "logs", "metrics", "changes"}
    assert payload["alerts"]
    for alert in payload["alerts"]:
        assert set(alert) == {"name", "service", "instance", "severity", "starts_at", "summary"}


def test_scenario_without_alerts_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "empty-alerts.json"
    path.write_text(
        json.dumps({"alerts": [], "logs": [], "metrics": [], "changes": []}),
        encoding="utf-8",
    )

    with pytest.raises(DiagnosisContentError):
        prepare_diagnosis_context(
            DiagnosisConfig(mode="mock", mockScenarioPath=str(path)),
        )


def test_knowledge_template_is_empty_and_secret_free() -> None:
    text = KNOWLEDGE_TEMPLATE.read_text(encoding="utf-8")

    assert 'project_overview: ""' in text
    assert "services: {}" in text
    for forbidden in ("sk-", "AKID", "secretKey", "预计根因", "expected_root_cause"):
        assert forbidden not in text


def _all_keys(value: object) -> set[str]:
    if isinstance(value, list):
        return {nested for item in cast(list[object], value) for nested in _all_keys(item)}
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        keys = {str(key) for key in mapping}
        return keys | {nested for item in mapping.values() for nested in _all_keys(item)}
    return set()
