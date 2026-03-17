from __future__ import annotations

import unittest

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.core.models import EffectiveRequest, ModelProfile, Scope
from kvcache_upper_bound.oracle import analyze_content_upper_bound


class ContentOracleTest(unittest.TestCase):
    def test_repeated_prefix_hits_on_second_request(self) -> None:
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
                turn=1,
                request_type="text",
                input_length=32,
                output_length=1,
                total_blocks=2,
                effective_blocks=2,
                effective_tokens=32,
                effective_hash_ids=("a", "b"),
            ),
        ]

        result = analyze_content_upper_bound(requests)

        self.assertEqual(result.request_metrics[0].hit_blocks, 0)
        self.assertEqual(result.request_metrics[1].hit_blocks, 2)
        self.assertEqual(result.summary.hit_blocks, 2)
        self.assertAlmostEqual(result.summary.block_hit_rate, 0.5)

    def test_same_block_under_different_prefix_is_not_a_hit(self) -> None:
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
                effective_hash_ids=("x", "y"),
            ),
            EffectiveRequest(
                request_id="r1",
                source_index=1,
                timestamp_ms=2000,
                chat_id="c1",
                scope=Scope.GLOBAL,
                scope_root_id="__global__",
                turn=1,
                request_type="text",
                input_length=32,
                output_length=1,
                total_blocks=2,
                effective_blocks=2,
                effective_tokens=32,
                effective_hash_ids=("z", "y"),
            ),
        ]

        result = analyze_content_upper_bound(requests)

        self.assertEqual(result.request_metrics[1].hit_blocks, 0)
        self.assertEqual(result.summary.hit_blocks, 0)

    def test_session_scope_blocks_cross_session_reuse(self) -> None:
        requests = [
            EffectiveRequest(
                request_id="r0",
                source_index=0,
                timestamp_ms=1000,
                chat_id="s1-r0",
                scope=Scope.SESSION,
                scope_root_id="session-1",
                turn=1,
                request_type="text",
                input_length=16,
                output_length=1,
                total_blocks=1,
                effective_blocks=1,
                effective_tokens=16,
                effective_hash_ids=("a",),
            ),
            EffectiveRequest(
                request_id="r1",
                source_index=1,
                timestamp_ms=2000,
                chat_id="s2-r0",
                scope=Scope.SESSION,
                scope_root_id="session-2",
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

        result = analyze_content_upper_bound(requests)

        self.assertEqual(result.summary.hit_blocks, 0)
        self.assertEqual(result.request_metrics[1].hit_blocks, 0)

    def test_model_profile_enables_kv_byte_metrics(self) -> None:
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
                input_length=24,
                output_length=1,
                total_blocks=2,
                effective_blocks=2,
                effective_tokens=24,
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
                input_length=24,
                output_length=1,
                total_blocks=2,
                effective_blocks=2,
                effective_tokens=24,
                effective_hash_ids=("a", "b"),
            ),
        ]
        model_profile = ModelProfile(
            n_layers=2,
            n_kv_heads=4,
            head_dim=8,
            dtype_bytes=2,
            block_size=16,
        )

        result = analyze_content_upper_bound(requests, model_profile=model_profile)

        bytes_per_block = model_profile.kv_bytes_per_block()
        self.assertEqual(result.summary.total_kv_bytes, 4 * bytes_per_block)
        self.assertEqual(result.summary.hit_kv_bytes, 2 * bytes_per_block)
        self.assertAlmostEqual(result.summary.kv_byte_hit_rate or 0.0, 0.5)

    def test_hybrid_model_profile_uses_kv_cache_layer_count(self) -> None:
        model_profile = ModelProfile(
            n_layers=64,
            kv_cache_layer_count=16,
            n_kv_heads=4,
            head_dim=256,
            dtype_bytes=2,
            tp_size=8,
            block_size=16,
        )

        self.assertEqual(model_profile.kv_bytes_per_token(), 65536)
        self.assertEqual(model_profile.kv_bytes_per_token_per_rank(), 8192)


if __name__ == "__main__":
    unittest.main()
