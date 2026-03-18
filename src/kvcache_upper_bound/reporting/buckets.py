from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from kvcache_upper_bound.core.models import ModelProfile, RequestRecord, Scope
from kvcache_upper_bound.ingest.normalizer import build_effective_requests
from kvcache_upper_bound.oracle.capacity import CapacityAnalysisResult, analyze_capacity_upper_bound
from kvcache_upper_bound.oracle.content import ContentAnalysisResult, analyze_content_upper_bound
from kvcache_upper_bound.oracle.lru import LRUSimulationResult, analyze_lru_baseline
from kvcache_upper_bound.oracle.strict_prefix import (
    StrictPrefixAnalysisResult,
    analyze_strict_prefix_capacity_upper_bound,
)
from kvcache_upper_bound.reporting.planning_search import (
    build_target_tps_plan,
    cluster_capacity_tps,
    estimated_card_count,
    estimated_machine_count,
    estimated_total_tps,
    tps_gain,
)

BYTES_PER_GB = 1024**3
VALID_TOTAL_TPS_UNITS = ("cluster_total", "per_machine", "per_card")


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
    planning_target_total_tps: float | None = None
    baseline_per_card_tps: float | None = None
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

    def resolved_planning_target_total_tps(self) -> float | None:
        if self.planning_target_total_tps is not None:
            return self.planning_target_total_tps
        if self.baseline_per_card_tps is None:
            return None
        return self.resolved_total_tps()

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
    planning_target_total_tps: float | None
    baseline_per_card_tps: float | None
    prefill_savings_alpha: float
    hbm_kv_gb_per_card: float
    hbm_kv_total_gb: float
    model_weight_gb_per_card: float | None
    extreme_hit_rate: float | None
    actual_hit_rate: float | None
    actual_hit_rate_note: str | None
    hbm_relaxed_upper_bound_hit_rate: float | None
    hbm_lru_hit_rate: float | None
    hbm_strict_prefix_replay_hit_rate: float | None
    hbm_strict_prefix_hit_rate: float | None
    hbm_strict_prefix_proof_source: str | None
    hbm_strict_prefix_tps_gain: float | None
    hbm_strict_prefix_estimated_total_tps: float | None
    hbm_strict_prefix_estimated_card_count_for_same_load: float | None
    hbm_strict_prefix_estimated_machine_count_for_same_load: float | None
    hbm_lru_tps_gain: float | None
    hbm_lru_estimated_total_tps: float | None
    hbm_lru_estimated_card_count_for_same_load: float | None
    hbm_lru_estimated_machine_count_for_same_load: float | None
    hbm_strict_prefix_current_cluster_capacity_tps: float | None
    hbm_strict_prefix_min_card_count_for_target_total_tps: int | None
    hbm_strict_prefix_min_machine_count_for_target_total_tps: int | None
    hbm_lru_current_cluster_capacity_tps: float | None
    hbm_lru_min_card_count_for_target_total_tps: int | None
    hbm_lru_min_machine_count_for_target_total_tps: int | None
    extra_tier_relaxed_upper_bound_hit_rates: dict[str, float | None]
    extra_tier_lru_hit_rates: dict[str, float | None]
    extra_tier_strict_prefix_replay_hit_rates: dict[str, float | None]
    extra_tier_strict_prefix_hit_rates: dict[str, float | None]
    extra_tier_strict_prefix_proof_sources: dict[str, str | None]
    extra_tier_strict_prefix_tps_gains: dict[str, float | None]
    extra_tier_strict_prefix_estimated_total_tps: dict[str, float | None]
    extra_tier_strict_prefix_estimated_card_counts_for_same_load: dict[str, float | None]
    extra_tier_strict_prefix_estimated_machine_counts_for_same_load: dict[str, float | None]
    extra_tier_lru_tps_gains: dict[str, float | None]
    extra_tier_lru_estimated_total_tps: dict[str, float | None]
    extra_tier_lru_estimated_card_counts_for_same_load: dict[str, float | None]
    extra_tier_lru_estimated_machine_counts_for_same_load: dict[str, float | None]
    extra_tier_strict_prefix_current_cluster_capacity_tps: dict[str, float | None]
    extra_tier_strict_prefix_min_card_counts_for_target_total_tps: dict[str, int | None]
    extra_tier_strict_prefix_min_machine_counts_for_target_total_tps: dict[str, int | None]
    extra_tier_lru_current_cluster_capacity_tps: dict[str, float | None]
    extra_tier_lru_min_card_counts_for_target_total_tps: dict[str, int | None]
    extra_tier_lru_min_machine_counts_for_target_total_tps: dict[str, int | None]
    request_count: int
    window_tokens: int | None
    input_lower_tokens: int
    input_upper_tokens: int | None


