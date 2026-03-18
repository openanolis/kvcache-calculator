from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache

from kvcache_upper_bound.core.models import ModelProfile
from kvcache_upper_bound.reporting.planning_search import (
    build_target_tps_plan,
    cluster_capacity_tps,
    estimated_total_tps,
    tps_gain,
)
from kvcache_upper_bound.reporting.table_common import (
    bottleneck_label,
    lru_reaches_strict_prefix,
    rate_delta,
    strict_prefix_reaches_content_ceiling,
)

BYTES_PER_GB = 1024**3
VALID_CURVE_MODES = ("linear", "power_law_fit", "zipf_harmonic")
VALID_TOTAL_TPS_UNITS = ("cluster_total", "per_machine", "per_card")


@dataclass(frozen=True)
class HeuristicCapacityTier:
    label: str
    kv_gb_per_machine: float


@dataclass(frozen=True)
class PolicyEfficiency:
    strict_prefix_upper_bound: float = 1.0
    lru_like: float = 0.55


@dataclass(frozen=True)
class CurveShapeConfig:
    mode: str = "zipf_harmonic"
    zipf_s: float = 1.3
    zipf_population_blocks: int = 4096
    power_law_beta: float | None = None

    def resolved_power_law_beta(self) -> float:
        if self.power_law_beta is not None:
            return self.power_law_beta
        if self.zipf_s <= 1.0:
            raise ValueError("zipf_s must be greater than 1 to derive power_law_beta")
        return 1.0 - 1.0 / self.zipf_s


@dataclass(frozen=True)
class MultiAgentHeuristicConfig:
    concurrent_agents: int
    shared_prefix_tokens: float
    avg_new_tokens_per_turn: float
    avg_turns_per_session: int
    private_window_tokens: float
    curve_shape: CurveShapeConfig = field(default_factory=CurveShapeConfig)
    policy_efficiency: PolicyEfficiency = field(default_factory=PolicyEfficiency)

    def average_reusable_private_tokens_per_agent(self) -> float:
        if self.avg_turns_per_session <= 0:
            raise ValueError("avg_turns_per_session must be positive")
        total = 0.0
        for step in range(self.avg_turns_per_session):
            total += min(self.private_window_tokens, step * self.avg_new_tokens_per_turn)
        return total / self.avg_turns_per_session

    def average_request_tokens(self) -> float:
        return (
            self.shared_prefix_tokens
            + self.avg_new_tokens_per_turn
            + self.average_reusable_private_tokens_per_agent()
        )

    def total_private_working_set_tokens(self) -> float:
        return self.concurrent_agents * self.average_reusable_private_tokens_per_agent()

    def total_working_set_tokens(self) -> float:
        return self.shared_prefix_tokens + self.total_private_working_set_tokens()

    def content_hit_rate(self) -> float:
        average_request_tokens = self.average_request_tokens()
        if average_request_tokens <= 0.0:
            return 0.0
        hit_tokens = self.shared_prefix_tokens + self.average_reusable_private_tokens_per_agent()
        return min(1.0, hit_tokens / average_request_tokens)

    def strict_saturation_capacity_tokens(self) -> float:
        return self.shared_prefix_tokens + self.total_private_working_set_tokens()

    def policy_saturation_capacity_tokens(self, efficiency: float) -> float:
        if efficiency <= 0.0:
            return math.inf
        return self.shared_prefix_tokens + self.total_private_working_set_tokens() / efficiency


@dataclass(frozen=True)
class HeuristicDeploymentConfig:
    label: str
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
    extra_capacity_tiers: tuple[HeuristicCapacityTier, ...] = field(default_factory=tuple)

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


@dataclass(frozen=True)
class HeuristicAnalysisConfig:
    model_profile: ModelProfile
    heuristic: MultiAgentHeuristicConfig
    deployments: tuple[HeuristicDeploymentConfig, ...]
    prefill_savings_alpha: float = 0.8


