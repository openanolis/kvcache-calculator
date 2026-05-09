from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .buckets import BucketReportRow

COMPARISON_EPSILON = 1e-9


def hit_prefix_fieldnames(*, include_total_tps: bool) -> list[str]:
    fieldnames = ["Bucket", "Machines", "Cards", "Cards per Machine", "Spec"]
    if include_total_tps:
        fieldnames.extend(["Total TPS", "Total TPS Input Unit"])
    fieldnames.extend(["HBM KVCache Total (GB)", "Content Upper Bound Hit Rate"])
    return fieldnames


def planning_prefix_fieldnames(
    *,
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> list[str]:
    fieldnames = ["Bucket", "Machines", "Cards", "Cards per Machine", "Spec"]
    if include_total_tps:
        fieldnames.extend(["Total TPS", "Total TPS Input Unit"])
    if include_target_tps_fields:
        fieldnames.extend(["Target Total TPS", "Baseline TPS per Card (No Hit)"])
    fieldnames.extend(["HBM KVCache Total (GB)", "Prefill Savings Alpha"])
    return fieldnames


def row_range_fieldnames() -> list[str]:
    return ["Request Count", "Window Limit", "Input Lower Tokens", "Input Upper Tokens"]


def common_row_payload(*, row: BucketReportRow, include_total_tps: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "Bucket": row.bucket_label,
        "Machines": row.machine_count,
        "Cards": row.card_count,
        "Cards per Machine": row.cards_per_machine,
        "Spec": row.machine_spec,
    }
    if include_total_tps:
        payload["Total TPS"] = row.total_tps if row.total_tps is not None else ""
        payload["Total TPS Input Unit"] = format_text(row.total_tps_input_unit)
    return payload


def hit_prefix_payload(row: BucketReportRow) -> dict[str, Any]:
    return {
        "HBM KVCache Total (GB)": f"{row.hbm_kv_total_gb:.2f}",
        "Content Upper Bound Hit Rate": format_rate(row.extreme_hit_rate),
    }


def planning_prefix_payload(
    row: BucketReportRow,
    *,
    include_target_tps_fields: bool,
) -> dict[str, Any]:
    payload = {
        "HBM KVCache Total (GB)": f"{row.hbm_kv_total_gb:.2f}",
        "Prefill Savings Alpha": format_number(row.prefill_savings_alpha),
    }
    if include_target_tps_fields:
        payload["Target Total TPS"] = format_number(row.planning_target_total_tps)
        payload["Baseline TPS per Card (No Hit)"] = format_number(row.baseline_per_card_tps)
    return payload


def row_range_payload(row: BucketReportRow) -> dict[str, Any]:
    return {
        "Request Count": row.request_count,
        "Window Limit": "" if row.window_tokens is None else row.window_tokens,
        "Input Lower Tokens": row.input_lower_tokens,
        "Input Upper Tokens": "" if row.input_upper_tokens is None else row.input_upper_tokens,
    }


def collect_tier_labels(rows: list[BucketReportRow]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for label in row.extra_tier_strict_prefix_hit_rates:
            if label in seen:
                continue
            seen.add(label)
            labels.append(label)
    return labels


def format_rate(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value * 100:.2f}%"


def format_number(value: float | None) -> str:
    if value is None:
        return ""
    if math.isinf(value):
        return "inf"
    return f"{value:.2f}"


def format_integer(value: int | None) -> str:
    if value is None:
        return ""
    return str(value)


def format_flag(value: bool | None) -> str:
    if value is None:
        return ""
    return "Yes" if value else "No"


def format_delta_pp(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value * 100:+.2f}pp"


def format_text(value: str | None) -> str:
    if value is None:
        return ""
    return value


def strict_prefix_reaches_content_ceiling(
    strict_prefix_hit_rate: float | None,
    content_hit_rate: float | None,
) -> bool | None:
    if strict_prefix_hit_rate is None or content_hit_rate is None:
        return None
    return strict_prefix_hit_rate + COMPARISON_EPSILON >= content_hit_rate


def lru_reaches_strict_prefix(
    lru_hit_rate: float | None,
    strict_prefix_hit_rate: float | None,
) -> bool | None:
    if lru_hit_rate is None or strict_prefix_hit_rate is None:
        return None
    return lru_hit_rate + COMPARISON_EPSILON >= strict_prefix_hit_rate


def bottleneck_label(
    *,
    content_hit_rate: float | None,
    strict_prefix_hit_rate: float | None,
    lru_hit_rate: float | None,
) -> str:
    strict_hits_content = strict_prefix_reaches_content_ceiling(
        strict_prefix_hit_rate,
        content_hit_rate,
    )
    lru_hits_strict = lru_reaches_strict_prefix(
        lru_hit_rate,
        strict_prefix_hit_rate,
    )
    if strict_hits_content is None or lru_hits_strict is None:
        return ""
    if not strict_hits_content:
        return "Capacity"
    if not lru_hits_strict:
        return "Policy"
    return "None"


def rate_delta(
    current_hit_rate: float | None,
    previous_hit_rate: float | None,
) -> float | None:
    if current_hit_rate is None or previous_hit_rate is None:
        return None
    return current_hit_rate - previous_hit_rate


def relaxed_upper_bound_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Relaxed Upper Bound Hit Rate"


def strict_prefix_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix Hit Rate"


def strict_prefix_replay_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix Replay Hit Rate"


def lru_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU Hit Rate"


def strict_prefix_proof_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix Proof Source"


def strict_prefix_tps_gain_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix TPS Gain"


def strict_prefix_estimated_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix Estimated Total TPS"


def strict_prefix_current_cluster_capacity_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix Current Cluster Capacity TPS"


def strict_prefix_min_card_count_for_target_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix Min Cards for Target Total TPS"


def strict_prefix_min_machine_count_for_target_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix Min Machines for Target Total TPS"


def lru_tps_gain_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU TPS Gain"


def lru_estimated_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU Estimated Total TPS"


def lru_current_cluster_capacity_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU Current Cluster Capacity TPS"


def lru_min_card_count_for_target_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU Min Cards for Target Total TPS"


def lru_min_machine_count_for_target_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU Min Machines for Target Total TPS"


def strict_prefix_column_base(label: str) -> str:
    """Strip a trailing English hit-rate suffix from a tier label."""
    suffix = " Hit Rate"
    if label.endswith(suffix):
        return label[: -len(suffix)]
    return label
