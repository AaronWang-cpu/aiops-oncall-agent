"""指标目录：服务 → 可查询指标白名单。

对标企业 Metric Governance（Datadog Metric Metadata / Prometheus
Metric Catalog）。生产系统中由 SRE 维护白名单，防止 LLM 幻觉
出不存在的 metric_name。QueryMetric 工具限制 LLM 只能从白名单
里选 metric_name，但 LLM 可以自主决定选哪一个或哪几个。

本模块以 MetricDefinition 封装指标名称、维度（labels）、聚合语义，
便于 Planner 把白名单透传给 LLM。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class MetricDefinition:
    """单个指标的元数据。"""

    name: str
    description: str
    unit: str
    labels: tuple[str, ...] = field(default_factory=tuple)
    recommended_aggregation: str = "avg"


# 服务 → 该服务可查询的指标列表
# 指标覆盖了核心告警场景（错误率、延迟、资源利用率、吞吐），
# 用于 LLM 根据告警内容选择最相关的指标进行查询。
_METRIC_CATALOG: Mapping[str, tuple[MetricDefinition, ...]] = {
    "order-service": (
        MetricDefinition(
            name="order_request_error_rate",
            description="订单接口错误率",
            unit="ratio",
            labels=("endpoint", "status"),
            recommended_aggregation="avg",
        ),
        MetricDefinition(
            name="order_request_latency_p99",
            description="订单接口 P99 延迟",
            unit="ms",
            labels=("endpoint",),
            recommended_aggregation="p99",
        ),
        MetricDefinition(
            name="order_qps",
            description="订单服务 QPS",
            unit="rps",
            labels=("endpoint",),
            recommended_aggregation="sum",
        ),
        MetricDefinition(
            name="order_db_connection_pool_usage",
            description="订单数据库连接池使用率",
            unit="ratio",
            labels=("instance",),
            recommended_aggregation="max",
        ),
    ),
    "payment-service": (
        MetricDefinition(
            name="payment_error_rate",
            description="支付接口错误率",
            unit="ratio",
            labels=("endpoint", "status"),
            recommended_aggregation="avg",
        ),
        MetricDefinition(
            name="payment_latency_p99",
            description="支付接口 P99 延迟",
            unit="ms",
            labels=("endpoint",),
            recommended_aggregation="p99",
        ),
        MetricDefinition(
            name="payment_gateway_timeout_count",
            description="第三方支付网关超时次数",
            unit="count",
            labels=("gateway",),
            recommended_aggregation="sum",
        ),
        MetricDefinition(
            name="payment_fraud_check_latency_p99",
            description="风控检查 P99 延迟",
            unit="ms",
            labels=(),
            recommended_aggregation="p99",
        ),
    ),
    "auth-service": (
        MetricDefinition(
            name="auth_error_rate",
            description="认证接口错误率",
            unit="ratio",
            labels=("endpoint", "status"),
        ),
        MetricDefinition(
            name="auth_jwk_refresh_duration",
            description="JWK 刷新耗时",
            unit="ms",
            labels=(),
            recommended_aggregation="p99",
        ),
        MetricDefinition(
            name="auth_token_verify_latency_p99",
            description="Token 校验 P99 延迟",
            unit="ms",
            labels=("endpoint",),
            recommended_aggregation="p99",
        ),
    ),
    "order-event-consumer": (
        MetricDefinition(
            name="kafka_consumer_lag",
            description="Kafka 消费积压条数",
            unit="count",
            labels=("topic", "partition"),
            recommended_aggregation="max",
        ),
        MetricDefinition(
            name="kafka_consumer_rate",
            description="Kafka 消费速率",
            unit="rps",
            labels=("topic",),
            recommended_aggregation="sum",
        ),
    ),
    "product-search-service": (
        MetricDefinition(
            name="search_latency_p99",
            description="搜索接口 P99 延迟",
            unit="ms",
            labels=("endpoint",),
            recommended_aggregation="p99",
        ),
        MetricDefinition(
            name="search_timeout_rate",
            description="搜索超时率",
            unit="ratio",
            labels=("endpoint",),
            recommended_aggregation="avg",
        ),
        MetricDefinition(
            name="elasticsearch_query_latency_p99",
            description="Elasticsearch 查询 P99 延迟",
            unit="ms",
            labels=("cluster",),
            recommended_aggregation="p99",
        ),
    ),
    "fulfillment-service": (
        MetricDefinition(
            name="fulfillment_error_rate",
            description="履约接口错误率",
            unit="ratio",
            labels=("endpoint", "status"),
        ),
        MetricDefinition(
            name="carrier_api_timeout_rate",
            description="承运商 API 超时率",
            unit="ratio",
            labels=("carrier",),
        ),
    ),
    "cart-service": (
        MetricDefinition(
            name="cart_latency_p99",
            description="购物车接口 P99 延迟",
            unit="ms",
            labels=("endpoint",),
            recommended_aggregation="p99",
        ),
        MetricDefinition(
            name="cart_redis_latency_p99",
            description="购物车 Redis 访问 P99 延迟",
            unit="ms",
            labels=(),
            recommended_aggregation="p99",
        ),
    ),
    "inventory-service": (
        MetricDefinition(
            name="inventory_lock_wait_duration_p99",
            description="库存锁等待 P99 时长",
            unit="ms",
            labels=("sku_group",),
            recommended_aggregation="p99",
        ),
        MetricDefinition(
            name="inventory_error_rate",
            description="库存接口错误率",
            unit="ratio",
            labels=("endpoint",),
        ),
    ),
    "promotion-service": (
        MetricDefinition(
            name="promotion_cpu_usage",
            description="营销服务 CPU 使用率",
            unit="ratio",
            labels=("instance",),
            recommended_aggregation="max",
        ),
        MetricDefinition(
            name="promotion_latency_p99",
            description="营销接口 P99 延迟",
            unit="ms",
            labels=("endpoint",),
            recommended_aggregation="p99",
        ),
    ),
    "api-gateway": (
        MetricDefinition(
            name="gateway_upstream_error_rate",
            description="网关上游错误率",
            unit="ratio",
            labels=("upstream_service", "status"),
        ),
        MetricDefinition(
            name="gateway_request_latency_p99",
            description="网关请求 P99 延迟",
            unit="ms",
            labels=("route",),
            recommended_aggregation="p99",
        ),
    ),
}


def get_metrics_for_service(service: str) -> tuple[MetricDefinition, ...]:
    """返回指定服务的可查询指标列表。未配置时返回空元组。"""
    return _METRIC_CATALOG.get(service, ())


def list_all_services() -> tuple[str, ...]:
    """列出所有配置了指标目录的服务名。"""
    return tuple(_METRIC_CATALOG.keys())
