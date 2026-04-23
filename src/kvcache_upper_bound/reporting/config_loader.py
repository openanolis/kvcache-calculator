from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kvcache_upper_bound.core.models import ModelProfile, Scope

from .buckets import BucketAnalysisConfig, BucketCapacityTier, BucketDeploymentConfig

VALID_TOTAL_TPS_UNITS = ("cluster_total", "per_machine", "per_card")
LEGACY_PER_MACHINE_BUDGET_FIELDS = (
    "hbm_kv_gb_per_machine",
    "gpu_memory_gb_per_machine",
    "runtime_reserve_gb_per_machine",
)


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
    _validate_bucket_deployments(bucket_deployments)
    include_output_kvcache = bool(payload.get("include_output_kvcache", False))
    return BucketAnalysisConfig(
        model_profile=model_profile,
        scope=scope,
        block_size=block_size,
        bucket_deployments=bucket_deployments,
        prefill_savings_alpha=prefill_savings_alpha,
        include_output_kvcache=include_output_kvcache,
    )


def _load_prefill_savings_alpha(payload: dict[str, Any]) -> float:
    alpha = _normalize_rate(payload.get("prefill_savings_alpha", 0.8))
    if alpha is None:
        return 0.8
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("prefill_savings_alpha must be within [0, 1]")
    return alpha


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
        window_tokens=None if payload.get("window_tokens") is None else int(payload["window_tokens"]),
        actual_hit_rate=actual_hit_rate,
        actual_hit_rate_note=actual_hit_rate_note,
        extra_capacity_tiers=extra_tiers,
    )


def _validate_bucket_deployments(
    bucket_deployments: tuple[BucketDeploymentConfig, ...],
) -> None:
    seen_labels: set[str] = set()
    previous_upper: int | None = None
    previous_label: str | None = None
    saw_open_ended = False

    for deployment in bucket_deployments:
        if deployment.label in seen_labels:
            raise ValueError(f"duplicate bucket label: {deployment.label}")
        seen_labels.add(deployment.label)
        deployment.node_count()
        deployment.resolved_total_tps()
        _validate_bucket_bounds(deployment)
        _validate_budget_fields(deployment)
        _validate_extra_capacity_tiers(deployment)
        if saw_open_ended:
            raise ValueError("open-ended bucket must be the last bucket_deployment")
        if previous_upper is not None and deployment.lower_tokens < previous_upper:
            raise ValueError(
                "bucket_deployments must be sorted by lower_tokens without overlap; "
                f"{deployment.label} starts at {deployment.lower_tokens} before {previous_label} ends at {previous_upper}"
            )
        previous_upper = deployment.upper_tokens
        previous_label = deployment.label
        if deployment.upper_tokens is None:
            saw_open_ended = True


def _validate_bucket_bounds(deployment: BucketDeploymentConfig) -> None:
    if deployment.lower_tokens < 0:
        raise ValueError(f"{deployment.label}: lower_tokens must be non-negative")
    if deployment.upper_tokens is not None and deployment.upper_tokens <= deployment.lower_tokens:
        raise ValueError(f"{deployment.label}: upper_tokens must be greater than lower_tokens")
    if deployment.window_tokens is not None and deployment.window_tokens < 0:
        raise ValueError(f"{deployment.label}: window_tokens must be non-negative")
    if deployment.total_tps is not None and deployment.total_tps < 0:
        raise ValueError(f"{deployment.label}: total_tps must be non-negative")
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
    if deployment.actual_hit_rate is not None and not 0.0 <= deployment.actual_hit_rate <= 1.0:
        raise ValueError(f"{deployment.label}: actual_hit_rate must be within [0, 1]")


def _validate_budget_fields(deployment: BucketDeploymentConfig) -> None:
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


def _validate_extra_capacity_tiers(deployment: BucketDeploymentConfig) -> None:
    seen_tier_labels: set[str] = set()
    for tier in deployment.extra_capacity_tiers:
        if not tier.label:
            raise ValueError(f"{deployment.label}: extra_capacity_tiers label must not be empty")
        if tier.label in seen_tier_labels:
            raise ValueError(f"{deployment.label}: duplicate extra_capacity_tier label: {tier.label}")
        if tier.kv_gb_per_machine < 0:
            raise ValueError(
                f"{deployment.label}: extra_capacity_tier {tier.label} must be non-negative"
            )
        seen_tier_labels.add(tier.label)


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
