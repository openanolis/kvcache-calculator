from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .hit_output import (
    combined_summary_fieldnames,
    combined_summary_payload,
    hit_summary_fieldnames,
    hit_summary_payload,
)
from .planning_output import (
    lru_planning_fieldnames,
    lru_planning_payload,
    strict_prefix_planning_fieldnames,
    strict_prefix_planning_payload,
)
from .table_common import (
    bottleneck_label,
    collect_tier_labels,
    common_row_payload,
    format_delta_pp,
    format_flag,
    format_integer,
    format_number,
    format_rate,
    lru_reaches_strict_prefix,
    row_range_fieldnames,
    row_range_payload,
    strict_prefix_column_base,
    strict_prefix_reaches_content_ceiling,
)

if TYPE_CHECKING:
    from .buckets import BucketAnalysisResult, BucketReportRow


def write_bucket_outputs(result: BucketAnalysisResult, output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    tier_labels = collect_tier_labels(result.rows)

    _write_summary_csv(output_path / "summary.csv", result.rows, tier_labels)
    _write_hit_summary_csv(output_path / "hit_summary.csv", result.rows, tier_labels)
    _write_strict_prefix_planning_csv(
        output_path / "planning_strict_prefix.csv",
        result.rows,
        tier_labels,
    )
    _write_lru_planning_csv(output_path / "planning_lru.csv", result.rows, tier_labels)
    _write_tier_summary_csv(output_path / "tier_summary.csv", result)
    _write_details_json(output_path / "details.json", result)


def _write_summary_csv(
    path: Path,
    rows: list[BucketReportRow],
    tier_labels: list[str],
) -> None:
    include_total_tps = any(row.total_tps is not None for row in rows)
    include_actual_hit_rate = any(row.actual_hit_rate is not None for row in rows)
    _write_csv(
        path,
        combined_summary_fieldnames(
            tier_labels=tier_labels,
            include_total_tps=include_total_tps,
            include_actual_hit_rate=include_actual_hit_rate,
        ),
        [
            combined_summary_payload(
                row=row,
                tier_labels=tier_labels,
                include_total_tps=include_total_tps,
                include_actual_hit_rate=include_actual_hit_rate,
            )
            for row in rows
        ],
    )


def _write_hit_summary_csv(
    path: Path,
    rows: list[BucketReportRow],
    tier_labels: list[str],
) -> None:
    include_total_tps = any(row.total_tps is not None for row in rows)
    include_actual_hit_rate = any(row.actual_hit_rate is not None for row in rows)
    _write_csv(
        path,
        hit_summary_fieldnames(
            tier_labels=tier_labels,
            include_total_tps=include_total_tps,
            include_actual_hit_rate=include_actual_hit_rate,
        ),
        [
            hit_summary_payload(
                row=row,
                tier_labels=tier_labels,
                include_total_tps=include_total_tps,
                include_actual_hit_rate=include_actual_hit_rate,
            )
            for row in rows
        ],
    )


def _write_strict_prefix_planning_csv(
    path: Path,
    rows: list[BucketReportRow],
    tier_labels: list[str],
) -> None:
    include_total_tps = any(row.total_tps is not None for row in rows)
    include_target_tps_fields = any(
        row.planning_target_total_tps is not None and row.baseline_per_card_tps is not None
        for row in rows
    )
    _write_csv(
        path,
        strict_prefix_planning_fieldnames(
            tier_labels=tier_labels,
            include_total_tps=include_total_tps,
            include_target_tps_fields=include_target_tps_fields,
        ),
        [
            strict_prefix_planning_payload(
                row=row,
                tier_labels=tier_labels,
                include_total_tps=include_total_tps,
                include_target_tps_fields=include_target_tps_fields,
            )
            for row in rows
        ],
    )


def _write_lru_planning_csv(
    path: Path,
    rows: list[BucketReportRow],
    tier_labels: list[str],
) -> None:
    include_total_tps = any(row.total_tps is not None for row in rows)
    include_target_tps_fields = any(
        row.planning_target_total_tps is not None and row.baseline_per_card_tps is not None
        for row in rows
    )
    _write_csv(
        path,
        lru_planning_fieldnames(
            tier_labels=tier_labels,
            include_total_tps=include_total_tps,
            include_target_tps_fields=include_target_tps_fields,
        ),
        [
            lru_planning_payload(
                row=row,
                tier_labels=tier_labels,
                include_total_tps=include_total_tps,
                include_target_tps_fields=include_target_tps_fields,
            )
            for row in rows
        ],
    )


def _write_tier_summary_csv(path: Path, result: BucketAnalysisResult) -> None:
    rows = result.rows
    include_total_tps = any(row.total_tps is not None for row in rows)
    include_target_tps_fields = any(
        row.planning_target_total_tps is not None and row.baseline_per_card_tps is not None
        for row in rows
    )
    payloads: list[dict[str, Any]] = []
    for row in rows:
        detail = result.details[row.bucket_label]
        previous_strict_hit_rate: float | None = None
        previous_lru_hit_rate: float | None = None
        payloads.append(
            _tier_summary_payload(
                row=row,
                tier_label="HBM",
                total_kv_gb=row.hbm_kv_total_gb,
                strict_prefix_hit_rate=row.hbm_strict_prefix_hit_rate,
                lru_hit_rate=row.hbm_lru_hit_rate,
                strict_prefix_proof_source=row.hbm_strict_prefix_proof_source,
                strict_prefix_tps_gain=row.hbm_strict_prefix_tps_gain,
                lru_tps_gain=row.hbm_lru_tps_gain,
                strict_prefix_estimated_total_tps=row.hbm_strict_prefix_estimated_total_tps,
                lru_estimated_total_tps=row.hbm_lru_estimated_total_tps,
                strict_prefix_current_cluster_capacity_tps=row.hbm_strict_prefix_current_cluster_capacity_tps,
                strict_prefix_min_card_count=row.hbm_strict_prefix_min_card_count_for_target_total_tps,
                strict_prefix_min_machine_count=row.hbm_strict_prefix_min_machine_count_for_target_total_tps,
                lru_current_cluster_capacity_tps=row.hbm_lru_current_cluster_capacity_tps,
                lru_min_card_count=row.hbm_lru_min_card_count_for_target_total_tps,
                lru_min_machine_count=row.hbm_lru_min_machine_count_for_target_total_tps,
                previous_strict_hit_rate=previous_strict_hit_rate,
                previous_lru_hit_rate=previous_lru_hit_rate,
                include_total_tps=include_total_tps,
                include_target_tps_fields=include_target_tps_fields,
            )
        )
        previous_strict_hit_rate = row.hbm_strict_prefix_hit_rate
        previous_lru_hit_rate = row.hbm_lru_hit_rate
        for tier in detail.config.extra_capacity_tiers:
            tier_label = strict_prefix_column_base(tier.label)
            total_kv_gb = row.hbm_kv_total_gb + row.machine_count * tier.kv_gb_per_machine
            strict_prefix_hit_rate = row.extra_tier_strict_prefix_hit_rates.get(tier.label)
            lru_hit_rate = row.extra_tier_lru_hit_rates.get(tier.label)
            payloads.append(
                _tier_summary_payload(
                    row=row,
                    tier_label=tier_label,
                    total_kv_gb=total_kv_gb,
                    strict_prefix_hit_rate=strict_prefix_hit_rate,
                    lru_hit_rate=lru_hit_rate,
                    strict_prefix_proof_source=row.extra_tier_strict_prefix_proof_sources.get(tier.label),
                    strict_prefix_tps_gain=row.extra_tier_strict_prefix_tps_gains.get(tier.label),
                    lru_tps_gain=row.extra_tier_lru_tps_gains.get(tier.label),
                    strict_prefix_estimated_total_tps=row.extra_tier_strict_prefix_estimated_total_tps.get(
                        tier.label
                    ),
                    lru_estimated_total_tps=row.extra_tier_lru_estimated_total_tps.get(tier.label),
                    strict_prefix_current_cluster_capacity_tps=row.extra_tier_strict_prefix_current_cluster_capacity_tps.get(
                        tier.label
                    ),
                    strict_prefix_min_card_count=row.extra_tier_strict_prefix_min_card_counts_for_target_total_tps.get(
                        tier.label
                    ),
                    strict_prefix_min_machine_count=row.extra_tier_strict_prefix_min_machine_counts_for_target_total_tps.get(
                        tier.label
                    ),
                    lru_current_cluster_capacity_tps=row.extra_tier_lru_current_cluster_capacity_tps.get(
                        tier.label
                    ),
                    lru_min_card_count=row.extra_tier_lru_min_card_counts_for_target_total_tps.get(
                        tier.label
                    ),
                    lru_min_machine_count=row.extra_tier_lru_min_machine_counts_for_target_total_tps.get(
                        tier.label
                    ),
                    previous_strict_hit_rate=previous_strict_hit_rate,
                    previous_lru_hit_rate=previous_lru_hit_rate,
                    include_total_tps=include_total_tps,
                    include_target_tps_fields=include_target_tps_fields,
                )
            )
            previous_strict_hit_rate = strict_prefix_hit_rate
            previous_lru_hit_rate = lru_hit_rate

    _write_csv(
        path,
        _tier_summary_fieldnames(
            include_total_tps=include_total_tps,
            include_target_tps_fields=include_target_tps_fields,
        ),
        payloads,
    )


def _tier_summary_fieldnames(
    *,
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> list[str]:
    fieldnames = ["Bucket", "Capacity Tier", "Machines", "Cards", "Cards per Machine", "Spec"]
    if include_total_tps:
        fieldnames.extend(["Total TPS", "Total TPS Input Unit"])
    if include_target_tps_fields:
        fieldnames.extend(["Target Total TPS", "Baseline TPS per Card (No Hit)"])
    fieldnames.extend(
        [
            "KVCache Total (GB)",
            "Prefill Savings Alpha",
            "Content Upper Bound Hit Rate",
            "Strict-Prefix Hit Rate",
            "LRU Hit Rate",
            "Strict-Prefix Proof Source",
            "Strict-Prefix Reaches Content Upper Bound",
            "LRU Reaches Strict-Prefix",
            "Current Bottleneck",
            "Strict-Prefix Gain vs Previous Tier",
            "LRU Gain vs Previous Tier",
            "Strict-Prefix TPS Gain",
            "LRU TPS Gain",
        ]
    )
    if include_total_tps:
        fieldnames.extend(["Strict-Prefix Estimated Total TPS", "LRU Estimated Total TPS"])
    if include_target_tps_fields:
        fieldnames.extend(
            [
                "Strict-Prefix Current Cluster Capacity TPS",
                "Strict-Prefix Min Cards for Target Total TPS",
                "Strict-Prefix Min Machines for Target Total TPS",
                "LRU Current Cluster Capacity TPS",
                "LRU Min Cards for Target Total TPS",
                "LRU Min Machines for Target Total TPS",
            ]
        )
    fieldnames.extend(row_range_fieldnames())
    return fieldnames


def _tier_summary_payload(
    *,
    row: BucketReportRow,
    tier_label: str,
    total_kv_gb: float,
    strict_prefix_hit_rate: float | None,
    lru_hit_rate: float | None,
    strict_prefix_proof_source: str | None,
    strict_prefix_tps_gain: float | None,
    lru_tps_gain: float | None,
    strict_prefix_estimated_total_tps: float | None,
    lru_estimated_total_tps: float | None,
    strict_prefix_current_cluster_capacity_tps: float | None,
    strict_prefix_min_card_count: int | None,
    strict_prefix_min_machine_count: int | None,
    lru_current_cluster_capacity_tps: float | None,
    lru_min_card_count: int | None,
    lru_min_machine_count: int | None,
    previous_strict_hit_rate: float | None,
    previous_lru_hit_rate: float | None,
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> dict[str, Any]:
    payload = common_row_payload(row=row, include_total_tps=include_total_tps)
    payload["Capacity Tier"] = tier_label
    if include_target_tps_fields:
        payload["Target Total TPS"] = format_number(row.planning_target_total_tps)
        payload["Baseline TPS per Card (No Hit)"] = format_number(row.baseline_per_card_tps)
    payload["KVCache Total (GB)"] = f"{total_kv_gb:.2f}"
    payload["Prefill Savings Alpha"] = format_number(row.prefill_savings_alpha)
    payload["Content Upper Bound Hit Rate"] = format_rate(row.extreme_hit_rate)
    payload["Strict-Prefix Hit Rate"] = format_rate(strict_prefix_hit_rate)
    payload["LRU Hit Rate"] = format_rate(lru_hit_rate)
    payload["Strict-Prefix Proof Source"] = strict_prefix_proof_source or ""
    payload["Strict-Prefix Reaches Content Upper Bound"] = format_flag(
        strict_prefix_reaches_content_ceiling(
            strict_prefix_hit_rate,
            row.extreme_hit_rate,
        )
    )
    payload["LRU Reaches Strict-Prefix"] = format_flag(
        lru_reaches_strict_prefix(
            lru_hit_rate,
            strict_prefix_hit_rate,
        )
    )
    payload["Current Bottleneck"] = bottleneck_label(
        content_hit_rate=row.extreme_hit_rate,
        strict_prefix_hit_rate=strict_prefix_hit_rate,
        lru_hit_rate=lru_hit_rate,
    )
    payload["Strict-Prefix Gain vs Previous Tier"] = format_delta_pp(
        strict_prefix_hit_rate - previous_strict_hit_rate
        if strict_prefix_hit_rate is not None and previous_strict_hit_rate is not None
        else None
    )
    payload["LRU Gain vs Previous Tier"] = format_delta_pp(
        lru_hit_rate - previous_lru_hit_rate
        if lru_hit_rate is not None and previous_lru_hit_rate is not None
        else None
    )
    payload["Strict-Prefix TPS Gain"] = format_number(strict_prefix_tps_gain)
    payload["LRU TPS Gain"] = format_number(lru_tps_gain)
    if include_total_tps:
        payload["Strict-Prefix Estimated Total TPS"] = format_number(strict_prefix_estimated_total_tps)
        payload["LRU Estimated Total TPS"] = format_number(lru_estimated_total_tps)
    if include_target_tps_fields:
        payload["Strict-Prefix Current Cluster Capacity TPS"] = format_number(
            strict_prefix_current_cluster_capacity_tps
        )
        payload["Strict-Prefix Min Cards for Target Total TPS"] = format_integer(strict_prefix_min_card_count)
        payload["Strict-Prefix Min Machines for Target Total TPS"] = format_integer(
            strict_prefix_min_machine_count
        )
        payload["LRU Current Cluster Capacity TPS"] = format_number(lru_current_cluster_capacity_tps)
        payload["LRU Min Cards for Target Total TPS"] = format_integer(lru_min_card_count)
        payload["LRU Min Machines for Target Total TPS"] = format_integer(lru_min_machine_count)
    payload.update(row_range_payload(row))
    return payload


def _write_details_json(path: Path, result: BucketAnalysisResult) -> None:
    serializable = {
        "rows": [asdict(row) for row in result.rows],
        "details": {
            label: {
                "config": asdict(detail.config),
                "content_summary": asdict(detail.content_result.summary),
                "hbm_capacity_summary": asdict(detail.hbm_capacity_result.summary),
                "hbm_lru_summary": asdict(detail.hbm_lru_result.summary),
                "hbm_strict_prefix_summary": asdict(detail.hbm_strict_prefix_result.summary),
                "extra_capacity_summaries": {
                    tier_label: asdict(tier_result.summary)
                    for tier_label, tier_result in detail.extra_capacity_results.items()
                },
                "extra_lru_summaries": {
                    tier_label: asdict(tier_result.summary)
                    for tier_label, tier_result in detail.extra_lru_results.items()
                },
                "extra_strict_prefix_summaries": {
                    tier_label: asdict(tier_result.summary)
                    for tier_label, tier_result in detail.extra_strict_prefix_results.items()
                },
            }
            for label, detail in result.details.items()
        },
    }
    path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], payloads: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(payloads)
