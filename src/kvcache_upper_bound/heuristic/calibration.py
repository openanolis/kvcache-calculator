from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kvcache_upper_bound.core.models import ModelProfile
from kvcache_upper_bound.reporting.table_common import format_delta_pp, format_number, format_rate

from .multi_agent import (
    CurveShapeConfig,
    HeuristicAnalysisConfig,
    HeuristicAnalysisResult,
    HeuristicCapacityTier,
    HeuristicDeploymentConfig,
    MultiAgentHeuristicConfig,
    PolicyEfficiency,
    analyze_multi_agent_heuristic,
)
from .structure import TraceStructureRecommendation

if TYPE_CHECKING:
    from kvcache_upper_bound.reporting import BucketAnalysisResult

BYTES_PER_GB = 1024**3
CAPACITY_EPSILON_GB = 1e-6
DEFAULT_ZIPF_S_MIN = 1.05
DEFAULT_ZIPF_S_MAX = 1.80
DEFAULT_ZIPF_S_STEP = 0.05
DEFAULT_LRU_LIKE_MIN = 0.35
DEFAULT_LRU_LIKE_MAX = 1.00
DEFAULT_LRU_LIKE_STEP = 0.02


@dataclass(frozen=True)
class CalibrationTierTarget:
    tier_label: str
    total_kv_gb: float
    strict_prefix_hit_rate: float
    lru_like_hit_rate: float


@dataclass(frozen=True)
class CalibrationTraceTarget:
    bucket_count: int
    bucket_labels: tuple[str, ...]
    machine_count: int
    card_count: int
    cards_per_machine: int
    machine_spec: str
    total_tps: float | None
    total_tps_input_unit: str | None
    planning_target_total_tps: float | None
    baseline_per_card_tps: float | None
    hbm_kv_gb_per_card: float
    content_hit_rate: float
    tiers: tuple[CalibrationTierTarget, ...]

    @property
    def hbm_total_kv_gb(self) -> float:
        return self.tiers[0].total_kv_gb

    def hbm_total_kv_tokens(self, model_profile: ModelProfile) -> float:
        return self.hbm_total_kv_gb * BYTES_PER_GB / model_profile.kv_bytes_per_token()


@dataclass(frozen=True)
class CalibrationGrid:
    zipf_s_values: tuple[float, ...]
    lru_like_values: tuple[float, ...]

    @property
    def trial_count(self) -> int:
        return len(self.zipf_s_values) * len(self.lru_like_values)


@dataclass(frozen=True)
class CalibrationTrial:
    zipf_s: float
    power_law_beta: float
    lru_like: float
    objective: float
    rmse_strict: float
    rmse_lru_like: float
    rmse_total: float
    max_abs_error: float
    content_gap: float


@dataclass(frozen=True)
class CalibrationTierComparison:
    tier_label: str
    total_kv_gb: float
    observed_strict_prefix_hit_rate: float
    predicted_strict_prefix_hit_rate: float
    observed_lru_like_hit_rate: float
    predicted_lru_like_hit_rate: float
    strict_prefix_error: float
    lru_like_error: float


@dataclass(frozen=True)
class CalibrationResult:
    target: CalibrationTraceTarget
    grid: CalibrationGrid
    best_trial: CalibrationTrial
    best_tier_comparisons: tuple[CalibrationTierComparison, ...]
    calibrated_config: HeuristicAnalysisConfig
    calibrated_analysis: HeuristicAnalysisResult
    structure_recommendation: TraceStructureRecommendation | None
    trials: list[CalibrationTrial]


def build_default_calibration_grid(*, curve_mode: str) -> CalibrationGrid:
    return build_calibration_grid_from_ranges(
        curve_mode=curve_mode,
        zipf_s_min=DEFAULT_ZIPF_S_MIN,
        zipf_s_max=DEFAULT_ZIPF_S_MAX,
        zipf_s_step=DEFAULT_ZIPF_S_STEP,
        lru_like_min=DEFAULT_LRU_LIKE_MIN,
        lru_like_max=DEFAULT_LRU_LIKE_MAX,
        lru_like_step=DEFAULT_LRU_LIKE_STEP,
    )


