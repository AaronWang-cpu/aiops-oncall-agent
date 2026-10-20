"""QueryMetric / QueryChange 的 Mock 工具实现。

这两个工具在生产环境中应该对接：
  - QueryMetric: Prometheus / VictoriaMetrics / Datadog Metrics API
  - QueryChange: Spinnaker / ArgoCD / 配置中心 / PagerDuty Change Events

本模块提供 Mock 实现，输入参数、输出结构与真实 API 保持一致，
便于后续替换为真实实现。数据生成基于：
  - 告警服务 + 时间窗口 → 确定性生成相关的指标序列和变更事件
  - 服务依赖图（Service Topology）→ 支持跨服务变更查询
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import md5
from typing import Any, Sequence

from super_ai.aiops.catalogs import get_dependencies, get_metrics_for_service


# ---------- QueryMetric ----------


@dataclass(frozen=True)
class MetricPoint:
    timestamp: str  # ISO 8601
    value: float


@dataclass(frozen=True)
class MetricSeries:
    metric_name: str
    labels: dict[str, str]
    unit: str
    aggregation: str
    points: list[MetricPoint] = field(default_factory=list)
    anomaly_summary: str = ""


def query_metric(
    *,
    service: str,
    metric_names: Sequence[str],
    time_range_ms: tuple[int, int],
    aggregation: str = "avg",
    labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Mock 指标查询，返回每个 metric_name 对应的一条时序。

    参数
    ----
    service: 查询目标服务，用于校验白名单
    metric_names: LLM 从 Metric Catalog 中选中的指标名
    time_range_ms: (from_ms, to_ms) 查询时间窗口（毫秒）
    aggregation: 聚合方式（avg/sum/max/p99）
    labels: 可选的维度过滤

    返回
    ----
    每个 metric_name 对应一个 MetricSeries（dict 形式）；
    若 metric_name 不在白名单内，会跳过并记录在 skipped 字段。
    """
    allowed = {m.name: m for m in get_metrics_for_service(service)}
    selected_labels = labels or {}
    series_results: list[dict[str, Any]] = []
    from_ms, to_ms = time_range_ms

    for name in metric_names:
        if name not in allowed:
            series_results.append(
                {
                    "metric_name": name,
                    "labels": selected_labels,
                    "status": "skipped",
                    "reason": "metric not in whitelist for service",
                }
            )
            continue
        definition = allowed[name]
        points = _generate_metric_points(
            service=service,
            metric_name=name,
            from_ms=from_ms,
            to_ms=to_ms,
        )
        series = MetricSeries(
            metric_name=name,
            labels={"service": service, **selected_labels},
            unit=definition.unit,
            aggregation=aggregation,
            points=points,
            anomaly_summary=_summarize_anomaly(service, name, points),
        )
        series_results.append(_series_to_dict(series) | {"status": "ok"})

    return series_results


def _series_to_dict(series: MetricSeries) -> dict[str, Any]:
    data = asdict(series)
    data["points"] = [asdict(point) for point in series.points]
    return data


