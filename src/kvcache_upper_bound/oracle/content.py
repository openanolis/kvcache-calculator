from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from kvcache_upper_bound.core.models import EffectiveRequest, ModelProfile
from kvcache_upper_bound.oracle.prefix_trie import PrefixTrie


@dataclass(frozen=True)
class ContentRequestMetric:
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
    total_kv_bytes: int | None
    hit_kv_bytes: int | None
    miss_kv_bytes: int | None


@dataclass(frozen=True)
class ContentSummary:
    total_requests: int
    total_blocks: int
    hit_blocks: int
    miss_blocks: int
    block_hit_rate: float
    total_tokens: int
    hit_tokens_est: int
    miss_tokens_est: int
    token_hit_rate_est: float
    total_kv_bytes: int | None
    hit_kv_bytes: int | None
    miss_kv_bytes: int | None
    kv_byte_hit_rate: float | None


@dataclass(frozen=True)
class ContentAnalysisResult:
    request_metrics: list[ContentRequestMetric]
    summary: ContentSummary


def analyze_content_upper_bound(
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
    tries_by_scope: dict[str, PrefixTrie] = {}
    request_metrics: list[ContentRequestMetric] = []

    total_blocks = 0
    hit_blocks = 0
    total_tokens = 0
    hit_tokens_est = 0

    kv_bytes_per_block = model_profile.kv_bytes_per_block() if model_profile else None
    total_kv_bytes = 0 if kv_bytes_per_block is not None else None
    hit_kv_bytes = 0 if kv_bytes_per_block is not None else None

    for request in ordered_requests:
        trie = tries_by_scope.setdefault(request.scope_root_id, PrefixTrie())
        matched_blocks = trie.match_and_insert(request.effective_hash_ids)
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

    summary = ContentSummary(
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
    )
    return ContentAnalysisResult(request_metrics=request_metrics, summary=summary)


def _estimate_hit_tokens(
    effective_blocks: int,
    effective_tokens: int,
    hit_blocks: int,
    block_size: int,
) -> int:
    if hit_blocks <= 0 or effective_blocks <= 0 or effective_tokens <= 0:
        return 0
    if hit_blocks >= effective_blocks:
        return effective_tokens
    return hit_blocks * block_size


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
