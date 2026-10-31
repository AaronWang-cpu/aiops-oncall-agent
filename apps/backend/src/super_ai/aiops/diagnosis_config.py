"""Diagnosis settings use the existing merged repository JSON configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from super_ai.project_config import ProjectConfigurationError, load_project_config

PositiveInteger = Annotated[int, Field(gt=0)]


class DiagnosisConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True, frozen=True)

    mode: Literal["real", "mock"] = "real"
    mock_scenario_path: str = Field(default="", alias="mockScenarioPath")
    project_knowledge_path: str = Field(default="", alias="projectKnowledgePath")
    max_rounds: PositiveInteger = Field(default=5, alias="maxRounds")
    max_tool_calls: PositiveInteger = Field(default=20, alias="maxToolCalls")
    max_calls_per_batch: PositiveInteger = Field(default=4, alias="maxCallsPerBatch")
    max_concurrent_calls: PositiveInteger = Field(default=4, alias="maxConcurrentCalls")
    max_internal_steps: PositiveInteger = Field(default=2, alias="maxInternalSteps")
    investigation_seconds: PositiveInteger = Field(default=390, alias="investigationSeconds")
    final_analysis_seconds: PositiveInteger = Field(default=60, alias="finalAnalysisSeconds")
    report_seconds: PositiveInteger = Field(default=30, alias="reportSeconds")
    total_seconds: PositiveInteger = Field(default=480, alias="totalSeconds")
    tool_timeout_seconds: PositiveInteger = Field(default=60, alias="toolTimeoutSeconds")
    model_timeout_seconds: PositiveInteger = Field(default=60, alias="modelTimeoutSeconds")

    @model_validator(mode="after")
    def validate_time_allocation(self) -> DiagnosisConfig:
        if (
            self.investigation_seconds + self.final_analysis_seconds + self.report_seconds
            != self.total_seconds
        ):
            raise ValueError("diagnosis phase durations must sum to totalSeconds")
        if self.mode == "mock" and not self.mock_scenario_path.strip():
            raise ValueError("mock mode requires an explicit mockScenarioPath")
        return self


def load_diagnosis_config(config_path: Path | str | None = None) -> DiagnosisConfig:
    raw: object = load_project_config(config_path).get("aiopsDiagnosis", {})
    try:
        return DiagnosisConfig.model_validate(raw)
    except ValidationError as exc:
        # Configuration values can contain local paths; expose only safe field names.
        fields = sorted(
            {
                ".".join(str(part) for part in error["loc"]) or "aiopsDiagnosis"
                for error in exc.errors(include_input=False)
            }
        )
        raise ProjectConfigurationError(
            "Invalid aiopsDiagnosis configuration fields: " + ", ".join(fields)
        ) from None
