from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kvcache_upper_bound.core.models import ModelProfile

from .multi_agent import (
    CurveShapeConfig,
    HeuristicAnalysisConfig,
    HeuristicCapacityTier,
    HeuristicDeploymentConfig,
    MultiAgentHeuristicConfig,
    PolicyEfficiency,
    VALID_CURVE_MODES,
    VALID_TOTAL_TPS_UNITS,
)

LEGACY_PER_MACHINE_BUDGET_FIELDS = (
    "hbm_kv_gb_per_machine",
    "gpu_memory_gb_per_machine",
    "runtime_reserve_gb_per_machine",
)


def load_multi_agent_heuristic_config(path: str | Path) -> HeuristicAnalysisConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    model_profile = _load_model_profile(payload.get("model_profile", {}))
    heuristic = _load_multi_agent_heuristic(payload.get("heuristic_multi_agent", {}))
    deployments = tuple(
        _load_heuristic_deployment(item) for item in payload.get("deployments", [])
    )
    if not deployments:
        raise ValueError("deployments must not be empty")
    _validate_deployments(deployments)
    prefill_savings_alpha = _load_prefill_savings_alpha(payload)
    return HeuristicAnalysisConfig(
        model_profile=model_profile,
        heuristic=heuristic,
        deployments=deployments,
        prefill_savings_alpha=prefill_savings_alpha,
    )


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


def _load_multi_agent_heuristic(payload: dict[str, Any]) -> MultiAgentHeuristicConfig:
    if not payload:
        raise ValueError("heuristic_multi_agent must not be empty")
    curve_shape = CurveShapeConfig(
        mode=str(payload.get("curve_mode", "zipf_harmonic")),
        zipf_s=float(payload.get("zipf_s", 1.3)),
        zipf_population_blocks=int(payload.get("zipf_population_blocks", 4096)),
        power_law_beta=None
        if payload.get("power_law_beta") is None
        else float(payload["power_law_beta"]),
    )
    policy_efficiency_payload = payload.get("policy_efficiency", {})
    policy_efficiency = PolicyEfficiency(
        strict_prefix_upper_bound=float(
            policy_efficiency_payload.get("strict_prefix_upper_bound", 1.0)
        ),
        lru_like=float(policy_efficiency_payload.get("lru_like", 0.55)),
    )
    heuristic = MultiAgentHeuristicConfig(
        concurrent_agents=int(payload["concurrent_agents"]),
        shared_prefix_tokens=float(payload["shared_prefix_tokens"]),
        avg_new_tokens_per_turn=float(payload["avg_new_tokens_per_turn"]),
        avg_turns_per_session=int(payload["avg_turns_per_session"]),
        private_window_tokens=float(payload["private_window_tokens"]),
        curve_shape=curve_shape,
        policy_efficiency=policy_efficiency,
    )
    _validate_multi_agent_heuristic(heuristic)
    return heuristic


def _load_heuristic_deployment(payload: dict[str, Any]) -> HeuristicDeploymentConfig:
    _reject_legacy_per_machine_budget_fields(payload)
    deployment = HeuristicDeploymentConfig(
        label=str(payload["label"]),
        accelerator_count=int(payload["accelerator_count"]),
        cards_per_machine=int(payload["cards_per_machine"]),
        machine_spec=str(payload["machine_spec"]),
        total_tps=None if payload.get("total_tps") is None else float(payload["total_tps"]),
        total_tps_unit=str(payload.get("total_tps_unit", "cluster_total")),
        planning_target_total_tps=None
        if payload.get("planning_target_total_tps") is None
        else float(payload["planning_target_total_tps"]),
        baseline_per_card_tps=None
        if payload.get("baseline_per_card_tps") is None
        else float(payload["baseline_per_card_tps"]),
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
        extra_capacity_tiers=tuple(
            HeuristicCapacityTier(
                label=str(item["label"]),
                kv_gb_per_machine=float(item["kv_gb_per_machine"]),
            )
            for item in payload.get("extra_capacity_tiers", [])
        ),
    )
    _validate_heuristic_deployment(deployment)
    return deployment


def _load_prefill_savings_alpha(payload: dict[str, Any]) -> float:
    alpha = float(payload.get("prefill_savings_alpha", 0.8))
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("prefill_savings_alpha must be within [0, 1]")
    return alpha


def _validate_multi_agent_heuristic(heuristic: MultiAgentHeuristicConfig) -> None:
    if heuristic.concurrent_agents <= 0:
        raise ValueError("concurrent_agents must be positive")
    if heuristic.shared_prefix_tokens < 0:
        raise ValueError("shared_prefix_tokens must be non-negative")
    if heuristic.avg_new_tokens_per_turn <= 0:
        raise ValueError("avg_new_tokens_per_turn must be positive")
    if heuristic.avg_turns_per_session <= 0:
        raise ValueError("avg_turns_per_session must be positive")
    if heuristic.private_window_tokens < 0:
        raise ValueError("private_window_tokens must be non-negative")
    if heuristic.curve_shape.mode not in VALID_CURVE_MODES:
        raise ValueError(f"curve_mode must be one of {', '.join(VALID_CURVE_MODES)}")
    if heuristic.curve_shape.zipf_s <= 1.0:
        raise ValueError("zipf_s must be greater than 1")
    if heuristic.curve_shape.zipf_population_blocks <= 0:
        raise ValueError("zipf_population_blocks must be positive")
    if (
        heuristic.curve_shape.power_law_beta is not None
        and heuristic.curve_shape.power_law_beta <= 0.0
    ):
        raise ValueError("power_law_beta must be positive")
    if not 0.0 < heuristic.policy_efficiency.strict_prefix_upper_bound <= 1.0:
        raise ValueError("strict_prefix_upper_bound efficiency must be within (0, 1]")
    if not 0.0 < heuristic.policy_efficiency.lru_like <= 1.0:
        raise ValueError("lru_like efficiency must be within (0, 1]")
    if heuristic.policy_efficiency.lru_like > heuristic.policy_efficiency.strict_prefix_upper_bound:
        raise ValueError("lru_like efficiency must not exceed strict_prefix_upper_bound")


