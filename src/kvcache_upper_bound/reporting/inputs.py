from __future__ import annotations

from dataclasses import dataclass

from .buckets import BucketAnalysisResult


@dataclass(frozen=True)
class BucketTierInputSummary:
    label: str
    extra_kv_gb_per_machine: float
    extra_kv_total_gb: float
    total_kv_gb: float


@dataclass(frozen=True)
class BucketInputSummary:
    bucket_label: str
    input_lower_tokens: int
    input_upper_tokens: int | None
    machine_count: int
    card_count: int
    cards_per_machine: int
    machine_spec: str
    total_tps_input: float | None
    total_tps_input_unit: str | None
    total_tps_cluster_total: float | None
    planning_target_total_tps: float | None
    baseline_per_card_tps: float | None
    hbm_kv_gb_per_card: float
    hbm_kv_total_gb: float
    model_weight_gb_per_card: float | None
    extra_capacity_tiers: tuple[BucketTierInputSummary, ...]


def build_bucket_input_summaries(result: BucketAnalysisResult) -> list[BucketInputSummary]:
    summaries: list[BucketInputSummary] = []
    for row in result.rows:
        detail = result.details[row.bucket_label]
        tier_summaries = tuple(
            BucketTierInputSummary(
                label=tier.label,
                extra_kv_gb_per_machine=tier.kv_gb_per_machine,
                extra_kv_total_gb=row.machine_count * tier.kv_gb_per_machine,
                total_kv_gb=row.hbm_kv_total_gb + row.machine_count * tier.kv_gb_per_machine,
            )
            for tier in detail.config.extra_capacity_tiers
        )
        summaries.append(
            BucketInputSummary(
                bucket_label=row.bucket_label,
                input_lower_tokens=row.input_lower_tokens,
                input_upper_tokens=row.input_upper_tokens,
                machine_count=row.machine_count,
                card_count=row.card_count,
                cards_per_machine=row.cards_per_machine,
                machine_spec=row.machine_spec,
                total_tps_input=detail.config.total_tps,
                total_tps_input_unit=row.total_tps_input_unit,
                total_tps_cluster_total=row.total_tps,
                planning_target_total_tps=row.planning_target_total_tps,
                baseline_per_card_tps=row.baseline_per_card_tps,
                hbm_kv_gb_per_card=row.hbm_kv_gb_per_card,
                hbm_kv_total_gb=row.hbm_kv_total_gb,
                model_weight_gb_per_card=row.model_weight_gb_per_card,
                extra_capacity_tiers=tier_summaries,
            )
        )
    return summaries
