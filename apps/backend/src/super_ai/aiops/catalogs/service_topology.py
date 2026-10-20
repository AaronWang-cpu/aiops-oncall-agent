"""服务拓扑：服务 → 一级依赖服务。

对标企业 CMDB / 服务注册中心（Service Mesh 的拓扑感知）。
生产系统中由 SRE 根据实际的服务依赖关系维护，Oncall Agent 的
变更查询工具（QueryChange）基于这份图进行跨服务查询。

本模块的数据覆盖了 eval_fixtures 中出现的所有告警服务与根因服务，
确保评测时 Agent 能从告警服务追溯到评测集中标注的上游根因服务。
"""

from __future__ import annotations

from typing import Mapping


# 服务 → 一级依赖服务列表
# 覆盖评测集中的全部跨服务 case 的上游服务。
_SERVICE_DEPENDENCIES: Mapping[str, tuple[str, ...]] = {
    "order-service": (
        "mysql-order",
        "payment-service",
        "inventory-service",
    ),
    "payment-service": (
        "mysql-payment",
        "redis-session",
        "fraud-detection-service",
        "external-payment-gateway",
    ),
    "auth-service": (
        "identity-provider",
        "redis-session",
    ),
    "order-event-consumer": (
        "kafka-cluster",
        "order-service",
    ),
    "product-search-service": (
        "elasticsearch-cluster",
    ),
    "fulfillment-service": (
        "internal-dns",
        "carrier-api-gateway",
        "mysql-order",
    ),
    "cart-service": (
        "redis-session",
        "mysql-order",
    ),
    "inventory-service": (
        "mysql-order",
    ),
    "promotion-service": (
        "redis-session",
    ),
    "api-gateway": (
        "order-service",
        "payment-service",
        "cart-service",
        "inventory-service",
        "auth-service",
    ),
}


def get_dependencies(service: str) -> tuple[str, ...]:
    """返回指定服务的一级依赖服务列表。

    未配置依赖的服务返回空元组，调用方应当容忍该情况。
    """
    return _SERVICE_DEPENDENCIES.get(service, ())


def list_all_services() -> tuple[str, ...]:
    """列出所有已配置依赖关系的服务名。"""
    return tuple(_SERVICE_DEPENDENCIES.keys())
