from __future__ import annotations

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
class PrefixAwareSimulationResult:
    request_metrics: list[CapacityRequestMetric]
    summary: CapacitySummary


def analyze_prefix_aware(
    requests: Iterable[EffectiveRequest],
    model_profile: ModelProfile,
    budget_bytes: int,
    block_size: int = 16,
    include_output_kvcache: bool = False,
) -> PrefixAwareSimulationResult:
    if budget_bytes < 0:
        raise ValueError("budget_bytes must be non-negative")
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if model_profile.block_size != block_size:
        raise ValueError("model_profile.block_size must match analysis block_size")

    bytes_per_block = model_profile.kv_bytes_per_block()
    resident_block_capacity = budget_bytes // bytes_per_block if bytes_per_block > 0 else 0
    access_trace = _build_access_trace(requests, include_output_kvcache=include_output_kvcache)
    event_hits = _run_prefix_aware(access_trace.access_events, resident_block_capacity)

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
    return PrefixAwareSimulationResult(request_metrics=request_metrics, summary=summary)


def _run_prefix_aware(access_events: Iterable[int], resident_block_capacity: int) -> bytearray:
    """Prefix-aware eviction: never evict a parent of another resident block.

    Among leaf nodes (blocks with no resident children), evict by LFU
    (lowest frequency; ties broken by earliest insertion).

    Parent relationships: if blocks [A, B, C] appear sequentially in one
    request's access pattern, then A is parent of B, and B is parent of C.
    """
    access_list = list(access_events)
    event_hits = bytearray(len(access_list))
    if resident_block_capacity <= 0 or not access_list:
        return event_hits

    # parent[node_id] = parent node_id (or None if root)
    parent: dict[int, int | None] = {}
    # children[node_id] = set of child node_ids that are currently resident
    children: dict[int, set[int]] = {}
    # freq[node_id] = access count while resident
    freq: dict[int, int] = {}
    # insertion_order[node_id] = order of first insertion (for tie-breaking)
    insertion_order: dict[int, int] = {}
    resident: set[int] = set()
    next_insertion_order = 0

    # We need to track sequential access patterns to build parent relationships.
    # Within each request's block sequence, consecutive blocks form parent-child chains.
    # We process event by event. We track per-request sequences by examining
    # the access_events in their original order (which is request-by-request, block-by-block).
    # Since access_events is a flat list of all block accesses across all requests
    # in order, and within each request the blocks are sequential, we need to know
    # the request boundaries. However, since we only have the flat list here,
    # we establish parent relationships based on consecutive appearances:
    # if node B immediately follows node A in the access stream AND they share
    # the same request (consecutive in the flat list), then A is parent of B.
    #
    # Since _build_access_trace appends blocks request-by-request in sequential
    # order within each request, consecutive events within the same request
    # represent a path. We'll use previous_node to track this.

    previous_node: int | None = None
    # We need to know request boundaries to reset previous_node between requests.
    # Since we don't have request_ranges here, we reconstruct from access patterns:
    # The simplest approach: build parent map from all sequential pairs in the trace.
    # A block can have only one parent (the last one seen to precede it).
    # Build parent map in a first pass.

    # First pass: build parent relationships from sequential access patterns
    # We track request boundaries by looking at the structure: within each request,
    # blocks form a path. Between requests, there's a boundary. Since we only have
    # the flat list, we use a heuristic: if the same node_id appears after its known
    # descendant, it's a new request start. More precisely, we track the "current path"
    # and reset when we see a node that's already an ancestor.
    #
    # Actually, the simplest correct approach: since access_events preserves
    # request-by-request ordering with blocks sequential within each request,
    # we just need to detect request boundaries. A request boundary occurs when
    # a new path starts. We detect this by: the next block is NOT a new child of
    # the current path (i.e., it either starts over or is already known).
    #
    # Best approach: build parent map from consecutive pairs, where a block's parent
    # is established by the FIRST time we see the pair (A, B) consecutively.
    # If B appears after different predecessors, keep the first-established parent.

    # Build parent relationships (first pass)
    for i in range(1, len(access_list)):
        node_id = access_list[i]
        prev_id = access_list[i - 1]
        if node_id not in parent:
            parent[node_id] = prev_id
    if access_list:
        if access_list[0] not in parent:
            parent[access_list[0]] = None

    # Ensure all nodes have parent entries
    for node_id in access_list:
        if node_id not in parent:
            parent[node_id] = None

    # Second pass: simulate the cache with prefix-aware eviction
    for index, node_id in enumerate(access_list):
        if node_id in resident:
            event_hits[index] = 1
            freq[node_id] += 1
            continue

        if len(resident) >= resident_block_capacity:
            # Evict a leaf node (no resident children) with lowest frequency
            victim = _find_leaf_victim(resident, children, freq, insertion_order)
            if victim is not None:
                _evict_node(victim, resident, children, parent, freq, insertion_order)

        # Admit the new block
        resident.add(node_id)
        freq[node_id] = 1
        insertion_order[node_id] = next_insertion_order
        next_insertion_order += 1
        children.setdefault(node_id, set())

        # Register this node as a child of its parent (if parent is resident)
        node_parent = parent.get(node_id)
        if node_parent is not None and node_parent in resident:
            children.setdefault(node_parent, set()).add(node_id)

    return event_hits


def _find_leaf_victim(
    resident: set[int],
    children: dict[int, set[int]],
    freq: dict[int, int],
    insertion_order: dict[int, int],
) -> int | None:
    """Find the leaf node (no resident children) with lowest frequency."""
    best_victim: int | None = None
    best_freq = float("inf")
    best_order = float("inf")

    for node_id in resident:
        resident_children = children.get(node_id, set())
        # A node is a leaf if it has no resident children
        if resident_children:
            continue
        node_freq = freq.get(node_id, 0)
        node_order = insertion_order.get(node_id, 0)
        if (node_freq, node_order) < (best_freq, best_order):
            best_freq = node_freq
            best_order = node_order
            best_victim = node_id

    # If no leaf found (shouldn't happen in practice since there's always at least
    # one leaf in a tree/forest), fall back to LFU on all resident blocks
    if best_victim is None:
        best_victim = min(resident, key=lambda nid: (freq.get(nid, 0), insertion_order.get(nid, 0)))

    return best_victim


def _evict_node(
    node_id: int,
    resident: set[int],
    children: dict[int, set[int]],
    parent: dict[int, int | None],
    freq: dict[int, int],
    insertion_order: dict[int, int],
) -> None:
    """Remove a node from resident set and update parent's children set."""
    resident.remove(node_id)
    freq.pop(node_id, None)
    insertion_order.pop(node_id, None)

    # Remove from parent's children set
    node_parent = parent.get(node_id)
    if node_parent is not None and node_parent in children:
        children[node_parent].discard(node_id)

    # Clean up own children set
    children.pop(node_id, None)
