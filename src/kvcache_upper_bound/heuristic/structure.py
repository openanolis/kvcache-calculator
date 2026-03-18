from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Iterable

from kvcache_upper_bound.core.models import RequestRecord
from kvcache_upper_bound.ingest import resolve_session_roots

from .multi_agent import HeuristicAnalysisConfig, HeuristicAnalysisResult, analyze_multi_agent_heuristic

DEFAULT_SHARED_PREFIX_COVERAGE = 0.8
DEFAULT_CONCURRENCY_QUANTILE = 0.95


@dataclass(frozen=True)
class TraceStructureHints:
    request_count: int
    session_count: int
    root_request_count: int
    shared_prefix_coverage: float
    stable_shared_prefix_tokens: float
    recommended_shared_prefix_tokens: float
    average_root_prompt_tokens: float
    recommended_avg_new_tokens_per_turn: float
    median_new_tokens_per_turn: float
    average_requests_per_session: float
    recommended_avg_turns_per_session: int
    observed_average_reusable_private_tokens: float
    recommended_private_window_tokens: float
    average_active_sessions: float
    p95_active_sessions: float
    max_active_sessions: int
    recommended_concurrent_agents: int
    recommended_zipf_population_blocks: int
    notes: tuple[str, ...]


@dataclass(frozen=True)
class TraceStructureRecommendation:
    hints: TraceStructureHints
    recommended_config: HeuristicAnalysisConfig
    recommended_analysis: HeuristicAnalysisResult


def estimate_multi_agent_structure_from_trace(
    records: Iterable[RequestRecord],
    *,
    block_size: int = 16,
    shared_prefix_coverage: float = DEFAULT_SHARED_PREFIX_COVERAGE,
    concurrency_quantile: float = DEFAULT_CONCURRENCY_QUANTILE,
) -> TraceStructureHints:
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if not 0.0 < shared_prefix_coverage <= 1.0:
        raise ValueError("shared_prefix_coverage must be within (0, 1]")
    if not 0.0 < concurrency_quantile <= 1.0:
        raise ValueError("concurrency_quantile must be within (0, 1]")

    ordered_records = sorted(records, key=lambda item: (item.timestamp_ms, item.source_index))
    request_count = len(ordered_records)
    if request_count == 0:
        raise ValueError("structure hints require at least one request")

    session_map = _build_trace_sessions(ordered_records)
    root_records = [session.root for session in session_map.sessions]
    stable_shared_prefix_tokens = _estimate_stable_shared_prefix_tokens(
        root_records,
        block_size=block_size,
        coverage=shared_prefix_coverage,
    )
    shared_prefix_tokens = _estimate_pairwise_shared_prefix_tokens(
        root_records,
        block_size=block_size,
    )
    new_tokens = _estimate_new_tokens_per_turn(
        session_map.sessions,
        shared_prefix_tokens=shared_prefix_tokens,
        block_size=block_size,
    )
    avg_new_tokens = _average(new_tokens)
    median_new_tokens = _median(new_tokens)
    avg_requests_per_session = _average(
        [float(len(session.records)) for session in session_map.sessions]
    )
    avg_turns_per_session = max(1, int(round(avg_requests_per_session)))
    reusable_private_observations = _estimate_reusable_private_tokens(
        session_map.sessions,
        shared_prefix_tokens=shared_prefix_tokens,
        block_size=block_size,
    )
    observed_average_reusable_private_tokens = _average(
        [item.reusable_private_tokens for item in reusable_private_observations]
    )
    private_window_tokens = _fit_private_window_tokens(
        reusable_private_observations,
        avg_new_tokens_per_turn=avg_new_tokens,
        block_size=block_size,
    )
    average_active_sessions, p95_active_sessions, max_active_sessions = _estimate_concurrency(
        session_map.sessions,
        quantile=concurrency_quantile,
    )
    concurrent_agents = max(1, int(math.ceil(p95_active_sessions)))
    recommended_zipf_population_blocks = max(
        1,
        math.ceil(
            (
                shared_prefix_tokens
                + concurrent_agents * observed_average_reusable_private_tokens
            )
            / block_size
        ),
    )

    notes: list[str] = []
    if len(root_records) < 4:
        notes.append("few session roots; shared-prefix estimate has low confidence")
    if stable_shared_prefix_tokens == 0:
        notes.append("no stable shared prefix at the configured coverage threshold")
    if avg_requests_per_session < 2.0:
        notes.append("sessions look shallow; private-window fit is driven mostly by first turns")
    if max_active_sessions <= 1:
        notes.append("trace shows little overlap between sessions; concurrency estimate stays conservative")

    return TraceStructureHints(
        request_count=request_count,
        session_count=len(session_map.sessions),
        root_request_count=len(root_records),
        shared_prefix_coverage=shared_prefix_coverage,
        stable_shared_prefix_tokens=stable_shared_prefix_tokens,
        recommended_shared_prefix_tokens=shared_prefix_tokens,
        average_root_prompt_tokens=_average([float(item.input_length) for item in root_records]),
        recommended_avg_new_tokens_per_turn=avg_new_tokens,
        median_new_tokens_per_turn=median_new_tokens,
        average_requests_per_session=avg_requests_per_session,
        recommended_avg_turns_per_session=avg_turns_per_session,
        observed_average_reusable_private_tokens=observed_average_reusable_private_tokens,
        recommended_private_window_tokens=private_window_tokens,
        average_active_sessions=average_active_sessions,
        p95_active_sessions=p95_active_sessions,
        max_active_sessions=max_active_sessions,
        recommended_concurrent_agents=concurrent_agents,
        recommended_zipf_population_blocks=recommended_zipf_population_blocks,
        notes=tuple(notes),
    )


