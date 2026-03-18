from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .buckets import BucketAnalysisResult, BucketReportRow


def write_bucket_outputs(result: BucketAnalysisResult, output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    summary_csv_path = output_path / "summary.csv"
    hit_summary_csv_path = output_path / "hit_summary.csv"
    planning_summary_csv_path = output_path / "planning_summary.csv"
    details_json_path = output_path / "details.json"

    tier_labels = _collect_tier_labels(result.rows)
    _write_summary_csv(summary_csv_path, result.rows, tier_labels)
    _write_hit_summary_csv(hit_summary_csv_path, result.rows, tier_labels)
    _write_planning_summary_csv(planning_summary_csv_path, result.rows, tier_labels)
    _write_details_json(details_json_path, result)


def _write_summary_csv(
    path: Path,
    rows: list[BucketReportRow],
    tier_labels: list[str],
) -> None:
    include_total_tps = any(row.total_tps is not None for row in rows)
    include_actual_hit_rate = any(row.actual_hit_rate is not None for row in rows)

    fieldnames = _combined_summary_fieldnames(
        tier_labels=tier_labels,
        include_total_tps=include_total_tps,
        include_actual_hit_rate=include_actual_hit_rate,
    )
    payloads = [
        _combined_summary_payload(
            row=row,
            tier_labels=tier_labels,
            include_total_tps=include_total_tps,
            include_actual_hit_rate=include_actual_hit_rate,
        )
        for row in rows
    ]
    _write_csv(path, fieldnames, payloads)


def _write_hit_summary_csv(
    path: Path,
    rows: list[BucketReportRow],
    tier_labels: list[str],
) -> None:
    include_total_tps = any(row.total_tps is not None for row in rows)
    include_actual_hit_rate = any(row.actual_hit_rate is not None for row in rows)
    fieldnames = _hit_summary_fieldnames(
        tier_labels=tier_labels,
        include_total_tps=include_total_tps,
        include_actual_hit_rate=include_actual_hit_rate,
    )
    payloads = [
        _hit_summary_payload(
            row=row,
            tier_labels=tier_labels,
            include_total_tps=include_total_tps,
            include_actual_hit_rate=include_actual_hit_rate,
        )
        for row in rows
    ]
    _write_csv(path, fieldnames, payloads)


def _write_planning_summary_csv(
    path: Path,
    rows: list[BucketReportRow],
    tier_labels: list[str],
) -> None:
    include_total_tps = any(row.total_tps is not None for row in rows)
    fieldnames = _planning_summary_fieldnames(
        tier_labels=tier_labels,
        include_total_tps=include_total_tps,
    )
    payloads = [
        _planning_summary_payload(
            row=row,
            tier_labels=tier_labels,
            include_total_tps=include_total_tps,
        )
        for row in rows
    ]
    _write_csv(path, fieldnames, payloads)


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
    path.write_text(
        json.dumps(serializable, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_csv(path: Path, fieldnames: list[str], payloads: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(payloads)


def _combined_summary_fieldnames(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
    include_actual_hit_rate: bool,
) -> list[str]:
    fieldnames = ["分桶", "机器数", "卡数", "单机卡数", "规格"]
    if include_total_tps:
        fieldnames.append("总 TPS")
        fieldnames.append("TPS 输入口径")
    fieldnames.extend(
        [
            "HBM KVCache 总大小 (GB)",
            "极限命中率",
        ]
    )
    if include_actual_hit_rate:
        fieldnames.append("实际命中率")
    fieldnames.extend(
        [
            "HBM Relaxed Upper Bound 命中率",
            "HBM LRU 命中率",
            "HBM Strict-Prefix Replay 命中率",
            "HBM Strict-Prefix 命中率",
            "HBM Strict-Prefix 求解路径",
        ]
    )
    fieldnames.extend(_base_planning_metric_fieldnames(include_total_tps=include_total_tps))
    for label in tier_labels:
        fieldnames.extend(
            [
                label,
                _relaxed_upper_bound_column(label),
                _lru_column(label),
                _strict_prefix_replay_column(label),
                _strict_prefix_proof_column(label),
            ]
        )
        fieldnames.extend(_tier_planning_fieldnames(label=label, include_total_tps=include_total_tps))
    fieldnames.extend(["请求数", "窗口上限", "输入下界", "输入上界"])
    return fieldnames


def _hit_summary_fieldnames(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
    include_actual_hit_rate: bool,
) -> list[str]:
    return _base_hit_fieldnames(
        tier_labels=tier_labels,
        include_total_tps=include_total_tps,
        include_actual_hit_rate=include_actual_hit_rate,
    )


def _planning_summary_fieldnames(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
) -> list[str]:
    fieldnames = ["分桶", "机器数", "卡数", "单机卡数", "规格"]
    if include_total_tps:
        fieldnames.append("总 TPS")
        fieldnames.append("TPS 输入口径")
    fieldnames.extend(
        [
            "HBM KVCache 总大小 (GB)",
            "Prefill 节省系数 alpha",
            "HBM Strict-Prefix 命中率",
            "HBM Strict-Prefix 求解路径",
        ]
    )
    fieldnames.extend(_base_planning_metric_fieldnames(include_total_tps=include_total_tps))
    for label in tier_labels:
        fieldnames.extend(
            [
                label,
                _strict_prefix_proof_column(label),
                _tps_gain_column(label),
                _estimated_card_count_column(label),
                _estimated_machine_count_column(label),
            ]
        )
        if include_total_tps:
            fieldnames.append(_estimated_total_tps_column(label))
    fieldnames.extend(["请求数", "窗口上限", "输入下界", "输入上界"])
    return fieldnames


def _base_hit_fieldnames(
    *,
    tier_labels: list[str],
    include_total_tps: bool,
    include_actual_hit_rate: bool,
) -> list[str]:
    fieldnames = ["分桶", "机器数", "卡数", "单机卡数", "规格"]
    if include_total_tps:
        fieldnames.append("总 TPS")
        fieldnames.append("TPS 输入口径")
    fieldnames.extend(
        [
            "HBM KVCache 总大小 (GB)",
            "极限命中率",
        ]
    )
    if include_actual_hit_rate:
        fieldnames.append("实际命中率")
    fieldnames.extend(
        [
            "HBM Relaxed Upper Bound 命中率",
            "HBM LRU 命中率",
            "HBM Strict-Prefix Replay 命中率",
            "HBM Strict-Prefix 命中率",
            "HBM Strict-Prefix 求解路径",
        ]
    )
    for label in tier_labels:
        fieldnames.extend(
            [
                label,
                _relaxed_upper_bound_column(label),
                _lru_column(label),
                _strict_prefix_replay_column(label),
                _strict_prefix_proof_column(label),
            ]
        )
    fieldnames.extend(["请求数", "窗口上限", "输入下界", "输入上界"])
    return fieldnames


def _base_planning_metric_fieldnames(*, include_total_tps: bool) -> list[str]:
    fieldnames = [
        "HBM TPS Gain",
        "HBM 同负载估算卡数",
        "HBM 同负载估算机器数",
    ]
    if include_total_tps:
        fieldnames.append("HBM 估算总 TPS")
    return fieldnames


def _combined_summary_payload(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_total_tps: bool,
    include_actual_hit_rate: bool,
) -> dict[str, Any]:
    payload = _hit_summary_payload(
        row=row,
        tier_labels=tier_labels,
        include_total_tps=include_total_tps,
        include_actual_hit_rate=include_actual_hit_rate,
    )
    payload.update(_planning_metric_payload(row=row, include_total_tps=include_total_tps))
    for label in tier_labels:
        payload.update(_tier_planning_payload(row=row, label=label, include_total_tps=include_total_tps))
    return payload


def _hit_summary_payload(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_total_tps: bool,
    include_actual_hit_rate: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = _common_row_payload(row=row, include_total_tps=include_total_tps)
    payload["HBM KVCache 总大小 (GB)"] = f"{row.hbm_kv_total_gb:.2f}"
    payload["极限命中率"] = _format_rate(row.extreme_hit_rate)
    if include_actual_hit_rate:
        payload["实际命中率"] = _format_rate(row.actual_hit_rate)
    payload["HBM Relaxed Upper Bound 命中率"] = _format_rate(row.hbm_relaxed_upper_bound_hit_rate)
    payload["HBM LRU 命中率"] = _format_rate(row.hbm_lru_hit_rate)
    payload["HBM Strict-Prefix Replay 命中率"] = _format_rate(row.hbm_strict_prefix_replay_hit_rate)
    payload["HBM Strict-Prefix 命中率"] = _format_rate(row.hbm_strict_prefix_hit_rate)
    payload["HBM Strict-Prefix 求解路径"] = _format_text(row.hbm_strict_prefix_proof_source)
    for label in tier_labels:
        payload[label] = _format_rate(row.extra_tier_strict_prefix_hit_rates.get(label))
        payload[_relaxed_upper_bound_column(label)] = _format_rate(
            row.extra_tier_relaxed_upper_bound_hit_rates.get(label)
        )
        payload[_lru_column(label)] = _format_rate(row.extra_tier_lru_hit_rates.get(label))
        payload[_strict_prefix_replay_column(label)] = _format_rate(
            row.extra_tier_strict_prefix_replay_hit_rates.get(label)
        )
        payload[_strict_prefix_proof_column(label)] = _format_text(
            row.extra_tier_strict_prefix_proof_sources.get(label)
        )
    payload.update(_row_range_payload(row))
    return payload


def _planning_summary_payload(
    *,
    row: BucketReportRow,
    tier_labels: list[str],
    include_total_tps: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = _common_row_payload(row=row, include_total_tps=include_total_tps)
    payload["HBM KVCache 总大小 (GB)"] = f"{row.hbm_kv_total_gb:.2f}"
    payload["Prefill 节省系数 alpha"] = _format_number(row.prefill_savings_alpha)
    payload["HBM Strict-Prefix 命中率"] = _format_rate(row.hbm_strict_prefix_hit_rate)
    payload["HBM Strict-Prefix 求解路径"] = _format_text(row.hbm_strict_prefix_proof_source)
    payload.update(_planning_metric_payload(row=row, include_total_tps=include_total_tps))
    for label in tier_labels:
        payload[label] = _format_rate(row.extra_tier_strict_prefix_hit_rates.get(label))
        payload[_strict_prefix_proof_column(label)] = _format_text(
            row.extra_tier_strict_prefix_proof_sources.get(label)
        )
        payload.update(_tier_planning_payload(row=row, label=label, include_total_tps=include_total_tps))
    payload.update(_row_range_payload(row))
    return payload


def _common_row_payload(*, row: BucketReportRow, include_total_tps: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "分桶": row.bucket_label,
        "机器数": row.machine_count,
        "卡数": row.card_count,
        "单机卡数": row.cards_per_machine,
        "规格": row.machine_spec,
    }
    if include_total_tps:
        payload["总 TPS"] = row.total_tps if row.total_tps is not None else ""
        payload["TPS 输入口径"] = _format_text(row.total_tps_input_unit)
    return payload


def _planning_metric_payload(*, row: BucketReportRow, include_total_tps: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "HBM TPS Gain": _format_number(row.hbm_tps_gain),
        "HBM 同负载估算卡数": _format_number(row.hbm_estimated_card_count_for_same_load),
        "HBM 同负载估算机器数": _format_number(row.hbm_estimated_machine_count_for_same_load),
    }
    if include_total_tps:
        payload["HBM 估算总 TPS"] = _format_number(row.hbm_estimated_total_tps)
    return payload


def _tier_planning_fieldnames(*, label: str, include_total_tps: bool) -> list[str]:
    fieldnames = [
        _tps_gain_column(label),
        _estimated_card_count_column(label),
        _estimated_machine_count_column(label),
    ]
    if include_total_tps:
        fieldnames.append(_estimated_total_tps_column(label))
    return fieldnames


def _tier_planning_payload(
    *,
    row: BucketReportRow,
    label: str,
    include_total_tps: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        _tps_gain_column(label): _format_number(row.extra_tier_tps_gains.get(label)),
        _estimated_card_count_column(label): _format_number(
            row.extra_tier_estimated_card_counts_for_same_load.get(label)
        ),
        _estimated_machine_count_column(label): _format_number(
            row.extra_tier_estimated_machine_counts_for_same_load.get(label)
        ),
    }
    if include_total_tps:
        payload[_estimated_total_tps_column(label)] = _format_number(
            row.extra_tier_estimated_total_tps.get(label)
        )
    return payload


def _row_range_payload(row: BucketReportRow) -> dict[str, Any]:
    return {
        "请求数": row.request_count,
        "窗口上限": "" if row.window_tokens is None else row.window_tokens,
        "输入下界": row.input_lower_tokens,
        "输入上界": "" if row.input_upper_tokens is None else row.input_upper_tokens,
    }


def _collect_tier_labels(rows: list[BucketReportRow]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for label in row.extra_tier_strict_prefix_hit_rates:
            if label in seen:
                continue
            seen.add(label)
            labels.append(label)
    return labels


def _format_rate(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value * 100:.2f}%"


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    if math.isinf(value):
        return "inf"
    return f"{value:.2f}"


def _format_text(value: str | None) -> str:
    if value is None:
        return ""
    return value


def _relaxed_upper_bound_column(label: str) -> str:
    return f"{_strict_prefix_column_base(label)} Relaxed Upper Bound 命中率"


def _strict_prefix_replay_column(label: str) -> str:
    return f"{_strict_prefix_column_base(label)} Strict-Prefix Replay 命中率"


def _lru_column(label: str) -> str:
    return f"{_strict_prefix_column_base(label)} LRU 命中率"


def _strict_prefix_proof_column(label: str) -> str:
    return f"{_strict_prefix_column_base(label)} Strict-Prefix 求解路径"


def _tps_gain_column(label: str) -> str:
    return f"{_strict_prefix_column_base(label)} TPS Gain"


def _estimated_total_tps_column(label: str) -> str:
    return f"{_strict_prefix_column_base(label)} 估算总 TPS"


def _estimated_card_count_column(label: str) -> str:
    return f"{_strict_prefix_column_base(label)} 同负载估算卡数"


def _estimated_machine_count_column(label: str) -> str:
    return f"{_strict_prefix_column_base(label)} 同负载估算机器数"


def _strict_prefix_column_base(label: str) -> str:
    suffix = " 命中率"
    if label.endswith(suffix):
        return label[: -len(suffix)]
    return label
