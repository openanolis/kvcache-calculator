from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from typing import Iterable, Literal

from kvcache_upper_bound.core.models import EffectiveRequest, ModelProfile
from kvcache_upper_bound.oracle.capacity import _build_access_trace, analyze_capacity_upper_bound
from kvcache_upper_bound.oracle.content import (
    _estimate_hit_tokens,
    _safe_ratio,
    analyze_content_upper_bound,
)


StrictPrefixProofSource = Literal["certificate", "search"]


@dataclass(frozen=True)
class StrictPrefixRequestMetric:
    request_id: str
    scope_root_id: str
    request_type: str
    turn: int
    total_blocks: int
    hit_blocks: int
    miss_blocks: int
    total_tokens: int
    hit_tokens_est: int
    miss_tokens_est: int
    total_kv_bytes: int
    hit_kv_bytes: int
    miss_kv_bytes: int


@dataclass(frozen=True)
class StrictPrefixSummary:
    budget_bytes: int
    resident_block_capacity: int
    total_requests: int
    total_blocks: int
    hit_blocks: int
    miss_blocks: int
    block_hit_rate: float
    total_tokens: int
    hit_tokens_est: int
    miss_tokens_est: int
    token_hit_rate_est: float
    total_kv_bytes: int
    hit_kv_bytes: int
    miss_kv_bytes: int
    kv_byte_hit_rate: float
    proof_source: StrictPrefixProofSource
    certified_lower_bound_hit_blocks: int
    certified_upper_bound_hit_blocks: int
    search_state_count: int


@dataclass(frozen=True)
class StrictPrefixAnalysisResult:
    request_metrics: list[StrictPrefixRequestMetric]
    summary: StrictPrefixSummary


def analyze_strict_prefix_capacity_upper_bound(
    requests: Iterable[EffectiveRequest],
    model_profile: ModelProfile,
    budget_bytes: int,
    block_size: int = 16,
    include_output_kvcache: bool = False,
) -> StrictPrefixAnalysisResult:
    if budget_bytes < 0:
        raise ValueError("budget_bytes must be non-negative")
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if model_profile.block_size != block_size:
        raise ValueError("model_profile.block_size must match analysis block_size")

    ordered_requests = sorted(
        requests,
        key=lambda request: (request.timestamp_ms, request.source_index),
    )
    content_result = analyze_content_upper_bound(
        ordered_requests,
        model_profile=model_profile,
        block_size=block_size,
        include_output_kvcache=include_output_kvcache,
    )
    relaxed_result = analyze_capacity_upper_bound(
        ordered_requests,
        model_profile=model_profile,
        budget_bytes=budget_bytes,
        block_size=block_size,
        include_output_kvcache=include_output_kvcache,
    )

    resident_block_capacity = relaxed_result.summary.resident_block_capacity
    certified_lower_bound_hit_blocks = relaxed_result.summary.strict_prefix_hit_blocks
    certified_upper_bound_hit_blocks = content_result.summary.hit_blocks

    if certified_lower_bound_hit_blocks == certified_upper_bound_hit_blocks:
        return _build_certificate_result(
            content_result=content_result,
            resident_block_capacity=resident_block_capacity,
            budget_bytes=budget_bytes,
            proof_source="certificate",
            certified_lower_bound_hit_blocks=certified_lower_bound_hit_blocks,
            certified_upper_bound_hit_blocks=certified_upper_bound_hit_blocks,
            search_state_count=0,
        )

    if relaxed_result.summary.hit_blocks == certified_lower_bound_hit_blocks:
        return _build_relaxed_certificate_result(
            relaxed_result=relaxed_result,
            budget_bytes=budget_bytes,
            proof_source="certificate",
            certified_lower_bound_hit_blocks=certified_lower_bound_hit_blocks,
            certified_upper_bound_hit_blocks=relaxed_result.summary.hit_blocks,
            search_state_count=0,
        )

    search_result = _run_exact_request_dp(
        ordered_requests=ordered_requests,
        resident_block_capacity=resident_block_capacity,
        model_profile=model_profile,
        budget_bytes=budget_bytes,
        block_size=block_size,
        certified_lower_bound_hit_blocks=certified_lower_bound_hit_blocks,
        certified_upper_bound_hit_blocks=certified_upper_bound_hit_blocks,
        include_output_kvcache=include_output_kvcache,
    )
    if search_result.summary.hit_blocks != certified_upper_bound_hit_blocks:
        return search_result

    return _build_certificate_result(
        content_result=content_result,
        resident_block_capacity=resident_block_capacity,
        budget_bytes=budget_bytes,
        proof_source="search",
        certified_lower_bound_hit_blocks=certified_lower_bound_hit_blocks,
        certified_upper_bound_hit_blocks=certified_upper_bound_hit_blocks,
        search_state_count=search_result.summary.search_state_count,
    )