def build_trace_structure_recommendation(
    base_config: HeuristicAnalysisConfig,
    *,
    records: Iterable[RequestRecord],
    block_size: int,
    observed_content_hit_rate: float | None = None,
    shared_prefix_coverage: float = DEFAULT_SHARED_PREFIX_COVERAGE,
    concurrency_quantile: float = DEFAULT_CONCURRENCY_QUANTILE,
) -> TraceStructureRecommendation:
    hints = estimate_multi_agent_structure_from_trace(
        records,
        block_size=block_size,
        shared_prefix_coverage=shared_prefix_coverage,
        concurrency_quantile=concurrency_quantile,
    )
    adjusted_avg_new_tokens = _derive_new_tokens_from_content_ceiling(
        shared_prefix_tokens=hints.recommended_shared_prefix_tokens,
        average_reusable_private_tokens=hints.observed_average_reusable_private_tokens,
        content_hit_rate=observed_content_hit_rate,
        fallback_avg_new_tokens=hints.recommended_avg_new_tokens_per_turn,
    )
    adjusted_avg_turns = max(
        hints.recommended_avg_turns_per_session,
        _minimum_turns_for_reuse(
            average_reusable_private_tokens=hints.observed_average_reusable_private_tokens,
            avg_new_tokens_per_turn=adjusted_avg_new_tokens,
        ),
    )
    adjusted_private_window_tokens = _fit_private_window_from_average_reuse(
        average_reusable_private_tokens=hints.observed_average_reusable_private_tokens,
        avg_turns_per_session=adjusted_avg_turns,
        avg_new_tokens_per_turn=adjusted_avg_new_tokens,
        block_size=block_size,
    )
    adjusted_average_reusable_private_tokens = _average_reusable_private_tokens(
        avg_turns_per_session=adjusted_avg_turns,
        avg_new_tokens_per_turn=adjusted_avg_new_tokens,
        private_window_tokens=adjusted_private_window_tokens,
    )
    adjusted_zipf_population_blocks = max(
        1,
        math.ceil(
            (
                hints.recommended_shared_prefix_tokens
                + hints.recommended_concurrent_agents * adjusted_average_reusable_private_tokens
            )
            / block_size
        ),
    )
    recommended_heuristic = replace(
        base_config.heuristic,
        concurrent_agents=hints.recommended_concurrent_agents,
        shared_prefix_tokens=hints.recommended_shared_prefix_tokens,
        avg_new_tokens_per_turn=adjusted_avg_new_tokens,
        avg_turns_per_session=adjusted_avg_turns,
        private_window_tokens=adjusted_private_window_tokens,
        curve_shape=replace(
            base_config.heuristic.curve_shape,
            zipf_population_blocks=adjusted_zipf_population_blocks,
        ),
    )
    recommended_config = replace(
        base_config,
        heuristic=recommended_heuristic,
    )
    recommended_analysis = analyze_multi_agent_heuristic(recommended_config)
    return TraceStructureRecommendation(
        hints=hints,
        recommended_config=recommended_config,
        recommended_analysis=recommended_analysis,
    )


@dataclass(frozen=True)
class _TraceSession:
    root: RequestRecord
    records: list[RequestRecord]


@dataclass(frozen=True)
class _ReusablePrivateObservation:
    turn_index: int
    reusable_private_tokens: float


@dataclass(frozen=True)
class _TraceSessionMap:
    sessions: list[_TraceSession]
    by_chat_id: dict[str, RequestRecord]


