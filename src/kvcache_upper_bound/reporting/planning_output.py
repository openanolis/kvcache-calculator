from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .table_common import (
    common_row_payload,
    format_number,
    format_rate,
    lru_column,
    lru_estimated_card_count_column,
    lru_estimated_machine_count_column,
    lru_estimated_total_tps_column,
    lru_tps_gain_column,
    planning_prefix_fieldnames,
    planning_prefix_payload,
    row_range_fieldnames,
    row_range_payload,
    strict_prefix_column,
    strict_prefix_estimated_card_count_column,
    strict_prefix_estimated_machine_count_column,
    strict_prefix_estimated_total_tps_column,
    strict_prefix_proof_column,
    strict_prefix_tps_gain_column,
)

if TYPE_CHECKING:
    from .buckets import BucketReportRow


def strict_prefix_metrics_columns(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
) -> list[str]:
    columns = _base_strict_prefix_metric_columns(include_total_tps=include_total_tps)
    for label in tier_labels:
        columns.extend(
            _tier_strict_prefix_metric_columns(
                label=label,
                include_total_tps=include_total_tps,
            )
        )
    return columns


def strict_prefix_planning_fieldnames(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
) -> list[str]:
    fieldnames = planning_prefix_fieldnames(include_total_tps=include_total_tps)
    fieldnames.extend(["HBM Strict-Prefix 命中率", "HBM Strict-Prefix 求解路径"])
    fieldnames.extend(strict_prefix_metrics_columns(tier_labels=tier_labels, include_total_tps=include_total_tps))
    for label in tier_labels:
        fieldnames.extend([strict_prefix_column(label), strict_prefix_proof_column(label)])
    fieldnames.extend(row_range_fieldnames())
    return fieldnames


def strict_prefix_metrics_payload(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_total_tps: bool,
) -> dict[str, Any]:
    payload = _base_strict_prefix_metric_payload(row=row, include_total_tps=include_total_tps)
    for label in tier_labels:
        payload.update(
            _tier_strict_prefix_metric_payload(
                row=row,
                label=label,
                include_total_tps=include_total_tps,
            )
        )
    return payload


def strict_prefix_planning_payload(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_total_tps: bool,
) -> dict[str, Any]:
    payload = common_row_payload(row=row, include_total_tps=include_total_tps)
    payload.update(planning_prefix_payload(row))
    payload["HBM Strict-Prefix 命中率"] = format_rate(row.hbm_strict_prefix_hit_rate)
    payload["HBM Strict-Prefix 求解路径"] = row.hbm_strict_prefix_proof_source or ""
    payload.update(strict_prefix_metrics_payload(row=row, tier_labels=tier_labels, include_total_tps=include_total_tps))
    for label in tier_labels:
        payload[strict_prefix_column(label)] = format_rate(row.extra_tier_strict_prefix_hit_rates.get(label))
        payload[strict_prefix_proof_column(label)] = row.extra_tier_strict_prefix_proof_sources.get(label) or ""
    payload.update(row_range_payload(row))
    return payload


def lru_planning_fieldnames(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
) -> list[str]:
    fieldnames = planning_prefix_fieldnames(include_total_tps=include_total_tps)
    fieldnames.append("HBM LRU 命中率")
    fieldnames.extend(_base_lru_metric_columns(include_total_tps=include_total_tps))
    for label in tier_labels:
        fieldnames.append(lru_column(label))
        fieldnames.extend(_tier_lru_metric_columns(label=label, include_total_tps=include_total_tps))
    fieldnames.extend(row_range_fieldnames())
    return fieldnames


def lru_planning_payload(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_total_tps: bool,
) -> dict[str, Any]:
    payload = common_row_payload(row=row, include_total_tps=include_total_tps)
    payload.update(planning_prefix_payload(row))
    payload["HBM LRU 命中率"] = format_rate(row.hbm_lru_hit_rate)
    payload.update(_base_lru_metric_payload(row=row, include_total_tps=include_total_tps))
    for label in tier_labels:
        payload[lru_column(label)] = format_rate(row.extra_tier_lru_hit_rates.get(label))
        payload.update(_tier_lru_metric_payload(row=row, label=label, include_total_tps=include_total_tps))
    payload.update(row_range_payload(row))
    return payload


