from __future__ import annotations

import unittest

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.core.models import EffectiveRequest, ModelProfile, Scope
from kvcache_upper_bound.oracle import analyze_lfu_baseline


class LFUOracleTest(unittest.TestCase):
    def test_lfu_hits_repeated_prefix_when_budget_is_sufficient(self) -> None:
        """LFU should hit on second access when budget holds all blocks."""
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
                input_length=32,
                output_length=1,
                total_blocks=2,
                effective_blocks=2,
                effective_tokens=32,
                effective_hash_ids=("a", "b"),
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
                input_length=32,
                output_length=1,
                total_blocks=2,
                effective_blocks=2,
                effective_tokens=32,
                effective_hash_ids=("a", "b"),
            ),
        ]
        model_profile = ModelProfile(
            n_layers=1,
            n_kv_heads=1,
            head_dim=1,
            dtype_bytes=1,
            block_size=16,
        )
        bytes_per_block = model_profile.kv_bytes_per_block()

        result = analyze_lfu_baseline(
            requests,
            model_profile=model_profile,
            budget_bytes=2 * bytes_per_block,
        )

        self.assertEqual(result.summary.hit_blocks, 2)
        self.assertEqual(result.summary.strict_prefix_hit_blocks, 2)
        self.assertAlmostEqual(result.summary.block_hit_rate, 0.5)
        self.assertEqual([m.hit_blocks for m in result.request_metrics], [0, 2])

    def test_lfu_evicts_least_frequent_block(self) -> None:
        """With capacity=1, LFU should evict the block accessed less often."""
        # Access pattern: a, b, a, c
        # After 'a' (freq=1), then 'b' evicts 'a' (cap=1), then 'a' evicts 'b',
        # then 'c' evicts 'a'. With cap=1, no reuse for single-access blocks.
        # But with cap=2: a(freq=1), b(freq=1), a(hit, freq=2), c evicts b(freq=1)
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
                input_length=32,
                output_length=1,
                total_blocks=2,
                effective_blocks=2,
                effective_tokens=32,
                effective_hash_ids=("a", "b"),
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
                input_length=32,
                output_length=1,
                total_blocks=2,
                effective_blocks=2,
                effective_tokens=32,
                effective_hash_ids=("a", "c"),
            ),
        ]
        model_profile = ModelProfile(
            n_layers=1,
            n_kv_heads=1,
            head_dim=1,
            dtype_bytes=1,
            block_size=16,
        )
        bytes_per_block = model_profile.kv_bytes_per_block()

        result = analyze_lfu_baseline(
            requests,
            model_profile=model_profile,
            budget_bytes=2 * bytes_per_block,
        )

        # r0 accesses a,b (both miss, freq a=1, b=1)
        # r1 accesses a (hit, freq a=2), c (evicts b which has freq=1, c admitted)
        self.assertEqual(result.request_metrics[0].hit_blocks, 0)
        self.assertEqual(result.request_metrics[1].hit_blocks, 1)
        self.assertEqual(result.summary.hit_blocks, 1)

    def test_lfu_tie_breaking_by_insertion_order(self) -> None:
        """When frequencies are tied, LFU evicts the block inserted earliest."""
        # Access: a, b, c (cap=2). After a,b are resident (freq=1 each).
        # c arrives: must evict one. Both a,b have freq=1. 'a' inserted first -> evict a.
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
                input_length=16,
                output_length=1,
                total_blocks=1,
                effective_blocks=1,
                effective_tokens=16,
                effective_hash_ids=("b",),
            ),
        ]
        model_profile = ModelProfile(
            n_layers=1,
            n_kv_heads=1,
            head_dim=1,
            dtype_bytes=1,
            block_size=16,
        )
        bytes_per_block = model_profile.kv_bytes_per_block()

        result = analyze_lfu_baseline(
            requests,
            model_profile=model_profile,
            budget_bytes=2 * bytes_per_block,
        )

        # After r0: a inserted (freq=1), b inserted (freq=1), then c needs space.
        # Evict a (earliest insertion among ties), so resident = {b, c}
        # r1 accesses b -> hit!
        self.assertEqual(result.request_metrics[1].hit_blocks, 1)

    def test_lfu_zero_budget(self) -> None:
        """Zero budget should produce zero hits."""
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
                input_length=16,
                output_length=1,
                total_blocks=1,
                effective_blocks=1,
                effective_tokens=16,
                effective_hash_ids=("a",),
            ),
        ]
        model_profile = ModelProfile(
            n_layers=1,
            n_kv_heads=1,
            head_dim=1,
            dtype_bytes=1,
            block_size=16,
        )

        result = analyze_lfu_baseline(
            requests,
            model_profile=model_profile,
            budget_bytes=0,
        )

        self.assertEqual(result.summary.hit_blocks, 0)
        self.assertEqual(result.summary.total_blocks, 1)


if __name__ == "__main__":
    unittest.main()
