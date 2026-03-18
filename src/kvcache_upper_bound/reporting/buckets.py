from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from kvcache_upper_bound.core.models import ModelProfile, RequestRecord, Scope
from kvcache_upper_bound.ingest.normalizer import build_effective_requests
from kvcache_upper_bound.oracle.capacity import CapacityAnalysisResult, analyze_capacity_upper_bound
from kvcache_upper_bound.oracle.content import ContentAnalysisResult, analyze_content_upper_bound
from kvcache_upper_bound.oracle.strict_prefix import (
    StrictPrefixAnalysisResult,
    analyze_strict_prefix_capacity_upper_bound,
)

BYTES_PER_GB = 1024**3
VALID_TOTAL_TPS_UNITS = ("cluster_total", "per_machine", "per_card")
LEGACY_PER_MACHINE_BUDGET_FIELDS = (
    "hbm_kv_gb_per_machine",
    "gpu_memory_gb_per_machine",
    "runtime_reserve_gb_per_machine",
)


@dataclass(frozen=True)
class BucketCapacityTier:
    label: str
    kv_gb_per_machine: float


@dataclass(frozen=True)
class BucketDeploymentConfig:
    label: str
    lower_tokens: int
    upper_tokens: int | None
    accelerator_count: int
    cards_per_machine: int
    machine_spec: str
    total_tps: float | None
    total_tps_unit: str = "cluster_total"
    hbm_kv_gb_per_card: float | None = None
    gpu_memory_gb_per_card: float | None = None
    hbm_kv_utilization: float | None = None
    runtime_reserve_gb_per_card: float = 0.0
    window_tokens: int | None = None
    actual_hit_rate: float | None = None
    actual_hit_rate_note: str | None = None
    extra_capacity_tiers: tuple[BucketCapacityTier, ...] = field(default_factory=tuple)

    def node_count(self) -> int:
        if self.cards_per_machine <= 0:
            raise ValueError(f"{self.label}: cards_per_machine must be positive")
        if self.accelerator_count % self.cards_per_machine != 0:
            raise ValueError(
                f"{self.label}: accelerator_count must be divisible by cards_per_machine"
            )
        return self.accelerator_count // self.cards_per_machine

    def resolved_total_tps(self) -> float | None:
        if self.total_tps is None:
            return None
        if self.total_tps_unit == "cluster_total":
            return self.total_tps
        if self.total_tps_unit == "per_machine":
            return self.total_tps * self.node_count()
        if self.total_tps_unit == "per_card":
            return self.total_tps * self.accelerator_count
        raise ValueError(
            f"{self.label}: total_tps_unit must be one of {', '.join(VALID_TOTAL_TPS_UNITS)}"
        )

    def contains(self, input_length: int) -> bool:
        if input_length < self.lower_tokens:
            return False
        if self.upper_tokens is None:
            return True
        return input_length < self.upper_tokens

    def resolved_hbm_kv_gb_per_card(self, model_profile: ModelProfile) -> float:
        if self.hbm_kv_gb_per_card is not None:
            return self.hbm_kv_gb_per_card
        if self.gpu_memory_gb_per_card is None:
            raise ValueError(
                f"{self.label}: either hbm_kv_gb_per_card or gpu_memory_gb_per_card must be provided"
            )
        if self.hbm_kv_utilization is not None:
            return self.gpu_memory_gb_per_card * self.hbm_kv_utilization

        model_weight_bytes_per_rank = model_profile.weight_bytes_per_rank()
        if model_weight_bytes_per_rank is None:
            raise ValueError(
                f"{self.label}: gpu_memory_gb_per_card requires either hbm_kv_utilization or model_profile.parameter_count"
            )
        model_weight_gb_per_rank = model_weight_bytes_per_rank / BYTES_PER_GB
        resolved = (
            self.gpu_memory_gb_per_card
            - model_weight_gb_per_rank
            - self.runtime_reserve_gb_per_card
        )
        if resolved < 0:
            raise ValueError(
                f"{self.label}: derived hbm kv budget is negative after subtracting model weights and runtime reserve"
            )
        return resolved

    def resolved_window_tokens(self, records: list[RequestRecord]) -> int:
        if self.window_tokens is not None:
            return self.window_tokens
        if self.upper_tokens is not None:
            return self.upper_tokens
        if not records:
            return 0
        return max(record.input_length for record in records)


