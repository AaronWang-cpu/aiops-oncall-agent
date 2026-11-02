"""Load operator-owned content once; checkpoints, not files, govern recovery."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, JsonValue, ValidationError, model_validator

from super_ai.aiops.catalogs import (
    get_dependencies,
    get_metrics_for_service,
    list_metric_services,
    list_topology_services,
)
from super_ai.aiops.diagnosis_config import DiagnosisConfig
from super_ai.aiops.diagnosis_models import DiagnosisModel, Text
from super_ai.project_config import DEFAULT_PROJECT_CONFIG_PATH

REPOSITORY_ROOT = DEFAULT_PROJECT_CONFIG_PATH.parent.parent


class DiagnosisContentError(RuntimeError):
    """Safe preparation error, without private content or absolute paths."""


def timestamp_ms(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return int(parsed.timestamp() * 1000)
    except (ValueError, OverflowError) as exc:
        raise ValueError("timestamp must be timezone-aware ISO 8601") from exc


class ServiceKnowledge(DiagnosisModel):
    description: str = ""


class ProjectKnowledge(DiagnosisModel):
    project_overview: str = ""
    services: dict[str, ServiceKnowledge] = Field(default_factory=dict)


class ScenarioAlert(DiagnosisModel):
    """One alert a scenario offers as a diagnosis entry point."""

    name: Text
    service: Text
    instance: Text
    severity: Text
    starts_at: Text
    summary: Text


class ScenarioLog(DiagnosisModel):
    timestamp: Text
    service: Text
    instance: Text
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"]
    message: Text


class ScenarioMetric(DiagnosisModel):
    timestamp: Text
    service: Text
    instance: Text
    metric_name: Text
    labels: dict[str, str]
    value: float


class ScenarioChange(DiagnosisModel):
    timestamp: Text
    service: Text
    instance: Text
    change_type: Literal["deployment", "config_change", "traffic_switch", "infra_change"]
    summary: Text
    details: dict[str, JsonValue]


class MockScenario(DiagnosisModel):
    """A fixed incident snapshot; every alert here is an entry into the same facts."""

    alerts: list[ScenarioAlert] = Field(min_length=1)
    logs: list[ScenarioLog]
    metrics: list[ScenarioMetric]
    changes: list[ScenarioChange]

    @model_validator(mode="after")
    def validate_timeline(self) -> MockScenario:
        for alert in self.alerts:
            timestamp_ms(alert.starts_at)
        for record in [*self.logs, *self.metrics, *self.changes]:
            timestamp_ms(record.timestamp)
        return self


class CatalogMetric(DiagnosisModel):
    name: Text
    description: str
    unit: str
    labels: list[str]
    recommended_aggregation: str


class DiagnosisContext(DiagnosisModel):
    mode: Literal["real", "mock"]
    knowledge: ProjectKnowledge
    metrics: dict[str, list[CatalogMetric]]
    dependencies: dict[str, list[str]]
    scenario: MockScenario | None

    @model_validator(mode="after")
    def validate_mode(self) -> DiagnosisContext:
        if (self.mode == "mock") != (self.scenario is not None):
            raise ValueError("only mock context must contain a scenario")
        return self


def resolve_content_path(value: str, *, repository_root: Path = REPOSITORY_ROOT) -> Path:
    path = Path(value.strip())
    return path.resolve() if path.is_absolute() else (repository_root / path).resolve()


def prepare_diagnosis_context(
    config: DiagnosisConfig, *, repository_root: Path = REPOSITORY_ROOT
) -> DiagnosisContext:
    knowledge = ProjectKnowledge()
    if config.project_knowledge_path.strip():
        path = resolve_content_path(config.project_knowledge_path, repository_root=repository_root)
        try:
            raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
            knowledge = ProjectKnowledge.model_validate({} if raw is None else raw)
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError):
            raise DiagnosisContentError("Project knowledge file is missing or invalid.") from None
    scenario: MockScenario | None = None
    if config.mode == "mock":
        path = resolve_content_path(config.mock_scenario_path, repository_root=repository_root)
        try:
            scenario = MockScenario.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError):
            raise DiagnosisContentError("Mock scenario file is missing or invalid.") from None
    metrics = {
        service: [
            CatalogMetric.model_validate({**asdict(metric), "labels": list(metric.labels)})
            for metric in get_metrics_for_service(service)
        ]
        for service in list_metric_services()
    }
    return DiagnosisContext(
        mode=config.mode,
        knowledge=knowledge,
        metrics=metrics,
        dependencies={
            service: list(get_dependencies(service)) for service in list_topology_services()
        },
        scenario=scenario,
    )


def restore_diagnosis_context(snapshot: dict[str, JsonValue]) -> DiagnosisContext:
    """Deliberately has no configuration/path input and cannot reload content."""
    return DiagnosisContext.model_validate(snapshot)
