"""Diagnosis tool adapters: one fixed snapshot per mode, never a silent fallback.

真实模式只暴露当前用户已启用连接中实际发现的工具；显式 Mock 模式只按参数筛选
固定事故快照。两种模式都不做自动重试，缺少能力时如实返回未满足需求，而不是用
本地模拟数据冒充真实观测。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from pydantic import JsonValue

from super_ai.aiops.catalogs import get_metrics_for_service
from super_ai.aiops.diagnosis_context import (
    DiagnosisContentError,
    DiagnosisContext,
    MockScenario,
    ScenarioChange,
    ScenarioLog,
    ScenarioMetric,
    timestamp_ms,
)
from super_ai.aiops.evidence_tools import (
    build_change_time_range,
    build_metric_time_range,
    resolve_change_query_services,
)
from super_ai.mcp_client import LocalMcpClient, McpToolDefinition

SearchLog = "SearchLog"
QueryMetric = "QueryMetric"
QueryChange = "QueryChange"

ToolArguments = dict[str, JsonValue]
ToolStatus = Literal["succeeded", "failed"]

MOCK_TOOL_NAMES = frozenset({SearchLog, QueryMetric, QueryChange})
AGGREGATIONS = frozenset({"avg", "sum", "max", "min", "p99"})
CHANGE_TYPES = frozenset({"deployment", "config_change", "traffic_switch", "infra_change"})
DEFAULT_LOG_LIMIT = 50
LOG_WINDOW_BEFORE_MINUTES = 10
LOG_WINDOW_AFTER_MINUTES = 5

# Mock 模式是程序定义的固定契约：只接受这些参数，未知参数明确失败而不是被忽略。
_MOCK_ALLOWED_ARGUMENTS: dict[str, frozenset[str]] = {
    SearchLog: frozenset({"service", "instance", "levels", "from_ms", "to_ms", "limit"}),
    QueryMetric: frozenset(
        {"service", "metric_names", "from_ms", "to_ms", "labels", "aggregation"}
    ),
    QueryChange: frozenset({"services", "from_ms", "to_ms", "change_type"}),
}

_SECRET_PATTERN = re.compile(r"(?:sk-[A-Za-z0-9_-]+|AKID[A-Za-z0-9]+)")


class DiagnosisToolError(RuntimeError):
    """Base class for safe, user-visible tool outcomes."""


class ToolCallRejected(DiagnosisToolError):
    """The request cannot be executed as specified; no external call is made."""


class ToolCapabilityUnavailable(DiagnosisToolError):
    """The current mode exposes no tool for this capability; report it as a gap."""


@dataclass(frozen=True, slots=True)
class ToolExecution:
    tool_name: str
    status: ToolStatus
    status_reason: str
    data: JsonValue = None


class DiagnosisToolbox(Protocol):
    """Mode-specific tool surface shared by the diagnosis graph."""

    @property
    def tool_names(self) -> frozenset[str]:
        """Names callable in this mode; the caller reports the rest as gaps."""
        ...

    async def execute(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, JsonValue],
        timeout_seconds: float,
    ) -> ToolExecution:
        """Run one already-planned call without any automatic retry."""
        ...


# ---------- 参数校验 ----------


def normalize_mock_arguments(
    *, tool_name: str, arguments: Mapping[str, JsonValue]
) -> ToolArguments:
    """Reject unknown mock arguments instead of silently ignoring filter conditions."""
    allowed = _MOCK_ALLOWED_ARGUMENTS.get(tool_name)
    if allowed is None:
        raise ToolCallRejected(f"unsupported mock tool: {tool_name}")
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ToolCallRejected(f"unsupported {tool_name} argument: {unknown[0]}")
    return {key: value for key, value in arguments.items() if value is not None}


def normalize_real_arguments(arguments: Mapping[str, JsonValue]) -> ToolArguments:
    """Real schemas belong to the MCP server; only reject an empty request."""
    if not arguments:
        raise ToolCallRejected("tool arguments must not be empty")
    return dict(arguments)


def _require_text(arguments: Mapping[str, JsonValue], key: str, *, tool_name: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolCallRejected(f"{tool_name} requires a non-empty {key}")
    return value.strip()


def _optional_text(arguments: Mapping[str, JsonValue], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolCallRejected(f"{key} must be a non-empty string when provided")
    return value.strip()


def _require_text_list(
    arguments: Mapping[str, JsonValue], key: str, *, tool_name: str
) -> list[str]:
    value = arguments.get(key)
    if not isinstance(value, list) or not value:
        raise ToolCallRejected(f"{tool_name} requires a non-empty {key} list")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ToolCallRejected(f"{tool_name} {key} must contain non-empty strings")
        items.append(item.strip())
    return items


def _optional_text_list(
    arguments: Mapping[str, JsonValue], key: str, *, tool_name: str
) -> list[str]:
    if key not in arguments:
        return []
    return _require_text_list(arguments, key, tool_name=tool_name)


def _require_ms_window(arguments: Mapping[str, JsonValue], *, tool_name: str) -> tuple[int, int]:
    start = arguments.get("from_ms")
    end = arguments.get("to_ms")
    if isinstance(start, bool) or isinstance(end, bool):
        raise ToolCallRejected(f"{tool_name} requires integer from_ms and to_ms")
    if not isinstance(start, int) or not isinstance(end, int):
        raise ToolCallRejected(f"{tool_name} requires integer from_ms and to_ms")
    if start > end:
        raise ToolCallRejected(f"{tool_name} requires from_ms <= to_ms")
    return start, end


def _optional_labels(arguments: Mapping[str, JsonValue]) -> dict[str, str]:
    value = arguments.get("labels")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ToolCallRejected("labels must be an object of string values")
    labels: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str):
            raise ToolCallRejected("labels must be an object of string values")
        labels[key] = item
    return labels


# ---------- 固定快照筛选 ----------


class MockDiagnosisToolbox:
    """Filter the single configured scenario; windows never move recorded facts."""

    def __init__(self, scenario: MockScenario) -> None:
        self._scenario = scenario

    @property
    def tool_names(self) -> frozenset[str]:
        return MOCK_TOOL_NAMES

    async def execute(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, JsonValue],
        timeout_seconds: float,
    ) -> ToolExecution:
        del timeout_seconds  # 本地筛选不发起网络请求，因此不需要超时
        normalized = normalize_mock_arguments(tool_name=tool_name, arguments=arguments)
        if tool_name == SearchLog:
            payload: JsonValue = self._search_logs(normalized)
        elif tool_name == QueryMetric:
            payload = self._query_metric(normalized)
        elif tool_name == QueryChange:
            payload = self._query_change(normalized)
        else:
            raise ToolCallRejected(f"unsupported mock tool: {tool_name}")
        return ToolExecution(
            tool_name=tool_name,
            status="succeeded",
            status_reason="scenario snapshot filtered by request arguments",
            data=payload,
        )

    def _search_logs(self, arguments: Mapping[str, JsonValue]) -> ToolArguments:
        service = _require_text(arguments, "service", tool_name=SearchLog)
        instance = _optional_text(arguments, "instance")
        levels = _optional_text_list(arguments, "levels", tool_name=SearchLog)
        start, end = _require_ms_window(arguments, tool_name=SearchLog)
        limit = arguments.get("limit", DEFAULT_LOG_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ToolCallRejected("SearchLog limit must be an integer between 1 and 100")

        records: list[JsonValue] = [
            _log_record(log)
            for log in sorted(self._scenario.logs, key=lambda item: item.timestamp)
            if log.service == service
            and (instance is None or log.instance == instance)
            and (not levels or log.level in levels)
            and start <= timestamp_ms(log.timestamp) <= end
        ]
        selected = records[:limit]
        return {
            "service": service,
            "records": selected,
            "recordCount": len(selected),
            "truncated": len(records) > len(selected),
        }

    def _query_metric(self, arguments: Mapping[str, JsonValue]) -> ToolArguments:
        service = _require_text(arguments, "service", tool_name=QueryMetric)
        names = _require_text_list(arguments, "metric_names", tool_name=QueryMetric)
        labels = _optional_labels(arguments)
        start, end = _require_ms_window(arguments, tool_name=QueryMetric)
        aggregation = _optional_text(arguments, "aggregation") or "avg"
        if aggregation not in AGGREGATIONS:
            raise ToolCallRejected(f"unsupported aggregation: {aggregation}")

        catalog = {definition.name: definition for definition in get_metrics_for_service(service)}
        if not catalog:
            raise ToolCallRejected(f"metric catalog does not cover service: {service}")
        for name in names:
            if name not in catalog:
                raise ToolCallRejected(f"metric not in whitelist: {name}")

        series: list[JsonValue] = []
        for name in names:
            points: list[JsonValue] = [
                {"timestamp": metric.timestamp, "value": metric.value}
                for metric in sorted(self._scenario.metrics, key=lambda item: item.timestamp)
                if metric.service == service
                and metric.metric_name == name
                and _labels_match(metric, labels)
                and start <= timestamp_ms(metric.timestamp) <= end
            ]
            if not points:
                continue
            definition = catalog[name]
            row: ToolArguments = {
                "metric_name": name,
                "unit": definition.unit,
                "aggregation": aggregation,
                "labels": {"service": service},
                "points": points,
                "sampleCount": len(points),
            }
            series.append(row)
        return {
            "service": service,
            "aggregation": aggregation,
            "series": series,
            "seriesCount": len(series),
        }

    def _query_change(self, arguments: Mapping[str, JsonValue]) -> ToolArguments:
        services = _require_text_list(arguments, "services", tool_name=QueryChange)
        start, end = _require_ms_window(arguments, tool_name=QueryChange)
        change_type = _optional_text(arguments, "change_type")
        if change_type is not None and change_type not in CHANGE_TYPES:
            raise ToolCallRejected(f"unsupported change_type: {change_type}")

        records: list[JsonValue] = [
            _change_record(change)
            for change in sorted(self._scenario.changes, key=lambda item: item.timestamp)
            if change.service in services
            and (change_type is None or change.change_type == change_type)
            and start <= timestamp_ms(change.timestamp) <= end
        ]
        return {"services": list(services), "records": records, "recordCount": len(records)}


def _log_record(log: ScenarioLog) -> JsonValue:
    record: ToolArguments = {
        "timestamp": log.timestamp,
        "service": log.service,
        "instance": log.instance,
        "level": log.level,
        "message": log.message,
    }
    return record


def _change_record(change: ScenarioChange) -> JsonValue:
    record: ToolArguments = {
        "timestamp": change.timestamp,
        "service": change.service,
        "instance": change.instance,
        "change_type": change.change_type,
        "summary": change.summary,
        "details": change.details,
    }
    return record


def _labels_match(metric: ScenarioMetric, labels: Mapping[str, str]) -> bool:
    observed = {"service": metric.service, "instance": metric.instance, **metric.labels}
    return all(observed.get(key) == value for key, value in labels.items())


def build_mock_diagnosis_toolbox(context: DiagnosisContext) -> MockDiagnosisToolbox:
    """Mock mode requires the scenario that was fixed during prepare_context."""
    if context.scenario is None:
        raise DiagnosisContentError("Mock diagnosis requires an explicit scenario.")
    return MockDiagnosisToolbox(context.scenario)


# ---------- 真实模式 ----------


class RealDiagnosisToolbox:
    """Only tools discovered for the authenticated owner; one attempt per call."""

    def __init__(self, *, client: LocalMcpClient, definitions: Sequence[McpToolDefinition]) -> None:
        names = [definition.name for definition in definitions]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate discovered MCP tool name.")
        self._client = client
        self._definitions = {definition.name: definition for definition in definitions}

    @property
    def tool_names(self) -> frozenset[str]:
        return frozenset(self._definitions)

    async def execute(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, JsonValue],
        timeout_seconds: float,
    ) -> ToolExecution:
        definition = self._definitions.get(tool_name)
        if definition is None:
            raise ToolCapabilityUnavailable(f"current real connections do not expose {tool_name}")
        payload = normalize_real_arguments(arguments)
        try:
            output = await self._client.call_discovered_tool(
                definition,
                payload,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:  # 外部边界：失败如实记录，绝不回退 Mock
            return ToolExecution(
                tool_name=tool_name,
                status="failed",
                status_reason=_safe_reason(exc),
            )
        return ToolExecution(
            tool_name=tool_name,
            status="succeeded",
            status_reason="tool returned records",
            data=cast(JsonValue, output),
        )


async def build_real_diagnosis_toolbox(*, client: LocalMcpClient) -> RealDiagnosisToolbox:
    """Discover once inside the owner scope; discovery itself never retries."""
    definitions = await client.discover_tools()
    return RealDiagnosisToolbox(client=client, definitions=definitions)


def _safe_reason(exc: Exception) -> str:
    message = _SECRET_PATTERN.sub("[redacted]", str(exc)).strip()
    return message[:300] or "tool invocation failed"


# ---------- 重复失败调用防护 ----------


class RepeatedFailureGuard:
    """Reject an identical call that already failed; new conditions must add value."""

    def __init__(self) -> None:
        self._failed: dict[str, str] = {}

    def check(self, *, tool_name: str, arguments: Mapping[str, JsonValue]) -> None:
        fingerprint = _fingerprint(arguments)
        if self._failed.get(tool_name) == fingerprint:
            raise ToolCallRejected(
                f"{tool_name} already failed with identical arguments; a new call needs new "
                "conditions or evidence value"
            )

    def record_failure(self, *, tool_name: str, arguments: Mapping[str, JsonValue]) -> None:
        self._failed[tool_name] = _fingerprint(arguments)


def _fingerprint(arguments: Mapping[str, JsonValue]) -> str:
    return json.dumps(dict(arguments), sort_keys=True, ensure_ascii=True, separators=(",", ":"))


# ---------- 首轮参数构建 ----------


def build_mock_search_log_arguments(
    *,
    service: str,
    alert_starts_at_ms: int,
    instance: str | None = None,
    limit: int = DEFAULT_LOG_LIMIT,
) -> ToolArguments:
    start, end = _log_time_range(alert_starts_at_ms)
    arguments: ToolArguments = {"service": service, "from_ms": start, "to_ms": end, "limit": limit}
    if instance:
        arguments["instance"] = instance
    return arguments


def build_mock_query_metric_arguments(
    *,
    service: str,
    alert_starts_at_ms: int,
    metric_names: Sequence[str] | None = None,
    labels: Mapping[str, str] | None = None,
) -> ToolArguments:
    catalog = {definition.name for definition in get_metrics_for_service(service)}
    if not catalog:
        raise ToolCapabilityUnavailable(f"metric catalog does not cover service: {service}")
    names = list(metric_names) if metric_names else sorted(catalog)
    unknown = [name for name in names if name not in catalog]
    if unknown:
        raise ToolCallRejected(f"metric not in whitelist: {unknown[0]}")
    start, end = build_metric_time_range(alert_starts_at_ms)
    arguments: ToolArguments = {
        "service": service,
        "metric_names": list(names),
        "from_ms": start,
        "to_ms": end,
    }
    if labels:
        arguments["labels"] = dict(labels)
    return arguments


def build_mock_query_change_arguments(
    *,
    alert_service: str,
    alert_starts_at_ms: int,
    services: Sequence[str] | None = None,
) -> ToolArguments:
    targets = list(services) if services else resolve_change_query_services(alert_service)
    start, end = build_change_time_range(alert_starts_at_ms)
    return {"services": list(targets), "from_ms": start, "to_ms": end}


@dataclass(frozen=True, slots=True)
class ClsSearchDefaults:
    """Existing CLS settings reused as the alert-scoped default log query."""

    region: str
    topic_id: str


def build_real_search_log_arguments(
    *,
    defaults: ClsSearchDefaults,
    service: str,
    alert_starts_at_ms: int,
    query: str | None = None,
    limit: int = DEFAULT_LOG_LIMIT,
) -> ToolArguments:
    start, end = _log_time_range(alert_starts_at_ms)
    text = (query or "").strip() or f"service:{service}"
    return {
        "Region": defaults.region,
        "TopicId": defaults.topic_id,
        "From": start,
        "To": end,
        "Query": text,
        "Limit": limit,
    }


def _log_time_range(alert_starts_at_ms: int) -> tuple[int, int]:
    return (
        alert_starts_at_ms - LOG_WINDOW_BEFORE_MINUTES * 60 * 1000,
        alert_starts_at_ms + LOG_WINDOW_AFTER_MINUTES * 60 * 1000,
    )