@dataclass(frozen=True)
class BucketAnalysisConfig:
    model_profile: ModelProfile
    scope: Scope
    block_size: int
    bucket_deployments: tuple[BucketDeploymentConfig, ...]
    prefill_savings_alpha: float = 0.8


@dataclass(frozen=True)
class BucketReportRow:
    bucket_label: str
    machine_count: int
    card_count: int
    cards_per_machine: int
    machine_spec: str
    total_tps: float | None
    total_tps_input_unit: str | None
    prefill_savings_alpha: float
    hbm_kv_gb_per_card: float
    hbm_kv_total_gb: float
    model_weight_gb_per_card: float | None
    extreme_hit_rate: float | None
    actual_hit_rate: float | None
    actual_hit_rate_note: str | None
    hbm_relaxed_upper_bound_hit_rate: float | None
    hbm_strict_prefix_replay_hit_rate: float | None
    hbm_strict_prefix_hit_rate: float | None
    hbm_strict_prefix_proof_source: str | None
    hbm_tps_gain: float | None
    hbm_estimated_total_tps: float | None
    hbm_estimated_card_count_for_same_load: float | None
    hbm_estimated_machine_count_for_same_load: float | None
    extra_tier_relaxed_upper_bound_hit_rates: dict[str, float | None]
    extra_tier_strict_prefix_replay_hit_rates: dict[str, float | None]
    extra_tier_strict_prefix_hit_rates: dict[str, float | None]
    extra_tier_strict_prefix_proof_sources: dict[str, str | None]
    extra_tier_tps_gains: dict[str, float | None]
    extra_tier_estimated_total_tps: dict[str, float | None]
    extra_tier_estimated_card_counts_for_same_load: dict[str, float | None]
    extra_tier_estimated_machine_counts_for_same_load: dict[str, float | None]
    request_count: int
    window_tokens: int | None
    input_lower_tokens: int
    input_upper_tokens: int | None


@dataclass(frozen=True)
class BucketDetail:
    config: BucketDeploymentConfig
    content_result: ContentAnalysisResult
    hbm_capacity_result: CapacityAnalysisResult
    hbm_strict_prefix_result: StrictPrefixAnalysisResult
    extra_capacity_results: dict[str, CapacityAnalysisResult]
    extra_strict_prefix_results: dict[str, StrictPrefixAnalysisResult]


@dataclass(frozen=True)
class BucketAnalysisResult:
    rows: list[BucketReportRow]
    details: dict[str, BucketDetail]


def load_bucket_analysis_config(path: str | Path) -> BucketAnalysisConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    model_profile = _load_model_profile(payload.get("model_profile", {}))
    scope = Scope(str(payload.get("scope", Scope.GLOBAL.value)))
    block_size = int(payload.get("block_size", model_profile.block_size))
    prefill_savings_alpha = _load_prefill_savings_alpha(payload)
    bucket_deployments = tuple(
        _load_bucket_deployment(item) for item in payload.get("bucket_deployments", [])
    )
    if not bucket_deployments:
        raise ValueError("bucket_deployments must not be empty")
    return BucketAnalysisConfig(
        model_profile=model_profile,
        scope=scope,
        block_size=block_size,
        bucket_deployments=bucket_deployments,
        prefill_savings_alpha=prefill_savings_alpha,
    )


