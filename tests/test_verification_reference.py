from __future__ import annotations

import unittest

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.core.models import EffectiveRequest, Scope
from kvcache_upper_bound.oracle import analyze_content_upper_bound
from kvcache_upper_bound.verification import (
    analyze_content_upper_bound_naive,
    find_smallest_strict_prefix_gap_counterexample,
    verify_exhaustive_small_cases,
)


class VerificationReferenceTest(unittest.TestCase):
    def test_naive_content_matches_fast_content(self) -> None:
        requests = [
            EffectiveRequest(
                request_id="r0",
                source_index=0,
                timestamp_ms=1000,
                chat_id="c0",
                scope=Scope.GLOBAL,
                scope_root_id="__global__",
                turn=1,
                request_type="text",
                input_length=48,
                output_length=1,
                total_blocks=3,
                effective_blocks=3,
                effective_tokens=48,
                effective_hash_ids=("a", "b", "c"),
            ),
            EffectiveRequest(
                request_id="r1",
                source_index=1,
                timestamp_ms=2000,
                chat_id="c1",
                scope=Scope.GLOBAL,
                scope_root_id="__global__",
                turn=2,
                request_type="text",
                input_length=48,
                output_length=1,
                total_blocks=3,
                effective_blocks=3,
                effective_tokens=48,
                effective_hash_ids=("a", "b", "d"),
            ),
        ]

        fast = analyze_content_upper_bound(requests)
        slow = analyze_content_upper_bound_naive(requests)

        self.assertEqual(fast.summary.hit_blocks, slow.summary.hit_blocks)
        self.assertEqual(
            [metric.hit_blocks for metric in fast.request_metrics],
            [metric.hit_blocks for metric in slow.request_metrics],
        )

    def test_exhaustive_small_cases_returns_positive_counts(self) -> None:
        summary = verify_exhaustive_small_cases(
            max_requests=2,
            max_blocks_per_request=2,
            alphabet=("a", "b"),
        )

        self.assertGreater(summary.content_case_count, 0)
        self.assertGreater(summary.relaxed_capacity_case_count, 0)

    def test_find_smallest_strict_prefix_gap_counterexample(self) -> None:
        counterexample = find_smallest_strict_prefix_gap_counterexample()

        self.assertGreater(
            counterexample.relaxed_capacity_hit_blocks,
            counterexample.strict_prefix_hit_blocks,
        )


if __name__ == "__main__":
    unittest.main()
