from __future__ import annotations

import heapq
from array import array
from dataclasses import dataclass
from typing import Iterable

from kvcache_upper_bound.core.models import EffectiveRequest, ModelProfile
from kvcache_upper_bound.oracle.content import _estimate_hit_tokens, _safe_ratio
from kvcache_upper_bound.oracle.prefix_trie import PrefixTrie


@dataclass(frozen=True)
class CapacityRequestMetric:
    request_id: str
    scope_root_id: str
    request_type: str
    turn: int
    total_blocks: int
    hit_blocks: int
    strict_prefix_hit_blocks: int
    miss_blocks: int
    total_tokens: int
    hit_tokens_est: int
    strict_prefix_hit_tokens_est: int
    miss_tokens_est: int
    total_kv_bytes: int
    hit_kv_bytes: int
    strict_prefix_hit_kv_bytes: int
    miss_kv_bytes: int


@dataclass(frozen=True)
class CapacitySummary:
    budget_bytes: int
    resident_block_capacity: int
    total_requests: int
    total_blocks: int
    hit_blocks: int
    strict_prefix_hit_blocks: int
    miss_blocks: int
    block_hit_rate: float
    strict_prefix_block_hit_rate: float
    total_tokens: int
    hit_tokens_est: int
    strict_prefix_hit_tokens_est: int
    miss_tokens_est: int
    token_hit_rate_est: float
    strict_prefix_token_hit_rate_est: float
    total_kv_bytes: int
    hit_kv_bytes: int
    strict_prefix_hit_kv_bytes: int
    miss_kv_bytes: int
    kv_byte_hit_rate: float
    strict_prefix_kv_byte_hit_rate: float


@dataclass(frozen=True)
class CapacityAnalysisResult:
    request_metrics: list[CapacityRequestMetric]
    summary: CapacitySummary


@dataclass(frozen=True)
class _AccessTrace:
    requests: list[EffectiveRequest]
    request_ranges: list[tuple[int, int]]
    access_events: array
    unique_node_count: int


def analyze_capacity_upper_bound(
    requests: Iterable[EffectiveRequest],
    model_profile: ModelProfile,
    budget_bytes: int,
    block_size: int = 16,
) -> CapacityAnalysisResult:
    if budget_bytes < 0:
        raise ValueError("budget_bytes must be non-negative")
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if model_profile.block_size != block_size:
        raise ValueError("model_profile.block_size must match analysis block_size")

    bytes_per_block = model_profile.kv_bytes_per_block()
    resident_block_capacity = budget_bytes // bytes_per_block if bytes_per_block > 0 else 0
    access_trace = _build_access_trace(requests)
    if resident_block_capacity >= access_trace.unique_node_count:
        event_hits = _run_unbounded_cache(access_trace.access_events)
    else:
        event_hits = _run_belady(access_trace.access_events, resident_block_capacity)

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
    return CapacityAnalysisResult(request_metrics=request_metrics, summary=summary)


def _build_access_trace(requests: Iterable[EffectiveRequest]) -> _AccessTrace:
    ordered_requests = sorted(requests, key=lambda request: (request.timestamp_ms, request.source_index))
    tries_by_scope: dict[str, PrefixTrie] = {}
    global_node_ids: dict[tuple[str, int], int] = {}
    next_global_node_id = 0

    access_events = array("I")
    request_ranges: list[tuple[int, int]] = []

    for request in ordered_requests:
        trie = tries_by_scope.setdefault(request.scope_root_id, PrefixTrie())
        _, local_node_ids = trie.match_and_insert_path(request.effective_hash_ids)
        start = len(access_events)
        for local_node_id in local_node_ids:
            key = (request.scope_root_id, local_node_id)
            global_node_id = global_node_ids.get(key)
            if global_node_id is None:
                global_node_id = next_global_node_id
                global_node_ids[key] = global_node_id
                next_global_node_id += 1
            access_events.append(global_node_id)
        end = len(access_events)
        request_ranges.append((start, end))

    return _AccessTrace(
        requests=ordered_requests,
        request_ranges=request_ranges,
        access_events=access_events,
        unique_node_count=len(global_node_ids),
    )


def _run_belady(access_events: array, resident_block_capacity: int) -> bytearray:
    event_count = len(access_events)
    event_hits = bytearray(event_count)
    if resident_block_capacity <= 0 or event_count == 0:
        return event_hits

    next_positions = array("I", [event_count]) * event_count
    next_seen: dict[int, int] = {}
    for index in range(event_count - 1, -1, -1):
        node_id = access_events[index]
        next_positions[index] = next_seen.get(node_id, event_count)
        next_seen[node_id] = index

    resident: set[int] = set()
    current_serial: dict[int, int] = {}
    heap: list[tuple[int, int, int]] = []
    serial = 0

    for index, node_id in enumerate(access_events):
        next_position = next_positions[index]
        if node_id in resident:
            event_hits[index] = 1
        else:
            if len(resident) >= resident_block_capacity:
                _evict_farthest_future(resident, current_serial, heap)
            if len(resident) < resident_block_capacity:
                resident.add(node_id)

        if node_id in resident:
            serial += 1
            current_serial[node_id] = serial
            heapq.heappush(heap, (-next_position, serial, node_id))

    return event_hits


def _run_unbounded_cache(access_events: array) -> bytearray:
    event_hits = bytearray(len(access_events))
    seen: set[int] = set()
    for index, node_id in enumerate(access_events):
        if node_id in seen:
            event_hits[index] = 1
        else:
            seen.add(node_id)
    return event_hits


def _count_prefix_hits(event_hits: bytearray, start: int, end: int) -> int:
    hit_blocks = 0
    for index in range(start, end):
        if event_hits[index] != 1:
            break
        hit_blocks += 1
    return hit_blocks


def _evict_farthest_future(
    resident: set[int],
    current_serial: dict[int, int],
    heap: list[tuple[int, int, int]],
) -> None:
    while heap:
        _, serial, node_id = heapq.heappop(heap)
        if node_id not in resident:
            continue
        if current_serial.get(node_id) != serial:
            continue
        resident.remove(node_id)
        current_serial.pop(node_id, None)
        return
