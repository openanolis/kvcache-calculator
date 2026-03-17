from __future__ import annotations

import unittest

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.core.models import RequestRecord, Scope
from kvcache_upper_bound.ingest import (
    build_effective_requests,
    input_length_matches_blocks,
    window_to_block_count,
)


class NormalizerTest(unittest.TestCase):
    def test_window_to_block_count_uses_ceil(self) -> None:
        self.assertEqual(window_to_block_count(0), 0)
        self.assertEqual(window_to_block_count(1), 1)
        self.assertEqual(window_to_block_count(16), 1)
        self.assertEqual(window_to_block_count(17), 2)

    def test_build_effective_requests_resolves_session_root_and_tail_window(self) -> None:
        records = [
            RequestRecord(
                request_id="r0",
                source_index=0,
                timestamp_ms=1000,
                chat_id="root",
                parent_chat_id=None,
                turn=1,
                request_type="text",
                input_length=30,
                output_length=4,
                hash_ids=("a", "b"),
            ),
            RequestRecord(
                request_id="r1",
                source_index=1,
                timestamp_ms=2000,
                chat_id="child",
                parent_chat_id="root",
                turn=2,
                request_type="text",
                input_length=45,
                output_length=5,
                hash_ids=("a", "b", "c"),
            ),
        ]

        result = build_effective_requests(records, window_tokens=32, scope=Scope.SESSION)

        self.assertEqual([request.scope_root_id for request in result.requests], ["root", "root"])
        self.assertEqual(result.requests[0].effective_hash_ids, ("a", "b"))
        self.assertEqual(result.requests[1].effective_hash_ids, ("b", "c"))
        self.assertEqual(result.stats.truncated_requests, 1)
        self.assertEqual(result.stats.effective_total_blocks, 4)
        self.assertEqual(result.stats.effective_total_tokens, 62)

    def test_build_effective_requests_global_scope_uses_single_root(self) -> None:
        records = [
            RequestRecord(
                request_id="r0",
                source_index=0,
                timestamp_ms=1000,
                chat_id="c0",
                parent_chat_id=None,
                turn=1,
                request_type="text",
                input_length=16,
                output_length=1,
                hash_ids=("a",),
            ),
            RequestRecord(
                request_id="r1",
                source_index=1,
                timestamp_ms=2000,
                chat_id="c1",
                parent_chat_id=None,
                turn=1,
                request_type="text",
                input_length=16,
                output_length=1,
                hash_ids=("b",),
            ),
        ]

        result = build_effective_requests(records, window_tokens=16, scope=Scope.GLOBAL)

        self.assertEqual({request.scope_root_id for request in result.requests}, {"__global__"})

    def test_build_effective_requests_counts_missing_parent_links(self) -> None:
        records = [
            RequestRecord(
                request_id="r0",
                source_index=0,
                timestamp_ms=1000,
                chat_id="child",
                parent_chat_id="missing-parent",
                turn=1,
                request_type="text",
                input_length=12,
                output_length=1,
                hash_ids=("a",),
            )
        ]

        result = build_effective_requests(records, window_tokens=16, scope=Scope.SESSION)

        self.assertEqual(result.requests[0].scope_root_id, "child")
        self.assertEqual(result.stats.missing_parent_links, 1)

    def test_input_length_matches_blocks_checks_bounds(self) -> None:
        self.assertTrue(input_length_matches_blocks(0, 0))
        self.assertTrue(input_length_matches_blocks(1, 1))
        self.assertTrue(input_length_matches_blocks(16, 1))
        self.assertTrue(input_length_matches_blocks(17, 2))
        self.assertFalse(input_length_matches_blocks(0, 1))
        self.assertFalse(input_length_matches_blocks(32, 1))


if __name__ == "__main__":
    unittest.main()