def build_calibration_grid_from_ranges(
    *,
    curve_mode: str,
    zipf_s_min: float,
    zipf_s_max: float,
    zipf_s_step: float,
    lru_like_min: float,
    lru_like_max: float,
    lru_like_step: float,
) -> CalibrationGrid:
    zipf_values = (
        _build_float_grid(
            start=zipf_s_min,
            stop=zipf_s_max,
            step=zipf_s_step,
        )
        if curve_mode in ("power_law_fit", "zipf_harmonic")
        else (1.3,)
    )
    lru_like_values = _build_float_grid(
        start=lru_like_min,
        stop=lru_like_max,
        step=lru_like_step,
    )
    return CalibrationGrid(
        zipf_s_values=zipf_values,
        lru_like_values=lru_like_values,
    )


def build_trace_calibration_target(result: BucketAnalysisResult) -> CalibrationTraceTarget:
    if not result.rows:
        raise ValueError("bucket analysis result must not be empty")

    first_row = result.rows[0]
    _validate_consistent_bucket_rows(result)

    content_total_blocks = 0
    content_hit_blocks = 0
    hbm_strict_total_blocks = 0
    hbm_strict_hit_blocks = 0
    hbm_lru_total_blocks = 0
    hbm_lru_hit_blocks = 0
    extra_strict_totals: dict[str, int] = {}
    extra_strict_hits: dict[str, int] = {}
    extra_lru_totals: dict[str, int] = {}
    extra_lru_hits: dict[str, int] = {}

    for row in result.rows:
        detail = result.details[row.bucket_label]
        content_total_blocks += detail.content_result.summary.total_blocks
        content_hit_blocks += detail.content_result.summary.hit_blocks
        hbm_strict_total_blocks += detail.hbm_strict_prefix_result.summary.total_blocks
        hbm_strict_hit_blocks += detail.hbm_strict_prefix_result.summary.hit_blocks
        hbm_lru_total_blocks += detail.hbm_lru_result.summary.total_blocks
        hbm_lru_hit_blocks += detail.hbm_lru_result.summary.strict_prefix_hit_blocks

        for tier in detail.config.extra_capacity_tiers:
            strict_summary = detail.extra_strict_prefix_results[tier.label].summary
            lru_summary = detail.extra_lru_results[tier.label].summary
            extra_strict_totals[tier.label] = extra_strict_totals.get(tier.label, 0) + strict_summary.total_blocks
            extra_strict_hits[tier.label] = extra_strict_hits.get(tier.label, 0) + strict_summary.hit_blocks
            extra_lru_totals[tier.label] = extra_lru_totals.get(tier.label, 0) + lru_summary.total_blocks
            extra_lru_hits[tier.label] = extra_lru_hits.get(tier.label, 0) + lru_summary.strict_prefix_hit_blocks

    content_hit_rate = _safe_ratio(content_hit_blocks, content_total_blocks)
    tiers = [
        CalibrationTierTarget(
            tier_label="HBM",
            total_kv_gb=first_row.hbm_kv_total_gb,
            strict_prefix_hit_rate=_safe_ratio(hbm_strict_hit_blocks, hbm_strict_total_blocks),
            lru_like_hit_rate=_safe_ratio(hbm_lru_hit_blocks, hbm_lru_total_blocks),
        )
    ]
    for tier in result.details[first_row.bucket_label].config.extra_capacity_tiers:
        tiers.append(
            CalibrationTierTarget(
                tier_label=_normalize_tier_label(tier.label),
                total_kv_gb=first_row.hbm_kv_total_gb + first_row.machine_count * tier.kv_gb_per_machine,
                strict_prefix_hit_rate=_safe_ratio(
                    extra_strict_hits[tier.label],
                    extra_strict_totals[tier.label],
                ),
                lru_like_hit_rate=_safe_ratio(
                    extra_lru_hits[tier.label],
                    extra_lru_totals[tier.label],
                ),
            )
        )

    return CalibrationTraceTarget(
        bucket_count=len(result.rows),
        bucket_labels=tuple(row.bucket_label for row in result.rows),
        machine_count=first_row.machine_count,
        card_count=first_row.card_count,
        cards_per_machine=first_row.cards_per_machine,
        machine_spec=first_row.machine_spec,
        total_tps=first_row.total_tps,
        total_tps_input_unit=first_row.total_tps_input_unit,
        planning_target_total_tps=first_row.planning_target_total_tps,
        baseline_per_card_tps=first_row.baseline_per_card_tps,
        hbm_kv_gb_per_card=first_row.hbm_kv_gb_per_card,
        content_hit_rate=content_hit_rate,
        tiers=tuple(tiers),
    )


