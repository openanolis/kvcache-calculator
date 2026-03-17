from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from typing import Iterable, Sequence

from kvcache_upper_bound.core.models import EffectiveRequest, ModelProfile, Scope
from kvcache_upper_bound.oracle.capacity import _build_access_trace
from kvcache_upper_bound.oracle.content import (
    ContentAnalysisResult,
    ContentRequestMetric,
    ContentSummary,
    _estimate_hit_tokens,
    _safe_ratio,
)


@dataclass(frozen=True)
class ExhaustiveVerificationSummary:
    content_case_count: int
    relaxed_capacity_case_count: int


@dataclass(frozen=True)
class StrictPrefixCounterexample:
    requests: tuple[tuple[str, ...], ...]
    resident_block_capacity: int
    content_hit_blocks: int
    relaxed_capacity_hit_blocks: int
    strict_prefix_hit_blocks: int


def analyze_content_upper_bound_naive(
    requests: Iterable[EffectiveRequest],
    model_profile: ModelProfile | None = None,
    block_size: int = 16,
) -> ContentAnalysisResult:
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if model_profile is not None and model_profile.block_size != block_size:
        raise ValueError("model_profile.block_size must match analysis block_size")

    ordered_requests = sorted(
        requests,
        key=lambda request: (request.timestamp_ms, request.source_index),
    )
    prior_paths_by_scope: dict[str, list[tuple[str, ...]]] = {}
    request_metrics: list[ContentRequestMetric] = []

    total_blocks = 0
    hit_blocks = 0
    total_tokens = 0
    hit_tokens_est = 0

    kv_bytes_per_block = model_profile.kv_bytes_per_block() if model_profile else None
    total_kv_bytes = 0 if kv_bytes_per_block is not None else None
    hit_kv_bytes = 0 if kv_bytes_per_block is not None else None

    for request in ordered_requests:
        prior_paths = prior_paths_by_scope.setdefault(request.scope_root_id, [])
        matched_blocks = _naive_matched_prefix_blocks(prior_paths, request.effective_hash_ids)
        miss_blocks = request.effective_blocks - matched_blocks
        matched_tokens = _estimate_hit_tokens(
            effective_blocks=request.effective_blocks,
            effective_tokens=request.effective_tokens,
            hit_blocks=matched_blocks,
            block_size=block_size,
        )
        miss_tokens = request.effective_tokens - matched_tokens

        request_total_kv_bytes = (
            request.effective_blocks * kv_bytes_per_block if kv_bytes_per_block is not None else None
        )
        request_hit_kv_bytes = matched_blocks * kv_bytes_per_block if kv_bytes_per_block is not None else None
        request_miss_kv_bytes = miss_blocks * kv_bytes_per_block if kv_bytes_per_block is not None else None

        request_metrics.append(
            ContentRequestMetric(
                request_id=request.request_id,
                scope_root_id=request.scope_root_id,
                request_type=request.request_type,
                turn=request.turn,
                total_blocks=request.effective_blocks,
                hit_blocks=matched_blocks,
                miss_blocks=miss_blocks,
                total_tokens=request.effective_tokens,
                hit_tokens_est=matched_tokens,
                miss_tokens_est=miss_tokens,
                total_kv_bytes=request_total_kv_bytes,
                hit_kv_bytes=request_hit_kv_bytes,
                miss_kv_bytes=request_miss_kv_bytes,
            )
        )

        prior_paths.append(request.effective_hash_ids)
        total_blocks += request.effective_blocks
        hit_blocks += matched_blocks
        total_tokens += request.effective_tokens
        hit_tokens_est += matched_tokens
        if total_kv_bytes is not None and hit_kv_bytes is not None:
            total_kv_bytes += request_total_kv_bytes or 0
            hit_kv_bytes += request_hit_kv_bytes or 0

    miss_blocks = total_blocks - hit_blocks
    miss_tokens_est = total_tokens - hit_tokens_est
    miss_kv_bytes = None if total_kv_bytes is None or hit_kv_bytes is None else total_kv_bytes - hit_kv_bytes

    return ContentAnalysisResult(
        request_metrics=request_metrics,
        summary=ContentSummary(
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
            kv_byte_hit_rate=None
            if total_kv_bytes is None or hit_kv_bytes is None
            else _safe_ratio(hit_kv_bytes, total_kv_bytes),
        ),
    )


