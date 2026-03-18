from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .multi_agent import (
    HeuristicAnalysisConfig,
    HeuristicAnalysisResult,
    HeuristicScenarioSummary,
    HeuristicTierRow,
)
from kvcache_upper_bound.reporting.table_common import (
    format_delta_pp,
    format_flag,
    format_integer,
    format_number,
    format_rate,
)


@dataclass(frozen=True)
class HeuristicTierInputSummary:
    label: str
    extra_kv_gb_per_machine: float
    extra_kv_total_gb: float
    total_kv_gb: float


@dataclass(frozen=True)
class HeuristicInputSummary:
    scenario_label: str
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
    hbm_total_kv_gb: float
    hbm_total_kv_tokens: float
    extra_capacity_tiers: tuple[HeuristicTierInputSummary, ...]


def build_multi_agent_input_summaries(
    config: HeuristicAnalysisConfig,
    result: HeuristicAnalysisResult,
) -> list[HeuristicInputSummary]:
    deployments_by_label = {deployment.label: deployment for deployment in config.deployments}
    summaries: list[HeuristicInputSummary] = []
    for row in result.scenario_summaries:
        deployment = deployments_by_label[row.scenario_label]
        tier_summaries = tuple(
            HeuristicTierInputSummary(
                label=tier.label,
                extra_kv_gb_per_machine=tier.kv_gb_per_machine,
                extra_kv_total_gb=row.machine_count * tier.kv_gb_per_machine,
                total_kv_gb=row.hbm_total_kv_gb + row.machine_count * tier.kv_gb_per_machine,
            )
            for tier in deployment.extra_capacity_tiers
        )
        summaries.append(
            HeuristicInputSummary(
                scenario_label=row.scenario_label,
                machine_count=row.machine_count,
                card_count=row.card_count,
                cards_per_machine=row.cards_per_machine,
                machine_spec=row.machine_spec,
                total_tps_input=deployment.total_tps,
                total_tps_input_unit=row.total_tps_input_unit,
                total_tps_cluster_total=row.total_tps,
                planning_target_total_tps=row.planning_target_total_tps,
                baseline_per_card_tps=row.baseline_per_card_tps,
                hbm_kv_gb_per_card=row.hbm_kv_gb_per_card,
                hbm_total_kv_gb=row.hbm_total_kv_gb,
                hbm_total_kv_tokens=row.hbm_total_kv_tokens,
                extra_capacity_tiers=tier_summaries,
            )
        )
    return summaries


def write_multi_agent_outputs(
    config: HeuristicAnalysisConfig,
    result: HeuristicAnalysisResult,
    output_dir: str | Path,
) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    include_total_tps = any(row.total_tps is not None for row in result.scenario_summaries)
    include_target_tps_fields = any(
        row.planning_target_total_tps is not None and row.baseline_per_card_tps is not None
        for row in result.scenario_summaries
    )

    _write_csv(
        output_path / "heuristic_summary.csv",
        _heuristic_summary_fieldnames(
            include_total_tps=include_total_tps,
            include_target_tps_fields=include_target_tps_fields,
        ),
        [
            _heuristic_summary_payload(
                row=row,
                include_total_tps=include_total_tps,
                include_target_tps_fields=include_target_tps_fields,
            )
            for row in result.scenario_summaries
        ],
    )
    _write_csv(
        output_path / "heuristic_tier_summary.csv",
        _heuristic_tier_summary_fieldnames(
            include_total_tps=include_total_tps,
            include_target_tps_fields=include_target_tps_fields,
        ),
        [
            _heuristic_tier_payload(
                row=row,
                include_total_tps=include_total_tps,
                include_target_tps_fields=include_target_tps_fields,
            )
            for row in result.tier_rows
        ],
    )
    _write_details_json(output_path / "details.json", config=config, result=result)