def _build_certificate_result(
    content_result: object,
    resident_block_capacity: int,
    budget_bytes: int,
    proof_source: StrictPrefixProofSource,
    certified_lower_bound_hit_blocks: int,
    certified_upper_bound_hit_blocks: int,
    search_state_count: int,
) -> StrictPrefixAnalysisResult:
    request_metrics = [
        StrictPrefixRequestMetric(
            request_id=metric.request_id,
            scope_root_id=metric.scope_root_id,
            request_type=metric.request_type,
            turn=metric.turn,
            total_blocks=metric.total_blocks,
            hit_blocks=metric.hit_blocks,
            miss_blocks=metric.miss_blocks,
            total_tokens=metric.total_tokens,
            hit_tokens_est=metric.hit_tokens_est,
            miss_tokens_est=metric.miss_tokens_est,
            total_kv_bytes=metric.total_kv_bytes or 0,
            hit_kv_bytes=metric.hit_kv_bytes or 0,
            miss_kv_bytes=metric.miss_kv_bytes or 0,
        )
        for metric in content_result.request_metrics
    ]
    summary = StrictPrefixSummary(
        budget_bytes=budget_bytes,
        resident_block_capacity=resident_block_capacity,
        total_requests=content_result.summary.total_requests,
        total_blocks=content_result.summary.total_blocks,
        hit_blocks=content_result.summary.hit_blocks,
        miss_blocks=content_result.summary.miss_blocks,
        block_hit_rate=content_result.summary.block_hit_rate,
        total_tokens=content_result.summary.total_tokens,
        hit_tokens_est=content_result.summary.hit_tokens_est,
        miss_tokens_est=content_result.summary.miss_tokens_est,
        token_hit_rate_est=content_result.summary.token_hit_rate_est,
        total_kv_bytes=content_result.summary.total_kv_bytes or 0,
        hit_kv_bytes=content_result.summary.hit_kv_bytes or 0,
        miss_kv_bytes=content_result.summary.miss_kv_bytes or 0,
        kv_byte_hit_rate=content_result.summary.kv_byte_hit_rate or 0.0,
        proof_source=proof_source,
        certified_lower_bound_hit_blocks=certified_lower_bound_hit_blocks,
        certified_upper_bound_hit_blocks=certified_upper_bound_hit_blocks,
        search_state_count=search_state_count,
    )
    return StrictPrefixAnalysisResult(request_metrics=request_metrics, summary=summary)