def verify_exhaustive_small_cases(
    max_requests: int = 4,
    max_blocks_per_request: int = 3,
    alphabet: Sequence[str] = ("a", "b"),
) -> ExhaustiveVerificationSummary:
    request_traces = _iter_small_request_traces(max_requests, max_blocks_per_request, alphabet)
    content_case_count = 0
    relaxed_capacity_case_count = 0
    model_profile = ModelProfile(
        n_layers=1,
        n_kv_heads=1,
        head_dim=1,
        dtype_bytes=1,
        block_size=16,
    )
    budget_bytes_per_block = model_profile.kv_bytes_per_block()

    from kvcache_upper_bound.oracle import analyze_capacity_upper_bound, analyze_content_upper_bound

    for requests in request_traces:
        content_case_count += 1
        fast = analyze_content_upper_bound(requests, block_size=16)
        slow = analyze_content_upper_bound_naive(requests, block_size=16)
        if fast.summary.hit_blocks != slow.summary.hit_blocks:
            raise AssertionError(
                f"content oracle mismatch: {[_request_path_key(request) for request in requests]}"
            )

        access_trace = _build_access_trace(requests)
        unique_node_count = access_trace.unique_node_count
        for capacity in range(0, min(4, unique_node_count + 1)):
            relaxed_capacity_case_count += 1
            got = analyze_capacity_upper_bound(
                requests,
                model_profile=model_profile,
                budget_bytes=capacity * budget_bytes_per_block,
            ).summary.hit_blocks
            want = _bruteforce_relaxed_event_hit_count(tuple(access_trace.access_events), capacity)
            if got != want:
                raise AssertionError(
                    "relaxed capacity mismatch: "
                    f"trace={[_request_path_key(request) for request in requests]} "
                    f"capacity={capacity} got={got} want={want}"
                )

    return ExhaustiveVerificationSummary(
        content_case_count=content_case_count,
        relaxed_capacity_case_count=relaxed_capacity_case_count,
    )


def find_smallest_strict_prefix_gap_counterexample() -> StrictPrefixCounterexample:
    from kvcache_upper_bound.oracle import analyze_capacity_upper_bound, analyze_content_upper_bound

    model_profile = ModelProfile(
        n_layers=1,
        n_kv_heads=1,
        head_dim=1,
        dtype_bytes=1,
        block_size=16,
    )
    budget_bytes_per_block = model_profile.kv_bytes_per_block()

    for requests in _iter_small_request_traces(max_requests=3, max_blocks_per_request=4, alphabet=("a", "b")):
        access_trace = _build_access_trace(requests)
        unique_node_count = access_trace.unique_node_count
        if unique_node_count <= 1:
            continue

        content_hit_blocks = analyze_content_upper_bound(requests, block_size=16).summary.hit_blocks
        for capacity in range(1, min(5, unique_node_count + 1)):
            relaxed_hit_blocks = analyze_capacity_upper_bound(
                requests,
                model_profile=model_profile,
                budget_bytes=capacity * budget_bytes_per_block,
            ).summary.hit_blocks
            strict_hit_blocks = _bruteforce_strict_prefix_hit_count(requests, capacity)
            if relaxed_hit_blocks > strict_hit_blocks:
                return StrictPrefixCounterexample(
                    requests=tuple(_request_path_key(request) for request in requests),
                    resident_block_capacity=capacity,
                    content_hit_blocks=content_hit_blocks,
                    relaxed_capacity_hit_blocks=relaxed_hit_blocks,
                    strict_prefix_hit_blocks=strict_hit_blocks,
                )

    raise AssertionError("failed to find a strict-prefix counterexample")