def _build_trace_sessions(records: list[RequestRecord]) -> _TraceSessionMap:
    session_resolution = resolve_session_roots(records)
    by_chat_id = {record.chat_id: record for record in records}
    session_buckets: dict[str, list[RequestRecord]] = {}
    for record in records:
        root_id = session_resolution.root_by_chat_id.get(record.chat_id, record.chat_id)
        session_buckets.setdefault(root_id, []).append(record)

    sessions: list[_TraceSession] = []
    for root_id, session_records in session_buckets.items():
        ordered = sorted(session_records, key=lambda item: (item.timestamp_ms, item.source_index))
        root_record = by_chat_id.get(root_id, ordered[0])
        if root_record not in ordered:
            ordered.insert(0, root_record)
        sessions.append(_TraceSession(root=root_record, records=ordered))

    sessions.sort(key=lambda session: (session.root.timestamp_ms, session.root.source_index))
    return _TraceSessionMap(
        sessions=sessions,
        by_chat_id=by_chat_id,
    )


@dataclass
class _RootPrefixNode:
    count: int = 0
    children: dict[str, "_RootPrefixNode"] | None = None

    def child(self, block_id: str) -> "_RootPrefixNode":
        if self.children is None:
            self.children = {}
        node = self.children.get(block_id)
        if node is None:
            node = _RootPrefixNode()
            self.children[block_id] = node
        return node


def _estimate_stable_shared_prefix_tokens(
    root_records: list[RequestRecord],
    *,
    block_size: int,
    coverage: float,
) -> float:
    if not root_records:
        return 0.0

    prefix_blocks = 0
    while True:
        position_counts: dict[str, int] = {}
        for record in root_records:
            if len(record.hash_ids) <= prefix_blocks:
                continue
            block_id = record.hash_ids[prefix_blocks]
            position_counts[block_id] = position_counts.get(block_id, 0) + 1

        if not position_counts:
            break
        best_count = max(position_counts.values())
        if best_count / len(root_records) < coverage:
            break
        prefix_blocks += 1

    return float(prefix_blocks * block_size)


def _estimate_pairwise_shared_prefix_tokens(
    root_records: list[RequestRecord],
    *,
    block_size: int,
) -> float:
    if len(root_records) < 2:
        return 0.0

    trie = _RootPrefixNode()
    for record in root_records:
        node = trie
        for block_id in record.hash_ids:
            node = node.child(block_id)
            node.count += 1

    pair_count = len(root_records) * (len(root_records) - 1) / 2.0
    if pair_count <= 0:
        return 0.0
    return float(block_size) * _shared_pair_blocks(trie) / pair_count


def _estimate_new_tokens_per_turn(
    sessions: list[_TraceSession],
    *,
    shared_prefix_tokens: float,
    block_size: int,
) -> list[float]:
    values: list[float] = []
    for session in sessions:
        parent_by_chat_id = {record.chat_id: record for record in session.records}
        for record in session.records:
            parent = parent_by_chat_id.get(record.parent_chat_id or "")
            if parent is None:
                values.append(max(0.0, float(record.input_length) - shared_prefix_tokens))
                continue
            reused_tokens = _shared_tokens_between(parent, record, block_size)
            values.append(max(0.0, float(record.input_length) - reused_tokens))
    return values or [float(block_size)]


def _estimate_reusable_private_tokens(
    sessions: list[_TraceSession],
    *,
    shared_prefix_tokens: float,
    block_size: int,
) -> list[_ReusablePrivateObservation]:
    observations: list[_ReusablePrivateObservation] = []
    for session in sessions:
        parent_by_chat_id = {record.chat_id: record for record in session.records}
        for record in session.records:
            turn_index = max(0, record.turn - 1)
            parent = parent_by_chat_id.get(record.parent_chat_id or "")
            if parent is None:
                observations.append(
                    _ReusablePrivateObservation(
                        turn_index=turn_index,
                        reusable_private_tokens=0.0,
                    )
                )
                continue
            reused_tokens = _shared_tokens_between(parent, record, block_size)
            observations.append(
                _ReusablePrivateObservation(
                    turn_index=turn_index,
                    reusable_private_tokens=max(0.0, reused_tokens - shared_prefix_tokens),
                )
            )
    return observations


def _fit_private_window_tokens(
    observations: list[_ReusablePrivateObservation],
    *,
    avg_new_tokens_per_turn: float,
    block_size: int,
) -> float:
    return _fit_private_window(
        avg_reuse_error=lambda window_tokens: _private_window_error(
            observations,
            window_tokens=window_tokens,
            avg_new_tokens_per_turn=avg_new_tokens_per_turn,
        ),
        avg_new_tokens_per_turn=avg_new_tokens_per_turn,
        block_size=block_size,
        upper_bound_hint=max((item.reusable_private_tokens for item in observations), default=0.0),
        turn_index_upper_bound=max((item.turn_index for item in observations), default=0),
    )