def _build_relaxed_certificate_result(
    relaxed_result: object,
    budget_bytes: int,
    proof_source: StrictPrefixProofSource,
    certified_lower_bound_hit_blocks: int,
    certified_upper_bound_hit_blocks: int,
    search_state_count: int,
) -> StrictPrefixAnalysisResult:
    request_metrics = [
        StrictPrefixRequestMetric(
            request_id=metric.request_id,
            scope_root_id=metric.scope_root_id,
            request_type=metric.request_type,
            turn=metric.turn,
            total_blocks=metric.total_blocks,
            hit_blocks=metric.strict_prefix_hit_blocks,
            miss_blocks=metric.total_blocks - metric.strict_prefix_hit_blocks,
            total_tokens=metric.total_tokens,
            hit_tokens_est=metric.strict_prefix_hit_tokens_est,
            miss_tokens_est=metric.total_tokens - metric.strict_prefix_hit_tokens_est,
            total_kv_bytes=metric.total_kv_bytes,
            hit_kv_bytes=metric.strict_prefix_hit_kv_bytes,
            miss_kv_bytes=metric.total_kv_bytes - metric.strict_prefix_hit_kv_bytes,
        )
        for metric in relaxed_result.request_metrics
    ]
    summary = StrictPrefixSummary(
        budget_bytes=budget_bytes,
        resident_block_capacity=relaxed_result.summary.resident_block_capacity,
        total_requests=relaxed_result.summary.total_requests,
        total_blocks=relaxed_result.summary.total_blocks,
        hit_blocks=relaxed_result.summary.strict_prefix_hit_blocks,
        miss_blocks=relaxed_result.summary.total_blocks - relaxed_result.summary.strict_prefix_hit_blocks,
        block_hit_rate=relaxed_result.summary.strict_prefix_block_hit_rate,
        total_tokens=relaxed_result.summary.total_tokens,
        hit_tokens_est=relaxed_result.summary.strict_prefix_hit_tokens_est,
        miss_tokens_est=relaxed_result.summary.total_tokens
        - relaxed_result.summary.strict_prefix_hit_tokens_est,
        token_hit_rate_est=relaxed_result.summary.strict_prefix_token_hit_rate_est,
        total_kv_bytes=relaxed_result.summary.total_kv_bytes,
        hit_kv_bytes=relaxed_result.summary.strict_prefix_hit_kv_bytes,
        miss_kv_bytes=relaxed_result.summary.total_kv_bytes
        - relaxed_result.summary.strict_prefix_hit_kv_bytes,
        kv_byte_hit_rate=relaxed_result.summary.strict_prefix_kv_byte_hit_rate,
        proof_source=proof_source,
        certified_lower_bound_hit_blocks=certified_lower_bound_hit_blocks,
        certified_upper_bound_hit_blocks=certified_upper_bound_hit_blocks,
        search_state_count=search_state_count,
    )
    return StrictPrefixAnalysisResult(request_metrics=request_metrics, summary=summary)