@dataclass(frozen=True)
class HeuristicTierRow:
    scenario_label: str
    tier_label: str
    machine_count: int
    card_count: int
    cards_per_machine: int
    machine_spec: str
    total_tps: float | None
    total_tps_input_unit: str | None
    planning_target_total_tps: float | None
    baseline_per_card_tps: float | None
    prefill_savings_alpha: float
    curve_mode: str
    zipf_s: float
    power_law_beta: float
    lru_like_efficiency: float
    hbm_kv_gb_per_card: float
    total_kv_gb: float
    total_kv_tokens: float
    shared_prefix_tokens: float
    avg_reusable_private_tokens_per_agent: float
    total_private_working_set_tokens: float
    total_working_set_tokens: float
    average_request_tokens: float
    content_hit_rate: float
    strict_prefix_hit_rate: float
    lru_like_hit_rate: float
    strict_prefix_hits_content_ceiling: bool
    lru_like_hits_strict_prefix: bool
    current_bottleneck: str
    strict_prefix_gain_from_previous_tier: float | None
    lru_like_gain_from_previous_tier: float | None
    strict_prefix_tps_gain: float | None
    lru_like_tps_gain: float | None
    strict_prefix_estimated_total_tps: float | None
    lru_like_estimated_total_tps: float | None
    strict_prefix_current_cluster_capacity_tps: float | None
    strict_prefix_min_card_count_for_target_total_tps: int | None
    strict_prefix_min_machine_count_for_target_total_tps: int | None
    lru_like_current_cluster_capacity_tps: float | None
    lru_like_min_card_count_for_target_total_tps: int | None
    lru_like_min_machine_count_for_target_total_tps: int | None
    strict_prefix_saturation_capacity_tokens: float
    lru_like_saturation_capacity_tokens: float
    strict_prefix_saturation_capacity_gb: float
    lru_like_saturation_capacity_gb: float


@dataclass(frozen=True)
class HeuristicScenarioSummary:
    scenario_label: str
    machine_count: int
    card_count: int
    cards_per_machine: int
    machine_spec: str
    total_tps: float | None
    total_tps_input_unit: str | None
    planning_target_total_tps: float | None
    baseline_per_card_tps: float | None
    prefill_savings_alpha: float
    curve_mode: str
    zipf_s: float
    power_law_beta: float
    lru_like_efficiency: float
    hbm_kv_gb_per_card: float
    hbm_total_kv_gb: float
    hbm_total_kv_tokens: float
    shared_prefix_tokens: float
    avg_reusable_private_tokens_per_agent: float
    total_private_working_set_tokens: float
    total_working_set_tokens: float
    average_request_tokens: float
    content_hit_rate: float
    hbm_strict_prefix_hit_rate: float
    hbm_lru_like_hit_rate: float
    hbm_strict_prefix_hits_content_ceiling: bool
    hbm_lru_like_hits_strict_prefix: bool
    hbm_current_bottleneck: str
    hbm_strict_prefix_tps_gain: float | None
    hbm_lru_like_tps_gain: float | None
    hbm_strict_prefix_estimated_total_tps: float | None
    hbm_lru_like_estimated_total_tps: float | None
    strict_prefix_saturation_capacity_tokens: float
    lru_like_saturation_capacity_tokens: float
    strict_prefix_saturation_capacity_gb: float
    lru_like_saturation_capacity_gb: float
    hbm_strict_prefix_current_cluster_capacity_tps: float | None
    hbm_strict_prefix_min_card_count_for_target_total_tps: int | None
    hbm_strict_prefix_min_machine_count_for_target_total_tps: int | None
    hbm_lru_like_current_cluster_capacity_tps: float | None
    hbm_lru_like_min_card_count_for_target_total_tps: int | None
    hbm_lru_like_min_machine_count_for_target_total_tps: int | None