def _base_strict_prefix_metric_columns(*, include_total_tps: bool) -> list[str]:
    columns = [
        "HBM Strict-Prefix TPS Gain",
        "HBM Strict-Prefix 同负载估算卡数",
        "HBM Strict-Prefix 同负载估算机器数",
    ]
    if include_total_tps:
        columns.append("HBM Strict-Prefix 估算总 TPS")
    return columns


def _base_strict_prefix_metric_payload(*, row: BucketReportRow, include_total_tps: bool) -> dict[str, Any]:
    payload = {
        "HBM Strict-Prefix TPS Gain": format_number(row.hbm_strict_prefix_tps_gain),
        "HBM Strict-Prefix 同负载估算卡数": format_number(
            row.hbm_strict_prefix_estimated_card_count_for_same_load
        ),
        "HBM Strict-Prefix 同负载估算机器数": format_number(
            row.hbm_strict_prefix_estimated_machine_count_for_same_load
        ),
    }
    if include_total_tps:
        payload["HBM Strict-Prefix 估算总 TPS"] = format_number(
            row.hbm_strict_prefix_estimated_total_tps
        )
    return payload


def _tier_strict_prefix_metric_columns(*, label: str, include_total_tps: bool) -> list[str]:
    columns = [
        strict_prefix_tps_gain_column(label),
        strict_prefix_estimated_card_count_column(label),
        strict_prefix_estimated_machine_count_column(label),
    ]
    if include_total_tps:
        columns.append(strict_prefix_estimated_total_tps_column(label))
    return columns


def _tier_strict_prefix_metric_payload(
    *,
    row: BucketReportRow,
    label: str,
    include_total_tps: bool,
) -> dict[str, Any]:
    payload = {
        strict_prefix_tps_gain_column(label): format_number(
            row.extra_tier_strict_prefix_tps_gains.get(label)
        ),
        strict_prefix_estimated_card_count_column(label): format_number(
            row.extra_tier_strict_prefix_estimated_card_counts_for_same_load.get(label)
        ),
        strict_prefix_estimated_machine_count_column(label): format_number(
            row.extra_tier_strict_prefix_estimated_machine_counts_for_same_load.get(label)
        ),
    }
    if include_total_tps:
        payload[strict_prefix_estimated_total_tps_column(label)] = format_number(
            row.extra_tier_strict_prefix_estimated_total_tps.get(label)
        )
    return payload


def _base_lru_metric_columns(*, include_total_tps: bool) -> list[str]:
    columns = [
        "HBM LRU TPS Gain",
        "HBM LRU 同负载估算卡数",
        "HBM LRU 同负载估算机器数",
    ]
    if include_total_tps:
        columns.append("HBM LRU 估算总 TPS")
    return columns


def _base_lru_metric_payload(*, row: BucketReportRow, include_total_tps: bool) -> dict[str, Any]:
    payload = {
        "HBM LRU TPS Gain": format_number(row.hbm_lru_tps_gain),
        "HBM LRU 同负载估算卡数": format_number(row.hbm_lru_estimated_card_count_for_same_load),
        "HBM LRU 同负载估算机器数": format_number(
            row.hbm_lru_estimated_machine_count_for_same_load
        ),
    }
    if include_total_tps:
        payload["HBM LRU 估算总 TPS"] = format_number(row.hbm_lru_estimated_total_tps)
    return payload


def _tier_lru_metric_columns(*, label: str, include_total_tps: bool) -> list[str]:
    columns = [
        lru_tps_gain_column(label),
        lru_estimated_card_count_column(label),
        lru_estimated_machine_count_column(label),
    ]
    if include_total_tps:
        columns.append(lru_estimated_total_tps_column(label))
    return columns


def _tier_lru_metric_payload(
    *,
    row: BucketReportRow,
    label: str,
    include_total_tps: bool,
) -> dict[str, Any]:
    payload = {
        lru_tps_gain_column(label): format_number(row.extra_tier_lru_tps_gains.get(label)),
        lru_estimated_card_count_column(label): format_number(
            row.extra_tier_lru_estimated_card_counts_for_same_load.get(label)
        ),
        lru_estimated_machine_count_column(label): format_number(
            row.extra_tier_lru_estimated_machine_counts_for_same_load.get(label)
        ),
    }
    if include_total_tps:
        payload[lru_estimated_total_tps_column(label)] = format_number(
            row.extra_tier_lru_estimated_total_tps.get(label)
        )
    return payload
