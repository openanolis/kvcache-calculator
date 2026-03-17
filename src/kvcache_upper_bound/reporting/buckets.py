from __future__ import annotations

import csv
import json
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


@dataclass(frozen=True)
class BucketCapacityTier:
    label: str
    kv_gb_per_machine: float


@dataclass(frozen=True)
class BucketDeploymentConfig:
    label: str
    lower_tokens: int
    upper_tokens: int | None
    machine_count: int
    machine_spec: str
    total_tps: float | None
    hbm_kv_gb_per_machine: float | None = None
    gpu_memory_gb_per_machine: float | None = None
    hbm_kv_utilization: float | None = None
    runtime_reserve_gb_per_machine: float = 0.0
    window_tokens: int | None = None
    actual_hit_rate: float | None = None
    actual_hit_rate_note: str | None = None
    extra_capacity_tiers: tuple[BucketCapacityTier, ...] = field(default_factory=tuple)

    def contains(self, input_length: int) -> bool:
        if input_length < self.lower_tokens:
            return False
        if self.upper_tokens is None:
            return True
        return input_length < self.upper_tokens

    def resolved_hbm_kv_gb_per_machine(self, model_profile: ModelProfile) -> float:
        if self.hbm_kv_gb_per_machine is not None:
            return self.hbm_kv_gb_per_machine
        if self.gpu_memory_gb_per_machine is None:
            raise ValueError(
                f"{self.label}: either hbm_kv_gb_per_machine or gpu_memory_gb_per_machine must be provided"
            )
        if self.hbm_kv_utilization is not None:
            return self.gpu_memory_gb_per_machine * self.hbm_kv_utilization

        model_weight_bytes_per_rank = model_profile.weight_bytes_per_rank()
        if model_weight_bytes_per_rank is None:
            raise ValueError(
                f"{self.label}: gpu_memory_gb_per_machine requires either hbm_kv_utilization or model_profile.parameter_count"
            )
        model_weight_gb_per_rank = model_weight_bytes_per_rank / BYTES_PER_GB
        resolved = (
            self.gpu_memory_gb_per_machine
            - model_weight_gb_per_rank
            - self.runtime_reserve_gb_per_machine
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


@dataclass(frozen=True)
class BucketReportRow:
    bucket_label: str
    machine_count: int
    machine_spec: str
    total_tps: float | None
    hbm_kv_gb_per_machine: float
    hbm_kv_total_gb: float
    model_weight_gb_per_machine: float | None
    extreme_hit_rate: float | None
    actual_hit_rate: float | None
    actual_hit_rate_note: str | None
    hbm_relaxed_upper_bound_hit_rate: float | None
    hbm_strict_prefix_replay_hit_rate: float | None
    hbm_strict_prefix_hit_rate: float | None
    hbm_strict_prefix_proof_source: str | None
    extra_tier_relaxed_upper_bound_hit_rates: dict[str, float | None]
    extra_tier_strict_prefix_replay_hit_rates: dict[str, float | None]
    extra_tier_strict_prefix_hit_rates: dict[str, float | None]
    extra_tier_strict_prefix_proof_sources: dict[str, str | None]
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

        hbm_kv_gb_per_machine = deployment.resolved_hbm_kv_gb_per_machine(config.model_profile)
        hbm_kv_total_gb = deployment.machine_count * hbm_kv_gb_per_machine
        model_weight_bytes_per_rank = config.model_profile.weight_bytes_per_rank()
        model_weight_gb_per_machine = (
            None
            if model_weight_bytes_per_rank is None
            else model_weight_bytes_per_rank / BYTES_PER_GB
        )
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
                total_budget_gb = hbm_kv_total_gb + deployment.machine_count * tier.kv_gb_per_machine
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
                total_budget_gb = hbm_kv_total_gb + deployment.machine_count * tier.kv_gb_per_machine
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
                None if not bucket_records else capacity_result.summary.block_hit_rate
            )
            extra_tier_strict_prefix_replay_hit_rates[tier.label] = (
                None if not bucket_records else capacity_result.summary.strict_prefix_block_hit_rate
            )
            extra_tier_strict_prefix_hit_rates[tier.label] = (
                None if not bucket_records else strict_prefix_result.summary.block_hit_rate
            )
            extra_tier_strict_prefix_proof_sources[tier.label] = (
                None if not bucket_records else strict_prefix_result.summary.proof_source
            )

        row = BucketReportRow(
            bucket_label=deployment.label,
            machine_count=deployment.machine_count,
            machine_spec=deployment.machine_spec,
            total_tps=deployment.total_tps,
            hbm_kv_gb_per_machine=hbm_kv_gb_per_machine,
            hbm_kv_total_gb=hbm_kv_total_gb,
            model_weight_gb_per_machine=model_weight_gb_per_machine,
            extreme_hit_rate=None if not bucket_records else content_result.summary.block_hit_rate,
            actual_hit_rate=deployment.actual_hit_rate,
            actual_hit_rate_note=deployment.actual_hit_rate_note,
            hbm_relaxed_upper_bound_hit_rate=None
            if not bucket_records
            else hbm_capacity_result.summary.block_hit_rate,
            hbm_strict_prefix_replay_hit_rate=None
            if not bucket_records
            else hbm_capacity_result.summary.strict_prefix_block_hit_rate,
            hbm_strict_prefix_hit_rate=None
            if not bucket_records
            else hbm_strict_prefix_result.summary.block_hit_rate,
            hbm_strict_prefix_proof_source=None
            if not bucket_records
            else hbm_strict_prefix_result.summary.proof_source,
            extra_tier_relaxed_upper_bound_hit_rates=extra_tier_relaxed_upper_bound_hit_rates,
            extra_tier_strict_prefix_replay_hit_rates=extra_tier_strict_prefix_replay_hit_rates,
            extra_tier_strict_prefix_hit_rates=extra_tier_strict_prefix_hit_rates,
            extra_tier_strict_prefix_proof_sources=extra_tier_strict_prefix_proof_sources,
            request_count=len(bucket_records),
            window_tokens=None if not bucket_records else window_tokens,
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
    details_json_path = output_path / "details.json"

    tier_labels = _collect_tier_labels(result.rows)
    _write_summary_csv(summary_csv_path, result.rows, tier_labels)
    _write_details_json(details_json_path, result)


def _write_summary_csv(
    path: Path,
    rows: list[BucketReportRow],
    tier_labels: list[str],
) -> None:
    include_total_tps = any(row.total_tps is not None for row in rows)
    include_actual_hit_rate = any(row.actual_hit_rate is not None for row in rows)

    fieldnames = ["分桶", "机器数", "规格"]
    if include_total_tps:
        fieldnames.append("总 TPS")
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
        relaxed_label = _relaxed_upper_bound_column(label)
        strict_prefix_replay_label = _strict_prefix_replay_column(label)
        strict_prefix_proof_label = _strict_prefix_proof_column(label)
        fieldnames.extend(
            [
                label,
                relaxed_label,
                strict_prefix_replay_label,
                strict_prefix_proof_label,
            ]
        )
    fieldnames.extend(["请求数", "窗口上限", "输入下界", "输入上界"])

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload: dict[str, Any] = {
                "分桶": row.bucket_label,
                "机器数": row.machine_count,
                "规格": row.machine_spec,
                "HBM KVCache 总大小 (GB)": f"{row.hbm_kv_total_gb:.2f}",
                "极限命中率": _format_rate(row.extreme_hit_rate),
                "HBM Relaxed Upper Bound 命中率": _format_rate(
                    row.hbm_relaxed_upper_bound_hit_rate
                ),
                "HBM Strict-Prefix Replay 命中率": _format_rate(row.hbm_strict_prefix_replay_hit_rate),
                "HBM Strict-Prefix 命中率": _format_rate(row.hbm_strict_prefix_hit_rate),
                "HBM Strict-Prefix 求解路径": _format_text(row.hbm_strict_prefix_proof_source),
                "请求数": row.request_count,
                "窗口上限": "" if row.window_tokens is None else row.window_tokens,
                "输入下界": row.input_lower_tokens,
                "输入上界": "" if row.input_upper_tokens is None else row.input_upper_tokens,
            }
            if include_total_tps:
                payload["总 TPS"] = row.total_tps if row.total_tps is not None else ""
            if include_actual_hit_rate:
                payload["实际命中率"] = _format_rate(row.actual_hit_rate)
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
            writer.writerow(payload)


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


def _format_bool(value: bool | None) -> str:
    if value is None:
        return ""
    return "yes" if value else "no"


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


def _strict_prefix_column_base(label: str) -> str:
    suffix = " 命中率"
    if label.endswith(suffix):
        return label[: -len(suffix)]
    return label


def _gb_to_bytes(value_gb: float) -> int:
    return int(value_gb * BYTES_PER_GB)


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
    machine_count, machine_spec = _parse_machine_fields(payload)
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
        machine_count=machine_count,
        machine_spec=machine_spec,
        total_tps=None if payload.get("total_tps") is None else float(payload["total_tps"]),
        hbm_kv_gb_per_machine=None
        if payload.get("hbm_kv_gb_per_machine") is None
        else float(payload["hbm_kv_gb_per_machine"]),
        gpu_memory_gb_per_machine=None
        if payload.get("gpu_memory_gb_per_machine") is None
        else float(payload["gpu_memory_gb_per_machine"]),
        hbm_kv_utilization=None
        if payload.get("hbm_kv_utilization") is None
        else float(payload["hbm_kv_utilization"]),
        runtime_reserve_gb_per_machine=float(payload.get("runtime_reserve_gb_per_machine", 0.0)),
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


def _parse_machine_fields(payload: dict[str, Any]) -> tuple[int, str]:
    if "machine_count" in payload and payload["machine_count"] is not None:
        return int(payload["machine_count"]), str(payload["machine_spec"])

    spec = str(payload["machine_spec"])
    if "*" not in spec:
        raise ValueError("machine_count is missing and machine_spec does not follow '<count>*<spec>' format")
    count_text, spec_name = spec.split("*", 1)
    return int(count_text), spec_name