@dataclass(frozen=True)
class HeuristicAnalysisResult:
    scenario_summaries: list[HeuristicScenarioSummary]
    tier_rows: list[HeuristicTierRow]


def analyze_multi_agent_heuristic(config: HeuristicAnalysisConfig) -> HeuristicAnalysisResult:
    scenario_summaries: list[HeuristicScenarioSummary] = []
    tier_rows: list[HeuristicTierRow] = []
    kv_bytes_per_token = config.model_profile.kv_bytes_per_token()
    heuristic = config.heuristic
    strict_capacity_tokens = heuristic.strict_saturation_capacity_tokens()
    lru_capacity_tokens = heuristic.policy_saturation_capacity_tokens(
        heuristic.policy_efficiency.lru_like
    )
    strict_capacity_gb = _tokens_to_gb(strict_capacity_tokens, kv_bytes_per_token)
    lru_capacity_gb = _tokens_to_gb(lru_capacity_tokens, kv_bytes_per_token)
    content_hit_rate = heuristic.content_hit_rate()
    average_private_tokens = heuristic.average_reusable_private_tokens_per_agent()
    total_private_tokens = heuristic.total_private_working_set_tokens()
    total_working_set_tokens = heuristic.total_working_set_tokens()
    average_request_tokens = heuristic.average_request_tokens()
    power_law_beta = config.heuristic.curve_shape.resolved_power_law_beta()

    for deployment in config.deployments:
        machine_count = deployment.node_count()
        hbm_kv_gb_per_card = deployment.resolved_hbm_kv_gb_per_card(config.model_profile)
        previous_strict_hit_rate: float | None = None
        previous_lru_hit_rate: float | None = None
        scenario_rows: list[HeuristicTierRow] = []
        tier_specs = [(deployment.label, 0.0)] + [
            (tier.label, tier.kv_gb_per_machine) for tier in deployment.extra_capacity_tiers
        ]
        resolved_total_tps = deployment.resolved_total_tps()
        planning_target_total_tps = deployment.resolved_planning_target_total_tps()
        baseline_per_card_tps = deployment.baseline_per_card_tps

        for tier_label, extra_kv_gb_per_machine in tier_specs:
            total_kv_gb = (
                deployment.accelerator_count * hbm_kv_gb_per_card
                + machine_count * extra_kv_gb_per_machine
            )
            total_kv_tokens = _gb_to_tokens(total_kv_gb, kv_bytes_per_token)
            strict_hit_rate = _hit_rate_for_capacity_tokens(
                capacity_tokens=total_kv_tokens,
                heuristic=heuristic,
                efficiency=heuristic.policy_efficiency.strict_prefix_upper_bound,
            )
            lru_hit_rate = _hit_rate_for_capacity_tokens(
                capacity_tokens=total_kv_tokens,
                heuristic=heuristic,
                efficiency=heuristic.policy_efficiency.lru_like,
            )
            strict_tps_gain = tps_gain(strict_hit_rate, config.prefill_savings_alpha)
            lru_tps_gain = tps_gain(lru_hit_rate, config.prefill_savings_alpha)
            strict_estimated_total_tps = estimated_total_tps(resolved_total_tps, strict_tps_gain)
            lru_estimated_total_tps = estimated_total_tps(resolved_total_tps, lru_tps_gain)

            def _cluster_capacity_tps(machine_count_value: int, *, efficiency: float) -> float | None:
                candidate_card_count = machine_count_value * deployment.cards_per_machine
                candidate_total_kv_gb = (
                    candidate_card_count * hbm_kv_gb_per_card
                    + machine_count_value * extra_kv_gb_per_machine
                )
                candidate_total_kv_tokens = _gb_to_tokens(candidate_total_kv_gb, kv_bytes_per_token)
                candidate_hit_rate = _hit_rate_for_capacity_tokens(
                    capacity_tokens=candidate_total_kv_tokens,
                    heuristic=heuristic,
                    efficiency=efficiency,
                )
                return cluster_capacity_tps(
                    card_count=candidate_card_count,
                    baseline_per_card_tps=baseline_per_card_tps,
                    hit_rate=candidate_hit_rate,
                    alpha=config.prefill_savings_alpha,
                )

            strict_target_plan = build_target_tps_plan(
                target_total_tps=planning_target_total_tps,
                baseline_per_card_tps=baseline_per_card_tps,
                current_machine_count=machine_count,
                cards_per_machine=deployment.cards_per_machine,
                cluster_tps_at_machine_count=lambda machine_count_value: _cluster_capacity_tps(
                    machine_count_value,
                    efficiency=heuristic.policy_efficiency.strict_prefix_upper_bound,
                ),
            )
            lru_target_plan = build_target_tps_plan(
                target_total_tps=planning_target_total_tps,
                baseline_per_card_tps=baseline_per_card_tps,
                current_machine_count=machine_count,
                cards_per_machine=deployment.cards_per_machine,
                cluster_tps_at_machine_count=lambda machine_count_value: _cluster_capacity_tps(
                    machine_count_value,
                    efficiency=heuristic.policy_efficiency.lru_like,
                ),
            )

            scenario_rows.append(
                HeuristicTierRow(
                    scenario_label=deployment.label,
                    tier_label="HBM" if extra_kv_gb_per_machine == 0.0 else _strip_rate_suffix(tier_label),
                    machine_count=machine_count,
                    card_count=deployment.accelerator_count,
                    cards_per_machine=deployment.cards_per_machine,
                    machine_spec=deployment.machine_spec,
                    total_tps=resolved_total_tps,
                    total_tps_input_unit=None
                    if deployment.total_tps is None
                    else deployment.total_tps_unit,
                    planning_target_total_tps=planning_target_total_tps,
                    baseline_per_card_tps=baseline_per_card_tps,
                    prefill_savings_alpha=config.prefill_savings_alpha,
                    curve_mode=heuristic.curve_shape.mode,
                    zipf_s=heuristic.curve_shape.zipf_s,
                    power_law_beta=power_law_beta,
                    lru_like_efficiency=heuristic.policy_efficiency.lru_like,
                    hbm_kv_gb_per_card=hbm_kv_gb_per_card,
                    total_kv_gb=total_kv_gb,
                    total_kv_tokens=total_kv_tokens,
                    shared_prefix_tokens=heuristic.shared_prefix_tokens,
                    avg_reusable_private_tokens_per_agent=average_private_tokens,
                    total_private_working_set_tokens=total_private_tokens,
                    total_working_set_tokens=total_working_set_tokens,
                    average_request_tokens=average_request_tokens,
                    content_hit_rate=content_hit_rate,
                    strict_prefix_hit_rate=strict_hit_rate,
                    lru_like_hit_rate=lru_hit_rate,
                    strict_prefix_hits_content_ceiling=bool(
                        strict_prefix_reaches_content_ceiling(strict_hit_rate, content_hit_rate)
                    ),
                    lru_like_hits_strict_prefix=bool(
                        lru_reaches_strict_prefix(lru_hit_rate, strict_hit_rate)
                    ),
                    current_bottleneck=bottleneck_label(
                        content_hit_rate=content_hit_rate,
                        strict_prefix_hit_rate=strict_hit_rate,
                        lru_hit_rate=lru_hit_rate,
                    ),
                    strict_prefix_gain_from_previous_tier=rate_delta(
                        strict_hit_rate,
                        previous_strict_hit_rate,
                    ),
                    lru_like_gain_from_previous_tier=rate_delta(
                        lru_hit_rate,
                        previous_lru_hit_rate,
                    ),
                    strict_prefix_tps_gain=strict_tps_gain,
                    lru_like_tps_gain=lru_tps_gain,
                    strict_prefix_estimated_total_tps=strict_estimated_total_tps,
                    lru_like_estimated_total_tps=lru_estimated_total_tps,
                    strict_prefix_current_cluster_capacity_tps=strict_target_plan.current_cluster_capacity_tps,
                    strict_prefix_min_card_count_for_target_total_tps=strict_target_plan.min_card_count,
                    strict_prefix_min_machine_count_for_target_total_tps=strict_target_plan.min_machine_count,
                    lru_like_current_cluster_capacity_tps=lru_target_plan.current_cluster_capacity_tps,
                    lru_like_min_card_count_for_target_total_tps=lru_target_plan.min_card_count,
                    lru_like_min_machine_count_for_target_total_tps=lru_target_plan.min_machine_count,
                    strict_prefix_saturation_capacity_tokens=strict_capacity_tokens,
                    lru_like_saturation_capacity_tokens=lru_capacity_tokens,
                    strict_prefix_saturation_capacity_gb=strict_capacity_gb,
                    lru_like_saturation_capacity_gb=lru_capacity_gb,
                )
            )
            previous_strict_hit_rate = strict_hit_rate
            previous_lru_hit_rate = lru_hit_rate

        tier_rows.extend(scenario_rows)
        hbm_row = scenario_rows[0]
        scenario_summaries.append(
            HeuristicScenarioSummary(
                scenario_label=hbm_row.scenario_label,
                machine_count=hbm_row.machine_count,
                card_count=hbm_row.card_count,
                cards_per_machine=hbm_row.cards_per_machine,
                machine_spec=hbm_row.machine_spec,
                total_tps=hbm_row.total_tps,
                total_tps_input_unit=hbm_row.total_tps_input_unit,
                planning_target_total_tps=hbm_row.planning_target_total_tps,
                baseline_per_card_tps=hbm_row.baseline_per_card_tps,
                prefill_savings_alpha=hbm_row.prefill_savings_alpha,
                curve_mode=hbm_row.curve_mode,
                zipf_s=hbm_row.zipf_s,
                power_law_beta=hbm_row.power_law_beta,
                lru_like_efficiency=hbm_row.lru_like_efficiency,
                hbm_kv_gb_per_card=hbm_row.hbm_kv_gb_per_card,
                hbm_total_kv_gb=hbm_row.total_kv_gb,
                hbm_total_kv_tokens=hbm_row.total_kv_tokens,
                shared_prefix_tokens=hbm_row.shared_prefix_tokens,
                avg_reusable_private_tokens_per_agent=hbm_row.avg_reusable_private_tokens_per_agent,
                total_private_working_set_tokens=hbm_row.total_private_working_set_tokens,
                total_working_set_tokens=hbm_row.total_working_set_tokens,
                average_request_tokens=hbm_row.average_request_tokens,
                content_hit_rate=hbm_row.content_hit_rate,
                hbm_strict_prefix_hit_rate=hbm_row.strict_prefix_hit_rate,
                hbm_lru_like_hit_rate=hbm_row.lru_like_hit_rate,
                hbm_strict_prefix_hits_content_ceiling=hbm_row.strict_prefix_hits_content_ceiling,
                hbm_lru_like_hits_strict_prefix=hbm_row.lru_like_hits_strict_prefix,
                hbm_current_bottleneck=hbm_row.current_bottleneck,
                hbm_strict_prefix_tps_gain=hbm_row.strict_prefix_tps_gain,
                hbm_lru_like_tps_gain=hbm_row.lru_like_tps_gain,
                hbm_strict_prefix_estimated_total_tps=hbm_row.strict_prefix_estimated_total_tps,
                hbm_lru_like_estimated_total_tps=hbm_row.lru_like_estimated_total_tps,
                strict_prefix_saturation_capacity_tokens=hbm_row.strict_prefix_saturation_capacity_tokens,
                lru_like_saturation_capacity_tokens=hbm_row.lru_like_saturation_capacity_tokens,
                strict_prefix_saturation_capacity_gb=hbm_row.strict_prefix_saturation_capacity_gb,
                lru_like_saturation_capacity_gb=hbm_row.lru_like_saturation_capacity_gb,
                hbm_strict_prefix_current_cluster_capacity_tps=hbm_row.strict_prefix_current_cluster_capacity_tps,
                hbm_strict_prefix_min_card_count_for_target_total_tps=hbm_row.strict_prefix_min_card_count_for_target_total_tps,
                hbm_strict_prefix_min_machine_count_for_target_total_tps=hbm_row.strict_prefix_min_machine_count_for_target_total_tps,
                hbm_lru_like_current_cluster_capacity_tps=hbm_row.lru_like_current_cluster_capacity_tps,
                hbm_lru_like_min_card_count_for_target_total_tps=hbm_row.lru_like_min_card_count_for_target_total_tps,
                hbm_lru_like_min_machine_count_for_target_total_tps=hbm_row.lru_like_min_machine_count_for_target_total_tps,
            )
        )

    return HeuristicAnalysisResult(
        scenario_summaries=scenario_summaries,
        tier_rows=tier_rows,
    )


