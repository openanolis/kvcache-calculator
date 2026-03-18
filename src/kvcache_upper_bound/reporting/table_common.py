from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .buckets import BucketReportRow


def hit_prefix_fieldnames(*, include_total_tps: bool) -> list[str]:
    fieldnames = ["分桶", "机器数", "卡数", "单机卡数", "规格"]
    if include_total_tps:
        fieldnames.extend(["总 TPS", "TPS 输入口径"])
    fieldnames.extend(["HBM KVCache 总大小 (GB)", "极限命中率"])
    return fieldnames


def planning_prefix_fieldnames(
    *,
    include_total_tps: bool,
    include_target_tps_fields: bool,
) -> list[str]:
    fieldnames = ["分桶", "机器数", "卡数", "单机卡数", "规格"]
    if include_total_tps:
        fieldnames.extend(["总 TPS", "TPS 输入口径"])
    if include_target_tps_fields:
        fieldnames.extend(["目标总 TPS", "单卡基线 TPS (无命中)"])
    fieldnames.extend(["HBM KVCache 总大小 (GB)", "Prefill 节省系数 alpha"])
    return fieldnames


def row_range_fieldnames() -> list[str]:
    return ["请求数", "窗口上限", "输入下界", "输入上界"]


def common_row_payload(*, row: BucketReportRow, include_total_tps: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "分桶": row.bucket_label,
        "机器数": row.machine_count,
        "卡数": row.card_count,
        "单机卡数": row.cards_per_machine,
        "规格": row.machine_spec,
    }
    if include_total_tps:
        payload["总 TPS"] = row.total_tps if row.total_tps is not None else ""
        payload["TPS 输入口径"] = format_text(row.total_tps_input_unit)
    return payload


def hit_prefix_payload(row: BucketReportRow) -> dict[str, Any]:
    return {
        "HBM KVCache 总大小 (GB)": f"{row.hbm_kv_total_gb:.2f}",
        "极限命中率": format_rate(row.extreme_hit_rate),
    }


def planning_prefix_payload(
    row: BucketReportRow,
    *,
    include_target_tps_fields: bool,
) -> dict[str, Any]:
    payload = {
        "HBM KVCache 总大小 (GB)": f"{row.hbm_kv_total_gb:.2f}",
        "Prefill 节省系数 alpha": format_number(row.prefill_savings_alpha),
    }
    if include_target_tps_fields:
        payload["目标总 TPS"] = format_number(row.planning_target_total_tps)
        payload["单卡基线 TPS (无命中)"] = format_number(row.baseline_per_card_tps)
    return payload


def row_range_payload(row: BucketReportRow) -> dict[str, Any]:
    return {
        "请求数": row.request_count,
        "窗口上限": "" if row.window_tokens is None else row.window_tokens,
        "输入下界": row.input_lower_tokens,
        "输入上界": "" if row.input_upper_tokens is None else row.input_upper_tokens,
    }


def collect_tier_labels(rows: list[BucketReportRow]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for label in row.extra_tier_strict_prefix_hit_rates:
            if label in seen:
                continue
            seen.add(label)
            labels.append(label)
    return labels


def format_rate(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value * 100:.2f}%"


def format_number(value: float | None) -> str:
    if value is None:
        return ""
    if math.isinf(value):
        return "inf"
    return f"{value:.2f}"


def format_integer(value: int | None) -> str:
    if value is None:
        return ""
    return str(value)


def format_text(value: str | None) -> str:
    if value is None:
        return ""
    return value


def relaxed_upper_bound_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Relaxed Upper Bound 命中率"


def strict_prefix_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix 命中率"


def strict_prefix_replay_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix Replay 命中率"


def lru_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU 命中率"


def strict_prefix_proof_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix 求解路径"


def strict_prefix_tps_gain_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix TPS Gain"


def strict_prefix_estimated_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix 估算总 TPS"


def strict_prefix_estimated_card_count_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix 同负载估算卡数"


def strict_prefix_estimated_machine_count_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix 同负载估算机器数"


def strict_prefix_current_cluster_capacity_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix 当前配置可承载总 TPS"


def strict_prefix_min_card_count_for_target_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix 目标总 TPS 最小卡数"


def strict_prefix_min_machine_count_for_target_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} Strict-Prefix 目标总 TPS 最小机器数"


def lru_tps_gain_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU TPS Gain"


def lru_estimated_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU 估算总 TPS"


def lru_estimated_card_count_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU 同负载估算卡数"


def lru_estimated_machine_count_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU 同负载估算机器数"


def lru_current_cluster_capacity_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU 当前配置可承载总 TPS"


def lru_min_card_count_for_target_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU 目标总 TPS 最小卡数"


def lru_min_machine_count_for_target_total_tps_column(label: str) -> str:
    return f"{strict_prefix_column_base(label)} LRU 目标总 TPS 最小机器数"


def strict_prefix_column_base(label: str) -> str:
    suffix = " 命中率"
    if label.endswith(suffix):
        return label[: -len(suffix)]
    return label
