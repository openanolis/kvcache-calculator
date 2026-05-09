from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .planning_output import strict_prefix_metrics_columns, strict_prefix_metrics_payload
from .table_common import (
    bottleneck_label,
    common_row_payload,
    format_flag,
    format_rate,
    hit_prefix_fieldnames,
    hit_prefix_payload,
    row_range_fieldnames,
    row_range_payload,
    lru_reaches_strict_prefix,
    strict_prefix_reaches_content_ceiling,
)

if TYPE_CHECKING:
    from .buckets import BucketReportRow


def combined_summary_fieldnames(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
    include_actual_hit_rate: bool,
) -> list[str]:
    fieldnames = hit_summary_fieldnames(
        tier_labels=tier_labels,
        include_total_tps=include_total_tps,
        include_actual_hit_rate=include_actual_hit_rate,
    )
    insert_at = len(fieldnames) - len(row_range_fieldnames())
    fieldnames[insert_at:insert_at] = strict_prefix_metrics_columns(
        tier_labels=tier_labels,
        include_total_tps=include_total_tps,
    )
    return fieldnames


def combined_summary_payload(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_total_tps: bool,
    include_actual_hit_rate: bool,
) -> dict[str, Any]:
    payload = hit_summary_payload(
        row=row,
        tier_labels=tier_labels,
        include_total_tps=include_total_tps,
        include_actual_hit_rate=include_actual_hit_rate,
    )
    payload.update(
        strict_prefix_metrics_payload(
            row=row,
            tier_labels=tier_labels,
            include_total_tps=include_total_tps,
        )
    )
    return payload


def hit_summary_fieldnames(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
    include_actual_hit_rate: bool,
) -> list[str]:
    fieldnames = hit_prefix_fieldnames(include_total_tps=include_total_tps)
    fieldnames.extend(_hit_columns(tier_labels=tier_labels, include_actual_hit_rate=include_actual_hit_rate))
    fieldnames.extend(row_range_fieldnames())
    return fieldnames


def hit_summary_payload(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_total_tps: bool,
    include_actual_hit_rate: bool,
) -> dict[str, Any]:
    payload = common_row_payload(row=row, include_total_tps=include_total_tps)
    payload.update(hit_prefix_payload(row))
    payload.update(
        _hit_payload_columns(
            row=row,
            tier_labels=tier_labels,
            include_actual_hit_rate=include_actual_hit_rate,
        )
    )
    payload.update(row_range_payload(row))
    return payload


def _hit_columns(*, tier_labels: list[str], include_actual_hit_rate: bool) -> list[str]:
    _ = tier_labels
    columns: list[str] = []
    if include_actual_hit_rate:
        columns.append("Actual Hit Rate")
    columns.extend(
        [
            "HBM Relaxed Upper Bound Hit Rate",
            "HBM LRU Hit Rate",
            "HBM Strict-Prefix Replay Hit Rate",
            "HBM Strict-Prefix Hit Rate",
            "HBM Strict-Prefix Proof Source",
            "HBM Strict-Prefix Reaches Content Upper Bound",
            "HBM LRU Reaches Strict-Prefix",
            "HBM Current Bottleneck",
        ]
    )
    return columns


def _hit_payload_columns(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_actual_hit_rate: bool,
) -> dict[str, Any]:
    _ = tier_labels
    payload: dict[str, Any] = {}
    if include_actual_hit_rate:
        payload["Actual Hit Rate"] = format_rate(row.actual_hit_rate)
    payload["HBM Relaxed Upper Bound Hit Rate"] = format_rate(row.hbm_relaxed_upper_bound_hit_rate)
    payload["HBM LRU Hit Rate"] = format_rate(row.hbm_lru_hit_rate)
    payload["HBM Strict-Prefix Replay Hit Rate"] = format_rate(row.hbm_strict_prefix_replay_hit_rate)
    payload["HBM Strict-Prefix Hit Rate"] = format_rate(row.hbm_strict_prefix_hit_rate)
    payload["HBM Strict-Prefix Proof Source"] = row.hbm_strict_prefix_proof_source or ""
    payload["HBM Strict-Prefix Reaches Content Upper Bound"] = format_flag(
        strict_prefix_reaches_content_ceiling(
            row.hbm_strict_prefix_hit_rate,
            row.extreme_hit_rate,
        )
    )
    payload["HBM LRU Reaches Strict-Prefix"] = format_flag(
        lru_reaches_strict_prefix(
            row.hbm_lru_hit_rate,
            row.hbm_strict_prefix_hit_rate,
        )
    )
    payload["HBM Current Bottleneck"] = bottleneck_label(
        content_hit_rate=row.extreme_hit_rate,
        strict_prefix_hit_rate=row.hbm_strict_prefix_hit_rate,
        lru_hit_rate=row.hbm_lru_hit_rate,
    )
    return payload
