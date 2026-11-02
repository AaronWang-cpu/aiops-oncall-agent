"""Mock-mode alert source: the scenario's own alerts, without any network call.

The real alert sources stay untouched — this provider only exists so that a mock
run offers the same operator entry point (pick an alert, then diagnose it) as a
real Alertmanager-backed run.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from super_ai.aiops.diagnosis_config import DiagnosisConfig
from super_ai.aiops.diagnosis_context import MockScenario, resolve_content_path
from super_ai.alerts import ActiveAlert, AlertProviderError

SCENARIO_SOURCE_ID = "local-scenario"


class ScenarioAlertProvider:
    """Return one active alert per alert declared by the fixed scenario."""

    def __init__(self, scenario: MockScenario) -> None:
        self._scenario = scenario

    async def list_active_alerts(self) -> list[ActiveAlert]:
        return [
            ActiveAlert(
                id=f"{SCENARIO_SOURCE_ID}:{index}:{alert.service}",
                source=SCENARIO_SOURCE_ID,
                alert_name=alert.name,
                service=alert.service,
                severity=alert.severity,
                status="active",
                starts_at=alert.starts_at,
                summary=alert.summary,
                labels={"service": alert.service, "instance": alert.instance},
                annotations={"summary": alert.summary},
                context={
                    "alertSourceType": "scenario-v1",
                    "instance": alert.instance,
                    "summary": alert.summary,
                },
            )
            for index, alert in enumerate(self._scenario.alerts, start=1)
        ]


def build_scenario_alert_provider(
    config: DiagnosisConfig, *, repository_root: Path | None = None
) -> ScenarioAlertProvider:
    """Load the scenario that also feeds diagnosis; no separate alert fixture."""
    if repository_root is None:
        path = resolve_content_path(config.mock_scenario_path)
    else:
        path = resolve_content_path(config.mock_scenario_path, repository_root=repository_root)
    try:
        scenario = MockScenario.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise AlertProviderError("The mock scenario for alerts is missing or invalid.") from exc
    return ScenarioAlertProvider(scenario)