def calibrate_multi_agent_parameters(
    base_config: HeuristicAnalysisConfig,
    target: CalibrationTraceTarget,
    grid: CalibrationGrid | None = None,
) -> CalibrationResult:
    if len(base_config.deployments) != 1:
        raise ValueError("calibration currently requires exactly one heuristic deployment")

    template_deployment = base_config.deployments[0]
    grid = grid or build_default_calibration_grid(
        curve_mode=base_config.heuristic.curve_shape.mode,
    )

    best_trial: CalibrationTrial | None = None
    best_comparisons: tuple[CalibrationTierComparison, ...] | None = None
    best_config: HeuristicAnalysisConfig | None = None
    best_analysis: HeuristicAnalysisResult | None = None
    trials: list[CalibrationTrial] = []

    for zipf_s in grid.zipf_s_values:
        for lru_like in grid.lru_like_values:
            candidate_heuristic = _build_calibrated_heuristic(
                base_config.heuristic,
                zipf_s=zipf_s,
                lru_like=lru_like,
            )
            candidate_deployment = _build_target_matched_deployment(
                template_deployment,
                target=target,
            )
            candidate_config = HeuristicAnalysisConfig(
                model_profile=base_config.model_profile,
                heuristic=candidate_heuristic,
                deployments=(candidate_deployment,),
                prefill_savings_alpha=base_config.prefill_savings_alpha,
            )
            candidate_analysis = analyze_multi_agent_heuristic(candidate_config)
            comparisons = _build_tier_comparisons(
                target=target,
                analysis=candidate_analysis,
            )
            trial = _build_calibration_trial(
                heuristic=candidate_heuristic,
                target=target,
                comparisons=comparisons,
            )
            trials.append(trial)

            if best_trial is None or _trial_score(trial) < _trial_score(best_trial):
                best_trial = trial
                best_comparisons = comparisons
                best_config = candidate_config
                best_analysis = candidate_analysis

    if best_trial is None or best_comparisons is None or best_config is None or best_analysis is None:
        raise RuntimeError("calibration search produced no trials")

    return CalibrationResult(
        target=target,
        grid=grid,
        best_trial=best_trial,
        best_tier_comparisons=best_comparisons,
        calibrated_config=best_config,
        calibrated_analysis=best_analysis,
        structure_recommendation=None,
        trials=trials,
    )


def write_calibration_outputs(
    result: CalibrationResult,
    output_dir: str | Path,
) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    _write_calibration_json(output_path / "calibration.json", result)
    _write_calibration_trials_csv(output_path / "calibration_trials.csv", result.trials)
    _write_calibrated_config_json(output_path / "calibrated_config.json", result.calibrated_config)
    if result.structure_recommendation is not None:
        _write_calibrated_config_json(
            output_path / "recommended_heuristic_config.json",
            result.structure_recommendation.recommended_config,
        )