def _naive_matched_prefix_blocks(
    prior_paths: list[tuple[str, ...]],
    current_path: tuple[str, ...],
) -> int:
    best = 0
    for prior_path in prior_paths:
        matched = 0
        for left, right in zip(prior_path, current_path):
            if left != right:
                break
            matched += 1
        if matched > best:
            best = matched
        if best == len(current_path):
            return best
    return best


def _bruteforce_relaxed_event_hit_count(access_events: tuple[int, ...], resident_block_capacity: int) -> int:
    @lru_cache(maxsize=None)
    def solve(index: int, resident: tuple[int, ...]) -> int:
        if index == len(access_events):
            return 0

        resident_set = set(resident)
        node_id = access_events[index]
        if node_id in resident_set:
            return 1 + solve(index + 1, resident)
        if resident_block_capacity <= 0:
            return solve(index + 1, tuple())
        if len(resident_set) < resident_block_capacity:
            return solve(index + 1, tuple(sorted((*resident_set, node_id))))

        best = 0
        for victim in resident:
            next_resident = set(resident_set)
            next_resident.remove(victim)
            next_resident.add(node_id)
            best = max(best, solve(index + 1, tuple(sorted(next_resident))))
        return best

    return solve(0, tuple())


def _bruteforce_strict_prefix_hit_count(
    requests: Sequence[EffectiveRequest],
    resident_block_capacity: int,
) -> int:
    access_trace = _build_access_trace(requests)
    access_events = tuple(access_trace.access_events)
    request_end_by_index = _build_request_end_flags(access_trace.request_ranges, len(access_events))

    @lru_cache(maxsize=None)
    def solve(index: int, resident: tuple[int, ...], prefix_alive: bool) -> int:
        if index == len(access_events):
            return 0

        resident_set = set(resident)
        node_id = access_events[index]
        request_ends_here = request_end_by_index[index]

        if node_id in resident_set:
            immediate = 1 if prefix_alive else 0
            next_prefix_alive = True if request_ends_here else prefix_alive
            return immediate + solve(index + 1, resident, next_prefix_alive)

        next_prefix_alive = True if request_ends_here else False
        if resident_block_capacity <= 0:
            return solve(index + 1, tuple(), next_prefix_alive)
        if len(resident_set) < resident_block_capacity:
            next_resident = tuple(sorted((*resident_set, node_id)))
            return solve(index + 1, next_resident, next_prefix_alive)

        best = 0
        for victim in resident:
            next_resident_set = set(resident_set)
            next_resident_set.remove(victim)
            next_resident_set.add(node_id)
            best = max(
                best,
                solve(index + 1, tuple(sorted(next_resident_set)), next_prefix_alive),
            )
        return best

    return solve(0, tuple(), True)


def _build_request_end_flags(
    request_ranges: Sequence[tuple[int, int]],
    event_count: int,
) -> tuple[bool, ...]:
    flags = [False] * event_count
    for _, end in request_ranges:
        if end > 0:
            flags[end - 1] = True
    return tuple(flags)


def _iter_small_request_traces(
    max_requests: int,
    max_blocks_per_request: int,
    alphabet: Sequence[str],
) -> Iterable[list[EffectiveRequest]]:
    request_shapes: list[tuple[str, ...]] = []
    for block_count in range(1, max_blocks_per_request + 1):
        request_shapes.extend(product(alphabet, repeat=block_count))

    for request_count in range(1, max_requests + 1):
        for trace in product(request_shapes, repeat=request_count):
            yield [
                EffectiveRequest(
                    request_id=f"ref-{request_index}",
                    source_index=request_index,
                    timestamp_ms=(request_index + 1) * 1000,
                    chat_id=f"chat-{request_index}",
                    scope=Scope.GLOBAL,
                    scope_root_id="__global__",
                    turn=request_index + 1,
                    request_type="text",
                    input_length=len(blocks) * 16,
                    output_length=1,
                    total_blocks=len(blocks),
                    effective_blocks=len(blocks),
                    effective_tokens=len(blocks) * 16,
                    effective_hash_ids=tuple(blocks),
                )
                for request_index, blocks in enumerate(trace)
            ]


def _request_path_key(request: EffectiveRequest) -> tuple[str, ...]:
    return tuple(request.effective_hash_ids)
