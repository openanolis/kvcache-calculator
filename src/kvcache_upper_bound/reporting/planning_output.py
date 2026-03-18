from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .table_common import (
    common_row_payload,
    format_integer,
    format_number,
    format_rate,
    planning_prefix_fieldnames,
    planning_prefix_payload,
    row_range_fieldnames,
    row_range_payload,
)

if TYPE_CHECKING:
    from .buckets import BucketReportRow


def strict_prefix_metrics_columns(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
) -> list[str]:
    _ = tier_labels
    return _base_strict_prefix_metric_columns(include_total_tps=include_total_tps)


def strict_prefix_planning_fieldnames(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> list[str]:
    fieldnames = planning_prefix_fieldnames(
        include_total_tps=include_total_tps,
        include_target_tps_fields=include_target_tps_fields,
    )
    fieldnames.extend(["HBM Strict-Prefix 命中率", "HBM Strict-Prefix 求解路径"])
    fieldnames.extend(
        strict_prefix_metrics_columns(
            tier_labels=tier_labels,
            include_total_tps=include_total_tps,
        )
    )
    if include_target_tps_fields:
        fieldnames.extend(_base_strict_prefix_target_metric_columns())
    fieldnames.extend(row_range_fieldnames())
    return fieldnames


def strict_prefix_metrics_payload(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_total_tps: bool,
) -> dict[str, Any]:
    _ = tier_labels
    return _base_strict_prefix_metric_payload(row=row, include_total_tps=include_total_tps)


def strict_prefix_planning_payload(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> dict[str, Any]:
    payload = common_row_payload(row=row, include_total_tps=include_total_tps)
    payload.update(
        planning_prefix_payload(
            row,
            include_target_tps_fields=include_target_tps_fields,
        )
    )
    payload["HBM Strict-Prefix 命中率"] = format_rate(row.hbm_strict_prefix_hit_rate)
    payload["HBM Strict-Prefix 求解路径"] = row.hbm_strict_prefix_proof_source or ""
    payload.update(
        strict_prefix_metrics_payload(
            row=row,
            tier_labels=tier_labels,
            include_total_tps=include_total_tps,
        )
    )
    if include_target_tps_fields:
        payload.update(_base_strict_prefix_target_metric_payload(row=row))
    payload.update(row_range_payload(row))
    return payload


def lru_planning_fieldnames(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> list[str]:
    _ = tier_labels
    fieldnames = planning_prefix_fieldnames(
        include_total_tps=include_total_tps,
        include_target_tps_fields=include_target_tps_fields,
    )
    fieldnames.append("HBM LRU 命中率")
    fieldnames.extend(_base_lru_metric_columns(include_total_tps=include_total_tps))
    if include_target_tps_fields:
        fieldnames.extend(_base_lru_target_metric_columns())
    fieldnames.extend(row_range_fieldnames())
    return fieldnames


def lru_planning_payload(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> dict[str, Any]:
    _ = tier_labels
    payload = common_row_payload(row=row, include_total_tps=include_total_tps)
    payload.update(
        planning_prefix_payload(
            row,
            include_target_tps_fields=include_target_tps_fields,
        )
    )
    payload["HBM LRU 命中率"] = format_rate(row.hbm_lru_hit_rate)
    payload.update(_base_lru_metric_payload(row=row, include_total_tps=include_total_tps))
    if include_target_tps_fields:
        payload.update(_base_lru_target_metric_payload(row=row))
    payload.update(row_range_payload(row))
    return payload


def _base_strict_prefix_metric_columns(*, include_total_tps: bool) -> list[str]:
    columns = ["HBM Strict-Prefix TPS Gain"]
    if include_total_tps:
        columns.append("HBM Strict-Prefix 估算总 TPS")
    return columns


def _base_strict_prefix_metric_payload(*, row: BucketReportRow, include_total_tps: bool) -> dict[str, Any]:
    payload = {"HBM Strict-Prefix TPS Gain": format_number(row.hbm_strict_prefix_tps_gain)}
    if include_total_tps:
        payload["HBM Strict-Prefix 估算总 TPS"] = format_number(
            row.hbm_strict_prefix_estimated_total_tps
        )
    return payload


def _base_strict_prefix_target_metric_columns() -> list[str]:
    return [
        "HBM Strict-Prefix 当前配置可承载总 TPS",
        "HBM Strict-Prefix 目标总 TPS 最小卡数",
        "HBM Strict-Prefix 目标总 TPS 最小机器数",
    ]


def _base_strict_prefix_target_metric_payload(*, row: BucketReportRow) -> dict[str, Any]:
    return {
        "HBM Strict-Prefix 当前配置可承载总 TPS": format_number(
            row.hbm_strict_prefix_current_cluster_capacity_tps
        ),
        "HBM Strict-Prefix 目标总 TPS 最小卡数": format_integer(
            row.hbm_strict_prefix_min_card_count_for_target_total_tps
        ),
        "HBM Strict-Prefix 目标总 TPS 最小机器数": format_integer(
            row.hbm_strict_prefix_min_machine_count_for_target_total_tps
        ),
    }


def _base_lru_metric_columns(*, include_total_tps: bool) -> list[str]:
    columns = ["HBM LRU TPS Gain"]
    if include_total_tps:
        columns.append("HBM LRU 估算总 TPS")
    return columns


def _base_lru_metric_payload(*, row: BucketReportRow, include_total_tps: bool) -> dict[str, Any]:
    payload = {"HBM LRU TPS Gain": format_number(row.hbm_lru_tps_gain)}
    if include_total_tps:
        payload["HBM LRU 估算总 TPS"] = format_number(row.hbm_lru_estimated_total_tps)
    return payload


def _base_lru_target_metric_columns() -> list[str]:
    return [
        "HBM LRU 当前配置可承载总 TPS",
        "HBM LRU 目标总 TPS 最小卡数",
        "HBM LRU 目标总 TPS 最小机器数",
    ]


def _base_lru_target_metric_payload(*, row: BucketReportRow) -> dict[str, Any]:
    return {
        "HBM LRU 当前配置可承载总 TPS": format_number(row.hbm_lru_current_cluster_capacity_tps),
        "HBM LRU 目标总 TPS 最小卡数": format_integer(
            row.hbm_lru_min_card_count_for_target_total_tps
        ),
        "HBM LRU 目标总 TPS 最小机器数": format_integer(
            row.hbm_lru_min_machine_count_for_target_total_tps
        ),
    }
