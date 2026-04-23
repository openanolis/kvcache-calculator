from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable

from kvcache_upper_bound.core.models import EffectiveRequest, ModelProfile
from kvcache_upper_bound.oracle.capacity import (
    CapacityRequestMetric,
    CapacitySummary,
    _build_access_trace,
    _count_prefix_hits,
)
from kvcache_upper_bound.oracle.content import _estimate_hit_tokens, _safe_ratio


@dataclass(frozen=True)
class LRUSimulationResult:
    request_metrics: list[CapacityRequestMetric]
    summary: CapacitySummary


def analyze_lru_baseline(
    requests: Iterable[EffectiveRequest],
    model_profile: ModelProfile,
    budget_bytes: int,
    block_size: int = 16,
    include_output_kvcache: bool = False,
) -> LRUSimulationResult:
    if budget_bytes < 0:
        raise ValueError("budget_bytes must be non-negative")
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if model_profile.block_size != block_size:
        raise ValueError("model_profile.block_size must match analysis block_size")

    bytes_per_block = model_profile.kv_bytes_per_block()
    resident_block_capacity = budget_bytes // bytes_per_block if bytes_per_block > 0 else 0
    access_trace = _build_access_trace(requests, include_output_kvcache=include_output_kvcache)
    event_hits = _run_lru(access_trace.access_events, resident_block_capacity)

    request_metrics: list[CapacityRequestMetric] = []
    total_blocks = 0
    hit_blocks = 0
    strict_prefix_hit_blocks = 0
    total_tokens = 0
    hit_tokens_est = 0
    strict_prefix_hit_tokens_est = 0

    for request, (start, end) in zip(access_trace.requests, access_trace.request_ranges):
        request_hit_blocks = sum(event_hits[start:end])
        request_strict_prefix_hit_blocks = _count_prefix_hits(event_hits, start, end)
        request_total_blocks = request.effective_blocks
        request_miss_blocks = request_total_blocks - request_hit_blocks
        request_hit_tokens = _estimate_hit_tokens(
            effective_blocks=request_total_blocks,
            effective_tokens=request.effective_tokens,
            hit_blocks=request_hit_blocks,
            block_size=block_size,
        )
        request_strict_prefix_hit_tokens = _estimate_hit_tokens(
            effective_blocks=request_total_blocks,
            effective_tokens=request.effective_tokens,
            hit_blocks=request_strict_prefix_hit_blocks,
            block_size=block_size,
        )
        request_miss_tokens = request.effective_tokens - request_hit_tokens
        request_total_kv_bytes = request_total_blocks * bytes_per_block
        request_hit_kv_bytes = request_hit_blocks * bytes_per_block
        request_strict_prefix_hit_kv_bytes = request_strict_prefix_hit_blocks * bytes_per_block
        request_miss_kv_bytes = request_miss_blocks * bytes_per_block

        request_metrics.append(
            CapacityRequestMetric(
                request_id=request.request_id,
                scope_root_id=request.scope_root_id,
                request_type=request.request_type,
                turn=request.turn,
                total_blocks=request_total_blocks,
                hit_blocks=request_hit_blocks,
                strict_prefix_hit_blocks=request_strict_prefix_hit_blocks,
                miss_blocks=request_miss_blocks,
                total_tokens=request.effective_tokens,
                hit_tokens_est=request_hit_tokens,
                strict_prefix_hit_tokens_est=request_strict_prefix_hit_tokens,
                miss_tokens_est=request_miss_tokens,
                total_kv_bytes=request_total_kv_bytes,
                hit_kv_bytes=request_hit_kv_bytes,
                strict_prefix_hit_kv_bytes=request_strict_prefix_hit_kv_bytes,
                miss_kv_bytes=request_miss_kv_bytes,
            )
        )

        total_blocks += request_total_blocks
        hit_blocks += request_hit_blocks
        strict_prefix_hit_blocks += request_strict_prefix_hit_blocks
        total_tokens += request.effective_tokens
        hit_tokens_est += request_hit_tokens
        strict_prefix_hit_tokens_est += request_strict_prefix_hit_tokens

    miss_blocks = total_blocks - hit_blocks
    miss_tokens_est = total_tokens - hit_tokens_est
    total_kv_bytes = total_blocks * bytes_per_block
    hit_kv_bytes = hit_blocks * bytes_per_block
    strict_prefix_hit_kv_bytes = strict_prefix_hit_blocks * bytes_per_block
    miss_kv_bytes = miss_blocks * bytes_per_block

    summary = CapacitySummary(
        budget_bytes=budget_bytes,
        resident_block_capacity=resident_block_capacity,
        total_requests=len(access_trace.requests),
        total_blocks=total_blocks,
        hit_blocks=hit_blocks,
        strict_prefix_hit_blocks=strict_prefix_hit_blocks,
        miss_blocks=miss_blocks,
        block_hit_rate=_safe_ratio(hit_blocks, total_blocks),
        strict_prefix_block_hit_rate=_safe_ratio(strict_prefix_hit_blocks, total_blocks),
        total_tokens=total_tokens,
        hit_tokens_est=hit_tokens_est,
        strict_prefix_hit_tokens_est=strict_prefix_hit_tokens_est,
        miss_tokens_est=miss_tokens_est,
        token_hit_rate_est=_safe_ratio(hit_tokens_est, total_tokens),
        strict_prefix_token_hit_rate_est=_safe_ratio(strict_prefix_hit_tokens_est, total_tokens),
        total_kv_bytes=total_kv_bytes,
        hit_kv_bytes=hit_kv_bytes,
        strict_prefix_hit_kv_bytes=strict_prefix_hit_kv_bytes,
        miss_kv_bytes=miss_kv_bytes,
        kv_byte_hit_rate=_safe_ratio(hit_kv_bytes, total_kv_bytes),
        strict_prefix_kv_byte_hit_rate=_safe_ratio(strict_prefix_hit_kv_bytes, total_kv_bytes),
    )
    return LRUSimulationResult(request_metrics=request_metrics, summary=summary)


def _run_lru(access_events: Iterable[int], resident_block_capacity: int) -> bytearray:
    access_list = list(access_events)
    event_hits = bytearray(len(access_list))
    if resident_block_capacity <= 0 or not access_list:
        return event_hits

    resident: OrderedDict[int, None] = OrderedDict()

    for index, node_id in enumerate(access_list):
        if node_id in resident:
            event_hits[index] = 1
            resident.move_to_end(node_id, last=True)
            continue

        if len(resident) >= resident_block_capacity:
            resident.popitem(last=False)
        resident[node_id] = None

    return event_hits