def _heuristic_summary_fieldnames(
    *,
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> list[str]:
    fieldnames = ["场景", "机器数", "卡数", "单机卡数", "规格"]
    if include_total_tps:
        fieldnames.extend(["总 TPS", "TPS 输入口径"])
    if include_target_tps_fields:
        fieldnames.extend(["目标总 TPS", "单卡基线 TPS (无命中)"])
    fieldnames.extend(
        [
            "HBM KVCache 总大小 (GB)",
            "曲线模型",
            "Zipf s",
            "Power-Law beta",
            "LRU-like 效率",
            "极限命中率",
            "HBM Strict-Prefix 命中率估计",
            "HBM LRU-like 命中率估计",
            "HBM Strict-Prefix 达到内容上界",
            "HBM LRU-like 达到 Strict-Prefix",
            "HBM 当前主要瓶颈",
            "HBM Strict-Prefix TPS Gain",
            "HBM LRU-like TPS Gain",
        ]
    )
    if include_total_tps:
        fieldnames.extend(["HBM Strict-Prefix 估算总 TPS", "HBM LRU-like 估算总 TPS"])
    if include_target_tps_fields:
        fieldnames.extend(
            [
                "HBM Strict-Prefix 当前配置可承载总 TPS",
                "HBM Strict-Prefix 目标总 TPS 最小卡数",
                "HBM Strict-Prefix 目标总 TPS 最小机器数",
                "HBM LRU-like 当前配置可承载总 TPS",
                "HBM LRU-like 目标总 TPS 最小卡数",
                "HBM LRU-like 目标总 TPS 最小机器数",
            ]
        )
    fieldnames.extend(["Strict-Prefix 饱和容量 (GB)", "LRU-like 饱和容量 (GB)"])
    return fieldnames


def _heuristic_summary_payload(
    *,
    row: HeuristicScenarioSummary,
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "场景": row.scenario_label,
        "机器数": row.machine_count,
        "卡数": row.card_count,
        "单机卡数": row.cards_per_machine,
        "规格": row.machine_spec,
    }
    if include_total_tps:
        payload["总 TPS"] = format_number(row.total_tps)
        payload["TPS 输入口径"] = row.total_tps_input_unit or ""
    if include_target_tps_fields:
        payload["目标总 TPS"] = format_number(row.planning_target_total_tps)
        payload["单卡基线 TPS (无命中)"] = format_number(row.baseline_per_card_tps)
    payload["HBM KVCache 总大小 (GB)"] = f"{row.hbm_total_kv_gb:.2f}"
    payload["曲线模型"] = row.curve_mode
    payload["Zipf s"] = format_number(row.zipf_s)
    payload["Power-Law beta"] = format_number(row.power_law_beta)
    payload["LRU-like 效率"] = format_number(row.lru_like_efficiency)
    payload["极限命中率"] = format_rate(row.content_hit_rate)
    payload["HBM Strict-Prefix 命中率估计"] = format_rate(row.hbm_strict_prefix_hit_rate)
    payload["HBM LRU-like 命中率估计"] = format_rate(row.hbm_lru_like_hit_rate)
    payload["HBM Strict-Prefix 达到内容上界"] = format_flag(
        row.hbm_strict_prefix_hits_content_ceiling
    )
    payload["HBM LRU-like 达到 Strict-Prefix"] = format_flag(
        row.hbm_lru_like_hits_strict_prefix
    )
    payload["HBM 当前主要瓶颈"] = row.hbm_current_bottleneck
    payload["HBM Strict-Prefix TPS Gain"] = format_number(row.hbm_strict_prefix_tps_gain)
    payload["HBM LRU-like TPS Gain"] = format_number(row.hbm_lru_like_tps_gain)
    if include_total_tps:
        payload["HBM Strict-Prefix 估算总 TPS"] = format_number(
            row.hbm_strict_prefix_estimated_total_tps
        )
        payload["HBM LRU-like 估算总 TPS"] = format_number(row.hbm_lru_like_estimated_total_tps)
    if include_target_tps_fields:
        payload["HBM Strict-Prefix 当前配置可承载总 TPS"] = format_number(
            row.hbm_strict_prefix_current_cluster_capacity_tps
        )
        payload["HBM Strict-Prefix 目标总 TPS 最小卡数"] = format_integer(
            row.hbm_strict_prefix_min_card_count_for_target_total_tps
        )
        payload["HBM Strict-Prefix 目标总 TPS 最小机器数"] = format_integer(
            row.hbm_strict_prefix_min_machine_count_for_target_total_tps
        )
        payload["HBM LRU-like 当前配置可承载总 TPS"] = format_number(
            row.hbm_lru_like_current_cluster_capacity_tps
        )
        payload["HBM LRU-like 目标总 TPS 最小卡数"] = format_integer(
            row.hbm_lru_like_min_card_count_for_target_total_tps
        )
        payload["HBM LRU-like 目标总 TPS 最小机器数"] = format_integer(
            row.hbm_lru_like_min_machine_count_for_target_total_tps
        )
    payload["Strict-Prefix 饱和容量 (GB)"] = format_number(row.strict_prefix_saturation_capacity_gb)
    payload["LRU-like 饱和容量 (GB)"] = format_number(row.lru_like_saturation_capacity_gb)
    return payload


def _heuristic_tier_summary_fieldnames(
    *,
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> list[str]:
    fieldnames = ["场景", "容量层", "机器数", "卡数", "单机卡数", "规格"]
    if include_total_tps:
        fieldnames.extend(["总 TPS", "TPS 输入口径"])
    if include_target_tps_fields:
        fieldnames.extend(["目标总 TPS", "单卡基线 TPS (无命中)"])
    fieldnames.extend(
        [
            "KVCache 总大小 (GB)",
            "极限命中率",
            "Strict-Prefix 命中率估计",
            "LRU-like 命中率估计",
            "Strict-Prefix 达到内容上界",
            "LRU-like 达到 Strict-Prefix",
            "当前主要瓶颈",
            "相对上一层 Strict-Prefix 增益",
            "相对上一层 LRU-like 增益",
            "Strict-Prefix TPS Gain",
            "LRU-like TPS Gain",
        ]
    )
    if include_total_tps:
        fieldnames.extend(["Strict-Prefix 估算总 TPS", "LRU-like 估算总 TPS"])
    if include_target_tps_fields:
        fieldnames.extend(
            [
                "Strict-Prefix 当前配置可承载总 TPS",
                "Strict-Prefix 目标总 TPS 最小卡数",
                "Strict-Prefix 目标总 TPS 最小机器数",
                "LRU-like 当前配置可承载总 TPS",
                "LRU-like 目标总 TPS 最小卡数",
                "LRU-like 目标总 TPS 最小机器数",
            ]
        )
    fieldnames.extend(["Strict-Prefix 饱和容量 (GB)", "LRU-like 饱和容量 (GB)"])
    return fieldnames


def _heuristic_tier_payload(
    *,
    row: HeuristicTierRow,
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "场景": row.scenario_label,
        "容量层": row.tier_label,
        "机器数": row.machine_count,
        "卡数": row.card_count,
        "单机卡数": row.cards_per_machine,
        "规格": row.machine_spec,
    }
    if include_total_tps:
        payload["总 TPS"] = format_number(row.total_tps)
        payload["TPS 输入口径"] = row.total_tps_input_unit or ""
    if include_target_tps_fields:
        payload["目标总 TPS"] = format_number(row.planning_target_total_tps)
        payload["单卡基线 TPS (无命中)"] = format_number(row.baseline_per_card_tps)
    payload["KVCache 总大小 (GB)"] = f"{row.total_kv_gb:.2f}"
    payload["极限命中率"] = format_rate(row.content_hit_rate)
    payload["Strict-Prefix 命中率估计"] = format_rate(row.strict_prefix_hit_rate)
    payload["LRU-like 命中率估计"] = format_rate(row.lru_like_hit_rate)
    payload["Strict-Prefix 达到内容上界"] = format_flag(
        row.strict_prefix_hits_content_ceiling
    )
    payload["LRU-like 达到 Strict-Prefix"] = format_flag(row.lru_like_hits_strict_prefix)
    payload["当前主要瓶颈"] = row.current_bottleneck
    payload["相对上一层 Strict-Prefix 增益"] = format_delta_pp(
        row.strict_prefix_gain_from_previous_tier
    )
    payload["相对上一层 LRU-like 增益"] = format_delta_pp(row.lru_like_gain_from_previous_tier)
    payload["Strict-Prefix TPS Gain"] = format_number(row.strict_prefix_tps_gain)
    payload["LRU-like TPS Gain"] = format_number(row.lru_like_tps_gain)
    if include_total_tps:
        payload["Strict-Prefix 估算总 TPS"] = format_number(row.strict_prefix_estimated_total_tps)
        payload["LRU-like 估算总 TPS"] = format_number(row.lru_like_estimated_total_tps)
    if include_target_tps_fields:
        payload["Strict-Prefix 当前配置可承载总 TPS"] = format_number(
            row.strict_prefix_current_cluster_capacity_tps
        )
        payload["Strict-Prefix 目标总 TPS 最小卡数"] = format_integer(
            row.strict_prefix_min_card_count_for_target_total_tps
        )
        payload["Strict-Prefix 目标总 TPS 最小机器数"] = format_integer(
            row.strict_prefix_min_machine_count_for_target_total_tps
        )
        payload["LRU-like 当前配置可承载总 TPS"] = format_number(
            row.lru_like_current_cluster_capacity_tps
        )
        payload["LRU-like 目标总 TPS 最小卡数"] = format_integer(
            row.lru_like_min_card_count_for_target_total_tps
        )
        payload["LRU-like 目标总 TPS 最小机器数"] = format_integer(
            row.lru_like_min_machine_count_for_target_total_tps
        )
    payload["Strict-Prefix 饱和容量 (GB)"] = format_number(row.strict_prefix_saturation_capacity_gb)
    payload["LRU-like 饱和容量 (GB)"] = format_number(row.lru_like_saturation_capacity_gb)
    return payload


def _write_details_json(
    path: Path,
    *,
    config: HeuristicAnalysisConfig,
    result: HeuristicAnalysisResult,
) -> None:
    scenarios: dict[str, dict[str, Any]] = {}
    for summary in result.scenario_summaries:
        scenarios[summary.scenario_label] = {
            "summary": asdict(summary),
            "tiers": [],
        }
    for tier_row in result.tier_rows:
        scenarios[tier_row.scenario_label]["tiers"].append(asdict(tier_row))

    payload = {
        "model_profile": asdict(config.model_profile),
        "heuristic_multi_agent": asdict(config.heuristic),
        "deployments": [asdict(deployment) for deployment in config.deployments],
        "scenario_summaries": [asdict(summary) for summary in result.scenario_summaries],
        "tier_rows": [asdict(row) for row in result.tier_rows],
        "scenarios": scenarios,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], payloads: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(payloads)