def _hit_rate_for_capacity_tokens(
    *,
    capacity_tokens: float,
    heuristic: MultiAgentHeuristicConfig,
    efficiency: float,
) -> float:
    if capacity_tokens <= 0.0:
        return 0.0
    average_request_tokens = heuristic.average_request_tokens()
    if average_request_tokens <= 0.0:
        return 0.0
    if capacity_tokens < heuristic.shared_prefix_tokens:
        return min(1.0, capacity_tokens / average_request_tokens)

    average_private_tokens = heuristic.average_reusable_private_tokens_per_agent()
    total_private_tokens = heuristic.total_private_working_set_tokens()
    if total_private_tokens <= 0.0:
        return heuristic.content_hit_rate()

    private_capacity_tokens = max(0.0, capacity_tokens - heuristic.shared_prefix_tokens)
    effective_private_ratio = max(0.0, efficiency * private_capacity_tokens / total_private_tokens)
    private_fraction = _shape_fraction(
        effective_private_ratio,
        heuristic.curve_shape,
    )
    hit_tokens = heuristic.shared_prefix_tokens + private_fraction * average_private_tokens
    return min(heuristic.content_hit_rate(), hit_tokens / average_request_tokens)


def _shape_fraction(ratio: float, curve_shape: CurveShapeConfig) -> float:
    clipped = max(0.0, min(1.0, ratio))
    if clipped <= 0.0:
        return 0.0
    if clipped >= 1.0:
        return 1.0
    if curve_shape.mode == "linear":
        return clipped
    if curve_shape.mode == "power_law_fit":
        return clipped ** curve_shape.resolved_power_law_beta()
    if curve_shape.mode == "zipf_harmonic":
        population_blocks = max(1, curve_shape.zipf_population_blocks)
        cached_blocks = min(population_blocks, max(0, math.floor(clipped * population_blocks)))
        if cached_blocks <= 0:
            return 0.0
        return _generalized_harmonic(cached_blocks, curve_shape.zipf_s) / _generalized_harmonic(
            population_blocks,
            curve_shape.zipf_s,
        )
    raise ValueError(f"unsupported curve mode: {curve_shape.mode}")


@lru_cache(maxsize=512)
def _generalized_harmonic(n: int, s: float) -> float:
    return sum(1.0 / (index**s) for index in range(1, n + 1))


def _gb_to_tokens(value_gb: float, kv_bytes_per_token: int) -> float:
    return value_gb * BYTES_PER_GB / kv_bytes_per_token


def _tokens_to_gb(tokens: float, kv_bytes_per_token: int) -> float:
    return tokens * kv_bytes_per_token / BYTES_PER_GB


def _strip_rate_suffix(label: str) -> str:
    suffix = " 命中率"
    if label.endswith(suffix):
        return label[: -len(suffix)]
    return label