def _run_exact_request_dp(
    ordered_requests: list[EffectiveRequest],
    resident_block_capacity: int,
    model_profile: ModelProfile,
    budget_bytes: int,
    block_size: int,
    certified_lower_bound_hit_blocks: int,
    certified_upper_bound_hit_blocks: int,
    include_output_kvcache: bool = False,
) -> StrictPrefixAnalysisResult:
    bytes_per_block = model_profile.kv_bytes_per_block()
    access_trace = _build_access_trace(ordered_requests, include_output_kvcache=include_output_kvcache)
    request_paths = [
        tuple(access_trace.access_events[start:end])
        for start, end in access_trace.request_ranges
    ]
    request_unique_nodes = [frozenset(path) for path in request_paths]
    future_nodes = _build_future_node_sets(request_unique_nodes)

    choice_cache: dict[tuple[int, tuple[int, ...]], tuple[int, ...]] = {}

    @lru_cache(maxsize=None)
    def solve(request_index: int, resident: tuple[int, ...]) -> int:
        if request_index >= len(ordered_requests):
            return 0

        current_path = request_paths[request_index]
        reward = _count_prefix_hits_from_resident(current_path, resident)
        next_pool = tuple(
            sorted((set(resident) | request_unique_nodes[request_index]) & future_nodes[request_index + 1])
        )
        next_size = min(resident_block_capacity, len(next_pool))

        if next_size <= 0:
            choice_cache[(request_index, resident)] = tuple()
            return reward + solve(request_index + 1, tuple())

        if next_size == len(next_pool):
            next_resident = next_pool
            choice_cache[(request_index, resident)] = next_resident
            return reward + solve(request_index + 1, next_resident)

        best_total = -1
        best_next = tuple()
        for next_resident in combinations(next_pool, next_size):
            total = solve(request_index + 1, next_resident)
            if total > best_total:
                best_total = total
                best_next = next_resident
        choice_cache[(request_index, resident)] = best_next
        return reward + best_total

    solve(0, tuple())

    request_metrics: list[StrictPrefixRequestMetric] = []
    total_blocks = 0
    hit_blocks = 0
    total_tokens = 0
    hit_tokens_est = 0
    resident = tuple()

    for request_index, request in enumerate(ordered_requests):
        request_hit_blocks = _count_prefix_hits_from_resident(request_paths[request_index], resident)
        request_total_blocks = request.effective_blocks
        request_miss_blocks = request_total_blocks - request_hit_blocks
        request_hit_tokens = _estimate_hit_tokens(
            effective_blocks=request_total_blocks,
            effective_tokens=request.effective_tokens,
            hit_blocks=request_hit_blocks,
            block_size=block_size,
        )
        request_miss_tokens = request.effective_tokens - request_hit_tokens
        request_total_kv_bytes = request_total_blocks * bytes_per_block
        request_hit_kv_bytes = request_hit_blocks * bytes_per_block
        request_miss_kv_bytes = request_miss_blocks * bytes_per_block

        request_metrics.append(
            StrictPrefixRequestMetric(
                request_id=request.request_id,
                scope_root_id=request.scope_root_id,
                request_type=request.request_type,
                turn=request.turn,
                total_blocks=request_total_blocks,
                hit_blocks=request_hit_blocks,
                miss_blocks=request_miss_blocks,
                total_tokens=request.effective_tokens,
                hit_tokens_est=request_hit_tokens,
                miss_tokens_est=request_miss_tokens,
                total_kv_bytes=request_total_kv_bytes,
                hit_kv_bytes=request_hit_kv_bytes,
                miss_kv_bytes=request_miss_kv_bytes,
            )
        )

        total_blocks += request_total_blocks
        hit_blocks += request_hit_blocks
        total_tokens += request.effective_tokens
        hit_tokens_est += request_hit_tokens
        resident = choice_cache.get((request_index, resident), tuple())

    miss_blocks = total_blocks - hit_blocks
    miss_tokens_est = total_tokens - hit_tokens_est
    total_kv_bytes = total_blocks * bytes_per_block
    hit_kv_bytes = hit_blocks * bytes_per_block
    miss_kv_bytes = miss_blocks * bytes_per_block

    summary = StrictPrefixSummary(
        budget_bytes=budget_bytes,
        resident_block_capacity=resident_block_capacity,
        total_requests=len(ordered_requests),
        total_blocks=total_blocks,
        hit_blocks=hit_blocks,
        miss_blocks=miss_blocks,
        block_hit_rate=_safe_ratio(hit_blocks, total_blocks),
        total_tokens=total_tokens,
        hit_tokens_est=hit_tokens_est,
        miss_tokens_est=miss_tokens_est,
        token_hit_rate_est=_safe_ratio(hit_tokens_est, total_tokens),
        total_kv_bytes=total_kv_bytes,
        hit_kv_bytes=hit_kv_bytes,
        miss_kv_bytes=miss_kv_bytes,
        kv_byte_hit_rate=_safe_ratio(hit_kv_bytes, total_kv_bytes),
        proof_source="search",
        certified_lower_bound_hit_blocks=certified_lower_bound_hit_blocks,
        certified_upper_bound_hit_blocks=certified_upper_bound_hit_blocks,
        search_state_count=solve.cache_info().currsize,
    )
    return StrictPrefixAnalysisResult(request_metrics=request_metrics, summary=summary)


def _build_future_node_sets(
    request_unique_nodes: list[frozenset[int]],
) -> list[frozenset[int]]:
    future_nodes: list[frozenset[int]] = [frozenset()] * (len(request_unique_nodes) + 1)
    current: set[int] = set()
    future_nodes[len(request_unique_nodes)] = frozenset()
    for request_index in range(len(request_unique_nodes) - 1, -1, -1):
        current.update(request_unique_nodes[request_index])
        future_nodes[request_index] = frozenset(current)
    return future_nodes


def _count_prefix_hits_from_resident(
    request_path: tuple[int, ...],
    resident: tuple[int, ...],
) -> int:
    resident_set = set(resident)
    for index, node_id in enumerate(request_path):
        if node_id not in resident_set:
            return index
    return len(request_path)
