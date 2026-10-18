"""第一层 Query 改动的评测 runner。

模拟 _generic_search_log_step 的第一层过滤逻辑：
  Query = service:{alert.labels.service}
  From  = startsAt - 10min
  To    = startsAt + 5min
  Limit = 50

对每个 EvalCase 的 log_pool 做过滤，计算 Recall 和 Precision，
结果写入 eval_results/layer1_service_time_window.json。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from super_ai.aiops.eval_fixtures import EVAL_CASES, EvalCase

_RESULT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "eval_results")
_RESULT_FILE = os.path.join(_RESULT_DIR, "layer1_service_time_window.json")

_TIME_WINDOW_BEFORE = timedelta(minutes=10)
_TIME_WINDOW_AFTER = timedelta(minutes=5)
_LIMIT = 50


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _simulate_layer1_query(case: EvalCase) -> list[str]:
    alert = case.alert
    alert_service: str = str(alert.get("labels", {}).get("service", ""))  # type: ignore[union-attr]
    starts_at_raw: str = str(alert.get("startsAt", ""))

    try:
        starts_at = _parse_ts(starts_at_raw)
    except ValueError:
        starts_at = datetime.now(tz=timezone.utc)

    from_dt = starts_at - _TIME_WINDOW_BEFORE
    to_dt = starts_at + _TIME_WINDOW_AFTER

    matched: list[dict[str, str]] = []
    for log in case.log_pool:
        if alert_service and log.get("service") != alert_service:
            continue
        try:
            log_ts = _parse_ts(log["timestamp"])
        except (KeyError, ValueError):
            continue
        if from_dt <= log_ts <= to_dt:
            matched.append(log)

    matched.sort(key=lambda l: l["timestamp"], reverse=True)
    return [l["log_id"] for l in matched[:_LIMIT]]


def _compute_metrics(
    retrieved: list[str],
    relevant_ids: tuple[str, ...],
    root_cause_ids: tuple[str, ...],
) -> dict[str, Any]:
    retrieved_set = set(retrieved)
    relevant_set = set(relevant_ids)
    root_cause_set = set(root_cause_ids)

    relevant_hit = retrieved_set & relevant_set
    root_cause_hit = retrieved_set & root_cause_set

    recall_relevant = len(relevant_hit) / len(relevant_set) if relevant_set else 0.0
    recall_root_cause = len(root_cause_hit) / len(root_cause_set) if root_cause_set else 0.0
    precision = len(relevant_hit) / len(retrieved_set) if retrieved_set else 0.0

    return {
        "recall_relevant": round(recall_relevant, 4),
        "recall_root_cause": round(recall_root_cause, 4),
        "precision": round(precision, 4),
        "retrieved_count": len(retrieved),
        "relevant_hit_count": len(relevant_hit),
        "root_cause_hit_count": len(root_cause_hit),
        "relevant_total": len(relevant_set),
        "root_cause_total": len(root_cause_set),
        "missed_relevant_ids": sorted(relevant_set - retrieved_set),
        "missed_root_cause_ids": sorted(root_cause_set - retrieved_set),
    }


def run_eval() -> dict[str, Any]:
    per_case: list[dict[str, Any]] = []

    difficulty_buckets: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: []}

    for case in EVAL_CASES:
        difficulty = int(case.case_id.split("-")[1][1])
        retrieved = _simulate_layer1_query(case)
        metrics = _compute_metrics(
            retrieved,
            case.ground_truth.relevant_log_ids,
            case.ground_truth.root_cause_log_ids,
        )
        case_result: dict[str, Any] = {
            "case_id": case.case_id,
            "difficulty": difficulty,
            "alert_service": str(case.alert.get("labels", {}).get("service", "")),  # type: ignore[union-attr]
            "root_cause_service": case.ground_truth.root_cause_service,
            "retrieved_log_ids": retrieved,
            **metrics,
        }
        per_case.append(case_result)
        difficulty_buckets[difficulty].append(case_result)

    def _avg(cases: list[dict[str, Any]], key: str) -> float:
        if not cases:
            return 0.0
        return round(sum(c[key] for c in cases) / len(cases), 4)

    summary: dict[str, Any] = {
        "overall_recall_relevant": _avg(per_case, "recall_relevant"),
        "overall_recall_root_cause": _avg(per_case, "recall_root_cause"),
        "overall_precision": _avg(per_case, "precision"),
        "total_cases": len(per_case),
    }
    for d in [1, 2, 3]:
        bucket = difficulty_buckets[d]
        summary[f"d{d}_recall_relevant"] = _avg(bucket, "recall_relevant")
        summary[f"d{d}_recall_root_cause"] = _avg(bucket, "recall_root_cause")
        summary[f"d{d}_precision"] = _avg(bucket, "precision")
        summary[f"d{d}_cases"] = len(bucket)

    result: dict[str, Any] = {
        "run_id": "layer1_service_time_window",
        "description": "第一层：service+时间窗口替换Query=*，Limit=50，时间窗口 startsAt-10min ~ startsAt+5min",
        "config": {
            "query_type": "service:{alert_service}",
            "time_window_before_min": 10,
            "time_window_after_min": 5,
            "limit": _LIMIT,
        },
        "summary": summary,
        "per_case": per_case,
    }
    return result


def main() -> None:
    result = run_eval()
    os.makedirs(_RESULT_DIR, exist_ok=True)
    with open(_RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"评测完成，结果写入: {_RESULT_FILE}")
    s = result["summary"]
    print(f"\n=== 评测摘要 ===")
    print(f"总 case 数: {s['total_cases']}")
    print(f"整体 Recall(relevant): {s['overall_recall_relevant']}")
    print(f"整体 Recall(root_cause): {s['overall_recall_root_cause']}")
    print(f"整体 Precision: {s['overall_precision']}")
    for d in [1, 2, 3]:
        print(f"\n难度{d} ({s[f'd{d}_cases']} cases):")
        print(f"  Recall(relevant):   {s[f'd{d}_recall_relevant']}")
        print(f"  Recall(root_cause): {s[f'd{d}_recall_root_cause']}")
        print(f"  Precision:          {s[f'd{d}_precision']}")


if __name__ == "__main__":
    main()
