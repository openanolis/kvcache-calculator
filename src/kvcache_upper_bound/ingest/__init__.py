"""Trace loading and normalization helpers."""

from .normalizer import (
    NormalizationResult,
    NormalizationStats,
    SessionRootResolution,
    build_effective_requests,
    input_length_matches_blocks,
    resolve_session_roots,
    window_to_block_count,
)
from .trace_loader import TraceLoadResult, TraceLoadStats, load_request_records

__all__ = [
    "NormalizationResult",
    "NormalizationStats",
    "SessionRootResolution",
    "TraceLoadResult",
    "TraceLoadStats",
    "build_effective_requests",
    "input_length_matches_blocks",
    "load_request_records",
    "resolve_session_roots",
    "window_to_block_count",
]
