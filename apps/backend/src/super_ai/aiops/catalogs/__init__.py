"""静态配置层：服务依赖图 + 指标目录。

这些配置在生产环境中应该由 SRE 根据实际的服务拓扑和监控规范手工维护，
对标企业 CMDB / Metric Governance 系统。本模块以静态字典形式提供
Mock 实现，供 Oncall Agent 的 Planner 和 Evidence Reasoning 节点使用。
"""

from super_ai.aiops.catalogs.metric_catalog import (
    MetricDefinition,
    get_metrics_for_service,
    list_all_services as list_metric_services,
)
from super_ai.aiops.catalogs.service_topology import (
    get_dependencies,
    list_all_services as list_topology_services,
)

__all__ = [
    "MetricDefinition",
    "get_metrics_for_service",
    "list_metric_services",
    "get_dependencies",
    "list_topology_services",
]