def _generate_metric_points(
    *,
    service: str,
    metric_name: str,
    from_ms: int,
    to_ms: int,
    step_seconds: int = 60,
) -> list[MetricPoint]:
    """基于 service + metric_name 的哈希，确定性地生成指标序列。

    序列特征：从 from_ms 到 to_ms，每 step_seconds 一个采样点。
    中段附近出现一个异常峰值（模拟故障发生），其余时段为稳定基线。
    """
    span_seconds = max((to_ms - from_ms) // 1000, step_seconds)
    sample_count = max(span_seconds // step_seconds, 1)
    baseline, peak = _baseline_and_peak(service, metric_name)
    anomaly_index = sample_count // 2

    points: list[MetricPoint] = []
    for i in range(sample_count):
        ts_ms = from_ms + i * step_seconds * 1000
        iso = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        if abs(i - anomaly_index) <= 1:
            value = peak
        else:
            value = baseline + (i % 3) * baseline * 0.02  # 轻微波动
        points.append(MetricPoint(timestamp=iso, value=round(value, 4)))
    return points


def _baseline_and_peak(service: str, metric_name: str) -> tuple[float, float]:
    """根据 service + metric_name 产生稳定的 baseline 和异常 peak 值。"""
    seed = int(md5(f"{service}::{metric_name}".encode()).hexdigest(), 16)
    if "error_rate" in metric_name or "timeout_rate" in metric_name:
        baseline = (seed % 10) / 1000 + 0.001  # 0.1% ~ 1%
        peak = baseline * (20 + (seed % 15))  # 异常时 ~20x
        return baseline, peak
    if "latency" in metric_name or "duration" in metric_name:
        baseline = 50 + (seed % 150)  # 50-200 ms
        peak = baseline * (10 + (seed % 10))
        return baseline, peak
    if "lag" in metric_name:
        baseline = (seed % 500) + 100
        peak = baseline * (30 + (seed % 20))
        return baseline, peak
    if "cpu" in metric_name or "pool_usage" in metric_name:
        baseline = ((seed % 40) + 20) / 100  # 20% - 60%
        peak = min(baseline + 0.35, 0.98)
        return baseline, peak
    if "qps" in metric_name or "rate" in metric_name:
        baseline = (seed % 500) + 100
        peak = baseline * (3 + (seed % 3))
        return baseline, peak
    if "count" in metric_name:
        baseline = (seed % 5)
        peak = baseline + (seed % 50) + 20
        return baseline, peak
    baseline = (seed % 100) + 10
    peak = baseline * 5
    return baseline, peak


def _summarize_anomaly(service: str, metric_name: str, points: list[MetricPoint]) -> str:
    if not points:
        return ""
    values = [p.value for p in points]
    max_v = max(values)
    min_v = min(values)
    median_v = sorted(values)[len(values) // 2]
    if max_v > median_v * 3:
        return (
            f"检测到异常跳变：{service}.{metric_name} 最大值 {max_v} 相对中位数 {median_v} 的"
            f" {round(max_v / max(median_v, 1e-6), 2)}x，异常持续约 2 个采样点。"
        )
    return f"{service}.{metric_name} 稳定在 {min_v}~{max_v} 区间，无显著异常。"


# ---------- QueryChange ----------


@dataclass(frozen=True)
class ChangeEvent:
    event_id: str
    timestamp: str  # ISO 8601
    service: str
    change_type: str  # deployment / config_change / traffic_switch / infra_change
    operator: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


# 预置变更事件：按服务组织，覆盖评测集中的典型根因变更。
# 每条变更带有相对告警 startsAt 的时间偏移（分钟），用于按时间窗口筛选。
# 偏移为负表示告警前，正表示告警后。
_PREBUILT_CHANGES: dict[str, list[dict[str, Any]]] = {
    "payment-service": [
        {
            "offset_minutes": -25,
            "change_type": "deployment",
            "operator": "ci-bot",
            "summary": "payment-service v2.3.1 发布：调整支付网关超时阈值从 5s 到 3s",
            "details": {"version": "v2.3.1", "commit": "a1b2c3d", "risk": "medium"},
        },
        {
            "offset_minutes": -90,
            "change_type": "config_change",
            "operator": "alice",
            "summary": "payment-service 日志采样率从 10% 调整到 50%（和故障无关）",
            "details": {"config_key": "logging.sample_rate"},
        },
    ],
    "mysql-order": [
        {
            "offset_minutes": -40,
            "change_type": "config_change",
            "operator": "dba-bob",
            "summary": "mysql-order 索引变更：对 orders 表新增复合索引 (user_id, created_at)",
            "details": {"ddl": "CREATE INDEX ...", "risk": "high"},
        },
    ],
    "fraud-detection-service": [
        {
            "offset_minutes": -15,
            "change_type": "deployment",
            "operator": "ci-bot",
            "summary": "fraud-detection-service v1.8.0 发布：引入新的风控规则链",
            "details": {"version": "v1.8.0", "risk": "high"},
        },
    ],
    "inventory-service": [
        {
            "offset_minutes": -20,
            "change_type": "deployment",
            "operator": "ci-bot",
            "summary": "inventory-service v3.0.0 发布：重构库存锁实现",
            "details": {"version": "v3.0.0", "risk": "high"},
        },
    ],
    "internal-dns": [
        {
            "offset_minutes": -30,
            "change_type": "infra_change",
            "operator": "sre-charlie",
            "summary": "internal-dns 升级 CoreDNS 版本：1.9.3 → 1.10.1",
            "details": {"from_version": "1.9.3", "to_version": "1.10.1", "risk": "high"},
        },
    ],
    "identity-provider": [
        {
            "offset_minutes": -18,
            "change_type": "config_change",
            "operator": "sec-team",
            "summary": "identity-provider 轮换 JWK 签名密钥",
            "details": {"operation": "jwk_rotation", "risk": "medium"},
        },
    ],
    "order-service": [
        {
            "offset_minutes": -120,
            "change_type": "deployment",
            "operator": "ci-bot",
            "summary": "order-service v4.1.2 发布：优化订单查询（和故障无关）",
            "details": {"version": "v4.1.2", "risk": "low"},
        },
    ],
    "auth-service": [
        {
            "offset_minutes": -60,
            "change_type": "config_change",
            "operator": "alice",
            "summary": "auth-service 调整 token 缓存 TTL",
            "details": {"from_ttl": "5m", "to_ttl": "10m"},
        },
    ],
    "cart-service": [
        {
            "offset_minutes": -45,
            "change_type": "traffic_switch",
            "operator": "sre-dan",
            "summary": "cart-service 灰度切流 10% → 50%",
            "details": {"from_percent": 10, "to_percent": 50},
        },
    ],
}


def query_change(
    *,
    services: Sequence[str],
    time_range_ms: tuple[int, int],
    alert_starts_at_ms: int | None = None,
    change_type: str | None = None,
) -> list[dict[str, Any]]:
    """Mock 变更事件查询。

    参数
    ----
    services: 待查询的服务列表（通常是 [告警服务] + 一级依赖）
    time_range_ms: (from_ms, to_ms) 查询时间窗口（毫秒）
    alert_starts_at_ms: 告警触发时间，用于把预置的 offset_minutes 转为绝对时间；
                        未提供时默认取 to_ms。
    change_type: 可选的变更类型过滤

    返回
    ----
    匹配的变更事件列表（dict 形式）。
    """
    from_ms, to_ms = time_range_ms
    anchor_ms = alert_starts_at_ms if alert_starts_at_ms is not None else to_ms

    events: list[dict[str, Any]] = []
    for svc in services:
        for change in _PREBUILT_CHANGES.get(svc, []):
            event_ts_ms = anchor_ms + change["offset_minutes"] * 60 * 1000
            if not (from_ms <= event_ts_ms <= to_ms):
                continue
            if change_type is not None and change["change_type"] != change_type:
                continue
            event = ChangeEvent(
                event_id=_generate_event_id(svc, change["summary"], event_ts_ms),
                timestamp=datetime.fromtimestamp(event_ts_ms / 1000, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                service=svc,
                change_type=change["change_type"],
                operator=change["operator"],
                summary=change["summary"],
                details=dict(change["details"]),
            )
            events.append(asdict(event))

    events.sort(key=lambda e: e["timestamp"])
    return events


def _generate_event_id(service: str, summary: str, ts_ms: int) -> str:
    seed = md5(f"{service}::{summary}::{ts_ms}".encode()).hexdigest()
    return f"chg_{seed[:12]}"


# ---------- 辅助：根据告警构建默认查询参数 ----------


def build_metric_time_range(
    alert_starts_at_ms: int,
    *,
    before_minutes: int = 15,
    after_minutes: int = 5,
) -> tuple[int, int]:
    """根据告警 startsAt 构建指标查询的时间窗口。

    指标窗口通常比日志窗口更宽，便于观察趋势。
    """
    return (
        alert_starts_at_ms - before_minutes * 60 * 1000,
        alert_starts_at_ms + after_minutes * 60 * 1000,
    )


def build_change_time_range(
    alert_starts_at_ms: int,
    *,
    before_minutes: int = 120,
    after_minutes: int = 10,
) -> tuple[int, int]:
    """根据告警 startsAt 构建变更查询的时间窗口。

    变更窗口比日志/指标更宽（默认 2 小时），因为变更到故障触发
    之间往往有一定延迟。
    """
    return (
        alert_starts_at_ms - before_minutes * 60 * 1000,
        alert_starts_at_ms + after_minutes * 60 * 1000,
    )


def resolve_change_query_services(alert_service: str) -> list[str]:
    """为变更查询解析目标服务列表：告警服务 + 一级依赖。"""
    deps = get_dependencies(alert_service)
    result = [alert_service]
    for dep in deps:
        if dep not in result:
            result.append(dep)
    return result


__all__ = [
    "MetricPoint",
    "MetricSeries",
    "ChangeEvent",
    "query_metric",
    "query_change",
    "build_metric_time_range",
    "build_change_time_range",
    "resolve_change_query_services",
]
