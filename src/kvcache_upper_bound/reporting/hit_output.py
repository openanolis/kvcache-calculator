from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .planning_output import strict_prefix_metrics_columns, strict_prefix_metrics_payload
from .table_common import (
    common_row_payload,
    format_rate,
    hit_prefix_fieldnames,
    hit_prefix_payload,
    lru_column,
    relaxed_upper_bound_column,
    row_range_fieldnames,
    row_range_payload,
    strict_prefix_column,
    strict_prefix_proof_column,
    strict_prefix_replay_column,
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
    columns: list[str] = []
    if include_actual_hit_rate:
        columns.append("实际命中率")
    columns.extend(
        [
            "HBM Relaxed Upper Bound 命中率",
            "HBM LRU 命中率",
            "HBM Strict-Prefix Replay 命中率",
            "HBM Strict-Prefix 命中率",
            "HBM Strict-Prefix 求解路径",
        ]
    )
    for label in tier_labels:
        columns.extend(
            [
                strict_prefix_column(label),
                relaxed_upper_bound_column(label),
                lru_column(label),
                strict_prefix_replay_column(label),
                strict_prefix_proof_column(label),
            ]
        )
    return columns


def _hit_payload_columns(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_actual_hit_rate: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if include_actual_hit_rate:
        payload["实际命中率"] = format_rate(row.actual_hit_rate)
    payload["HBM Relaxed Upper Bound 命中率"] = format_rate(row.hbm_relaxed_upper_bound_hit_rate)
    payload["HBM LRU 命中率"] = format_rate(row.hbm_lru_hit_rate)
    payload["HBM Strict-Prefix Replay 命中率"] = format_rate(row.hbm_strict_prefix_replay_hit_rate)
    payload["HBM Strict-Prefix 命中率"] = format_rate(row.hbm_strict_prefix_hit_rate)
    payload["HBM Strict-Prefix 求解路径"] = row.hbm_strict_prefix_proof_source or ""
    for label in tier_labels:
        payload[strict_prefix_column(label)] = format_rate(row.extra_tier_strict_prefix_hit_rates.get(label))
        payload[relaxed_upper_bound_column(label)] = format_rate(
            row.extra_tier_relaxed_upper_bound_hit_rates.get(label)
        )
        payload[lru_column(label)] = format_rate(row.extra_tier_lru_hit_rates.get(label))
        payload[strict_prefix_replay_column(label)] = format_rate(
            row.extra_tier_strict_prefix_replay_hit_rates.get(label)
        )
        payload[strict_prefix_proof_column(label)] = (
            row.extra_tier_strict_prefix_proof_sources.get(label) or ""
        )
    return payload
