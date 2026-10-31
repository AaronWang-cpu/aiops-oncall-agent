from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from super_ai.aiops.diagnosis_config import DiagnosisConfig, load_diagnosis_config
from super_ai.project_config import ProjectConfigurationError


def test_missing_section_uses_real_mode_and_independent_default_budgets(tmp_path: Path) -> None:
    path = tmp_path / "project.json"
    path.write_text("{}", encoding="utf-8")
    config = load_diagnosis_config(path)
    assert config.mode == "real"
    assert (config.max_rounds, config.max_tool_calls, config.max_internal_steps) == (5, 20, 2)
    assert (config.investigation_seconds, config.final_analysis_seconds, config.report_seconds) == (
        390,
        60,
        30,
    )
    assert config.total_seconds == 480


def test_recursive_user_override_keeps_unspecified_defaults(tmp_path: Path) -> None:
    path = tmp_path / "project.json"
    path.write_text(json.dumps({"aiopsDiagnosis": {"maxRounds": 3}}), encoding="utf-8")
    (tmp_path / "user.project.json").write_text(
        json.dumps({"aiopsDiagnosis": {"maxToolCalls": 8}}), encoding="utf-8"
    )
    config = load_diagnosis_config(path)
    assert (config.max_rounds, config.max_tool_calls, config.max_calls_per_batch) == (3, 8, 4)


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.2, "5", None])
def test_budget_values_are_positive_strict_integers(value: object) -> None:
    with pytest.raises(ValidationError):
        DiagnosisConfig.model_validate({"maxRounds": value})


@pytest.mark.parametrize(
    "payload",
    [
        {"totalSeconds": 481},
        {"investigationSeconds": 0},
        {"reportSeconds": -1},
        {"mode": "automatic"},
        {"mode": "mock"},
        {"maxRetries": 2},
        {"toolTimeoutSeconds": True},
    ],
)
def test_invalid_modes_time_allocation_and_extra_fields_are_rejected(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        DiagnosisConfig.model_validate(payload)


def test_mock_requires_explicit_path_and_config_is_frozen() -> None:
    config = DiagnosisConfig.model_validate(
        {
            "mode": "mock",
            "mockScenarioPath": "apps/backend/src/super_ai/aiops/mock_scenarios/demo.json",
        }
    )
    assert config.mode == "mock"
    with pytest.raises(ValidationError):
        config.mode = "real"


def test_loader_errors_do_not_expose_local_values(tmp_path: Path) -> None:
    path = tmp_path / "project.json"
    path.write_text(
        json.dumps(
            {
                "aiopsDiagnosis": {
                    "mode": "secret-local-value",
                    "projectKnowledgePath": "private/path",
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProjectConfigurationError) as exc:
        load_diagnosis_config(path)
    assert "mode" in str(exc.value)
    assert "secret-local-value" not in str(exc.value)
    assert "private/path" not in str(exc.value)


@pytest.mark.parametrize("section", [None, [], "not-an-object", False])
def test_present_invalid_section_is_not_silently_defaulted(tmp_path: Path, section: object) -> None:
    path = tmp_path / "project.json"
    path.write_text(json.dumps({"aiopsDiagnosis": section}), encoding="utf-8")
    with pytest.raises(ProjectConfigurationError):
        load_diagnosis_config(path)


def test_templates_validate_without_mock_or_real_secrets() -> None:
    root = Path(__file__).resolve().parents[3]
    config = load_diagnosis_config(root / "config" / "project.template.json")
    assert config == DiagnosisConfig()
    raw: object = json.loads((root / "config" / "user.project.template.json").read_text("utf-8"))
    assert isinstance(raw, dict)
    config = DiagnosisConfig.model_validate(raw["aiopsDiagnosis"])
    assert config.mode == "real"
    assert not config.mock_scenario_path
