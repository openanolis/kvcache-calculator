from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from kvcache_upper_bound.core.models import (
    GLOBAL_SCOPE_ROOT,
    EffectiveRequest,
    RequestRecord,
    Scope,
)


@dataclass(frozen=True)
class NormalizationStats:
    total_requests: int
    truncated_requests: int
    inconsistent_length_requests: int
    missing_parent_links: int
    effective_total_blocks: int
    effective_total_tokens: int


@dataclass(frozen=True)
class NormalizationResult:
    requests: list[EffectiveRequest]
    stats: NormalizationStats


@dataclass(frozen=True)
class SessionRootResolution:
    root_by_chat_id: dict[str, str]
    missing_parent_links: int


def build_effective_requests(
    records: Iterable[RequestRecord],
    window_tokens: int,
    scope: Scope,
    block_size: int = 16,
) -> NormalizationResult:
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if window_tokens < 0:
        raise ValueError("window_tokens must be non-negative")

    ordered_records = sorted(records, key=lambda record: (record.timestamp_ms, record.source_index))
    session_root_resolution = resolve_session_roots(ordered_records)
    session_roots = session_root_resolution.root_by_chat_id
    missing_parent_links = session_root_resolution.missing_parent_links
    window_blocks = window_to_block_count(window_tokens, block_size)

    effective_requests: list[EffectiveRequest] = []
    truncated_requests = 0
    inconsistent_length_requests = 0
    effective_total_blocks = 0
    effective_total_tokens = 0

    for record in ordered_records:
        if not input_length_matches_blocks(record.input_length, record.block_count, block_size):
            inconsistent_length_requests += 1

        effective_hash_ids = record.hash_ids[-window_blocks:] if window_blocks else ()
        effective_blocks = len(effective_hash_ids)
        effective_tokens = min(record.input_length, window_tokens)
        if effective_blocks < record.block_count or effective_tokens < record.input_length:
            truncated_requests += 1

        scope_root_id = (
            GLOBAL_SCOPE_ROOT if scope is Scope.GLOBAL else session_roots.get(record.chat_id, record.chat_id)
        )

        effective_requests.append(
            EffectiveRequest(
                request_id=record.request_id,
                source_index=record.source_index,
                timestamp_ms=record.timestamp_ms,
                chat_id=record.chat_id,
                scope=scope,
                scope_root_id=scope_root_id,
                turn=record.turn,
                request_type=record.request_type,
                input_length=record.input_length,
                output_length=record.output_length,
                total_blocks=record.block_count,
                effective_blocks=effective_blocks,
                effective_tokens=effective_tokens,
                effective_hash_ids=effective_hash_ids,
            )
        )
        effective_total_blocks += effective_blocks
        effective_total_tokens += effective_tokens

    return NormalizationResult(
        requests=effective_requests,
        stats=NormalizationStats(
            total_requests=len(ordered_records),
            truncated_requests=truncated_requests,
            inconsistent_length_requests=inconsistent_length_requests,
            missing_parent_links=missing_parent_links,
            effective_total_blocks=effective_total_blocks,
            effective_total_tokens=effective_total_tokens,
        ),
    )


def window_to_block_count(window_tokens: int, block_size: int = 16) -> int:
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    if window_tokens < 0:
        raise ValueError("window_tokens must be non-negative")
    return (window_tokens + block_size - 1) // block_size


def input_length_matches_blocks(input_length: int, block_count: int, block_size: int = 16) -> bool:
    if input_length < 0 or block_count < 0:
        return False
    if input_length == 0 or block_count == 0:
        return input_length == 0 and block_count == 0
    lower_bound = (block_count - 1) * block_size + 1
    upper_bound = block_count * block_size
    return lower_bound <= input_length <= upper_bound


def resolve_session_roots(records: Iterable[RequestRecord]) -> SessionRootResolution:
    ordered_records = list(records)
    root_by_chat_id, missing_parent_links = _resolve_session_roots(ordered_records)
    return SessionRootResolution(
        root_by_chat_id=root_by_chat_id,
        missing_parent_links=missing_parent_links,
    )


def _resolve_session_roots(records: list[RequestRecord]) -> tuple[dict[str, str], int]:
    by_chat_id = {record.chat_id: record for record in records}
    cache: dict[str, str] = {}
    missing_parent_links = 0

    for record in records:
        current_id = record.chat_id
        path: list[str] = []
        seen: set[str] = set()

        while True:
            if current_id in cache:
                root_id = cache[current_id]
                break
            if current_id in seen:
                raise ValueError(f"cycle detected in chat tree at {current_id}")
            seen.add(current_id)

            current_record = by_chat_id.get(current_id)
            if current_record is None:
                missing_parent_links += 1
                root_id = path[-1]
                break

            path.append(current_id)
            parent_id = current_record.parent_chat_id
            if parent_id is None:
                root_id = current_id
                break
            current_id = parent_id

        for chat_id in path:
            cache[chat_id] = root_id

    return cache, missing_parent_links
