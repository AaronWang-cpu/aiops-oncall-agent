"""通用 AIOps 评测集。

日志、告警、SOP 三者独立生成，互不对答案：
- 告警仅含 service/startsAt/severity/alertname/指标，无 trace_id/sop
- 日志池含根因日志与噪声日志，日志内有 trace_id，告警不知道
- ground truth 只记客观事实，不记对 agent 行为的期望

每个 case 包含：
  alert       Alertmanager v2 格式告警
  log_pool    混合日志列表（根因 + 噪声）
  ground_truth EvalGroundTruth

EvalGroundTruth 字段：
  relevant_log_ids   与本次告警相关的日志 ID（用于评测 query 召回）
  root_cause_log_ids 真正根因日志 ID（relevant 的子集，用于评测 LLM 分析）
  root_cause_service 根因所在服务（难度三与告警 service 不同）
  root_cause_summary 人工标注的根因描述
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True, slots=True)
class EvalGroundTruth:
    relevant_log_ids: tuple[str, ...]
    root_cause_log_ids: tuple[str, ...]
    root_cause_service: str
    root_cause_summary: str


@dataclass(frozen=True, slots=True)
class EvalCase:
    case_id: str
    alert: dict[str, object]
    log_pool: tuple[dict[str, str], ...]
    ground_truth: EvalGroundTruth


_BASE_TIME = datetime(2026, 9, 8, 10, 0, 0, tzinfo=timezone.utc)


def _ts(delta_seconds: int = 0) -> str:
    return (_BASE_TIME + timedelta(seconds=delta_seconds)).isoformat().replace("+00:00", "Z")


def _alert(
    alertname: str,
    service: str,
    severity: str,
    summary: str,
    metric_name: str,
    metric_value: str,
    threshold: str,
    starts_at: str,
) -> dict[str, object]:
    return {
        "labels": {
            "alertname": alertname,
            "service": service,
            "environment": "test",
            "namespace": "java-ecommerce",
            "severity": severity,
            "team": "ecommerce-platform",
        },
        "annotations": {
            "summary": summary,
            "description": f"{metric_name}={metric_value}; threshold {threshold}.",
        },
        "startsAt": starts_at,
        "endsAt": "",
        "generatorURL": f"http://localhost:9090/graph?g0.expr={metric_name}",
    }


def _log(
    log_id: str,
    level: str,
    service: str,
    message: str,
    timestamp: str,
    logger: str = "",
    trace_id: str = "",
    exception: str = "",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    entry: dict[str, str] = {
        "log_id": log_id,
        "timestamp": timestamp,
        "level": level,
        "service": service,
        "message": message,
    }
    if logger:
        entry["logger"] = logger
    if trace_id:
        entry["trace_id"] = trace_id
    if exception:
        entry["exception"] = exception
    if extra:
        entry.update(extra)
    return entry


EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        case_id="eval-d1-order-db-pool",
        alert=_alert(
            alertname="OrderDatabasePoolExhausted",
            service="order-service",
            severity="critical",
            summary="订单服务 HikariCP 连接池耗尽，订单创建大量返回 503。",
            metric_name="hikaricp_pending_connections",
            metric_value="134",
            threshold="> 20 for 3m",
            starts_at=_ts(0),
        ),
        log_pool=(
            _log("d1-ord-001", "ERROR", "order-service", "Connection is not available, request timed out after 30000ms", _ts(-180), logger="com.zaxxer.hikari.pool.HikariPool", trace_id="a1b2c3d4e5f60001a1b2c3d4e5f60001", exception="java.sql.SQLTransientConnectionException", extra={"pool": "HikariPool-1", "active": "40", "pending": "134"}),
            _log("d1-ord-002", "ERROR", "order-service", "Connection is not available, request timed out after 30000ms", _ts(-170), logger="com.zaxxer.hikari.pool.HikariPool", trace_id="a1b2c3d4e5f60002a1b2c3d4e5f60002", exception="java.sql.SQLTransientConnectionException", extra={"pool": "HikariPool-1", "active": "40", "pending": "128"}),
            _log("d1-ord-003", "ERROR", "order-service", "Slow query detected: SELECT * FROM orders WHERE user_id=? took 42000ms, missing pagination", _ts(-200), logger="com.shop.order.application.OrderApplicationService", trace_id="a1b2c3d4e5f60003a1b2c3d4e5f60003", exception="", extra={"duration_ms": "42000", "table": "orders"}),
            _log("d1-ord-004", "WARN", "order-service", "HikariCP pool utilization above 90%", _ts(-240), logger="com.zaxxer.hikari.pool.HikariPool", trace_id="a1b2c3d4e5f60004a1b2c3d4e5f60004", extra={"active": "38", "total": "40"}),
            _log("d1-ord-005", "INFO", "order-service", "Order created successfully", _ts(-300), logger="com.shop.order.application.OrderApplicationService", trace_id="a1b2c3d4e5f60005a1b2c3d4e5f60005", extra={"order_id": "ORD-10021"}),
            _log("d1-ord-006", "INFO", "order-service", "Order created successfully", _ts(-310), logger="com.shop.order.application.OrderApplicationService", trace_id="a1b2c3d4e5f60006a1b2c3d4e5f60006", extra={"order_id": "ORD-10020"}),
            _log("d1-noise-001", "INFO", "cart-service", "Cart updated for user", _ts(-150), logger="com.shop.cart.CartService", trace_id="noise0001noise0001noise0001noise01", extra={"user_id": "U-5523"}),
            _log("d1-noise-002", "INFO", "cart-service", "Cart checkout initiated", _ts(-120), logger="com.shop.cart.CartService", trace_id="noise0002noise0002noise0002noise02", extra={"user_id": "U-5524"}),
            _log("d1-noise-003", "WARN", "promotion-service", "Promotion rule cache miss", _ts(-190), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="noise0003noise0003noise0003noise03", extra={"rule_id": "PROMO-99"}),
            _log("d1-noise-004", "INFO", "promotion-service", "Promotion applied to cart", _ts(-160), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="noise0004noise0004noise0004noise04", extra={"discount": "10%"}),
            _log("d1-noise-005", "INFO", "auth-service", "User login successful", _ts(-400), logger="com.shop.auth.AuthService", trace_id="noise0005noise0005noise0005noise05", extra={"user_id": "U-5523"}),
            _log("d1-noise-006", "INFO", "fulfillment-service", "Shipment dispatched", _ts(-500), logger="com.shop.fulfillment.FulfillmentService", trace_id="noise0006noise0006noise0006noise06", extra={"order_id": "ORD-10019"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d1-ord-001", "d1-ord-002", "d1-ord-003", "d1-ord-004"),
            root_cause_log_ids=("d1-ord-003",),
            root_cause_service="order-service",
            root_cause_summary="订单详情查询缺少分页，慢 SQL 长期占用连接，耗尽 HikariCP 连接池全部 40 个连接。",
        ),
    ),
    EvalCase(
        case_id="eval-d1-payment-gateway-timeout",
        alert=_alert(
            alertname="PaymentGatewayTimeoutHigh",
            service="payment-service",
            severity="critical",
            summary="支付确认接口持续超时，结算请求停留在 PAYING 状态。",
            metric_name="payment_gateway_timeout_rate",
            metric_value="19.2%",
            threshold="> 5% for 5m",
            starts_at=_ts(3600),
        ),
        log_pool=(
            _log("d1-pay-001", "ERROR", "payment-service", "Read timed out after 3000ms connecting to payment-gateway.example.com:443", _ts(3420), logger="com.shop.payment.gateway.PaymentGatewayClient", trace_id="b1c2d3e4f5a60001b1c2d3e4f5a60001", exception="java.net.SocketTimeoutException", extra={"gateway_host": "payment-gateway.example.com", "timeout_ms": "3000"}),
            _log("d1-pay-002", "ERROR", "payment-service", "Read timed out after 3000ms connecting to payment-gateway.example.com:443", _ts(3430), logger="com.shop.payment.gateway.PaymentGatewayClient", trace_id="b1c2d3e4f5a60002b1c2d3e4f5a60002", exception="java.net.SocketTimeoutException", extra={"gateway_host": "payment-gateway.example.com", "timeout_ms": "3000"}),
            _log("d1-pay-003", "ERROR", "payment-service", "TLS handshake latency spike detected: 2800ms (threshold 500ms)", _ts(3400), logger="com.shop.payment.gateway.PaymentGatewayClient", trace_id="b1c2d3e4f5a60003b1c2d3e4f5a60003", extra={"tls_handshake_ms": "2800", "gateway_host": "payment-gateway.example.com"}),
            _log("d1-pay-004", "WARN", "payment-service", "Payment order stuck in PAYING status, no gateway transaction id received", _ts(3440), logger="com.shop.payment.order.PaymentOrderService", trace_id="b1c2d3e4f5a60001b1c2d3e4f5a60001", extra={"order_id": "ORD-88801", "status": "PAYING"}),
            _log("d1-pay-005", "INFO", "payment-service", "Payment confirmed successfully", _ts(3200), logger="com.shop.payment.order.PaymentOrderService", trace_id="b1c2d3e4f5a60010b1c2d3e4f5a60010", extra={"order_id": "ORD-88790", "gateway_tx": "GW-TX-9900"}),
            _log("d1-pay-006", "INFO", "payment-service", "Payment confirmed successfully", _ts(3210), logger="com.shop.payment.order.PaymentOrderService", trace_id="b1c2d3e4f5a60011b1c2d3e4f5a60011", extra={"order_id": "ORD-88791", "gateway_tx": "GW-TX-9901"}),
            _log("d1-noise-007", "INFO", "order-service", "Order submitted to payment", _ts(3415), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0007noise0007noise0007noise07", extra={"order_id": "ORD-88801"}),
            _log("d1-noise-008", "INFO", "inventory-service", "Stock reserved for SKU-2231", _ts(3390), logger="com.shop.inventory.StockService", trace_id="noise0008noise0008noise0008noise08", extra={"sku": "SKU-2231", "qty": "2"}),
            _log("d1-noise-009", "INFO", "cart-service", "Cart cleared after checkout", _ts(3450), logger="com.shop.cart.CartService", trace_id="noise0009noise0009noise0009noise09", extra={"user_id": "U-6612"}),
            _log("d1-noise-010", "INFO", "auth-service", "Token refreshed", _ts(3300), logger="com.shop.auth.AuthService", trace_id="noise0010noise0010noise0010noise10", extra={"user_id": "U-6612"}),
            _log("d1-noise-011", "WARN", "fulfillment-service", "Carrier API response slow: 1200ms", _ts(3500), logger="com.shop.fulfillment.client.CarrierBookingClient", trace_id="noise0011noise0011noise0011noise11", extra={"carrier": "carrier-b", "latency_ms": "1200"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d1-pay-001", "d1-pay-002", "d1-pay-003", "d1-pay-004"),
            root_cause_log_ids=("d1-pay-003",),
            root_cause_service="payment-service",
            root_cause_summary="第三方支付网关 TLS 握手延迟升至 2800ms，触发 3000ms 读取超时，订单无法获取网关流水号停留在 PAYING 状态。",
        ),
    ),
    EvalCase(
        case_id="eval-d1-auth-jwk-refresh",
        alert=_alert(
            alertname="AuthJwkRefreshFailureHigh",
            service="auth-service",
            severity="critical",
            summary="JWT 验签失败率升高，新登录和受保护 API 大量返回 401。",
            metric_name="jwt_unknown_kid_rate",
            metric_value="23.1%",
            threshold="> 1% for 3m",
            starts_at=_ts(7200),
        ),
        log_pool=(
            _log("d1-auth-001", "ERROR", "auth-service", "Failed to fetch JWK from https://idp.example.com/.well-known/jwks.json: connection refused", _ts(7020), logger="com.shop.auth.jwt.JwkKeyProvider", trace_id="c1d2e3f4a5b60001c1d2e3f4a5b60001", exception="com.nimbusds.jose.RemoteKeySourceException", extra={"jwk_url": "https://idp.example.com/.well-known/jwks.json"}),
            _log("d1-auth-002", "ERROR", "auth-service", "Failed to fetch JWK from https://idp.example.com/.well-known/jwks.json: connection refused", _ts(7080), logger="com.shop.auth.jwt.JwkKeyProvider", trace_id="c1d2e3f4a5b60002c1d2e3f4a5b60002", exception="com.nimbusds.jose.RemoteKeySourceException", extra={"jwk_url": "https://idp.example.com/.well-known/jwks.json"}),
            _log("d1-auth-003", "ERROR", "auth-service", "JWT verification failed: unknown kid=key-2026-09-08-v2, cached keys=[key-2026-09-08-v1]", _ts(7100), logger="com.shop.auth.jwt.JwtVerifier", trace_id="c1d2e3f4a5b60003c1d2e3f4a5b60003", exception="com.nimbusds.jose.proc.BadJOSEException", extra={"kid": "key-2026-09-08-v2", "cached_kids": "key-2026-09-08-v1"}),
            _log("d1-auth-004", "WARN", "auth-service", "JWK cache stale, last refresh 1800s ago, retrying", _ts(7000), logger="com.shop.auth.jwt.JwkKeyProvider", trace_id="c1d2e3f4a5b60004c1d2e3f4a5b60004", extra={"last_refresh_seconds": "1800"}),
            _log("d1-auth-005", "INFO", "auth-service", "User login successful", _ts(6800), logger="com.shop.auth.AuthService", trace_id="c1d2e3f4a5b60010c1d2e3f4a5b60010", extra={"user_id": "U-9901"}),
            _log("d1-auth-006", "INFO", "auth-service", "Token issued", _ts(6810), logger="com.shop.auth.AuthService", trace_id="c1d2e3f4a5b60011c1d2e3f4a5b60011", extra={"user_id": "U-9901"}),
            _log("d1-noise-012", "INFO", "order-service", "Order query executed", _ts(7050), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0012noise0012noise0012noise12", extra={"order_id": "ORD-77701"}),
            _log("d1-noise-013", "INFO", "cart-service", "Cart loaded", _ts(7060), logger="com.shop.cart.CartService", trace_id="noise0013noise0013noise0013noise13", extra={"user_id": "U-8801"}),
            _log("d1-noise-014", "WARN", "inventory-service", "Low stock alert for SKU-5512", _ts(6900), logger="com.shop.inventory.StockService", trace_id="noise0014noise0014noise0014noise14", extra={"sku": "SKU-5512", "qty": "3"}),
            _log("d1-noise-015", "INFO", "fulfillment-service", "Shipment label printed", _ts(6950), logger="com.shop.fulfillment.FulfillmentService", trace_id="noise0015noise0015noise0015noise15", extra={"order_id": "ORD-77690"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d1-auth-001", "d1-auth-002", "d1-auth-003", "d1-auth-004"),
            root_cause_log_ids=("d1-auth-001", "d1-auth-002"),
            root_cause_service="auth-service",
            root_cause_summary="代理 DNS 故障导致 JWK 端点无法访问，身份提供方轮换签名 key 后缓存无法刷新，新 kid 未命中缓存导致验签失败率飙升。",
        ),
    ),
    EvalCase(
        case_id="eval-d1-kafka-consumer-lag",
        alert=_alert(
            alertname="OrderEventConsumerLagHigh",
            service="order-event-consumer",
            severity="critical",
            summary="订单事件消费者积压量超阈值，积分和履约状态更新延迟。",
            metric_name="kafka_consumer_group_lag",
            metric_value="52340",
            threshold="> 10000 for 10m",
            starts_at=_ts(10800),
        ),
        log_pool=(
            _log("d1-kafka-001", "ERROR", "order-event-consumer", "Listener failed to deserialize message at partition=2 offset=88721: Unrecognized enum value 'PARTIALLY_REFUNDED' for OrderStatus", _ts(10620), logger="com.shop.order.event.OrderCreatedConsumer", trace_id="d1e2f3a4b5c60001d1e2f3a4b5c60001", exception="org.springframework.kafka.listener.ListenerExecutionFailedException", extra={"partition": "2", "offset": "88721", "schema_version": "v3"}),
            _log("d1-kafka-002", "ERROR", "order-event-consumer", "Listener failed to deserialize message at partition=2 offset=88721: Unrecognized enum value 'PARTIALLY_REFUNDED' for OrderStatus", _ts(10680), logger="com.shop.order.event.OrderCreatedConsumer", trace_id="d1e2f3a4b5c60001d1e2f3a4b5c60001", exception="org.springframework.kafka.listener.ListenerExecutionFailedException", extra={"partition": "2", "offset": "88721", "retry": "3"}),
            _log("d1-kafka-003", "ERROR", "order-event-consumer", "Max retry exhausted for partition=2 offset=88721, message sent to DLT", _ts(10740), logger="com.shop.order.event.OrderCreatedConsumer", trace_id="d1e2f3a4b5c60001d1e2f3a4b5c60001", extra={"partition": "2", "offset": "88721", "dlt_topic": "order-events.DLT"}),
            _log("d1-kafka-004", "WARN", "order-event-consumer", "Consumer group lag increasing: current=52340, rate=+1200/min", _ts(10780), logger="com.shop.order.event.OrderCreatedConsumer", extra={"lag": "52340", "rate": "1200"}),
            _log("d1-kafka-005", "INFO", "order-event-consumer", "Message processed successfully partition=0 offset=88100", _ts(10500), logger="com.shop.order.event.OrderCreatedConsumer", trace_id="d1e2f3a4b5c60010d1e2f3a4b5c60010", extra={"partition": "0", "offset": "88100"}),
            _log("d1-kafka-006", "INFO", "order-event-consumer", "Message processed successfully partition=1 offset=88200", _ts(10510), logger="com.shop.order.event.OrderCreatedConsumer", trace_id="d1e2f3a4b5c60011d1e2f3a4b5c60011", extra={"partition": "1", "offset": "88200"}),
            _log("d1-noise-016", "INFO", "order-service", "Order status updated to SHIPPED", _ts(10600), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0016noise0016noise0016noise16", extra={"order_id": "ORD-55501"}),
            _log("d1-noise-017", "INFO", "fulfillment-service", "Fulfillment record created", _ts(10550), logger="com.shop.fulfillment.FulfillmentService", trace_id="noise0017noise0017noise0017noise17", extra={"order_id": "ORD-55500"}),
            _log("d1-noise-018", "WARN", "promotion-service", "Promotion expired, auto-disabled", _ts(10400), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="noise0018noise0018noise0018noise18", extra={"promotion_id": "PROMO-2026-09"}),
            _log("d1-noise-019", "INFO", "cart-service", "Cart session expired", _ts(10300), logger="com.shop.cart.CartService", trace_id="noise0019noise0019noise0019noise19", extra={"session_id": "sess-7712"}),
            _log("d1-noise-020", "INFO", "auth-service", "User logout", _ts(10200), logger="com.shop.auth.AuthService", trace_id="noise0020noise0020noise0020noise20", extra={"user_id": "U-4401"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d1-kafka-001", "d1-kafka-002", "d1-kafka-003", "d1-kafka-004"),
            root_cause_log_ids=("d1-kafka-001", "d1-kafka-002"),
            root_cause_service="order-event-consumer",
            root_cause_summary="生产者 schema 引入新枚举值 PARTIALLY_REFUNDED，消费者反序列化失败后持续重试同一 poison message，导致 partition=2 消费停滞，整体积压量持续攀升。",
        ),
    ),
    EvalCase(
        case_id="eval-d1-es-search-timeout",
        alert=_alert(
            alertname="ProductSearchTimeoutHigh",
            service="product-search-service",
            severity="critical",
            summary="商品搜索请求超时，关键词搜索返回空结果或降级结果。",
            metric_name="elasticsearch_search_rejected_rate",
            metric_value="15.3%",
            threshold="> 2% for 5m",
            starts_at=_ts(14400),
        ),
        log_pool=(
            _log("d1-es-001", "ERROR", "product-search-service", "Elasticsearch search request rejected: search thread pool exhausted (queue=200/200)", _ts(14220), logger="com.shop.search.repository.ElasticsearchProductRepository", trace_id="e1f2a3b4c5d60001e1f2a3b4c5d60001", exception="co.elastic.clients.transport.TransportException", extra={"index": "products-v3", "thread_pool_queue": "200"}),
            _log("d1-es-002", "ERROR", "product-search-service", "Wildcard query on field 'description.raw' matched 2.4M documents, exceeded 10000 limit", _ts(14200), logger="com.shop.search.repository.ElasticsearchProductRepository", trace_id="e1f2a3b4c5d60002e1f2a3b4c5d60002", extra={"query_type": "wildcard", "field": "description.raw", "matched": "2400000"}),
            _log("d1-es-003", "ERROR", "product-search-service", "Elasticsearch search request rejected: search thread pool exhausted (queue=200/200)", _ts(14240), logger="com.shop.search.repository.ElasticsearchProductRepository", trace_id="e1f2a3b4c5d60003e1f2a3b4c5d60003", exception="co.elastic.clients.transport.TransportException", extra={"index": "products-v3", "thread_pool_queue": "200"}),
            _log("d1-es-004", "WARN", "product-search-service", "Search fallback activated: returning cached results", _ts(14250), logger="com.shop.search.service.ProductSearchService", trace_id="e1f2a3b4c5d60004e1f2a3b4c5d60004", extra={"fallback": "cache", "cache_age_seconds": "120"}),
            _log("d1-es-005", "INFO", "product-search-service", "Search request completed in 380ms", _ts(14000), logger="com.shop.search.repository.ElasticsearchProductRepository", trace_id="e1f2a3b4c5d60010e1f2a3b4c5d60010", extra={"latency_ms": "380"}),
            _log("d1-es-006", "INFO", "product-search-service", "Search request completed in 410ms", _ts(14010), logger="com.shop.search.repository.ElasticsearchProductRepository", trace_id="e1f2a3b4c5d60011e1f2a3b4c5d60011", extra={"latency_ms": "410"}),
            _log("d1-noise-021", "INFO", "cart-service", "Product added to cart", _ts(14210), logger="com.shop.cart.CartService", trace_id="noise0021noise0021noise0021noise21", extra={"product_id": "PROD-3312"}),
            _log("d1-noise-022", "INFO", "order-service", "Order confirmed", _ts(14150), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0022noise0022noise0022noise22", extra={"order_id": "ORD-22201"}),
            _log("d1-noise-023", "WARN", "inventory-service", "Restock job started", _ts(14100), logger="com.shop.inventory.batch.RestockJob", trace_id="noise0023noise0023noise0023noise23", extra={"batch_id": "BATCH-0908"}),
            _log("d1-noise-024", "INFO", "auth-service", "Session extended", _ts(14050), logger="com.shop.auth.AuthService", trace_id="noise0024noise0024noise0024noise24", extra={"user_id": "U-3301"}),
            _log("d1-noise-025", "INFO", "fulfillment-service", "Delivery confirmed by carrier", _ts(14300), logger="com.shop.fulfillment.FulfillmentService", trace_id="noise0025noise0025noise0025noise25", extra={"order_id": "ORD-22190"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d1-es-001", "d1-es-002", "d1-es-003", "d1-es-004"),
            root_cause_log_ids=("d1-es-002",),
            root_cause_service="product-search-service",
            root_cause_summary="未受限的 wildcard 查询扫描高基数字段 description.raw，单次匹配 240 万文档，耗尽 Elasticsearch search 线程池队列，触发大量请求拒绝和降级。",
        ),
    ),
    EvalCase(
        case_id="eval-d1-fulfillment-503",
        alert=_alert(
            alertname="FulfillmentProviderUnavailable",
            service="fulfillment-service",
            severity="critical",
            summary="运单创建持续失败，已支付订单停留在待分配物流状态。",
            metric_name="carrier_booking_503_rate",
            metric_value="38.7%",
            threshold="> 5% for 5m",
            starts_at=_ts(18000),
        ),
        log_pool=(
            _log("d1-ful-001", "ERROR", "fulfillment-service", "Carrier API returned 503 Service Unavailable for booking request", _ts(17820), logger="com.shop.fulfillment.client.CarrierBookingClient", trace_id="f1a2b3c4d5e60001f1a2b3c4d5e60001", exception="org.springframework.web.client.HttpServerErrorException$ServiceUnavailable", extra={"carrier": "primary-carrier", "order_id": "ORD-44401", "retry": "1"}),
            _log("d1-ful-002", "ERROR", "fulfillment-service", "Carrier API returned 503 Service Unavailable for booking request", _ts(17821), logger="com.shop.fulfillment.client.CarrierBookingClient", trace_id="f1a2b3c4d5e60001f1a2b3c4d5e60001", exception="org.springframework.web.client.HttpServerErrorException$ServiceUnavailable", extra={"carrier": "primary-carrier", "order_id": "ORD-44401", "retry": "2"}),
            _log("d1-ful-003", "ERROR", "fulfillment-service", "Carrier API returned 503 Service Unavailable for booking request", _ts(17822), logger="com.shop.fulfillment.client.CarrierBookingClient", trace_id="f1a2b3c4d5e60001f1a2b3c4d5e60001", exception="org.springframework.web.client.HttpServerErrorException$ServiceUnavailable", extra={"carrier": "primary-carrier", "order_id": "ORD-44401", "retry": "3"}),
            _log("d1-ful-004", "WARN", "fulfillment-service", "No exponential backoff configured for CarrierBookingClient, retrying immediately", _ts(17815), logger="com.shop.fulfillment.client.CarrierBookingClient", trace_id="f1a2b3c4d5e60002f1a2b3c4d5e60002", extra={"carrier": "primary-carrier"}),
            _log("d1-ful-005", "INFO", "fulfillment-service", "Shipment booked successfully via primary-carrier", _ts(17600), logger="com.shop.fulfillment.client.CarrierBookingClient", trace_id="f1a2b3c4d5e60010f1a2b3c4d5e60010", extra={"order_id": "ORD-44390", "tracking_no": "TRK-99001"}),
            _log("d1-ful-006", "INFO", "fulfillment-service", "Shipment booked successfully via primary-carrier", _ts(17610), logger="com.shop.fulfillment.client.CarrierBookingClient", trace_id="f1a2b3c4d5e60011f1a2b3c4d5e60011", extra={"order_id": "ORD-44391", "tracking_no": "TRK-99002"}),
            _log("d1-noise-026", "INFO", "order-service", "Payment confirmed, dispatching to fulfillment", _ts(17810), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0026noise0026noise0026noise26", extra={"order_id": "ORD-44401"}),
            _log("d1-noise-027", "INFO", "payment-service", "Payment settled", _ts(17800), logger="com.shop.payment.order.PaymentOrderService", trace_id="noise0027noise0027noise0027noise27", extra={"order_id": "ORD-44401"}),
            _log("d1-noise-028", "INFO", "cart-service", "Cart cleared", _ts(17790), logger="com.shop.cart.CartService", trace_id="noise0028noise0028noise0028noise28", extra={"user_id": "U-1122"}),
            _log("d1-noise-029", "WARN", "product-search-service", "Index refresh delayed by 3s", _ts(17700), logger="com.shop.search.index.IndexRefreshJob", trace_id="noise0029noise0029noise0029noise29", extra={"index": "products-v3"}),
            _log("d1-noise-030", "INFO", "auth-service", "User login successful", _ts(17650), logger="com.shop.auth.AuthService", trace_id="noise0030noise0030noise0030noise30", extra={"user_id": "U-1122"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d1-ful-001", "d1-ful-002", "d1-ful-003", "d1-ful-004"),
            root_cause_log_ids=("d1-ful-004",),
            root_cause_service="fulfillment-service",
            root_cause_summary="主物流供应商进入维护窗口返回 503，客户端缺少指数退避配置，立即重试造成请求放大，运单创建成功率骤降。",
        ),
    ),
    EvalCase(
        case_id="eval-d2-redis-latency",
        alert=_alert(
            alertname="CartRedisLatencyHigh",
            service="cart-service",
            severity="warning",
            summary="购物车读取延迟升高，部分用户看到购物车加载失败。",
            metric_name="redis_command_latency_p99",
            metric_value="1820ms",
            threshold="> 500ms for 5m",
            starts_at=_ts(21600),
        ),
        log_pool=(
            _log("d2-cart-001", "WARN", "cart-service", "Redis command HGETALL timed out after 1500ms for key cart:promotion:index", _ts(21420), logger="com.shop.cart.infrastructure.RedisCartRepository", trace_id="a2b3c4d5e6f70001a2b3c4d5e6f70001", exception="io.lettuce.core.RedisCommandTimeoutException", extra={"key": "cart:promotion:index", "command": "HGETALL", "timeout_ms": "1500"}),
            _log("d2-cart-002", "WARN", "cart-service", "Redis command HGETALL timed out after 1500ms for key cart:promotion:index", _ts(21480), logger="com.shop.cart.infrastructure.RedisCartRepository", trace_id="a2b3c4d5e6f70002a2b3c4d5e6f70002", exception="io.lettuce.core.RedisCommandTimeoutException", extra={"key": "cart:promotion:index", "command": "HGETALL", "timeout_ms": "1500"}),
            _log("d2-cart-003", "WARN", "cart-service", "Hot key detected: cart:promotion:index, value size=4.2MB, deserialization blocked event loop for 890ms", _ts(21400), logger="com.shop.cart.infrastructure.RedisCartRepository", trace_id="a2b3c4d5e6f70003a2b3c4d5e6f70003", extra={"key": "cart:promotion:index", "value_size_mb": "4.2", "block_ms": "890"}),
            _log("d2-cart-004", "WARN", "cart-service", "Cart load degraded: returning partial cart without promotion decorations", _ts(21490), logger="com.shop.cart.application.CartApplicationService", trace_id="a2b3c4d5e6f70004a2b3c4d5e6f70004", extra={"user_id": "U-7731", "degraded": "true"}),
            _log("d2-cart-005", "INFO", "cart-service", "Cart loaded successfully", _ts(21200), logger="com.shop.cart.application.CartApplicationService", trace_id="a2b3c4d5e6f70010a2b3c4d5e6f70010", extra={"user_id": "U-7720", "latency_ms": "45"}),
            _log("d2-cart-006", "INFO", "cart-service", "Cart loaded successfully", _ts(21210), logger="com.shop.cart.application.CartApplicationService", trace_id="a2b3c4d5e6f70011a2b3c4d5e6f70011", extra={"user_id": "U-7721", "latency_ms": "52"}),
            _log("d2-cart-007", "INFO", "cart-service", "Item added to cart", _ts(21300), logger="com.shop.cart.application.CartApplicationService", trace_id="a2b3c4d5e6f70012a2b3c4d5e6f70012", extra={"user_id": "U-7725", "sku": "SKU-1102"}),
            _log("d2-noise-001", "INFO", "promotion-service", "Promotion rule evaluated", _ts(21410), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="noise0031noise0031noise0031noise31", extra={"rule_id": "PROMO-55", "result": "eligible"}),
            _log("d2-noise-002", "INFO", "product-search-service", "Search completed in 290ms", _ts(21350), logger="com.shop.search.repository.ElasticsearchProductRepository", trace_id="noise0032noise0032noise0032noise32", extra={"latency_ms": "290"}),
            _log("d2-noise-003", "WARN", "order-service", "Order query took 1100ms", _ts(21500), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0033noise0033noise0033noise33", extra={"duration_ms": "1100", "order_id": "ORD-11100"}),
            _log("d2-noise-004", "INFO", "auth-service", "User authenticated", _ts(21250), logger="com.shop.auth.AuthService", trace_id="noise0034noise0034noise0034noise34", extra={"user_id": "U-7731"}),
            _log("d2-noise-005", "INFO", "fulfillment-service", "Shipment status updated to IN_TRANSIT", _ts(21150), logger="com.shop.fulfillment.FulfillmentService", trace_id="noise0035noise0035noise0035noise35", extra={"order_id": "ORD-11090"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d2-cart-001", "d2-cart-002", "d2-cart-003", "d2-cart-004"),
            root_cause_log_ids=("d2-cart-003",),
            root_cause_service="cart-service",
            root_cause_summary="Redis 热 key cart:promotion:index 存储 4.2MB 大对象，HGETALL 反序列化阻塞 Lettuce 事件循环 890ms，导致后续 Redis 命令超时，购物车加载降级。",
        ),
    ),
    EvalCase(
        case_id="eval-d2-inventory-lock-wait",
        alert=_alert(
            alertname="InventoryReservationLockWaitHigh",
            service="inventory-service",
            severity="warning",
            summary="热门 SKU 库存预占超时，下单接口返回库存繁忙。",
            metric_name="inventory_lock_wait_seconds_p95",
            metric_value="7.4s",
            threshold="> 2s for 5m",
            starts_at=_ts(25200),
        ),
        log_pool=(
            _log("d2-inv-001", "WARN", "inventory-service", "Lock wait timeout for SKU-8801 reservation, waited 7200ms", _ts(25020), logger="com.shop.inventory.repository.StockReservationRepository", trace_id="b2c3d4e5f6a70001b2c3d4e5f6a70001", exception="org.springframework.dao.CannotAcquireLockException", extra={"sku": "SKU-8801", "wait_ms": "7200"}),
            _log("d2-inv-002", "WARN", "inventory-service", "Lock wait timeout for SKU-8801 reservation, waited 7400ms", _ts(25080), logger="com.shop.inventory.repository.StockReservationRepository", trace_id="b2c3d4e5f6a70002b2c3d4e5f6a70002", exception="org.springframework.dao.CannotAcquireLockException", extra={"sku": "SKU-8801", "wait_ms": "7400"}),
            _log("d2-inv-003", "WARN", "inventory-service", "Batch restock job holding row lock on stock table for 18s (batch_id=BATCH-0908, rows=50000)", _ts(24900), logger="com.shop.inventory.batch.RestockJob", trace_id="b2c3d4e5f6a70003b2c3d4e5f6a70003", extra={"batch_id": "BATCH-0908", "lock_duration_s": "18", "rows": "50000"}),
            _log("d2-inv-004", "WARN", "inventory-service", "Reservation retry scheduled due to lock contention", _ts(25090), logger="com.shop.inventory.repository.StockReservationRepository", trace_id="b2c3d4e5f6a70004b2c3d4e5f6a70004", extra={"sku": "SKU-8801", "retry_after_ms": "500"}),
            _log("d2-inv-005", "INFO", "inventory-service", "Stock reserved for SKU-3301", _ts(24800), logger="com.shop.inventory.StockService", trace_id="b2c3d4e5f6a70010b2c3d4e5f6a70010", extra={"sku": "SKU-3301", "qty": "1"}),
            _log("d2-inv-006", "INFO", "inventory-service", "Restock job completed for SKU-3301", _ts(24750), logger="com.shop.inventory.batch.RestockJob", trace_id="b2c3d4e5f6a70011b2c3d4e5f6a70011", extra={"sku": "SKU-3301", "added": "500"}),
            _log("d2-noise-006", "INFO", "order-service", "Order dispatched to inventory reservation", _ts(25010), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0036noise0036noise0036noise36", extra={"order_id": "ORD-66601", "sku": "SKU-8801"}),
            _log("d2-noise-007", "INFO", "cart-service", "Cart checkout initiated", _ts(25000), logger="com.shop.cart.CartService", trace_id="noise0037noise0037noise0037noise37", extra={"user_id": "U-2211"}),
            _log("d2-noise-008", "INFO", "payment-service", "Payment initiated", _ts(24990), logger="com.shop.payment.order.PaymentOrderService", trace_id="noise0038noise0038noise0038noise38", extra={"order_id": "ORD-66601"}),
            _log("d2-noise-009", "WARN", "promotion-service", "Rule evaluation slow: 1200ms for 8 rules", _ts(25100), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="noise0039noise0039noise0039noise39", extra={"rule_count": "8", "duration_ms": "1200"}),
            _log("d2-noise-010", "INFO", "auth-service", "Session validated", _ts(24950), logger="com.shop.auth.AuthService", trace_id="noise0040noise0040noise0040noise40", extra={"user_id": "U-2211"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d2-inv-001", "d2-inv-002", "d2-inv-003", "d2-inv-004"),
            root_cause_log_ids=("d2-inv-003",),
            root_cause_service="inventory-service",
            root_cause_summary="补库存批任务（BATCH-0908）对库存表持有行锁长达 18s，与热门 SKU-8801 的预占更新发生行锁竞争，导致预占请求等待超时。",
        ),
    ),
    EvalCase(
        case_id="eval-d2-promotion-cpu",
        alert=_alert(
            alertname="PromotionRuleEvaluationCpuHigh",
            service="promotion-service",
            severity="warning",
            summary="促销试算延迟超过 2 秒，实例 CPU 持续接近满载。",
            metric_name="process_cpu_usage",
            metric_value="94%",
            threshold="> 85% for 10m",
            starts_at=_ts(28800),
        ),
        log_pool=(
            _log("d2-promo-001", "WARN", "promotion-service", "Rule evaluation took 3200ms for cart with 12 active promotions (activity_id=ACT-2026-09-VIP)", _ts(28620), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="c2d3e4f5a6b70001c2d3e4f5a6b70001", extra={"activity_id": "ACT-2026-09-VIP", "rule_count": "12", "duration_ms": "3200"}),
            _log("d2-promo-002", "WARN", "promotion-service", "Combinatorial promotion candidate set size exceeded 50000 for activity_id=ACT-2026-09-VIP", _ts(28600), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="c2d3e4f5a6b70002c2d3e4f5a6b70002", extra={"activity_id": "ACT-2026-09-VIP", "candidate_size": "50000", "max_depth": "8"}),
            _log("d2-promo-003", "WARN", "promotion-service", "CPU utilization at 91%, throttling low-priority rule evaluations", _ts(28700), logger="com.shop.promotion.engine.PromotionRuleEngine", extra={"cpu_pct": "91", "throttled": "true"}),
            _log("d2-promo-004", "WARN", "promotion-service", "Rule evaluation took 2900ms for cart (activity_id=ACT-2026-09-VIP)", _ts(28680), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="c2d3e4f5a6b70003c2d3e4f5a6b70003", extra={"activity_id": "ACT-2026-09-VIP", "duration_ms": "2900"}),
            _log("d2-promo-005", "INFO", "promotion-service", "Promotion rule evaluated in 210ms", _ts(28400), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="c2d3e4f5a6b70010c2d3e4f5a6b70010", extra={"activity_id": "ACT-2026-08-SUMMER", "duration_ms": "210"}),
            _log("d2-promo-006", "INFO", "promotion-service", "Promotion rule cache refreshed", _ts(28300), logger="com.shop.promotion.engine.PromotionRuleEngine", extra={"cache_size": "45"}),
            _log("d2-noise-011", "INFO", "cart-service", "Checkout initiated", _ts(28610), logger="com.shop.cart.CartService", trace_id="noise0041noise0041noise0041noise41", extra={"user_id": "U-9901"}),
            _log("d2-noise-012", "INFO", "order-service", "Order validated", _ts(28650), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0042noise0042noise0042noise42", extra={"order_id": "ORD-33301"}),
            _log("d2-noise-013", "INFO", "product-search-service", "Category search completed in 180ms", _ts(28500), logger="com.shop.search.repository.ElasticsearchProductRepository", trace_id="noise0043noise0043noise0043noise43", extra={"latency_ms": "180"}),
            _log("d2-noise-014", "WARN", "inventory-service", "Stock level low for SKU-9901", _ts(28400), logger="com.shop.inventory.StockService", trace_id="noise0044noise0044noise0044noise44", extra={"sku": "SKU-9901", "qty": "2"}),
            _log("d2-noise-015", "INFO", "auth-service", "Token validated", _ts(28350), logger="com.shop.auth.AuthService", trace_id="noise0045noise0045noise0045noise45", extra={"user_id": "U-9901"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d2-promo-001", "d2-promo-002", "d2-promo-003", "d2-promo-004"),
            root_cause_log_ids=("d2-promo-002",),
            root_cause_service="promotion-service",
            root_cause_summary="新上架的组合促销活动 ACT-2026-09-VIP 触发指数级候选组合计算（max_depth=8，候选集超 5 万），CPU 满载导致所有促销试算超时。",
        ),
    ),
    EvalCase(
        case_id="eval-d2-search-slow-warmup",
        alert=_alert(
            alertname="ProductSearchLatencyHigh",
            service="product-search-service",
            severity="warning",
            summary="商品搜索 p95 延迟超过 2 秒，影响首屏加载体验。",
            metric_name="search_latency_p95_ms",
            metric_value="2340",
            threshold="> 800ms for 10m",
            starts_at=_ts(32400),
        ),
        log_pool=(
            _log("d2-srch-001", "WARN", "product-search-service", "Search index warming up after restart, fielddata cache cold: completion rate 12%", _ts(32220), logger="com.shop.search.index.IndexWarmupJob", extra={"cache_warm_pct": "12", "index": "products-v3"}),
            _log("d2-srch-002", "WARN", "product-search-service", "Aggregation on field 'category.keyword' loaded 890MB fielddata into heap, GC pressure increasing", _ts(32280), logger="com.shop.search.repository.ElasticsearchProductRepository", trace_id="d2e3f4a5b6c70001d2e3f4a5b6c70001", extra={"field": "category.keyword", "fielddata_mb": "890", "heap_used_pct": "82"}),
            _log("d2-srch-003", "WARN", "product-search-service", "Search request latency degraded: p95=2200ms (baseline 350ms)", _ts(32350), logger="com.shop.search.service.ProductSearchService", trace_id="d2e3f4a5b6c70002d2e3f4a5b6c70002", extra={"p95_ms": "2200", "baseline_ms": "350"}),
            _log("d2-srch-004", "WARN", "product-search-service", "JVM old-gen GC pause 1800ms, search threads blocked", _ts(32300), logger="com.shop.search.jvm.GcMonitor", extra={"gc_pause_ms": "1800", "old_gen_used_pct": "89"}),
            _log("d2-srch-005", "INFO", "product-search-service", "Index restart completed", _ts(32200), logger="com.shop.search.index.IndexManager", extra={"index": "products-v3", "duration_ms": "12000"}),
            _log("d2-srch-006", "INFO", "product-search-service", "Search request completed in 380ms", _ts(32100), logger="com.shop.search.repository.ElasticsearchProductRepository", trace_id="d2e3f4a5b6c70010d2e3f4a5b6c70010", extra={"latency_ms": "380"}),
            _log("d2-noise-016", "INFO", "cart-service", "Checkout completed", _ts(32310), logger="com.shop.cart.CartService", trace_id="noise0046noise0046noise0046noise46", extra={"user_id": "U-5501"}),
            _log("d2-noise-017", "INFO", "order-service", "Order created", _ts(32320), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0047noise0047noise0047noise47", extra={"order_id": "ORD-44501"}),
            _log("d2-noise-018", "WARN", "inventory-service", "Reservation timeout for SKU-2201", _ts(32330), logger="com.shop.inventory.repository.StockReservationRepository", trace_id="noise0048noise0048noise0048noise48", extra={"sku": "SKU-2201", "wait_ms": "3100"}),
            _log("d2-noise-019", "INFO", "promotion-service", "Rule evaluated in 190ms", _ts(32250), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="noise0049noise0049noise0049noise49", extra={"activity_id": "ACT-2026-08-SUMMER"}),
            _log("d2-noise-020", "INFO", "auth-service", "User authenticated", _ts(32150), logger="com.shop.auth.AuthService", trace_id="noise0050noise0050noise0050noise50", extra={"user_id": "U-5501"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d2-srch-001", "d2-srch-002", "d2-srch-003", "d2-srch-004"),
            root_cause_log_ids=("d2-srch-002", "d2-srch-004"),
            root_cause_service="product-search-service",
            root_cause_summary="索引重启后 fielddata 缓存冷启动，category.keyword 聚合加载 890MB 到堆内存，触发 JVM old-gen GC 暂停 1800ms，搜索线程阻塞导致 p95 延迟升至 2340ms。",
        ),
    ),
    EvalCase(
        case_id="eval-d3-gateway-inventory",
        alert=_alert(
            alertname="GatewayCheckoutCircuitOpen",
            service="api-gateway",
            severity="critical",
            summary="结算路由熔断器打开，网关快速失败并返回 503。",
            metric_name="checkout_circuit_open_state",
            metric_value="1",
            threshold="= 1 for 2m",
            starts_at=_ts(36000),
        ),
        log_pool=(
            _log("d3-gw-001", "ERROR", "api-gateway", "Circuit breaker checkoutInventory opened: upstream inventory-service error rate 42% exceeds threshold 20%", _ts(35820), logger="com.shop.gateway.filter.CheckoutCircuitBreakerFilter", trace_id="e3f4a5b6c7d80001e3f4a5b6c7d80001", exception="io.github.resilience4j.circuitbreaker.CallNotPermittedException", extra={"circuit": "checkoutInventory", "error_rate": "42%", "upstream": "inventory-service"}),
            _log("d3-gw-002", "ERROR", "api-gateway", "Upstream inventory-service returned 500 after 8200ms, half-open probe failed", _ts(35880), logger="com.shop.gateway.filter.CheckoutCircuitBreakerFilter", trace_id="e3f4a5b6c7d80002e3f4a5b6c7d80002", exception="io.github.resilience4j.circuitbreaker.CallNotPermittedException", extra={"circuit": "checkoutInventory", "upstream_latency_ms": "8200", "probe": "half-open"}),
            _log("d3-gw-003", "WARN", "api-gateway", "Checkout requests fast-failing due to open circuit, returning 503 to clients", _ts(35900), logger="com.shop.gateway.filter.CheckoutCircuitBreakerFilter", extra={"circuit": "checkoutInventory", "rejected_count": "312"}),
            _log("d3-gw-004", "INFO", "api-gateway", "Checkout request routed to inventory-service successfully", _ts(35600), logger="com.shop.gateway.filter.CheckoutCircuitBreakerFilter", trace_id="e3f4a5b6c7d80010e3f4a5b6c7d80010", extra={"upstream": "inventory-service", "latency_ms": "120"}),
            _log("d3-inv-001", "ERROR", "inventory-service", "Lock wait timeout for SKU-8801 reservation, waited 8100ms", _ts(35810), logger="com.shop.inventory.repository.StockReservationRepository", trace_id="e3f4a5b6c7d80001e3f4a5b6c7d80001", exception="org.springframework.dao.CannotAcquireLockException", extra={"sku": "SKU-8801", "wait_ms": "8100"}),
            _log("d3-inv-002", "ERROR", "inventory-service", "Lock wait timeout for SKU-8801 reservation, waited 8200ms", _ts(35830), logger="com.shop.inventory.repository.StockReservationRepository", trace_id="e3f4a5b6c7d80002e3f4a5b6c7d80002", exception="org.springframework.dao.CannotAcquireLockException", extra={"sku": "SKU-8801", "wait_ms": "8200"}),
            _log("d3-inv-003", "ERROR", "inventory-service", "Batch restock job holding exclusive lock on stock table for 25s (batch_id=BATCH-0908-B, rows=80000)", _ts(35700), logger="com.shop.inventory.batch.RestockJob", trace_id="e3f4a5b6c7d80003e3f4a5b6c7d80003", extra={"batch_id": "BATCH-0908-B", "lock_duration_s": "25", "rows": "80000"}),
            _log("d3-inv-004", "WARN", "inventory-service", "Service health check failing: p95 response time 8500ms", _ts(35850), logger="com.shop.inventory.health.InventoryHealthIndicator", extra={"p95_ms": "8500", "health": "degraded"}),
            _log("d3-noise-001", "INFO", "payment-service", "Payment confirmed", _ts(35820), logger="com.shop.payment.order.PaymentOrderService", trace_id="noise0051noise0051noise0051noise51", extra={"order_id": "ORD-77701"}),
            _log("d3-noise-002", "INFO", "cart-service", "Cart cleared after checkout", _ts(35830), logger="com.shop.cart.CartService", trace_id="noise0052noise0052noise0052noise52", extra={"user_id": "U-3312"}),
            _log("d3-noise-003", "INFO", "auth-service", "Token validated", _ts(35800), logger="com.shop.auth.AuthService", trace_id="noise0053noise0053noise0053noise53", extra={"user_id": "U-3312"}),
            _log("d3-noise-004", "INFO", "promotion-service", "Promotion evaluated in 220ms", _ts(35750), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="noise0054noise0054noise0054noise54", extra={"activity_id": "ACT-2026-09-VIP"}),
            _log("d3-noise-005", "INFO", "fulfillment-service", "Shipment dispatched", _ts(35700), logger="com.shop.fulfillment.FulfillmentService", trace_id="noise0055noise0055noise0055noise55", extra={"order_id": "ORD-77690"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d3-gw-001", "d3-gw-002", "d3-gw-003", "d3-inv-001", "d3-inv-002", "d3-inv-003", "d3-inv-004"),
            root_cause_log_ids=("d3-inv-003",),
            root_cause_service="inventory-service",
            root_cause_summary="补库存批任务（BATCH-0908-B）持有库存表排他锁 25s，导致 inventory-service 预占请求全部超时，错误率升至 42%，触发 api-gateway 对 inventory-service 的熔断器打开。",
        ),
    ),
    EvalCase(
        case_id="eval-d3-order-payment-mysql",
        alert=_alert(
            alertname="OrderDatabasePoolExhausted",
            service="order-service",
            severity="critical",
            summary="订单服务连接池耗尽，下单接口返回 503。",
            metric_name="hikaricp_pending_connections",
            metric_value="98",
            threshold="> 20 for 3m",
            starts_at=_ts(39600),
        ),
        log_pool=(
            _log("d3-ord-001", "ERROR", "order-service", "Connection is not available, request timed out after 30000ms", _ts(39420), logger="com.zaxxer.hikari.pool.HikariPool", trace_id="f4a5b6c7d8e90001f4a5b6c7d8e90001", exception="java.sql.SQLTransientConnectionException", extra={"pool": "HikariPool-1", "active": "40", "pending": "98"}),
            _log("d3-ord-002", "ERROR", "order-service", "MySQL connection to mysql-order.internal:3306 refused: too many connections (max=151)", _ts(39400), logger="com.shop.order.application.OrderApplicationService", trace_id="f4a5b6c7d8e90002f4a5b6c7d8e90002", exception="com.mysql.cj.exceptions.CJCommunicationsException", extra={"host": "mysql-order.internal", "port": "3306", "mysql_error": "too many connections"}),
            _log("d3-ord-003", "WARN", "order-service", "HikariCP pool 95% utilized, pending requests accumulating", _ts(39380), logger="com.zaxxer.hikari.pool.HikariPool", trace_id="f4a5b6c7d8e90003f4a5b6c7d8e90003", extra={"active": "38", "total": "40", "pending": "72"}),
            _log("d3-ord-004", "INFO", "order-service", "Order query executed in 120ms", _ts(39200), logger="com.shop.order.application.OrderApplicationService", trace_id="f4a5b6c7d8e90010f4a5b6c7d8e90010", extra={"order_id": "ORD-55001", "duration_ms": "120"}),
            _log("d3-mysql-001", "ERROR", "mysql-order", "Thread pool exhausted: 151/151 connections in use, rejecting new connections", _ts(39390), logger="mysql.general", trace_id="f4a5b6c7d8e90001f4a5b6c7d8e90001", extra={"max_connections": "151", "current": "151"}),
            _log("d3-mysql-002", "ERROR", "mysql-order", "Long-running query detected: SELECT * FROM order_items WHERE order_id IN (SELECT id FROM orders) running for 95s, blocking 38 other threads", _ts(39300), logger="mysql.slow_query", trace_id="f4a5b6c7d8e90002f4a5b6c7d8e90002", extra={"duration_s": "95", "blocked_threads": "38", "query_type": "full_scan"}),
            _log("d3-mysql-003", "ERROR", "mysql-order", "InnoDB row lock wait timeout exceeded for 12 transactions", _ts(39350), logger="mysql.innodb", trace_id="f4a5b6c7d8e90003f4a5b6c7d8e90003", extra={"lock_wait_timeout": "50", "transactions": "12"}),
            _log("d3-mysql-004", "WARN", "mysql-order", "Replication lag increased to 45s", _ts(39320), logger="mysql.replication", extra={"lag_s": "45", "replica": "mysql-order-replica-01"}),
            _log("d3-noise-006", "INFO", "payment-service", "Payment initiated for order", _ts(39410), logger="com.shop.payment.order.PaymentOrderService", trace_id="noise0056noise0056noise0056noise56", extra={"order_id": "ORD-55101"}),
            _log("d3-noise-007", "INFO", "cart-service", "Checkout initiated", _ts(39405), logger="com.shop.cart.CartService", trace_id="noise0057noise0057noise0057noise57", extra={"user_id": "U-8812"}),
            _log("d3-noise-008", "INFO", "auth-service", "Token validated", _ts(39400), logger="com.shop.auth.AuthService", trace_id="noise0058noise0058noise0058noise58", extra={"user_id": "U-8812"}),
            _log("d3-noise-009", "INFO", "promotion-service", "Promotion rule cache hit", _ts(39380), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="noise0059noise0059noise0059noise59", extra={"rule_id": "PROMO-77"}),
            _log("d3-noise-010", "INFO", "fulfillment-service", "Delivery status synced", _ts(39350), logger="com.shop.fulfillment.FulfillmentService", trace_id="noise0060noise0060noise0060noise60", extra={"order_id": "ORD-54990"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d3-ord-001", "d3-ord-002", "d3-ord-003", "d3-mysql-001", "d3-mysql-002", "d3-mysql-003", "d3-mysql-004"),
            root_cause_log_ids=("d3-mysql-002",),
            root_cause_service="mysql-order",
            root_cause_summary="order-service 的底层数据库 mysql-order 中存在执行 95s 的全表扫描 SQL，占满 151 个连接并阻塞 38 个线程，导致 order-service HikariCP 连接池耗尽。",
        ),
    ),
    EvalCase(
        case_id="eval-d3-payment-upstream-fraud",
        alert=_alert(
            alertname="PaymentGatewayTimeoutHigh",
            service="payment-service",
            severity="critical",
            summary="支付成功率下降，大量订单支付超时。",
            metric_name="payment_gateway_timeout_rate",
            metric_value="31.5%",
            threshold="> 5% for 5m",
            starts_at=_ts(43200),
        ),
        log_pool=(
            _log("d3-pay-001", "ERROR", "payment-service", "Upstream fraud-detection-service returned 504 Gateway Timeout after 5000ms", _ts(43020), logger="com.shop.payment.gateway.PaymentGatewayClient", trace_id="a5b6c7d8e9f00001a5b6c7d8e9f00001", exception="java.net.SocketTimeoutException", extra={"upstream": "fraud-detection-service", "timeout_ms": "5000"}),
            _log("d3-pay-002", "ERROR", "payment-service", "Upstream fraud-detection-service returned 504 Gateway Timeout after 5000ms", _ts(43080), logger="com.shop.payment.gateway.PaymentGatewayClient", trace_id="a5b6c7d8e9f00002a5b6c7d8e9f00002", exception="java.net.SocketTimeoutException", extra={"upstream": "fraud-detection-service", "timeout_ms": "5000"}),
            _log("d3-pay-003", "WARN", "payment-service", "Payment flow blocking on fraud check result, total wait 5100ms", _ts(43090), logger="com.shop.payment.flow.PaymentFlowOrchestrator", trace_id="a5b6c7d8e9f00001a5b6c7d8e9f00001", extra={"fraud_wait_ms": "5100", "order_id": "ORD-88901"}),
            _log("d3-pay-004", "INFO", "payment-service", "Payment completed in 320ms", _ts(42800), logger="com.shop.payment.order.PaymentOrderService", trace_id="a5b6c7d8e9f00010a5b6c7d8e9f00010", extra={"order_id": "ORD-88890", "gateway_tx": "GW-TX-11001"}),
            _log("d3-fraud-001", "ERROR", "fraud-detection-service", "Model inference endpoint unresponsive: GPU worker pool exhausted (0/8 workers available)", _ts(43000), logger="com.shop.fraud.inference.ModelInferenceClient", trace_id="a5b6c7d8e9f00001a5b6c7d8e9f00001", exception="java.util.concurrent.TimeoutException", extra={"gpu_workers_available": "0", "gpu_workers_total": "8"}),
            _log("d3-fraud-002", "ERROR", "fraud-detection-service", "Inference queue full (depth=500), rejecting new scoring requests", _ts(43010), logger="com.shop.fraud.inference.ModelInferenceClient", trace_id="a5b6c7d8e9f00002a5b6c7d8e9f00002", extra={"queue_depth": "500", "queue_max": "500"}),
            _log("d3-fraud-003", "ERROR", "fraud-detection-service", "GPU OOM: fraud model batch inference failed, CUDA out of memory on device 0", _ts(42950), logger="com.shop.fraud.model.FraudModelRunner", trace_id="a5b6c7d8e9f00003a5b6c7d8e9f00003", exception="ai.djl.engine.EngineException", extra={"device": "cuda:0", "error": "CUDA out of memory"}),
            _log("d3-fraud-004", "WARN", "fraud-detection-service", "Fallback to rule-based fraud check, model unavailable", _ts(43050), logger="com.shop.fraud.FraudCheckService", trace_id="a5b6c7d8e9f00004a5b6c7d8e9f00004", extra={"fallback": "rule_based", "reason": "model_unavailable"}),
            _log("d3-noise-011", "INFO", "order-service", "Order submitted for payment", _ts(43015), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0061noise0061noise0061noise61", extra={"order_id": "ORD-88901"}),
            _log("d3-noise-012", "INFO", "cart-service", "Cart cleared after order", _ts(43005), logger="com.shop.cart.CartService", trace_id="noise0062noise0062noise0062noise62", extra={"user_id": "U-9912"}),
            _log("d3-noise-013", "INFO", "auth-service", "Session extended", _ts(43000), logger="com.shop.auth.AuthService", trace_id="noise0063noise0063noise0063noise63", extra={"user_id": "U-9912"}),
            _log("d3-noise-014", "INFO", "inventory-service", "Stock reserved", _ts(42990), logger="com.shop.inventory.StockService", trace_id="noise0064noise0064noise0064noise64", extra={"sku": "SKU-4411", "qty": "1"}),
            _log("d3-noise-015", "INFO", "promotion-service", "Promotion applied", _ts(42980), logger="com.shop.promotion.engine.PromotionRuleEngine", trace_id="noise0065noise0065noise0065noise65", extra={"activity_id": "ACT-2026-09-VIP"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d3-pay-001", "d3-pay-002", "d3-pay-003", "d3-fraud-001", "d3-fraud-002", "d3-fraud-003", "d3-fraud-004"),
            root_cause_log_ids=("d3-fraud-003",),
            root_cause_service="fraud-detection-service",
            root_cause_summary="fraud-detection-service 的 GPU 显存溢出导致模型推理 Worker 全部挂起，推理队列打满后拒绝新请求，payment-service 的欺诈检测调用全部超时，支付流程阻塞。",
        ),
    ),
    EvalCase(
        case_id="eval-d3-fulfillment-carrier-dns",
        alert=_alert(
            alertname="FulfillmentProviderUnavailable",
            service="fulfillment-service",
            severity="critical",
            summary="运单创建失败率飙升，物流分配停滞。",
            metric_name="carrier_booking_503_rate",
            metric_value="41.2%",
            threshold="> 5% for 5m",
            starts_at=_ts(46800),
        ),
        log_pool=(
            _log("d3-ful-001", "ERROR", "fulfillment-service", "DNS resolution failed for carrier-api.primary-carrier.com: no such host", _ts(46620), logger="com.shop.fulfillment.client.CarrierBookingClient", trace_id="b6c7d8e9f0a10001b6c7d8e9f0a10001", exception="java.net.UnknownHostException", extra={"host": "carrier-api.primary-carrier.com"}),
            _log("d3-ful-002", "ERROR", "fulfillment-service", "DNS resolution failed for carrier-api.primary-carrier.com: no such host", _ts(46680), logger="com.shop.fulfillment.client.CarrierBookingClient", trace_id="b6c7d8e9f0a10002b6c7d8e9f0a10002", exception="java.net.UnknownHostException", extra={"host": "carrier-api.primary-carrier.com"}),
            _log("d3-ful-003", "WARN", "fulfillment-service", "Carrier booking failed, switching to secondary carrier", _ts(46690), logger="com.shop.fulfillment.client.CarrierBookingClient", trace_id="b6c7d8e9f0a10001b6c7d8e9f0a10001", extra={"primary": "primary-carrier", "fallback": "secondary-carrier"}),
            _log("d3-ful-004", "INFO", "fulfillment-service", "Shipment booked via primary carrier", _ts(46400), logger="com.shop.fulfillment.client.CarrierBookingClient", trace_id="b6c7d8e9f0a10010b6c7d8e9f0a10010", extra={"carrier": "primary-carrier", "order_id": "ORD-99001"}),
            _log("d3-dns-001", "ERROR", "internal-dns", "Zone transfer failed for primary-carrier.com: upstream authoritative server timeout", _ts(46600), logger="bind9.named", trace_id="b6c7d8e9f0a10001b6c7d8e9f0a10001", extra={"zone": "primary-carrier.com", "authoritative_server": "ns1.primary-carrier.com"}),
            _log("d3-dns-002", "ERROR", "internal-dns", "Cache expired for carrier-api.primary-carrier.com, unable to refresh: SERVFAIL from upstream", _ts(46610), logger="bind9.named", trace_id="b6c7d8e9f0a10002b6c7d8e9f0a10002", extra={"record": "carrier-api.primary-carrier.com", "ttl_expired": "true", "upstream_response": "SERVFAIL"}),
            _log("d3-dns-003", "WARN", "internal-dns", "Stale DNS cache serving expired records for primary-carrier.com, TTL=0", _ts(46590), logger="bind9.named", extra={"zone": "primary-carrier.com", "stale_records": "3"}),
            _log("d3-dns-004", "WARN", "internal-dns", "DNS query rate for primary-carrier.com increased 10x in last 60s", _ts(46650), logger="bind9.named", extra={"zone": "primary-carrier.com", "qps": "1200", "baseline_qps": "120"}),
            _log("d3-noise-016", "INFO", "order-service", "Order ready for fulfillment", _ts(46615), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0066noise0066noise0066noise66", extra={"order_id": "ORD-99101"}),
            _log("d3-noise-017", "INFO", "payment-service", "Payment confirmed", _ts(46610), logger="com.shop.payment.order.PaymentOrderService", trace_id="noise0067noise0067noise0067noise67", extra={"order_id": "ORD-99101"}),
            _log("d3-noise-018", "INFO", "auth-service", "Token issued", _ts(46500), logger="com.shop.auth.AuthService", trace_id="noise0068noise0068noise0068noise68", extra={"user_id": "U-1234"}),
            _log("d3-noise-019", "INFO", "cart-service", "Cart cleared", _ts(46590), logger="com.shop.cart.CartService", trace_id="noise0069noise0069noise0069noise69", extra={"user_id": "U-1234"}),
            _log("d3-noise-020", "WARN", "inventory-service", "Low stock for SKU-7701", _ts(46550), logger="com.shop.inventory.StockService", trace_id="noise0070noise0070noise0070noise70", extra={"sku": "SKU-7701", "qty": "1"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d3-ful-001", "d3-ful-002", "d3-ful-003", "d3-dns-001", "d3-dns-002", "d3-dns-003", "d3-dns-004"),
            root_cause_log_ids=("d3-dns-002",),
            root_cause_service="internal-dns",
            root_cause_summary="内部 DNS 服务器无法从上游权威服务器刷新 primary-carrier.com 的记录，缓存过期后返回 SERVFAIL，fulfillment-service DNS 解析失败导致运单创建中断。",
        ),
    ),
    EvalCase(
        case_id="eval-d3-auth-upstream-idp",
        alert=_alert(
            alertname="AuthJwkRefreshFailureHigh",
            service="auth-service",
            severity="critical",
            summary="JWT 验签失败率持续升高，用户无法完成认证。",
            metric_name="jwt_unknown_kid_rate",
            metric_value="28.4%",
            threshold="> 1% for 3m",
            starts_at=_ts(50400),
        ),
        log_pool=(
            _log("d3-auth-001", "ERROR", "auth-service", "JWK endpoint https://idp.internal/jwks.json unreachable: connection timeout after 5000ms", _ts(50220), logger="com.shop.auth.jwt.JwkKeyProvider", trace_id="c7d8e9f0a1b20001c7d8e9f0a1b20001", exception="com.nimbusds.jose.RemoteKeySourceException", extra={"jwk_url": "https://idp.internal/jwks.json", "timeout_ms": "5000"}),
            _log("d3-auth-002", "ERROR", "auth-service", "JWT verification failed: kid=kid-v4 not in local cache [kid-v3]", _ts(50280), logger="com.shop.auth.jwt.JwtVerifier", trace_id="c7d8e9f0a1b20002c7d8e9f0a1b20002", exception="com.nimbusds.jose.proc.BadJOSEException", extra={"kid": "kid-v4", "cached": "kid-v3"}),
            _log("d3-auth-003", "WARN", "auth-service", "JWK refresh scheduled but IDP unreachable, retrying in 30s", _ts(50240), logger="com.shop.auth.jwt.JwkKeyProvider", trace_id="c7d8e9f0a1b20003c7d8e9f0a1b20003", extra={"retry_in_s": "30", "idp_url": "https://idp.internal"}),
            _log("d3-auth-004", "INFO", "auth-service", "User login successful", _ts(50000), logger="com.shop.auth.AuthService", trace_id="c7d8e9f0a1b20010c7d8e9f0a1b20010", extra={"user_id": "U-7701"}),
            _log("d3-idp-001", "ERROR", "identity-provider", "Database connection pool exhausted: 0/50 connections available", _ts(50200), logger="com.idp.repository.UserRepository", trace_id="c7d8e9f0a1b20001c7d8e9f0a1b20001", exception="java.sql.SQLTransientConnectionException", extra={"pool_size": "50", "available": "0"}),
            _log("d3-idp-002", "ERROR", "identity-provider", "JWKS endpoint handler thread pool exhausted, returning 503 to callers", _ts(50210), logger="com.idp.api.JwksController", trace_id="c7d8e9f0a1b20002c7d8e9f0a1b20002", exception="java.util.concurrent.RejectedExecutionException", extra={"thread_pool": "http-handler", "queue_size": "200"}),
            _log("d3-idp-003", "ERROR", "identity-provider", "Slow query on user_sessions table: 45s full scan, missing index on expires_at", _ts(50100), logger="com.idp.repository.SessionRepository", trace_id="c7d8e9f0a1b20003c7d8e9f0a1b20003", extra={"table": "user_sessions", "duration_s": "45", "missing_index": "expires_at"}),
            _log("d3-idp-004", "WARN", "identity-provider", "Key rotation completed but JWKS cache not invalidated due to handler unavailability", _ts(50190), logger="com.idp.key.KeyRotationJob", extra={"new_kid": "kid-v4", "cache_invalidated": "false"}),
            _log("d3-noise-021", "INFO", "order-service", "Order query completed", _ts(50220), logger="com.shop.order.application.OrderApplicationService", trace_id="noise0071noise0071noise0071noise71", extra={"order_id": "ORD-12201"}),
            _log("d3-noise-022", "INFO", "cart-service", "Cart loaded", _ts(50210), logger="com.shop.cart.CartService", trace_id="noise0072noise0072noise0072noise72", extra={"user_id": "U-8801"}),
            _log("d3-noise-023", "WARN", "inventory-service", "Restock batch started", _ts(50100), logger="com.shop.inventory.batch.RestockJob", trace_id="noise0073noise0073noise0073noise73", extra={"batch_id": "BATCH-0908-C"}),
            _log("d3-noise-024", "INFO", "payment-service", "Refund processed", _ts(50050), logger="com.shop.payment.order.PaymentOrderService", trace_id="noise0074noise0074noise0074noise74", extra={"order_id": "ORD-12180", "amount": "99.00"}),
            _log("d3-noise-025", "INFO", "fulfillment-service", "Shipment in transit", _ts(50000), logger="com.shop.fulfillment.FulfillmentService", trace_id="noise0075noise0075noise0075noise75", extra={"order_id": "ORD-12170"}),
        ),
        ground_truth=EvalGroundTruth(
            relevant_log_ids=("d3-auth-001", "d3-auth-002", "d3-auth-003", "d3-idp-001", "d3-idp-002", "d3-idp-003", "d3-idp-004"),
            root_cause_log_ids=("d3-idp-003",),
            root_cause_service="identity-provider",
            root_cause_summary="identity-provider 的 user_sessions 表缺失 expires_at 索引，慢查询（45s 全表扫描）耗尽数据库连接池，JWKS 接口线程池也因此耗尽，auth-service 无法刷新 JWK 缓存，新 kid 未命中导致验签失败。",
        ),
    ),
)