def _write_calibration_json(path: Path, result: CalibrationResult) -> None:
    payload = {
        "target": asdict(result.target),
        "grid": asdict(result.grid),
        "best_trial": asdict(result.best_trial),
        "best_tier_comparisons": [asdict(item) for item in result.best_tier_comparisons],
        "structure_recommendation": None
        if result.structure_recommendation is None
        else {
            "hints": asdict(result.structure_recommendation.hints),
            "recommended_config": asdict(result.structure_recommendation.recommended_config),
            "recommended_analysis": {
                "scenario_summaries": [
                    asdict(row)
                    for row in result.structure_recommendation.recommended_analysis.scenario_summaries
                ],
                "tier_rows": [
                    asdict(row)
                    for row in result.structure_recommendation.recommended_analysis.tier_rows
                ],
            },
        },
        "trial_count": len(result.trials),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_calibration_trials_csv(path: Path, trials: list[CalibrationTrial]) -> None:
    fieldnames = [
        "zipf_s",
        "power_law_beta",
        "lru_like",
        "objective",
        "rmse_total",
        "rmse_strict",
        "rmse_lru_like",
        "max_abs_error",
        "content_gap",
    ]
    payloads = [
        {
            "zipf_s": format_number(trial.zipf_s),
            "power_law_beta": format_number(trial.power_law_beta),
            "lru_like": format_number(trial.lru_like),
            "objective": format_number(trial.objective),
            "rmse_total": format_number(trial.rmse_total),
            "rmse_strict": format_number(trial.rmse_strict),
            "rmse_lru_like": format_number(trial.rmse_lru_like),
            "max_abs_error": format_delta_pp(trial.max_abs_error),
            "content_gap": format_delta_pp(trial.content_gap),
        }
        for trial in sorted(trials, key=_trial_score)
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(payloads)


def _write_calibrated_config_json(path: Path, config: HeuristicAnalysisConfig) -> None:
    path.write_text(
        json.dumps(_build_heuristic_config_payload(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _build_heuristic_config_payload(config: HeuristicAnalysisConfig) -> dict[str, Any]:
    return {
        "model_profile": asdict(config.model_profile),
        "prefill_savings_alpha": config.prefill_savings_alpha,
        "heuristic_multi_agent": {
            "concurrent_agents": config.heuristic.concurrent_agents,
            "shared_prefix_tokens": config.heuristic.shared_prefix_tokens,
            "avg_new_tokens_per_turn": config.heuristic.avg_new_tokens_per_turn,
            "avg_turns_per_session": config.heuristic.avg_turns_per_session,
            "private_window_tokens": config.heuristic.private_window_tokens,
            "curve_mode": config.heuristic.curve_shape.mode,
            "zipf_s": config.heuristic.curve_shape.zipf_s,
            "zipf_population_blocks": config.heuristic.curve_shape.zipf_population_blocks,
            "power_law_beta": config.heuristic.curve_shape.power_law_beta,
            "policy_efficiency": asdict(config.heuristic.policy_efficiency),
        },
        "deployments": [
            {
                "label": deployment.label,
                "accelerator_count": deployment.accelerator_count,
                "cards_per_machine": deployment.cards_per_machine,
                "machine_spec": deployment.machine_spec,
                "total_tps": deployment.total_tps,
                "total_tps_unit": deployment.total_tps_unit,
                "planning_target_total_tps": deployment.planning_target_total_tps,
                "baseline_per_card_tps": deployment.baseline_per_card_tps,
                "hbm_kv_gb_per_card": deployment.hbm_kv_gb_per_card,
                "gpu_memory_gb_per_card": deployment.gpu_memory_gb_per_card,
                "hbm_kv_utilization": deployment.hbm_kv_utilization,
                "runtime_reserve_gb_per_card": deployment.runtime_reserve_gb_per_card,
                "extra_capacity_tiers": [
                    {
                        "label": tier.label,
                        "kv_gb_per_machine": tier.kv_gb_per_machine,
                    }
                    for tier in deployment.extra_capacity_tiers
                ],
            }
            for deployment in config.deployments
        ],
    }


def _validate_consistent_bucket_rows(result: BucketAnalysisResult) -> None:
    first_row = result.rows[0]
    reference_tiers = tuple(
        (
            _normalize_tier_label(tier.label),
            tier.kv_gb_per_machine,
        )
        for tier in result.details[first_row.bucket_label].config.extra_capacity_tiers
    )
    for row in result.rows[1:]:
        if row.machine_count != first_row.machine_count:
            raise ValueError("calibration requires identical machine_count across buckets")
        if row.card_count != first_row.card_count:
            raise ValueError("calibration requires identical card_count across buckets")
        if row.cards_per_machine != first_row.cards_per_machine:
            raise ValueError("calibration requires identical cards_per_machine across buckets")
        if row.machine_spec != first_row.machine_spec:
            raise ValueError("calibration requires identical machine_spec across buckets")
        if abs(row.hbm_kv_gb_per_card - first_row.hbm_kv_gb_per_card) > CAPACITY_EPSILON_GB:
            raise ValueError("calibration requires identical HBM KV budgets across buckets")
        tier_labels = tuple(
            (
                _normalize_tier_label(tier.label),
                tier.kv_gb_per_machine,
            )
            for tier in result.details[row.bucket_label].config.extra_capacity_tiers
        )
        if tier_labels != reference_tiers:
            raise ValueError("calibration requires identical extra capacity tiers across buckets")


def _build_target_matched_deployment(
    template: HeuristicDeploymentConfig,
    *,
    target: CalibrationTraceTarget,
) -> HeuristicDeploymentConfig:
    extra_capacity_tiers = tuple(
        HeuristicCapacityTier(
            label=tier.tier_label,
            kv_gb_per_machine=(tier.total_kv_gb - target.hbm_total_kv_gb) / target.machine_count,
        )
        for tier in target.tiers[1:]
    )
    return HeuristicDeploymentConfig(
        label=template.label,
        accelerator_count=target.card_count,
        cards_per_machine=target.cards_per_machine,
        machine_spec=target.machine_spec,
        total_tps=target.total_tps if template.total_tps is None else template.total_tps,
        total_tps_unit=target.total_tps_input_unit or template.total_tps_unit,
        planning_target_total_tps=(
            target.planning_target_total_tps
            if template.planning_target_total_tps is None
            else template.planning_target_total_tps
        ),
        baseline_per_card_tps=(
            target.baseline_per_card_tps
            if template.baseline_per_card_tps is None
            else template.baseline_per_card_tps
        ),
        hbm_kv_gb_per_card=target.hbm_kv_gb_per_card,
        extra_capacity_tiers=extra_capacity_tiers,
    )


def _build_calibrated_heuristic(
    heuristic: MultiAgentHeuristicConfig,
    *,
    zipf_s: float,
    lru_like: float,
) -> MultiAgentHeuristicConfig:
    curve_shape = replace(
        heuristic.curve_shape,
        zipf_s=zipf_s,
    )
    policy_efficiency = replace(
        heuristic.policy_efficiency,
        lru_like=lru_like,
    )
    return replace(
        heuristic,
        curve_shape=curve_shape,
        policy_efficiency=policy_efficiency,
    )


def _build_tier_comparisons(
    *,
    target: CalibrationTraceTarget,
    analysis: HeuristicAnalysisResult,
) -> tuple[CalibrationTierComparison, ...]:
    if len(analysis.scenario_summaries) != 1:
        raise ValueError("calibration analysis must produce exactly one scenario")
    predicted_by_label = {row.tier_label: row for row in analysis.tier_rows}
    comparisons: list[CalibrationTierComparison] = []
    for tier in target.tiers:
        predicted = predicted_by_label.get(tier.tier_label)
        if predicted is None:
            raise ValueError(f"missing predicted tier: {tier.tier_label}")
        comparisons.append(
            CalibrationTierComparison(
                tier_label=tier.tier_label,
                total_kv_gb=tier.total_kv_gb,
                observed_strict_prefix_hit_rate=tier.strict_prefix_hit_rate,
                predicted_strict_prefix_hit_rate=predicted.strict_prefix_hit_rate,
                observed_lru_like_hit_rate=tier.lru_like_hit_rate,
                predicted_lru_like_hit_rate=predicted.lru_like_hit_rate,
                strict_prefix_error=predicted.strict_prefix_hit_rate - tier.strict_prefix_hit_rate,
                lru_like_error=predicted.lru_like_hit_rate - tier.lru_like_hit_rate,
            )
        )
    return tuple(comparisons)


def _build_calibration_trial(
    *,
    heuristic: MultiAgentHeuristicConfig,
    target: CalibrationTraceTarget,
    comparisons: tuple[CalibrationTierComparison, ...],
) -> CalibrationTrial:
    strict_squared_errors = [item.strict_prefix_error**2 for item in comparisons]
    lru_squared_errors = [item.lru_like_error**2 for item in comparisons]
    strict_errors = [abs(item.strict_prefix_error) for item in comparisons]
    lru_errors = [abs(item.lru_like_error) for item in comparisons]
    rmse_strict = math.sqrt(sum(strict_squared_errors) / len(strict_squared_errors))
    rmse_lru_like = math.sqrt(sum(lru_squared_errors) / len(lru_squared_errors))
    rmse_total = math.sqrt(
        (sum(strict_squared_errors) + sum(lru_squared_errors))
        / (len(strict_squared_errors) + len(lru_squared_errors))
    )
    max_abs_error = max(strict_errors + lru_errors)
    content_gap = heuristic.content_hit_rate() - target.content_hit_rate
    return CalibrationTrial(
        zipf_s=heuristic.curve_shape.zipf_s,
        power_law_beta=heuristic.curve_shape.resolved_power_law_beta(),
        lru_like=heuristic.policy_efficiency.lru_like,
        objective=rmse_total,
        rmse_strict=rmse_strict,
        rmse_lru_like=rmse_lru_like,
        rmse_total=rmse_total,
        max_abs_error=max_abs_error,
        content_gap=content_gap,
    )


def _build_float_grid(*, start: float, stop: float, step: float) -> tuple[float, ...]:
    if step <= 0:
        raise ValueError("grid step must be positive")
    if start > stop:
        raise ValueError("grid start must not exceed grid stop")
    values: list[float] = []
    current = start
    while current <= stop + 1e-12:
        values.append(round(current, 4))
        current += step
    return tuple(values)


def _trial_score(trial: CalibrationTrial) -> tuple[float, float, float]:
    return (
        trial.objective,
        trial.max_abs_error,
        abs(trial.content_gap),
    )


def _normalize_tier_label(label: str) -> str:
    suffix = " Hit Rate"
    if label.endswith(suffix):
        return label[: -len(suffix)]
    return label


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