def _fit_private_window_from_average_reuse(
    *,
    average_reusable_private_tokens: float,
    avg_turns_per_session: int,
    avg_new_tokens_per_turn: float,
    block_size: int,
) -> float:
    if avg_turns_per_session <= 0:
        return 0.0
    return _fit_private_window(
        avg_reuse_error=lambda window_tokens: (
            _average_reusable_private_tokens(
                avg_turns_per_session=avg_turns_per_session,
                avg_new_tokens_per_turn=avg_new_tokens_per_turn,
                private_window_tokens=window_tokens,
            )
            - average_reusable_private_tokens
        )
        ** 2,
        avg_new_tokens_per_turn=avg_new_tokens_per_turn,
        block_size=block_size,
        upper_bound_hint=average_reusable_private_tokens,
        turn_index_upper_bound=max(0, avg_turns_per_session - 1),
    )


def _fit_private_window(
    *,
    avg_reuse_error,
    avg_new_tokens_per_turn: float,
    block_size: int,
    upper_bound_hint: float,
    turn_index_upper_bound: int,
) -> float:
    if avg_new_tokens_per_turn <= 0.0:
        return 0.0
    if upper_bound_hint <= 0.0 and turn_index_upper_bound <= 0:
        return 0.0

    max_index_target = turn_index_upper_bound * avg_new_tokens_per_turn
    upper_bound = max(upper_bound_hint, max_index_target)
    upper_bound = max(float(block_size), block_size * math.ceil(upper_bound / block_size))

    best_window = 0.0
    best_error: float | None = None
    current = 0.0
    while current <= upper_bound + 1e-9:
        error = avg_reuse_error(current)
        if best_error is None or error < best_error:
            best_error = error
            best_window = current
        current += block_size
    return best_window


def _derive_new_tokens_from_content_ceiling(
    *,
    shared_prefix_tokens: float,
    average_reusable_private_tokens: float,
    content_hit_rate: float | None,
    fallback_avg_new_tokens: float,
) -> float:
    if content_hit_rate is None or not 0.0 < content_hit_rate < 1.0:
        return fallback_avg_new_tokens
    numerator = shared_prefix_tokens + average_reusable_private_tokens
    if numerator <= 0.0:
        return fallback_avg_new_tokens
    derived = numerator * (1.0 - content_hit_rate) / content_hit_rate
    return max(1.0, derived)


def _average_reusable_private_tokens(
    *,
    avg_turns_per_session: int,
    avg_new_tokens_per_turn: float,
    private_window_tokens: float,
) -> float:
    if avg_turns_per_session <= 0:
        return 0.0
    total = 0.0
    for turn_index in range(avg_turns_per_session):
        total += min(private_window_tokens, turn_index * avg_new_tokens_per_turn)
    return total / avg_turns_per_session


def _minimum_turns_for_reuse(
    *,
    average_reusable_private_tokens: float,
    avg_new_tokens_per_turn: float,
) -> int:
    if avg_new_tokens_per_turn <= 0.0:
        return 1
    if average_reusable_private_tokens <= 0.0:
        return 1
    return max(1, int(math.ceil(1.0 + 2.0 * average_reusable_private_tokens / avg_new_tokens_per_turn)))


def _estimate_concurrency(
    sessions: list[_TraceSession],
    *,
    quantile: float,
) -> tuple[float, float, int]:
    if not sessions:
        return 0.0, 0.0, 0

    timestamps = sorted(
        {
            timestamp
            for session in sessions
            for timestamp in (session.records[0].timestamp_ms, session.records[-1].timestamp_ms)
        }
    )
    if len(timestamps) == 1:
        only_count = len(sessions)
        return float(only_count), float(only_count), only_count

    intervals = [
        (session.records[0].timestamp_ms, session.records[-1].timestamp_ms)
        for session in sessions
    ]
    counts = [
        float(sum(1 for start, end in intervals if start <= timestamp <= end))
        for timestamp in timestamps
    ]
    return _average(counts), _quantile(counts, quantile), int(max(counts))


def _private_window_error(
    observations: list[_ReusablePrivateObservation],
    *,
    window_tokens: float,
    avg_new_tokens_per_turn: float,
) -> float:
    squared_error = 0.0
    for item in observations:
        predicted = min(window_tokens, item.turn_index * avg_new_tokens_per_turn)
        squared_error += (predicted - item.reusable_private_tokens) ** 2
    return squared_error / len(observations)


def _shared_tokens_between(parent: RequestRecord, child: RequestRecord, block_size: int) -> float:
    prefix_blocks = _shared_prefix_blocks(parent.hash_ids, child.hash_ids)
    return float(min(child.input_length, prefix_blocks * block_size))


def _shared_prefix_blocks(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    matched = 0
    for left_block, right_block in zip(left, right):
        if left_block != right_block:
            break
        matched += 1
    return matched


def _shared_pair_blocks(node: _RootPrefixNode) -> float:
    total = 0.0
    stack = list((node.children or {}).values())
    while stack:
        current = stack.pop()
        total += current.count * (current.count - 1) / 2.0
        stack.extend((current.children or {}).values())
    return total


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _quantile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
