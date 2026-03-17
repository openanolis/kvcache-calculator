"""Reference implementations and audit helpers."""

from .audit import BucketAuditReport, BucketAuditRow, build_bucket_audit_report, write_bucket_audit_outputs
from .reference import (
    ExhaustiveVerificationSummary,
    StrictPrefixCounterexample,
    StrictPrefixReplayGapCounterexample,
    analyze_content_upper_bound_naive,
    find_smallest_strict_prefix_gap_counterexample,
    find_smallest_strict_prefix_replay_gap_counterexample,
    verify_exhaustive_small_cases,
)

__all__ = [
    "BucketAuditReport",
    "BucketAuditRow",
    "ExhaustiveVerificationSummary",
    "StrictPrefixCounterexample",
    "StrictPrefixReplayGapCounterexample",
    "analyze_content_upper_bound_naive",
    "build_bucket_audit_report",
    "find_smallest_strict_prefix_gap_counterexample",
    "find_smallest_strict_prefix_replay_gap_counterexample",
    "verify_exhaustive_small_cases",
    "write_bucket_audit_outputs",
]
