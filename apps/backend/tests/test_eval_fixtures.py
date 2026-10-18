from __future__ import annotations

from super_ai.aiops.eval_fixtures import EVAL_CASES, EvalCase

_DIFFICULTY_ONE_IDS = {
    "eval-d1-order-db-pool",
    "eval-d1-payment-gateway-timeout",
    "eval-d1-auth-jwk-refresh",
    "eval-d1-kafka-consumer-lag",
    "eval-d1-es-search-timeout",
    "eval-d1-fulfillment-503",
}

_DIFFICULTY_TWO_IDS = {
    "eval-d2-redis-latency",
    "eval-d2-inventory-lock-wait",
    "eval-d2-promotion-cpu",
    "eval-d2-search-slow-warmup",
}

_DIFFICULTY_THREE_IDS = {
    "eval-d3-gateway-inventory",
    "eval-d3-order-payment-mysql",
    "eval-d3-payment-upstream-fraud",
    "eval-d3-fulfillment-carrier-dns",
    "eval-d3-auth-upstream-idp",
}


def test_eval_cases_total_count() -> None:
    assert len(EVAL_CASES) == 15


def test_eval_case_ids_are_unique() -> None:
    ids = [c.case_id for c in EVAL_CASES]
    assert len(ids) == len(set(ids))


def test_eval_cases_cover_all_three_difficulties() -> None:
    ids = {c.case_id for c in EVAL_CASES}
    assert _DIFFICULTY_ONE_IDS.issubset(ids)
    assert _DIFFICULTY_TWO_IDS.issubset(ids)
    assert _DIFFICULTY_THREE_IDS.issubset(ids)


def test_alert_has_no_trace_id_or_sop() -> None:
    for case in EVAL_CASES:
        labels = case.alert.get("labels", {})
        annotations = case.alert.get("annotations", {})
        assert "trace_id" not in labels, f"{case.case_id}: trace_id in labels"
        assert "trace_id" not in annotations, f"{case.case_id}: trace_id in annotations"
        assert "sop" not in labels, f"{case.case_id}: sop in labels"
        assert "sop" not in annotations, f"{case.case_id}: sop in annotations"


def test_alert_has_required_label_fields() -> None:
    required_label_fields = {"alertname", "service", "severity", "environment"}
    for case in EVAL_CASES:
        labels = case.alert.get("labels", {})
        for field in required_label_fields:
            assert field in labels, f"{case.case_id}: missing label field '{field}'"


def test_alert_severity_is_valid() -> None:
    valid = {"critical", "warning"}
    for case in EVAL_CASES:
        severity = case.alert["labels"]["severity"]  # type: ignore[index]
        assert severity in valid, f"{case.case_id}: invalid severity '{severity}'"


def test_difficulty_two_alerts_are_warning_severity() -> None:
    for case in EVAL_CASES:
        if case.case_id in _DIFFICULTY_TWO_IDS:
            severity = case.alert["labels"]["severity"]  # type: ignore[index]
            assert severity == "warning", f"{case.case_id}: expected warning severity"


def test_log_pool_log_ids_are_unique_within_case() -> None:
    for case in EVAL_CASES:
        log_ids = [log["log_id"] for log in case.log_pool]
        assert len(log_ids) == len(set(log_ids)), f"{case.case_id}: duplicate log_ids"


def test_log_pool_log_ids_are_unique_globally() -> None:
    all_ids: list[str] = []
    for case in EVAL_CASES:
        all_ids.extend(log["log_id"] for log in case.log_pool)
    assert len(all_ids) == len(set(all_ids)), "Duplicate log_ids across cases"


def test_log_pool_minimum_size() -> None:
    for case in EVAL_CASES:
        assert len(case.log_pool) >= 10, f"{case.case_id}: log_pool has fewer than 10 entries"


def test_ground_truth_relevant_ids_exist_in_log_pool() -> None:
    for case in EVAL_CASES:
        pool_ids = {log["log_id"] for log in case.log_pool}
        for log_id in case.ground_truth.relevant_log_ids:
            assert log_id in pool_ids, f"{case.case_id}: relevant_log_id '{log_id}' not in log_pool"


def test_ground_truth_root_cause_ids_are_subset_of_relevant() -> None:
    for case in EVAL_CASES:
        relevant = set(case.ground_truth.relevant_log_ids)
        for log_id in case.ground_truth.root_cause_log_ids:
            assert log_id in relevant, (
                f"{case.case_id}: root_cause_log_id '{log_id}' not in relevant_log_ids"
            )


def test_ground_truth_has_nonempty_fields() -> None:
    for case in EVAL_CASES:
        gt = case.ground_truth
        assert gt.relevant_log_ids, f"{case.case_id}: relevant_log_ids is empty"
        assert gt.root_cause_log_ids, f"{case.case_id}: root_cause_log_ids is empty"
        assert gt.root_cause_service, f"{case.case_id}: root_cause_service is empty"
        assert gt.root_cause_summary, f"{case.case_id}: root_cause_summary is empty"


def test_noise_logs_exist_in_every_case() -> None:
    for case in EVAL_CASES:
        relevant = set(case.ground_truth.relevant_log_ids)
        noise_logs = [log for log in case.log_pool if log["log_id"] not in relevant]
        assert len(noise_logs) >= 3, f"{case.case_id}: fewer than 3 noise logs"


def test_difficulty_three_root_cause_service_differs_from_alert_service() -> None:
    for case in EVAL_CASES:
        if case.case_id in _DIFFICULTY_THREE_IDS:
            alert_service = case.alert["labels"]["service"]  # type: ignore[index]
            root_cause_service = case.ground_truth.root_cause_service
            assert alert_service != root_cause_service, (
                f"{case.case_id}: root_cause_service should differ from alert service for difficulty-3 cases"
            )


def test_difficulty_three_root_cause_logs_belong_to_upstream_service() -> None:
    for case in EVAL_CASES:
        if case.case_id in _DIFFICULTY_THREE_IDS:
            alert_service = case.alert["labels"]["service"]  # type: ignore[index]
            pool_by_id = {log["log_id"]: log for log in case.log_pool}
            for log_id in case.ground_truth.root_cause_log_ids:
                log = pool_by_id[log_id]
                assert log["service"] != alert_service, (
                    f"{case.case_id}: root cause log '{log_id}' belongs to alert service, expected upstream"
                )


def test_difficulty_three_shared_trace_id_links_alert_service_to_upstream() -> None:
    for case in EVAL_CASES:
        if case.case_id not in _DIFFICULTY_THREE_IDS:
            continue
        alert_service = case.alert["labels"]["service"]  # type: ignore[index]
        root_cause_service = case.ground_truth.root_cause_service
        alert_service_trace_ids = {
            log["trace_id"]
            for log in case.log_pool
            if log.get("service") == alert_service and log.get("trace_id")
        }
        upstream_trace_ids = {
            log["trace_id"]
            for log in case.log_pool
            if log.get("service") == root_cause_service and log.get("trace_id")
        }
        shared = alert_service_trace_ids & upstream_trace_ids
        assert shared, (
            f"{case.case_id}: no shared trace_id between alert service '{alert_service}' "
            f"and root cause service '{root_cause_service}'"
        )


def test_no_credentials_in_generated_data() -> None:
    banned = ("secretid", "secretkey", "sk-", "bearer ", "password=", "token=")
    for case in EVAL_CASES:
        serialized = " ".join(
            " ".join(str(v) for v in log.values()) for log in case.log_pool
        ).lower()
        for keyword in banned:
            assert keyword not in serialized, (
                f"{case.case_id}: found banned keyword '{keyword}' in log_pool"
            )