def _validate_deployments(deployments: tuple[HeuristicDeploymentConfig, ...]) -> None:
    seen_labels: set[str] = set()
    for deployment in deployments:
        if deployment.label in seen_labels:
            raise ValueError(f"duplicate deployment label: {deployment.label}")
        seen_labels.add(deployment.label)


def _validate_heuristic_deployment(deployment: HeuristicDeploymentConfig) -> None:
    if deployment.accelerator_count <= 0:
        raise ValueError(f"{deployment.label}: accelerator_count must be positive")
    deployment.node_count()
    if not deployment.machine_spec:
        raise ValueError(f"{deployment.label}: machine_spec must not be empty")
    if "*" in deployment.machine_spec:
        raise ValueError(f"{deployment.label}: machine_spec must be a plain spec label")
    if deployment.total_tps is not None and deployment.total_tps < 0:
        raise ValueError(f"{deployment.label}: total_tps must be non-negative")
    if deployment.total_tps_unit not in VALID_TOTAL_TPS_UNITS:
        raise ValueError(
            f"{deployment.label}: total_tps_unit must be one of {', '.join(VALID_TOTAL_TPS_UNITS)}"
        )
    if (
        deployment.planning_target_total_tps is not None
        and deployment.planning_target_total_tps < 0
    ):
        raise ValueError(f"{deployment.label}: planning_target_total_tps must be non-negative")
    if deployment.baseline_per_card_tps is not None and deployment.baseline_per_card_tps <= 0:
        raise ValueError(f"{deployment.label}: baseline_per_card_tps must be positive")
    if (
        deployment.planning_target_total_tps is not None
        and deployment.baseline_per_card_tps is None
    ):
        raise ValueError(
            f"{deployment.label}: planning_target_total_tps requires baseline_per_card_tps"
        )
    if deployment.hbm_kv_gb_per_card is not None and deployment.hbm_kv_gb_per_card < 0:
        raise ValueError(f"{deployment.label}: hbm_kv_gb_per_card must be non-negative")
    if deployment.gpu_memory_gb_per_card is not None and deployment.gpu_memory_gb_per_card <= 0:
        raise ValueError(f"{deployment.label}: gpu_memory_gb_per_card must be positive")
    if deployment.runtime_reserve_gb_per_card < 0:
        raise ValueError(f"{deployment.label}: runtime_reserve_gb_per_card must be non-negative")
    if deployment.hbm_kv_utilization is not None and not 0.0 <= deployment.hbm_kv_utilization <= 1.0:
        raise ValueError(f"{deployment.label}: hbm_kv_utilization must be within [0, 1]")
    if (
        deployment.hbm_kv_gb_per_card is not None
        and deployment.gpu_memory_gb_per_card is not None
    ):
        raise ValueError(
            f"{deployment.label}: provide either hbm_kv_gb_per_card or gpu_memory_gb_per_card, not both"
        )
    if (
        deployment.hbm_kv_utilization is not None
        and deployment.gpu_memory_gb_per_card is None
    ):
        raise ValueError(
            f"{deployment.label}: hbm_kv_utilization requires gpu_memory_gb_per_card"
        )
    if (
        deployment.hbm_kv_utilization is not None
        and deployment.hbm_kv_gb_per_card is not None
    ):
        raise ValueError(
            f"{deployment.label}: hbm_kv_utilization cannot be combined with hbm_kv_gb_per_card"
        )
    if (
        deployment.hbm_kv_gb_per_card is None
        and deployment.gpu_memory_gb_per_card is None
    ):
        raise ValueError(
            f"{deployment.label}: either hbm_kv_gb_per_card or gpu_memory_gb_per_card must be provided"
        )
    seen_tiers: set[str] = set()
    for tier in deployment.extra_capacity_tiers:
        if not tier.label:
            raise ValueError(f"{deployment.label}: extra_capacity_tiers label must not be empty")
        if tier.label in seen_tiers:
            raise ValueError(f"{deployment.label}: duplicate extra_capacity_tier label: {tier.label}")
        seen_tiers.add(tier.label)
        if tier.kv_gb_per_machine < 0:
            raise ValueError(
                f"{deployment.label}: extra_capacity_tiers kv_gb_per_machine must be non-negative"
            )


def _reject_legacy_per_machine_budget_fields(payload: dict[str, Any]) -> None:
    present_fields = [field for field in LEGACY_PER_MACHINE_BUDGET_FIELDS if field in payload]
    if present_fields:
        raise ValueError(
            "legacy per-machine budget fields are no longer accepted; "
            f"found: {', '.join(present_fields)}"
        )
