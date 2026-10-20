"""基础单元测试：验证 catalogs + evidence_tools（QueryMetric / QueryChange Mock）。

这些测试独立于 LangGraph 图编排，确保数据层本身可用。
"""

from __future__ import annotations

from super_ai.aiops.catalogs import (
    get_dependencies,
    get_metrics_for_service,
    list_metric_services,
    list_topology_services,
)
from super_ai.aiops.evidence_tools import (
    build_change_time_range,
    build_metric_time_range,
    query_change,
    query_metric,
    resolve_change_query_services,
)


# ---------- Catalogs ----------


def test_service_topology_covers_eval_root_cause_services() -> None:
    """评测集中出现的告警服务都应该在拓扑中登记依赖，且其根因服务被作为一级依赖。"""
    # order-service 的根因在 mysql-order（d3-order-payment-mysql）
    assert "mysql-order" in get_dependencies("order-service")
    # payment-service 的根因在 fraud-detection-service（d3-payment-upstream-fraud）
    assert "fraud-detection-service" in get_dependencies("payment-service")
    # fulfillment-service 的根因在 internal-dns（d3-fulfillment-carrier-dns）
    assert "internal-dns" in get_dependencies("fulfillment-service")
    # auth-service 的根因在 identity-provider（d3-auth-upstream-idp）
    assert "identity-provider" in get_dependencies("auth-service")
    # api-gateway 的根因在 inventory-service（d3-gateway-inventory）
    assert "inventory-service" in get_dependencies("api-gateway")


def test_metric_catalog_has_payment_service_core_metrics() -> None:
    metrics = get_metrics_for_service("payment-service")
    names = {m.name for m in metrics}
    assert "payment_error_rate" in names
    assert "payment_latency_p99" in names
    # 支付类场景常用的指标必须齐全
    assert len(metrics) >= 3


def test_catalogs_unconfigured_service_returns_empty() -> None:
    assert get_dependencies("non-existent-service") == ()
    assert get_metrics_for_service("non-existent-service") == ()


def test_catalogs_can_list_all_services() -> None:
    assert len(list_topology_services()) > 0
    assert len(list_metric_services()) > 0


# ---------- QueryMetric ----------


def test_query_metric_returns_series_for_whitelisted_metrics() -> None:
    from_ms = 1_000_000_000_000
    to_ms = from_ms + 15 * 60 * 1000
    result = query_metric(
        service="payment-service",
        metric_names=["payment_error_rate", "payment_latency_p99"],
        time_range_ms=(from_ms, to_ms),
    )
    assert len(result) == 2
    for series in result:
        assert series["status"] == "ok"
        assert series["labels"]["service"] == "payment-service"
        assert len(series["points"]) > 0


def test_query_metric_skips_metrics_not_in_whitelist() -> None:
    result = query_metric(
        service="payment-service",
        metric_names=["payment_error_rate", "non_existent_metric"],
        time_range_ms=(1_000_000_000_000, 1_000_000_900_000),
    )
    assert result[0]["status"] == "ok"
    assert result[1]["status"] == "skipped"


def test_query_metric_produces_anomaly_in_middle_of_series() -> None:
    """序列中段应该有一个明显的异常峰值（模拟故障发生）。"""
    from_ms = 1_000_000_000_000
    to_ms = from_ms + 15 * 60 * 1000
    result = query_metric(
        service="payment-service",
        metric_names=["payment_error_rate"],
        time_range_ms=(from_ms, to_ms),
    )
    values = [p["value"] for p in result[0]["points"]]
    assert max(values) > min(values) * 2


# ---------- QueryChange ----------


def test_query_change_returns_root_cause_change_for_payment_fraud_scenario() -> None:
    """评测集 d3-payment-upstream-fraud 的根因是 fraud-detection-service 的发布。
    用 payment-service + 其一级依赖查询，应能捞到这条变更。
    """
    alert_starts_at_ms = 1_000_000_000_000
    time_range = build_change_time_range(alert_starts_at_ms)
    services = resolve_change_query_services("payment-service")
    assert "fraud-detection-service" in services

    events = query_change(
        services=services,
        time_range_ms=time_range,
        alert_starts_at_ms=alert_starts_at_ms,
    )
    service_hits = {e["service"] for e in events}
    assert "fraud-detection-service" in service_hits


def test_query_change_filters_by_time_window() -> None:
    """时间窗口外的变更不应被返回。"""
    alert_starts_at_ms = 1_000_000_000_000
    # 极窄窗口：告警前后各 5 分钟
    narrow_range = (
        alert_starts_at_ms - 5 * 60 * 1000,
        alert_starts_at_ms + 5 * 60 * 1000,
    )
    events = query_change(
        services=["payment-service"],
        time_range_ms=narrow_range,
        alert_starts_at_ms=alert_starts_at_ms,
    )
    # payment-service 的两条变更分别在 -25min 和 -90min，都在窄窗口外
    assert all(e["service"] != "payment-service" for e in events)


def test_query_change_filters_by_change_type() -> None:
    alert_starts_at_ms = 1_000_000_000_000
    time_range = build_change_time_range(alert_starts_at_ms)
    deployment_only = query_change(
        services=["payment-service"],
        time_range_ms=time_range,
        alert_starts_at_ms=alert_starts_at_ms,
        change_type="deployment",
    )
    assert all(e["change_type"] == "deployment" for e in deployment_only)


# ---------- time range helpers ----------


def test_metric_time_range_wider_than_log_default() -> None:
    """指标窗口默认比日志窗口（10min）更宽。"""
    alert_starts_at_ms = 1_000_000_000_000
    from_ms, to_ms = build_metric_time_range(alert_starts_at_ms)
    assert to_ms - from_ms >= 10 * 60 * 1000


def test_change_time_range_wider_than_metric() -> None:
    """变更窗口默认比指标窗口更宽（故障前变更可能较早发生）。"""
    alert_starts_at_ms = 1_000_000_000_000
    metric_from, metric_to = build_metric_time_range(alert_starts_at_ms)
    change_from, change_to = build_change_time_range(alert_starts_at_ms)
    assert (change_to - change_from) > (metric_to - metric_from)
