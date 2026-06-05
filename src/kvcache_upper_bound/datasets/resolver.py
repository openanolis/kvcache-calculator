from __future__ import annotations

from typing import Any

from kvcache_upper_bound.core.models import ModelProfile, Scope
from kvcache_upper_bound.heuristic.multi_agent import (
    CurveShapeConfig,
    HeuristicAnalysisConfig,
    HeuristicDeploymentConfig,
    MultiAgentHeuristicConfig,
    PolicyEfficiency,
)
from kvcache_upper_bound.reporting.buckets import (
    BucketAnalysisConfig,
    BucketDeploymentConfig,
)

from .registry import get_dataset


def resolve_heuristic_config(dataset_id: str) -> HeuristicAnalysisConfig:
    ds = get_dataset(dataset_id)
    model_profile = _build_model_profile(ds["model_profile"])
    heuristic = _build_heuristic(ds["default_heuristic"])
    deployment = _build_heuristic_deployment(ds["default_deployment"])
    return HeuristicAnalysisConfig(
        model_profile=model_profile,
        heuristic=heuristic,
        deployments=(deployment,),
        prefill_savings_alpha=0.8,
    )


def resolve_trace_url(dataset_id: str) -> str:
    ds = get_dataset(dataset_id)
    trace_url = ds.get("trace_url")
    if trace_url is None:
        raise ValueError(
            f"Dataset {dataset_id!r} does not have a direct trace URL. "
            f"It requires download and conversion (format: {ds['format']}). "
            f"Source: {ds['source']}"
        )
    return trace_url


def resolve_bucket_config(dataset_id: str) -> BucketAnalysisConfig:
    ds = get_dataset(dataset_id)
    model_profile = _build_model_profile(ds["model_profile"])
    depl = ds["default_deployment"]
    bucket_deployments = (
        BucketDeploymentConfig(
            label=f"{depl['label']} (0-32K)",
            lower_tokens=0,
            upper_tokens=32768,
            accelerator_count=depl["accelerator_count"],
            cards_per_machine=depl["cards_per_machine"],
            machine_spec=depl["machine_spec"],
            total_tps=float(depl["accelerator_count"]) * depl.get("baseline_per_card_tps", 1.0),
            baseline_per_card_tps=depl.get("baseline_per_card_tps"),
            gpu_memory_gb_per_card=depl.get("gpu_memory_gb_per_card"),
        ),
        BucketDeploymentConfig(
            label=f"{depl['label']} (32K-128K)",
            lower_tokens=32768,
            upper_tokens=131072,
            accelerator_count=depl["accelerator_count"],
            cards_per_machine=depl["cards_per_machine"],
            machine_spec=depl["machine_spec"],
            total_tps=float(depl["accelerator_count"]) * depl.get("baseline_per_card_tps", 1.0),
            baseline_per_card_tps=depl.get("baseline_per_card_tps"),
            gpu_memory_gb_per_card=depl.get("gpu_memory_gb_per_card"),
        ),
        BucketDeploymentConfig(
            label=f"{depl['label']} (128K+)",
            lower_tokens=131072,
            upper_tokens=None,
            accelerator_count=depl["accelerator_count"],
            cards_per_machine=depl["cards_per_machine"],
            machine_spec=depl["machine_spec"],
            total_tps=float(depl["accelerator_count"]) * depl.get("baseline_per_card_tps", 1.0),
            baseline_per_card_tps=depl.get("baseline_per_card_tps"),
            gpu_memory_gb_per_card=depl.get("gpu_memory_gb_per_card"),
        ),
    )
    return BucketAnalysisConfig(
        model_profile=model_profile,
        scope=Scope.GLOBAL,
        block_size=model_profile.block_size,
        bucket_deployments=bucket_deployments,
        prefill_savings_alpha=0.8,
        include_output_kvcache=True,
    )


def _build_model_profile(payload: dict[str, Any]) -> ModelProfile:
    return ModelProfile(
        n_layers=int(payload["n_layers"]),
        n_kv_heads=int(payload["n_kv_heads"]),
        head_dim=int(payload["head_dim"]),
        dtype_bytes=int(payload["dtype_bytes"]),
        kv_cache_layer_count=None
        if payload.get("kv_cache_layer_count") is None
        else int(payload["kv_cache_layer_count"]),
        block_size=int(payload.get("block_size", 16)),
        parameter_count=None
        if payload.get("parameter_count") is None
        else int(payload["parameter_count"]),
        weight_dtype_bytes=None
        if payload.get("weight_dtype_bytes") is None
        else int(payload["weight_dtype_bytes"]),
    )


def _build_heuristic(payload: dict[str, Any]) -> MultiAgentHeuristicConfig:
    pe = payload.get("policy_efficiency", {})
    return MultiAgentHeuristicConfig(
        concurrent_agents=int(payload["concurrent_agents"]),
        shared_prefix_tokens=float(payload["shared_prefix_tokens"]),
        avg_new_tokens_per_turn=float(payload["avg_new_tokens_per_turn"]),
        avg_turns_per_session=int(payload["avg_turns_per_session"]),
        private_window_tokens=float(payload["private_window_tokens"]),
        curve_shape=CurveShapeConfig(
            mode=str(payload.get("curve_mode", "zipf_harmonic")),
            zipf_s=float(payload.get("zipf_s", 1.3)),
            zipf_population_blocks=int(payload.get("zipf_population_blocks", 4096)),
            power_law_beta=None,
        ),
        policy_efficiency=PolicyEfficiency(
            strict_prefix_upper_bound=float(pe.get("strict_prefix_upper_bound", 1.0)),
            lru_like=float(pe.get("lru_like", 0.55)),
        ),
    )


def _build_heuristic_deployment(payload: dict[str, Any]) -> HeuristicDeploymentConfig:
    return HeuristicDeploymentConfig(
        label=payload["label"],
        accelerator_count=int(payload["accelerator_count"]),
        cards_per_machine=int(payload["cards_per_machine"]),
        machine_spec=payload["machine_spec"],
        gpu_memory_gb_per_card=payload.get("gpu_memory_gb_per_card"),
        baseline_per_card_tps=payload.get("baseline_per_card_tps"),
        total_tps=float(payload["accelerator_count"]) * payload.get("baseline_per_card_tps", 1.0),
        total_tps_unit="cluster_total",
        planning_target_total_tps=float(payload["accelerator_count"]) * payload.get("baseline_per_card_tps", 1.0),
    )
