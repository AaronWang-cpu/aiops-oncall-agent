"""P3：诊断工具适配器（固定 Mock 快照筛选 + 真实入口隔离）。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import JsonValue

from super_ai.aiops.diagnosis_config import DiagnosisConfig
from super_ai.aiops.diagnosis_context import prepare_diagnosis_context
from super_ai.aiops.diagnosis_tools import (
    DEFAULT_LOG_LIMIT,
    ClsSearchDefaults,
    MockDiagnosisToolbox,
    RealDiagnosisToolbox,
    RepeatedFailureGuard,
    ToolCallRejected,
    ToolCapabilityUnavailable,
    build_mock_diagnosis_toolbox,
    build_mock_query_change_arguments,
    build_mock_query_metric_arguments,
    build_mock_search_log_arguments,
    build_real_search_log_arguments,
    normalize_mock_arguments,
)
from super_ai.mcp_client import (
    LocalMcpClient,
    McpClientError,
    McpServerConnection,
    McpToolDefinition,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = BACKEND_ROOT / "src" / "super_ai" / "aiops" / "mock_scenarios"
ALERT_START_MS = 1_773_825_120_000  # 2026-03-18T09:12:00Z
PAYMENT_ALERT_START_MS = 1_773_930_900_000  # 2026-03-19T14:35:00Z


def _mock_toolbox(scenario_name: str) -> MockDiagnosisToolbox:
    context = prepare_diagnosis_context(
        DiagnosisConfig(
            mode="mock",
            mockScenarioPath=str(SCENARIO_DIR / scenario_name),
        )
    )
    return build_mock_diagnosis_toolbox(context)


# ---------- 固定 Mock 筛选 ----------


@pytest.mark.asyncio
async def test_mock_search_logs_filter_by_service_level_and_window() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")
    arguments = build_mock_search_log_arguments(
        service="order-service",
        alert_starts_at_ms=ALERT_START_MS,
    )
    arguments["levels"] = ["ERROR"]

    execution = await toolbox.execute(
        tool_name="SearchLog", arguments=arguments, timeout_seconds=30
    )

    assert execution.status == "succeeded"
    data = _as_dict(execution.data)
    assert data["recordCount"] == 2
    assert [record["level"] for record in _records(data["records"])] == ["ERROR", "ERROR"]


@pytest.mark.asyncio
async def test_mock_search_logs_exclude_records_outside_window() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")
    execution = await toolbox.execute(
        tool_name="SearchLog",
        arguments={
            "service": "order-service",
            "from_ms": ALERT_START_MS,
            "to_ms": ALERT_START_MS + 60_000,
        },
        timeout_seconds=30,
    )

    records = _records(_as_dict(execution.data)["records"])
    assert all(str(record["timestamp"]) >= "2026-03-18T09:12:00Z" for record in records)
    assert all(str(record["timestamp"]) <= "2026-03-18T09:13:00Z" for record in records)


@pytest.mark.asyncio
async def test_mock_search_logs_honor_instance_and_limit() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")
    execution = await toolbox.execute(
        tool_name="SearchLog",
        arguments={
            "service": "order-service",
            "instance": "order-service-7c9f4d8b5-hxz2q",
            "from_ms": ALERT_START_MS - 30 * 60_000,
            "to_ms": ALERT_START_MS + 30 * 60_000,
            "limit": 1,
        },
        timeout_seconds=30,
    )

    data = _as_dict(execution.data)
    assert data["recordCount"] == 1
    assert data["truncated"] is True
    records = _records(data["records"])
    assert records[0]["instance"] == "order-service-7c9f4d8b5-hxz2q"


@pytest.mark.asyncio
async def test_mock_metric_series_only_returns_snapshot_points() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")
    arguments = build_mock_query_metric_arguments(
        service="order-service",
        alert_starts_at_ms=ALERT_START_MS,
        metric_names=["order_db_connection_pool_usage"],
        labels={"instance": "order-service-7c9f4d8b5-hxz2q"},
    )

    execution = await toolbox.execute(
        tool_name="QueryMetric", arguments=arguments, timeout_seconds=30
    )

    series = _records(_as_dict(execution.data)["series"])
    assert len(series) == 1
    points = _records(series[0]["points"])
    assert points
    assert max(float(str(point["value"])) for point in points) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_mock_metric_rejects_name_outside_catalog() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")

    with pytest.raises(ToolCallRejected, match="whitelist"):
        await toolbox.execute(
            tool_name="QueryMetric",
            arguments={
                "service": "order-service",
                "metric_names": ["not_in_catalog"],
                "from_ms": ALERT_START_MS,
                "to_ms": ALERT_START_MS + 60_000,
            },
            timeout_seconds=30,
        )


@pytest.mark.asyncio
async def test_mock_metric_rejects_service_without_catalog() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")

    with pytest.raises(ToolCallRejected, match="metric catalog"):
        await toolbox.execute(
            tool_name="QueryMetric",
            arguments={
                "service": "unknown-service",
                "metric_names": ["any"],
                "from_ms": ALERT_START_MS,
                "to_ms": ALERT_START_MS + 60_000,
            },
            timeout_seconds=30,
        )


@pytest.mark.asyncio
async def test_mock_change_query_keeps_distractors_and_filters_target_service() -> None:
    toolbox = _mock_toolbox("payment-gateway-timeout-with-distractors.json")
    arguments = build_mock_query_change_arguments(
        alert_service="payment-service",
        alert_starts_at_ms=PAYMENT_ALERT_START_MS,
        services=["payment-service", "fraud-detection-service"],
    )

    execution = await toolbox.execute(
        tool_name="QueryChange", arguments=arguments, timeout_seconds=30
    )

    records = _records(_as_dict(execution.data)["records"])
    # 事实全部返回，不替用户筛选"哪个才是根因"；窗口外的 cart-service 不出现。
    assert {record["service"] for record in records} == {
        "payment-service",
        "fraud-detection-service",
    }


@pytest.mark.asyncio
async def test_mock_change_query_supports_change_type_filter() -> None:
    toolbox = _mock_toolbox("payment-gateway-timeout-with-distractors.json")
    execution = await toolbox.execute(
        tool_name="QueryChange",
        arguments={
            "services": ["payment-service"],
            "from_ms": PAYMENT_ALERT_START_MS - 30 * 60_000,
            "to_ms": PAYMENT_ALERT_START_MS + 30 * 60_000,
            "change_type": "config_change",
        },
        timeout_seconds=30,
    )

    records = _records(_as_dict(execution.data)["records"])
    assert len(records) == 1
    assert records[0]["change_type"] == "config_change"


@pytest.mark.asyncio
async def test_mock_change_query_without_change_type_returns_all_types() -> None:
    toolbox = _mock_toolbox("payment-gateway-timeout-with-distractors.json")
    execution = await toolbox.execute(
        tool_name="QueryChange",
        arguments={
            "services": ["fraud-detection-service", "payment-service", "cart-service"],
            "from_ms": PAYMENT_ALERT_START_MS - 120 * 60_000,
            "to_ms": PAYMENT_ALERT_START_MS + 10 * 60_000,
        },
        timeout_seconds=30,
    )

    records = _records(_as_dict(execution.data)["records"])
    assert len(records) == 3


@pytest.mark.asyncio
async def test_mock_toolbox_tool_names_are_fixed_contract() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")

    assert toolbox.tool_names == frozenset({"SearchLog", "QueryMetric", "QueryChange"})


@pytest.mark.asyncio
async def test_mock_repeated_identical_query_returns_same_facts() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")
    arguments: dict[str, JsonValue] = {
        "service": "order-service",
        "from_ms": ALERT_START_MS - 10 * 60_000,
        "to_ms": ALERT_START_MS + 5 * 60_000,
    }

    first = await toolbox.execute(tool_name="SearchLog", arguments=arguments, timeout_seconds=30)
    second = await toolbox.execute(tool_name="SearchLog", arguments=arguments, timeout_seconds=30)

    assert first.data == second.data


# ---------- 参数校验 ----------


def test_normalize_rejects_unknown_mock_argument() -> None:
    with pytest.raises(ToolCallRejected, match="unsupported SearchLog argument"):
        normalize_mock_arguments(
            tool_name="SearchLog",
            arguments={"service": "order-service", "unknown_filter": "x"},
        )


def test_normalize_rejects_unsupported_mock_tool() -> None:
    with pytest.raises(ToolCallRejected, match="unsupported mock tool"):
        normalize_mock_arguments(tool_name="ExplainEverything", arguments={})


@pytest.mark.asyncio
async def test_mock_rejects_non_integer_window() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")

    with pytest.raises(ToolCallRejected, match="integer from_ms and to_ms"):
        await toolbox.execute(
            tool_name="SearchLog",
            arguments={"service": "order-service", "from_ms": "1", "to_ms": "2"},
            timeout_seconds=30,
        )


@pytest.mark.asyncio
async def test_mock_rejects_reversed_window() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")

    with pytest.raises(ToolCallRejected, match="from_ms <= to_ms"):
        await toolbox.execute(
            tool_name="SearchLog",
            arguments={"service": "order-service", "from_ms": 2, "to_ms": 1},
            timeout_seconds=30,
        )


@pytest.mark.asyncio
async def test_mock_rejects_missing_service() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")

    with pytest.raises(ToolCallRejected, match="non-empty service"):
        await toolbox.execute(
            tool_name="SearchLog",
            arguments={"from_ms": 1, "to_ms": 2},
            timeout_seconds=30,
        )


@pytest.mark.asyncio
async def test_mock_rejects_out_of_range_limit() -> None:
    toolbox = _mock_toolbox("order-pool-exhaustion.json")

    with pytest.raises(ToolCallRejected, match="limit"):
        await toolbox.execute(
            tool_name="SearchLog",
            arguments={"service": "order-service", "from_ms": 1, "to_ms": 2, "limit": 500},
            timeout_seconds=30,
        )


def test_build_mock_metric_arguments_rejects_unknown_metric() -> None:
    with pytest.raises(ToolCallRejected, match="whitelist"):
        build_mock_query_metric_arguments(
            service="order-service",
            alert_starts_at_ms=ALERT_START_MS,
            metric_names=["unknown_metric"],
        )


def test_build_mock_search_log_arguments_omits_absent_instance() -> None:
    arguments = build_mock_search_log_arguments(
        service="cart-service",
        alert_starts_at_ms=ALERT_START_MS,
    )

    assert "instance" not in arguments
    assert arguments["limit"] == DEFAULT_LOG_LIMIT


def test_build_mock_search_log_arguments_uses_alert_scoped_window() -> None:
    arguments = build_mock_search_log_arguments(
        service="order-service",
        alert_starts_at_ms=ALERT_START_MS,
    )

    assert arguments["from_ms"] == ALERT_START_MS - 10 * 60_000
    assert arguments["to_ms"] == ALERT_START_MS + 5 * 60_000


def test_build_mock_metric_arguments_default_to_catalog_whitelist() -> None:
    arguments = build_mock_query_metric_arguments(
        service="order-service",
        alert_starts_at_ms=ALERT_START_MS,
    )

    assert arguments["metric_names"] == [
        "order_db_connection_pool_usage",
        "order_qps",
        "order_request_error_rate",
        "order_request_latency_p99",
    ]
    assert arguments["from_ms"] == ALERT_START_MS - 15 * 60_000
    assert arguments["to_ms"] == ALERT_START_MS + 5 * 60_000
    assert "labels" not in arguments


def test_build_mock_metric_arguments_keep_explicit_dimension() -> None:
    arguments = build_mock_query_metric_arguments(
        service="order-service",
        alert_starts_at_ms=ALERT_START_MS,
        labels={"instance": "order-service-7c9f4d8b5-hxz2q"},
    )

    assert arguments["labels"] == {"instance": "order-service-7c9f4d8b5-hxz2q"}


def test_build_mock_change_arguments_default_to_alert_service_and_first_level_deps() -> None:
    arguments = build_mock_query_change_arguments(
        alert_service="order-service",
        alert_starts_at_ms=ALERT_START_MS,
    )

    assert arguments["services"] == [
        "order-service",
        "mysql-order",
        "payment-service",
        "inventory-service",
    ]
    assert arguments["from_ms"] == ALERT_START_MS - 120 * 60_000
    assert arguments["to_ms"] == ALERT_START_MS + 10 * 60_000


def test_build_mock_change_arguments_allow_explicit_cross_service_expansion() -> None:
    arguments = build_mock_query_change_arguments(
        alert_service="order-service",
        alert_starts_at_ms=ALERT_START_MS,
        services=["mysql-order", "mysql-order-instance"],
    )

    assert arguments["services"] == ["mysql-order", "mysql-order-instance"]


# ---------- 真实入口隔离（传输替身，不发真实请求） ----------


@dataclass
class _FakeResult:
    isError: bool = False
    content: tuple[object, ...] = ()


def _connection(index: int) -> McpServerConnection:
    return McpServerConnection(
        name="cls" if index == 0 else f"extra-{index}",
        url="http://mcp.test/sse",
        timeout_seconds=30,
        retries=1,
    )


class _TransportDouble(LocalMcpClient):
    """只替换传输层，用于统计真实入口实际发起的请求次数。"""

    def __init__(self, *, fail: bool = False, connections: int = 1) -> None:
        # 存储连接本身带 retries=1，诊断路径必须覆盖为 0。
        super().__init__(connections=[_connection(index) for index in range(connections)])
        self.fail = fail
        self.calls: list[str] = []

    async def _run_connection(
        self,
        connection: McpServerConnection,
        operation: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        del operation
        self.calls.append(connection.name)
        if self.fail:
            raise McpClientError("MCP server unavailable")
        return _FakeResult()


@pytest.mark.asyncio
async def test_real_toolbox_uses_discovered_tool_without_rediscovery() -> None:
    double = _TransportDouble()
    toolbox = RealDiagnosisToolbox(
        client=double,
        definitions=[
            McpToolDefinition("SearchLog", "search", {"type": "object"}, "cls"),
        ],
    )

    execution = await toolbox.execute(
        tool_name="SearchLog", arguments={"Query": "*"}, timeout_seconds=5
    )

    assert execution.status == "succeeded"
    assert double.calls == ["cls"]


@pytest.mark.asyncio
async def test_real_toolbox_does_not_retry_failed_call() -> None:
    double = _TransportDouble(fail=True)
    toolbox = RealDiagnosisToolbox(
        client=double,
        definitions=[McpToolDefinition("SearchLog", "search", {}, "cls")],
    )

    execution = await toolbox.execute(
        tool_name="SearchLog", arguments={"Query": "*"}, timeout_seconds=5
    )

    assert execution.status == "failed"
    assert len(double.calls) == 1


@pytest.mark.asyncio
async def test_real_toolbox_reports_unknown_capability_as_gap() -> None:
    double = _TransportDouble()
    toolbox = RealDiagnosisToolbox(
        client=double,
        definitions=[McpToolDefinition("SearchLog", "search", {}, "cls")],
    )

    assert toolbox.tool_names == frozenset({"SearchLog"})
    with pytest.raises(ToolCapabilityUnavailable, match="QueryChange"):
        await toolbox.execute(tool_name="QueryChange", arguments={"x": 1}, timeout_seconds=5)
    assert double.calls == []


@pytest.mark.asyncio
async def test_real_toolbox_never_falls_back_to_mock_on_failure() -> None:
    double = _TransportDouble(fail=True)
    toolbox = RealDiagnosisToolbox(
        client=double,
        definitions=[McpToolDefinition("SearchLog", "search", {}, "cls")],
    )

    execution = await toolbox.execute(
        tool_name="SearchLog", arguments={"Query": "*"}, timeout_seconds=5
    )

    assert execution.data is None
    assert execution.status == "failed"


def test_real_toolbox_rejects_duplicate_tool_names() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        RealDiagnosisToolbox(
            client=_TransportDouble(),
            definitions=[
                McpToolDefinition("SearchLog", "search", {}, "cls"),
                McpToolDefinition("SearchLog", "other", {}, "extra-1"),
            ],
        )


def test_diagnostic_copy_disables_stored_retries() -> None:
    double = _TransportDouble(connections=2)

    diagnostic = double.diagnostic_copy(timeout_seconds=10)

    assert diagnostic is not double
    stored = _stored_connections(double)
    copied = _stored_connections(diagnostic)
    assert stored[0].retries == 1
    assert copied[0].retries == 0
    assert copied[0].timeout_seconds <= 10
    assert copied[0].url == stored[0].url


def test_diagnostic_copy_requires_positive_timeout() -> None:
    with pytest.raises(ValueError, match="positive"):
        _TransportDouble().diagnostic_copy(timeout_seconds=0)


def test_real_search_log_arguments_scope_missing_query_to_service() -> None:
    arguments = build_real_search_log_arguments(
        defaults=ClsSearchDefaults(region="ap-guangzhou", topic_id="topic-1"),
        service="order-service",
        alert_starts_at_ms=ALERT_START_MS,
    )

    assert arguments["Query"] == "service:order-service"
    assert arguments["Region"] == "ap-guangzhou"
    assert arguments["TopicId"] == "topic-1"


# ---------- 参数差异与重复失败约束 ----------


def test_repeated_failure_guard_blocks_identical_call() -> None:
    guard = RepeatedFailureGuard()
    arguments: Mapping[str, object] = {"service": "order-service"}
    guard.check(tool_name="SearchLog", arguments=arguments)
    guard.record_failure(tool_name="SearchLog", arguments=arguments)

    with pytest.raises(ToolCallRejected, match="identical arguments"):
        guard.check(tool_name="SearchLog", arguments=arguments)


def test_repeated_failure_guard_allows_new_conditions() -> None:
    guard = RepeatedFailureGuard()
    guard.record_failure(tool_name="SearchLog", arguments={"service": "order-service"})

    guard.check(tool_name="SearchLog", arguments={"service": "cart-service"})
    guard.check(tool_name="QueryChange", arguments={"service": "order-service"})


def _stored_connections(client: LocalMcpClient) -> list[McpServerConnection]:
    return cast(list[McpServerConnection], cast(Any, client)._connections)


def _as_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    mapping = cast(dict[object, object], value)
    return {str(key): item for key, item in mapping.items()}


def _records(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [_as_dict(item) for item in cast(list[object], value)]