def analyze_bucket_deployments(
    records: Iterable[RequestRecord],
    config: BucketAnalysisConfig,
) -> BucketAnalysisResult:
    record_list = list(records)
    rows: list[BucketReportRow] = []
    details: dict[str, BucketDetail] = {}

    for deployment in config.bucket_deployments:
        bucket_records = [record for record in record_list if deployment.contains(record.input_length)]
        has_bucket_records = bool(bucket_records)
        node_count = deployment.node_count()
        window_tokens = deployment.resolved_window_tokens(bucket_records)
        normalized = build_effective_requests(
            bucket_records,
            window_tokens=window_tokens,
            scope=config.scope,
            block_size=config.block_size,
        )
        content_result = analyze_content_upper_bound(
            normalized.requests,
            model_profile=config.model_profile,
            block_size=config.block_size,
        )

        hbm_kv_gb_per_card = deployment.resolved_hbm_kv_gb_per_card(config.model_profile)
        hbm_kv_total_gb = deployment.accelerator_count * hbm_kv_gb_per_card
        model_weight_bytes_per_rank = config.model_profile.weight_bytes_per_rank()
        model_weight_gb_per_card = (
            None
            if model_weight_bytes_per_rank is None
            else model_weight_bytes_per_rank / BYTES_PER_GB
        )
        resolved_total_tps = deployment.resolved_total_tps()
        hbm_budget_bytes = _gb_to_bytes(hbm_kv_total_gb)
        hbm_capacity_result = analyze_capacity_upper_bound(
            normalized.requests,
            model_profile=config.model_profile,
            budget_bytes=hbm_budget_bytes,
            block_size=config.block_size,
        )
        hbm_strict_prefix_result = analyze_strict_prefix_capacity_upper_bound(
            normalized.requests,
            model_profile=config.model_profile,
            budget_bytes=hbm_budget_bytes,
            block_size=config.block_size,
        )

        extra_capacity_results: dict[str, CapacityAnalysisResult] = {}
        extra_strict_prefix_results: dict[str, StrictPrefixAnalysisResult] = {}
        extra_tier_relaxed_upper_bound_hit_rates: dict[str, float | None] = {}
        extra_tier_strict_prefix_replay_hit_rates: dict[str, float | None] = {}
        extra_tier_strict_prefix_hit_rates: dict[str, float | None] = {}
        extra_tier_strict_prefix_proof_sources: dict[str, str | None] = {}
        extra_tier_tps_gains: dict[str, float | None] = {}
        extra_tier_estimated_total_tps: dict[str, float | None] = {}
        extra_tier_estimated_card_counts_for_same_load: dict[str, float | None] = {}
        extra_tier_estimated_machine_counts_for_same_load: dict[str, float | None] = {}
        ceiling_capacity_result = hbm_capacity_result if (
            hbm_capacity_result.summary.hit_blocks == content_result.summary.hit_blocks
            and hbm_capacity_result.summary.total_blocks == content_result.summary.total_blocks
        ) else None
        ceiling_strict_prefix_result = hbm_strict_prefix_result if (
            hbm_strict_prefix_result.summary.hit_blocks == content_result.summary.hit_blocks
            and hbm_strict_prefix_result.summary.total_blocks == content_result.summary.total_blocks
        ) else None
        for tier in deployment.extra_capacity_tiers:
            if ceiling_capacity_result is not None:
                capacity_result = ceiling_capacity_result
            else:
                total_budget_gb = hbm_kv_total_gb + node_count * tier.kv_gb_per_machine
                capacity_result = analyze_capacity_upper_bound(
                    normalized.requests,
                    model_profile=config.model_profile,
                    budget_bytes=_gb_to_bytes(total_budget_gb),
                    block_size=config.block_size,
                )
                if (
                    capacity_result.summary.hit_blocks == content_result.summary.hit_blocks
                    and capacity_result.summary.total_blocks == content_result.summary.total_blocks
                ):
                    ceiling_capacity_result = capacity_result

            if ceiling_strict_prefix_result is not None:
                strict_prefix_result = ceiling_strict_prefix_result
            else:
                total_budget_gb = hbm_kv_total_gb + node_count * tier.kv_gb_per_machine
                strict_prefix_result = analyze_strict_prefix_capacity_upper_bound(
                    normalized.requests,
                    model_profile=config.model_profile,
                    budget_bytes=_gb_to_bytes(total_budget_gb),
                    block_size=config.block_size,
                )
                if (
                    strict_prefix_result.summary.hit_blocks == content_result.summary.hit_blocks
                    and strict_prefix_result.summary.total_blocks == content_result.summary.total_blocks
                ):
                    ceiling_strict_prefix_result = strict_prefix_result

            extra_capacity_results[tier.label] = capacity_result
            extra_strict_prefix_results[tier.label] = strict_prefix_result
            extra_tier_relaxed_upper_bound_hit_rates[tier.label] = (
                None if not has_bucket_records else capacity_result.summary.block_hit_rate
            )
            extra_tier_strict_prefix_replay_hit_rates[tier.label] = (
                None if not has_bucket_records else capacity_result.summary.strict_prefix_block_hit_rate
            )
            extra_tier_strict_prefix_hit_rates[tier.label] = (
                None if not has_bucket_records else strict_prefix_result.summary.block_hit_rate
            )
            extra_tier_strict_prefix_proof_sources[tier.label] = (
                None if not has_bucket_records else strict_prefix_result.summary.proof_source
            )
            extra_tier_tps_gains[tier.label] = _tps_gain(
                extra_tier_strict_prefix_hit_rates[tier.label],
                config.prefill_savings_alpha,
            )
            extra_tier_estimated_total_tps[tier.label] = _estimated_total_tps(
                resolved_total_tps,
                extra_tier_tps_gains[tier.label],
            )
            extra_tier_estimated_card_counts_for_same_load[tier.label] = _estimated_card_count(
                deployment.accelerator_count,
                extra_tier_tps_gains[tier.label],
            )
            extra_tier_estimated_machine_counts_for_same_load[tier.label] = _estimated_machine_count(
                extra_tier_estimated_card_counts_for_same_load[tier.label],
                deployment.cards_per_machine,
            )

        hbm_relaxed_upper_bound_hit_rate = (
            None if not has_bucket_records else hbm_capacity_result.summary.block_hit_rate
        )
        hbm_strict_prefix_replay_hit_rate = (
            None if not has_bucket_records else hbm_capacity_result.summary.strict_prefix_block_hit_rate
        )
        hbm_strict_prefix_hit_rate = (
            None if not has_bucket_records else hbm_strict_prefix_result.summary.block_hit_rate
        )
        hbm_strict_prefix_proof_source = (
            None if not has_bucket_records else hbm_strict_prefix_result.summary.proof_source
        )
        hbm_tps_gain = _tps_gain(hbm_strict_prefix_hit_rate, config.prefill_savings_alpha)
        hbm_estimated_total_tps = _estimated_total_tps(resolved_total_tps, hbm_tps_gain)
        hbm_estimated_card_count_for_same_load = _estimated_card_count(
            deployment.accelerator_count,
            hbm_tps_gain,
        )
        hbm_estimated_machine_count_for_same_load = _estimated_machine_count(
            hbm_estimated_card_count_for_same_load,
            deployment.cards_per_machine,
        )

        row = BucketReportRow(
            bucket_label=deployment.label,
            machine_count=node_count,
            card_count=deployment.accelerator_count,
            cards_per_machine=deployment.cards_per_machine,
            machine_spec=deployment.machine_spec,
            total_tps=resolved_total_tps,
            total_tps_input_unit=None if deployment.total_tps is None else deployment.total_tps_unit,
            prefill_savings_alpha=config.prefill_savings_alpha,
            hbm_kv_gb_per_card=hbm_kv_gb_per_card,
            hbm_kv_total_gb=hbm_kv_total_gb,
            model_weight_gb_per_card=model_weight_gb_per_card,
            extreme_hit_rate=None if not has_bucket_records else content_result.summary.block_hit_rate,
            actual_hit_rate=deployment.actual_hit_rate,
            actual_hit_rate_note=deployment.actual_hit_rate_note,
            hbm_relaxed_upper_bound_hit_rate=hbm_relaxed_upper_bound_hit_rate,
            hbm_strict_prefix_replay_hit_rate=hbm_strict_prefix_replay_hit_rate,
            hbm_strict_prefix_hit_rate=hbm_strict_prefix_hit_rate,
            hbm_strict_prefix_proof_source=hbm_strict_prefix_proof_source,
            hbm_tps_gain=hbm_tps_gain,
            hbm_estimated_total_tps=hbm_estimated_total_tps,
            hbm_estimated_card_count_for_same_load=hbm_estimated_card_count_for_same_load,
            hbm_estimated_machine_count_for_same_load=hbm_estimated_machine_count_for_same_load,
            extra_tier_relaxed_upper_bound_hit_rates=extra_tier_relaxed_upper_bound_hit_rates,
            extra_tier_strict_prefix_replay_hit_rates=extra_tier_strict_prefix_replay_hit_rates,
            extra_tier_strict_prefix_hit_rates=extra_tier_strict_prefix_hit_rates,
            extra_tier_strict_prefix_proof_sources=extra_tier_strict_prefix_proof_sources,
            extra_tier_tps_gains=extra_tier_tps_gains,
            extra_tier_estimated_total_tps=extra_tier_estimated_total_tps,
            extra_tier_estimated_card_counts_for_same_load=extra_tier_estimated_card_counts_for_same_load,
            extra_tier_estimated_machine_counts_for_same_load=extra_tier_estimated_machine_counts_for_same_load,
            request_count=len(bucket_records),
            window_tokens=None if not has_bucket_records else window_tokens,
            input_lower_tokens=deployment.lower_tokens,
            input_upper_tokens=deployment.upper_tokens,
        )
        rows.append(row)
        details[deployment.label] = BucketDetail(
            config=deployment,
            content_result=content_result,
            hbm_capacity_result=hbm_capacity_result,
            hbm_strict_prefix_result=hbm_strict_prefix_result,
            extra_capacity_results=extra_capacity_results,
            extra_strict_prefix_results=extra_strict_prefix_results,
        )

    return BucketAnalysisResult(rows=rows, details=details)


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
                "hbm_strict_prefix_summary": asdict(detail.hbm_strict_prefix_result.summary),
                "extra_capacity_summaries": {
                    tier_label: asdict(tier_result.summary)
                    for tier_label, tier_result in detail.extra_capacity_results.items()
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
    payload["HBM Strict-Prefix Replay 命中率"] = _format_rate(row.hbm_strict_prefix_replay_hit_rate)
    payload["HBM Strict-Prefix 命中率"] = _format_rate(row.hbm_strict_prefix_hit_rate)
    payload["HBM Strict-Prefix 求解路径"] = _format_text(row.hbm_strict_prefix_proof_source)
    for label in tier_labels:
        payload[label] = _format_rate(row.extra_tier_strict_prefix_hit_rates.get(label))
        payload[_relaxed_upper_bound_column(label)] = _format_rate(
            row.extra_tier_relaxed_upper_bound_hit_rates.get(label)
        )
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


def _gb_to_bytes(value_gb: float) -> int:
    return int(value_gb * BYTES_PER_GB)


def _load_prefill_savings_alpha(payload: dict[str, Any]) -> float:
    alpha = _normalize_rate(payload.get("prefill_savings_alpha", 0.8))
    if alpha is None:
        return 0.8
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("prefill_savings_alpha must be within [0, 1]")
    return alpha


def _tps_gain(hit_rate: float | None, alpha: float) -> float | None:
    if hit_rate is None:
        return None
    denominator = 1.0 - alpha * hit_rate
    if denominator <= 0.0:
        return math.inf
    return 1.0 / denominator


def _estimated_total_tps(base_tps: float | None, gain: float | None) -> float | None:
    if base_tps is None or gain is None:
        return None
    return base_tps * gain


def _estimated_card_count(card_count: int, gain: float | None) -> float | None:
    if gain is None:
        return None
    if math.isinf(gain):
        return 0.0
    return card_count / gain


def _estimated_machine_count(
    estimated_card_count: float | None,
    cards_per_machine: int,
) -> float | None:
    if estimated_card_count is None:
        return None
    if cards_per_machine <= 0:
        raise ValueError("cards_per_machine must be positive")
    return estimated_card_count / cards_per_machine


def _load_model_profile(payload: dict[str, Any]) -> ModelProfile:
    required = ["n_layers", "n_kv_heads", "head_dim", "dtype_bytes"]
    for key in required:
        if key not in payload:
            raise ValueError(f"model_profile missing required field: {key}")
    return ModelProfile(
        n_layers=int(payload["n_layers"]),
        n_kv_heads=int(payload["n_kv_heads"]),
        head_dim=int(payload["head_dim"]),
        dtype_bytes=int(payload["dtype_bytes"]),
        kv_cache_layer_count=None
        if payload.get("kv_cache_layer_count") is None
        else int(payload["kv_cache_layer_count"]),
        tp_size=int(payload.get("tp_size", 1)),
        pp_size=int(payload.get("pp_size", 1)),
        block_size=int(payload.get("block_size", 16)),
        parameter_count=None
        if payload.get("parameter_count") is None
        else int(payload["parameter_count"]),
        weight_dtype_bytes=None
        if payload.get("weight_dtype_bytes") is None
        else int(payload["weight_dtype_bytes"]),
    )


def _load_bucket_deployment(payload: dict[str, Any]) -> BucketDeploymentConfig:
    accelerator_count, cards_per_machine, machine_spec = _parse_machine_fields(payload)
    total_tps_unit = _parse_total_tps_unit(payload)
    _reject_legacy_per_machine_budget_fields(payload)
    extra_tiers = tuple(
        BucketCapacityTier(
            label=str(item["label"]),
            kv_gb_per_machine=float(item["kv_gb_per_machine"]),
        )
        for item in payload.get("extra_capacity_tiers", [])
    )
    actual_hit_rate, actual_hit_rate_note = _parse_actual_hit_fields(payload)
    return BucketDeploymentConfig(
        label=str(payload["label"]),
        lower_tokens=int(payload["lower_tokens"]),
        upper_tokens=None
        if payload.get("upper_tokens") is None
        else int(payload["upper_tokens"]),
        accelerator_count=accelerator_count,
        cards_per_machine=cards_per_machine,
        machine_spec=machine_spec,
        total_tps=None if payload.get("total_tps") is None else float(payload["total_tps"]),
        total_tps_unit=total_tps_unit,
        hbm_kv_gb_per_card=None
        if payload.get("hbm_kv_gb_per_card") is None
        else float(payload["hbm_kv_gb_per_card"]),
        gpu_memory_gb_per_card=None
        if payload.get("gpu_memory_gb_per_card") is None
        else float(payload["gpu_memory_gb_per_card"]),
        hbm_kv_utilization=None
        if payload.get("hbm_kv_utilization") is None
        else float(payload["hbm_kv_utilization"]),
        runtime_reserve_gb_per_card=float(payload.get("runtime_reserve_gb_per_card", 0.0)),
        window_tokens=None if payload.get("window_tokens") is None else int(payload["window_tokens"]),
        actual_hit_rate=actual_hit_rate,
        actual_hit_rate_note=actual_hit_rate_note,
        extra_capacity_tiers=extra_tiers,
    )


def _normalize_rate(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().replace("%", "")
        rate = float(text)
    else:
        rate = float(value)
    if rate > 1.0:
        rate /= 100.0
    return rate


def _parse_actual_hit_fields(payload: dict[str, Any]) -> tuple[float | None, str | None]:
    note = payload.get("actual_hit_rate_note")
    raw_value = payload.get("actual_hit_rate")
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if "(" in text and ")" in text and note is None:
            prefix, suffix = text.split("(", 1)
            raw_value = prefix.strip()
            note = suffix.rsplit(")", 1)[0].strip()
    return _normalize_rate(raw_value), note


def _parse_machine_fields(payload: dict[str, Any]) -> tuple[int, int, str]:
    if "machine_count" in payload and payload["machine_count"] is not None:
        raise ValueError(
            "machine_count is no longer accepted; use accelerator_count and cards_per_machine"
        )
    if "accelerator_count" not in payload or payload["accelerator_count"] is None:
        raise ValueError("accelerator_count is required")
    if "cards_per_machine" not in payload or payload["cards_per_machine"] is None:
        raise ValueError("cards_per_machine is required")
    if "machine_spec" not in payload or payload["machine_spec"] is None:
        raise ValueError("machine_spec is required")

    accelerator_count = int(payload["accelerator_count"])
    cards_per_machine = int(payload["cards_per_machine"])
    machine_spec = str(payload["machine_spec"]).strip()

    if accelerator_count <= 0:
        raise ValueError("accelerator_count must be positive")
    if cards_per_machine <= 0:
        raise ValueError("cards_per_machine must be positive")
    if not machine_spec:
        raise ValueError("machine_spec must not be empty")
    if "*" in machine_spec:
        raise ValueError(
            "machine_spec must be a plain spec label; move counts into accelerator_count and cards_per_machine"
        )
    return accelerator_count, cards_per_machine, machine_spec


def _parse_total_tps_unit(payload: dict[str, Any]) -> str:
    raw_unit = payload.get("total_tps_unit", "cluster_total")
    unit = str(raw_unit).strip()
    if unit not in VALID_TOTAL_TPS_UNITS:
        raise ValueError(
            f"total_tps_unit must be one of {', '.join(VALID_TOTAL_TPS_UNITS)}"
        )
    return unit


def _reject_legacy_per_machine_budget_fields(payload: dict[str, Any]) -> None:
    legacy_fields = [
        field_name
        for field_name in LEGACY_PER_MACHINE_BUDGET_FIELDS
        if field_name in payload and payload[field_name] is not None
    ]
    if not legacy_fields:
        return
    formatted = ", ".join(legacy_fields)
    raise ValueError(
        f"legacy per-machine budget fields are no longer accepted: {formatted}; "
        "use hbm_kv_gb_per_card, gpu_memory_gb_per_card, runtime_reserve_gb_per_card"
    )
