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
from .table_common import collect_tier_labels

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
