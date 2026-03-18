from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class TargetTPSPlan:
    target_total_tps: float | None
    baseline_per_card_tps: float | None
    current_cluster_capacity_tps: float | None
    min_card_count: int | None
    min_machine_count: int | None


def tps_gain(hit_rate: float | None, alpha: float) -> float | None:
    if hit_rate is None:
        return None
    denominator = 1.0 - alpha * hit_rate
    if denominator <= 0.0:
        return math.inf
    return 1.0 / denominator


def estimated_total_tps(base_tps: float | None, gain: float | None) -> float | None:
    if base_tps is None or gain is None:
        return None
    return base_tps * gain


def estimated_card_count(card_count: int, gain: float | None) -> float | None:
    if gain is None:
        return None
    if math.isinf(gain):
        return 0.0
    return card_count / gain


def estimated_machine_count(
    estimated_card_count_value: float | None,
    cards_per_machine: int,
) -> float | None:
    if estimated_card_count_value is None:
        return None
    if cards_per_machine <= 0:
        raise ValueError("cards_per_machine must be positive")
    return estimated_card_count_value / cards_per_machine


def cluster_capacity_tps(
    *,
    card_count: int,
    baseline_per_card_tps: float | None,
    hit_rate: float | None,
    alpha: float,
) -> float | None:
    if baseline_per_card_tps is None:
        return None
    gain = tps_gain(hit_rate, alpha)
    if gain is None:
        return None
    return card_count * baseline_per_card_tps * gain


def build_target_tps_plan(
    *,
    target_total_tps: float | None,
    baseline_per_card_tps: float | None,
    current_machine_count: int,
    cards_per_machine: int,
    cluster_tps_at_machine_count: Callable[[int], float | None],
) -> TargetTPSPlan:
    current_cluster_capacity_tps = cluster_tps_at_machine_count(current_machine_count)
    if target_total_tps is None or baseline_per_card_tps is None:
        return TargetTPSPlan(
            target_total_tps=target_total_tps,
            baseline_per_card_tps=baseline_per_card_tps,
            current_cluster_capacity_tps=current_cluster_capacity_tps,
            min_card_count=None,
            min_machine_count=None,
        )
    if target_total_tps < 0.0:
        raise ValueError("planning_target_total_tps must be non-negative")
    if baseline_per_card_tps <= 0.0:
        raise ValueError("baseline_per_card_tps must be positive")
    if cards_per_machine <= 0:
        raise ValueError("cards_per_machine must be positive")
    if target_total_tps == 0.0:
        return TargetTPSPlan(
            target_total_tps=target_total_tps,
            baseline_per_card_tps=baseline_per_card_tps,
            current_cluster_capacity_tps=current_cluster_capacity_tps,
            min_card_count=0,
            min_machine_count=0,
        )

    no_hit_machine_upper_bound = max(
        1,
        math.ceil(target_total_tps / (baseline_per_card_tps * cards_per_machine)),
    )
    upper_capacity_tps = cluster_tps_at_machine_count(no_hit_machine_upper_bound)
    if upper_capacity_tps is None:
        return TargetTPSPlan(
            target_total_tps=target_total_tps,
            baseline_per_card_tps=baseline_per_card_tps,
            current_cluster_capacity_tps=current_cluster_capacity_tps,
            min_card_count=None,
            min_machine_count=None,
        )

    low = 1
    high = no_hit_machine_upper_bound
    while low < high:
        mid = (low + high) // 2
        mid_capacity_tps = cluster_tps_at_machine_count(mid)
        if mid_capacity_tps is None:
            return TargetTPSPlan(
                target_total_tps=target_total_tps,
                baseline_per_card_tps=baseline_per_card_tps,
                current_cluster_capacity_tps=current_cluster_capacity_tps,
                min_card_count=None,
                min_machine_count=None,
            )
        if mid_capacity_tps >= target_total_tps:
            high = mid
        else:
            low = mid + 1

    min_machine_count = low
    return TargetTPSPlan(
        target_total_tps=target_total_tps,
        baseline_per_card_tps=baseline_per_card_tps,
        current_cluster_capacity_tps=current_cluster_capacity_tps,
        min_card_count=min_machine_count * cards_per_machine,
        min_machine_count=min_machine_count,
    )