@dataclass(frozen=True)
class BucketDetail:
    config: BucketDeploymentConfig
    content_result: ContentAnalysisResult
    hbm_capacity_result: CapacityAnalysisResult
    hbm_lru_result: LRUSimulationResult
    hbm_strict_prefix_result: StrictPrefixAnalysisResult
    extra_capacity_results: dict[str, CapacityAnalysisResult]
    extra_lru_results: dict[str, LRUSimulationResult]
    extra_strict_prefix_results: dict[str, StrictPrefixAnalysisResult]


@dataclass(frozen=True)
class BucketAnalysisResult:
    rows: list[BucketReportRow]
    details: dict[str, BucketDetail]
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
        planning_target_total_tps = deployment.resolved_planning_target_total_tps()
        baseline_per_card_tps = deployment.baseline_per_card_tps
        hbm_budget_bytes = _gb_to_bytes(hbm_kv_total_gb)
        hbm_capacity_result = analyze_capacity_upper_bound(
            normalized.requests,
            model_profile=config.model_profile,
            budget_bytes=hbm_budget_bytes,
            block_size=config.block_size,
        )
        hbm_lru_result = analyze_lru_baseline(
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
        extra_lru_results: dict[str, LRUSimulationResult] = {}
        extra_strict_prefix_results: dict[str, StrictPrefixAnalysisResult] = {}
        extra_tier_relaxed_upper_bound_hit_rates: dict[str, float | None] = {}
        extra_tier_lru_hit_rates: dict[str, float | None] = {}
        extra_tier_strict_prefix_replay_hit_rates: dict[str, float | None] = {}
        extra_tier_strict_prefix_hit_rates: dict[str, float | None] = {}
        extra_tier_strict_prefix_proof_sources: dict[str, str | None] = {}
        extra_tier_strict_prefix_tps_gains: dict[str, float | None] = {}
        extra_tier_strict_prefix_estimated_total_tps: dict[str, float | None] = {}
        extra_tier_strict_prefix_estimated_card_counts_for_same_load: dict[str, float | None] = {}
        extra_tier_strict_prefix_estimated_machine_counts_for_same_load: dict[str, float | None] = {}
        extra_tier_lru_tps_gains: dict[str, float | None] = {}
        extra_tier_lru_estimated_total_tps: dict[str, float | None] = {}
        extra_tier_lru_estimated_card_counts_for_same_load: dict[str, float | None] = {}
        extra_tier_lru_estimated_machine_counts_for_same_load: dict[str, float | None] = {}
        extra_tier_strict_prefix_current_cluster_capacity_tps: dict[str, float | None] = {}
        extra_tier_strict_prefix_min_card_counts_for_target_total_tps: dict[str, int | None] = {}
        extra_tier_strict_prefix_min_machine_counts_for_target_total_tps: dict[str, int | None] = {}
        extra_tier_lru_current_cluster_capacity_tps: dict[str, float | None] = {}
        extra_tier_lru_min_card_counts_for_target_total_tps: dict[str, int | None] = {}
        extra_tier_lru_min_machine_counts_for_target_total_tps: dict[str, int | None] = {}
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

            total_budget_gb = hbm_kv_total_gb + node_count * tier.kv_gb_per_machine
            lru_result = analyze_lru_baseline(
                normalized.requests,
                model_profile=config.model_profile,
                budget_bytes=_gb_to_bytes(total_budget_gb),
                block_size=config.block_size,
            )
            extra_capacity_results[tier.label] = capacity_result
            extra_lru_results[tier.label] = lru_result
            extra_strict_prefix_results[tier.label] = strict_prefix_result
            extra_tier_relaxed_upper_bound_hit_rates[tier.label] = (
                None if not has_bucket_records else capacity_result.summary.block_hit_rate
            )
            extra_tier_lru_hit_rates[tier.label] = (
                None if not has_bucket_records else lru_result.summary.strict_prefix_block_hit_rate
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
            extra_tier_strict_prefix_tps_gains[tier.label] = tps_gain(
                extra_tier_strict_prefix_hit_rates[tier.label],
                config.prefill_savings_alpha,
            )
            extra_tier_strict_prefix_estimated_total_tps[tier.label] = estimated_total_tps(
                resolved_total_tps,
                extra_tier_strict_prefix_tps_gains[tier.label],
            )
            extra_tier_strict_prefix_estimated_card_counts_for_same_load[tier.label] = estimated_card_count(
                deployment.accelerator_count,
                extra_tier_strict_prefix_tps_gains[tier.label],
            )
            extra_tier_strict_prefix_estimated_machine_counts_for_same_load[tier.label] = estimated_machine_count(
                extra_tier_strict_prefix_estimated_card_counts_for_same_load[tier.label],
                deployment.cards_per_machine,
            )
            extra_tier_lru_tps_gains[tier.label] = tps_gain(
                extra_tier_lru_hit_rates[tier.label],
                config.prefill_savings_alpha,
            )
            extra_tier_lru_estimated_total_tps[tier.label] = estimated_total_tps(
                resolved_total_tps,
                extra_tier_lru_tps_gains[tier.label],
            )
            extra_tier_lru_estimated_card_counts_for_same_load[tier.label] = estimated_card_count(
                deployment.accelerator_count,
                extra_tier_lru_tps_gains[tier.label],
            )
            extra_tier_lru_estimated_machine_counts_for_same_load[tier.label] = estimated_machine_count(
                extra_tier_lru_estimated_card_counts_for_same_load[tier.label],
                deployment.cards_per_machine,
            )
            tier_hit_rate_cache: dict[int, tuple[float | None, float | None]] = {
                node_count: (
                    extra_tier_strict_prefix_hit_rates[tier.label],
                    extra_tier_lru_hit_rates[tier.label],
                )
            }

            def _tier_cluster_capacity_tps(
                machine_count: int,
                *,
                policy: str,
            ) -> float | None:
                strict_hit_rate, lru_hit_rate = tier_hit_rate_cache.get(machine_count, (None, None))
                if machine_count not in tier_hit_rate_cache:
                    if not has_bucket_records:
                        tier_hit_rate_cache[machine_count] = (None, None)
                        strict_hit_rate, lru_hit_rate = tier_hit_rate_cache[machine_count]
                    else:
                        candidate_card_count = machine_count * deployment.cards_per_machine
                        candidate_total_budget_gb = (
                            candidate_card_count * hbm_kv_gb_per_card
                            + machine_count * tier.kv_gb_per_machine
                        )
                        strict_result = analyze_strict_prefix_capacity_upper_bound(
                            normalized.requests,
                            model_profile=config.model_profile,
                            budget_bytes=_gb_to_bytes(candidate_total_budget_gb),
                            block_size=config.block_size,
                        )
                        lru_result = analyze_lru_baseline(
                            normalized.requests,
                            model_profile=config.model_profile,
                            budget_bytes=_gb_to_bytes(candidate_total_budget_gb),
                            block_size=config.block_size,
                        )
                        strict_hit_rate = strict_result.summary.block_hit_rate
                        lru_hit_rate = lru_result.summary.strict_prefix_block_hit_rate
                        tier_hit_rate_cache[machine_count] = (strict_hit_rate, lru_hit_rate)
                hit_rate = strict_hit_rate if policy == "strict_prefix" else lru_hit_rate
                return cluster_capacity_tps(
                    card_count=machine_count * deployment.cards_per_machine,
                    baseline_per_card_tps=baseline_per_card_tps,
                    hit_rate=hit_rate,
                    alpha=config.prefill_savings_alpha,
                )

            strict_prefix_target_plan = build_target_tps_plan(
                target_total_tps=planning_target_total_tps,
                baseline_per_card_tps=baseline_per_card_tps,
                current_machine_count=node_count,
                cards_per_machine=deployment.cards_per_machine,
                cluster_tps_at_machine_count=lambda machine_count: _tier_cluster_capacity_tps(
                    machine_count,
                    policy="strict_prefix",
                ),
            )
            lru_target_plan = build_target_tps_plan(
                target_total_tps=planning_target_total_tps,
                baseline_per_card_tps=baseline_per_card_tps,
                current_machine_count=node_count,
                cards_per_machine=deployment.cards_per_machine,
                cluster_tps_at_machine_count=lambda machine_count: _tier_cluster_capacity_tps(
                    machine_count,
                    policy="lru",
                ),
            )
            extra_tier_strict_prefix_current_cluster_capacity_tps[tier.label] = (
                strict_prefix_target_plan.current_cluster_capacity_tps
            )
            extra_tier_strict_prefix_min_card_counts_for_target_total_tps[tier.label] = (
                strict_prefix_target_plan.min_card_count
            )
            extra_tier_strict_prefix_min_machine_counts_for_target_total_tps[tier.label] = (
                strict_prefix_target_plan.min_machine_count
            )
            extra_tier_lru_current_cluster_capacity_tps[tier.label] = (
                lru_target_plan.current_cluster_capacity_tps
            )
            extra_tier_lru_min_card_counts_for_target_total_tps[tier.label] = (
                lru_target_plan.min_card_count
            )
            extra_tier_lru_min_machine_counts_for_target_total_tps[tier.label] = (
                lru_target_plan.min_machine_count
            )

        hbm_relaxed_upper_bound_hit_rate = (
            None if not has_bucket_records else hbm_capacity_result.summary.block_hit_rate
        )
        hbm_lru_hit_rate = (
            None if not has_bucket_records else hbm_lru_result.summary.strict_prefix_block_hit_rate
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
        hbm_strict_prefix_tps_gain = tps_gain(
            hbm_strict_prefix_hit_rate,
            config.prefill_savings_alpha,
        )
        hbm_strict_prefix_estimated_total_tps = estimated_total_tps(
            resolved_total_tps,
            hbm_strict_prefix_tps_gain,
        )
        hbm_strict_prefix_estimated_card_count_for_same_load = estimated_card_count(
            deployment.accelerator_count,
            hbm_strict_prefix_tps_gain,
        )
        hbm_strict_prefix_estimated_machine_count_for_same_load = estimated_machine_count(
            hbm_strict_prefix_estimated_card_count_for_same_load,
            deployment.cards_per_machine,
        )
        hbm_lru_tps_gain = tps_gain(hbm_lru_hit_rate, config.prefill_savings_alpha)
        hbm_lru_estimated_total_tps = estimated_total_tps(resolved_total_tps, hbm_lru_tps_gain)
        hbm_lru_estimated_card_count_for_same_load = estimated_card_count(
            deployment.accelerator_count,
            hbm_lru_tps_gain,
        )
        hbm_lru_estimated_machine_count_for_same_load = estimated_machine_count(
            hbm_lru_estimated_card_count_for_same_load,
            deployment.cards_per_machine,
        )
        hbm_hit_rate_cache: dict[int, tuple[float | None, float | None]] = {
            node_count: (
                hbm_strict_prefix_hit_rate,
                hbm_lru_hit_rate,
            )
        }

        def _hbm_cluster_capacity_tps(
            machine_count: int,
            *,
            policy: str,
        ) -> float | None:
            strict_hit_rate, lru_hit_rate = hbm_hit_rate_cache.get(machine_count, (None, None))
            if machine_count not in hbm_hit_rate_cache:
                if not has_bucket_records:
                    hbm_hit_rate_cache[machine_count] = (None, None)
                    strict_hit_rate, lru_hit_rate = hbm_hit_rate_cache[machine_count]
                else:
                    candidate_card_count = machine_count * deployment.cards_per_machine
                    candidate_total_budget_gb = candidate_card_count * hbm_kv_gb_per_card
                    strict_result = analyze_strict_prefix_capacity_upper_bound(
                        normalized.requests,
                        model_profile=config.model_profile,
                        budget_bytes=_gb_to_bytes(candidate_total_budget_gb),
                        block_size=config.block_size,
                    )
                    lru_result = analyze_lru_baseline(
                        normalized.requests,
                        model_profile=config.model_profile,
                        budget_bytes=_gb_to_bytes(candidate_total_budget_gb),
                        block_size=config.block_size,
                    )
                    strict_hit_rate = strict_result.summary.block_hit_rate
                    lru_hit_rate = lru_result.summary.strict_prefix_block_hit_rate
                    hbm_hit_rate_cache[machine_count] = (strict_hit_rate, lru_hit_rate)
            hit_rate = strict_hit_rate if policy == "strict_prefix" else lru_hit_rate
            return cluster_capacity_tps(
                card_count=machine_count * deployment.cards_per_machine,
                baseline_per_card_tps=baseline_per_card_tps,
                hit_rate=hit_rate,
                alpha=config.prefill_savings_alpha,
            )

        hbm_strict_prefix_target_plan = build_target_tps_plan(
            target_total_tps=planning_target_total_tps,
            baseline_per_card_tps=baseline_per_card_tps,
            current_machine_count=node_count,
            cards_per_machine=deployment.cards_per_machine,
            cluster_tps_at_machine_count=lambda machine_count: _hbm_cluster_capacity_tps(
                machine_count,
                policy="strict_prefix",
            ),
        )
        hbm_lru_target_plan = build_target_tps_plan(
            target_total_tps=planning_target_total_tps,
            baseline_per_card_tps=baseline_per_card_tps,
            current_machine_count=node_count,
            cards_per_machine=deployment.cards_per_machine,
            cluster_tps_at_machine_count=lambda machine_count: _hbm_cluster_capacity_tps(
                machine_count,
                policy="lru",
            ),
        )

        row = BucketReportRow(
            bucket_label=deployment.label,
            machine_count=node_count,
            card_count=deployment.accelerator_count,
            cards_per_machine=deployment.cards_per_machine,
            machine_spec=deployment.machine_spec,
            total_tps=resolved_total_tps,
            total_tps_input_unit=None if deployment.total_tps is None else deployment.total_tps_unit,
            planning_target_total_tps=planning_target_total_tps,
            baseline_per_card_tps=baseline_per_card_tps,
            prefill_savings_alpha=config.prefill_savings_alpha,
            hbm_kv_gb_per_card=hbm_kv_gb_per_card,
            hbm_kv_total_gb=hbm_kv_total_gb,
            model_weight_gb_per_card=model_weight_gb_per_card,
            extreme_hit_rate=None if not has_bucket_records else content_result.summary.block_hit_rate,
            actual_hit_rate=deployment.actual_hit_rate,
            actual_hit_rate_note=deployment.actual_hit_rate_note,
            hbm_relaxed_upper_bound_hit_rate=hbm_relaxed_upper_bound_hit_rate,
            hbm_lru_hit_rate=hbm_lru_hit_rate,
            hbm_strict_prefix_replay_hit_rate=hbm_strict_prefix_replay_hit_rate,
            hbm_strict_prefix_hit_rate=hbm_strict_prefix_hit_rate,
            hbm_strict_prefix_proof_source=hbm_strict_prefix_proof_source,
            hbm_strict_prefix_tps_gain=hbm_strict_prefix_tps_gain,
            hbm_strict_prefix_estimated_total_tps=hbm_strict_prefix_estimated_total_tps,
            hbm_strict_prefix_estimated_card_count_for_same_load=hbm_strict_prefix_estimated_card_count_for_same_load,
            hbm_strict_prefix_estimated_machine_count_for_same_load=hbm_strict_prefix_estimated_machine_count_for_same_load,
            hbm_lru_tps_gain=hbm_lru_tps_gain,
            hbm_lru_estimated_total_tps=hbm_lru_estimated_total_tps,
            hbm_lru_estimated_card_count_for_same_load=hbm_lru_estimated_card_count_for_same_load,
            hbm_lru_estimated_machine_count_for_same_load=hbm_lru_estimated_machine_count_for_same_load,
            hbm_strict_prefix_current_cluster_capacity_tps=hbm_strict_prefix_target_plan.current_cluster_capacity_tps,
            hbm_strict_prefix_min_card_count_for_target_total_tps=hbm_strict_prefix_target_plan.min_card_count,
            hbm_strict_prefix_min_machine_count_for_target_total_tps=hbm_strict_prefix_target_plan.min_machine_count,
            hbm_lru_current_cluster_capacity_tps=hbm_lru_target_plan.current_cluster_capacity_tps,
            hbm_lru_min_card_count_for_target_total_tps=hbm_lru_target_plan.min_card_count,
            hbm_lru_min_machine_count_for_target_total_tps=hbm_lru_target_plan.min_machine_count,
            extra_tier_relaxed_upper_bound_hit_rates=extra_tier_relaxed_upper_bound_hit_rates,
            extra_tier_lru_hit_rates=extra_tier_lru_hit_rates,
            extra_tier_strict_prefix_replay_hit_rates=extra_tier_strict_prefix_replay_hit_rates,
            extra_tier_strict_prefix_hit_rates=extra_tier_strict_prefix_hit_rates,
            extra_tier_strict_prefix_proof_sources=extra_tier_strict_prefix_proof_sources,
            extra_tier_strict_prefix_tps_gains=extra_tier_strict_prefix_tps_gains,
            extra_tier_strict_prefix_estimated_total_tps=extra_tier_strict_prefix_estimated_total_tps,
            extra_tier_strict_prefix_estimated_card_counts_for_same_load=extra_tier_strict_prefix_estimated_card_counts_for_same_load,
            extra_tier_strict_prefix_estimated_machine_counts_for_same_load=extra_tier_strict_prefix_estimated_machine_counts_for_same_load,
            extra_tier_lru_tps_gains=extra_tier_lru_tps_gains,
            extra_tier_lru_estimated_total_tps=extra_tier_lru_estimated_total_tps,
            extra_tier_lru_estimated_card_counts_for_same_load=extra_tier_lru_estimated_card_counts_for_same_load,
            extra_tier_lru_estimated_machine_counts_for_same_load=extra_tier_lru_estimated_machine_counts_for_same_load,
            extra_tier_strict_prefix_current_cluster_capacity_tps=extra_tier_strict_prefix_current_cluster_capacity_tps,
            extra_tier_strict_prefix_min_card_counts_for_target_total_tps=extra_tier_strict_prefix_min_card_counts_for_target_total_tps,
            extra_tier_strict_prefix_min_machine_counts_for_target_total_tps=extra_tier_strict_prefix_min_machine_counts_for_target_total_tps,
            extra_tier_lru_current_cluster_capacity_tps=extra_tier_lru_current_cluster_capacity_tps,
            extra_tier_lru_min_card_counts_for_target_total_tps=extra_tier_lru_min_card_counts_for_target_total_tps,
            extra_tier_lru_min_machine_counts_for_target_total_tps=extra_tier_lru_min_machine_counts_for_target_total_tps,
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
            hbm_lru_result=hbm_lru_result,
            hbm_strict_prefix_result=hbm_strict_prefix_result,
            extra_capacity_results=extra_capacity_results,
            extra_lru_results=extra_lru_results,
            extra_strict_prefix_results=extra_strict_prefix_results,
        )

    return BucketAnalysisResult(rows=rows, details=details)


def _gb_to_bytes(value_gb: float) -> int:
    return int(value_gb * BYTES_PER_GB)
