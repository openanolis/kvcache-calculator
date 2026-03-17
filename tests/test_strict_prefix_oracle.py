from __future__ import annotations

import unittest

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.core.models import EffectiveRequest, ModelProfile, Scope
from kvcache_upper_bound.oracle import analyze_strict_prefix_capacity_upper_bound


class StrictPrefixOracleTest(unittest.TestCase):
    def test_certificate_path_matches_content_when_replay_reaches_ceiling(self) -> None:
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

        result = analyze_strict_prefix_capacity_upper_bound(
            requests,
            model_profile=model_profile,
            budget_bytes=2 * bytes_per_block,
        )

        self.assertEqual(result.summary.proof_source, "certificate")
        self.assertEqual(result.summary.hit_blocks, 2)
        self.assertEqual(result.request_metrics[1].hit_blocks, 2)

    def test_relaxed_equals_replay_also_certifies_exact_strict_prefix(self) -> None:
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
                effective_hash_ids=("a", "a", "a"),
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
                effective_hash_ids=("a", "a", "a"),
            ),
            EffectiveRequest(
                request_id="r2",
                source_index=2,
                timestamp_ms=3000,
                chat_id="c2",
                scope=Scope.GLOBAL,
                scope_root_id="__global__",
                turn=3,
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
        bytes_per_block = model_profile.kv_bytes_per_block()

        result = analyze_strict_prefix_capacity_upper_bound(
            requests,
            model_profile=model_profile,
            budget_bytes=2 * bytes_per_block,
        )

        self.assertEqual(result.summary.proof_source, "certificate")
        self.assertEqual(result.summary.hit_blocks, 3)
        self.assertEqual(result.request_metrics[0].hit_blocks, 0)
        self.assertEqual(result.request_metrics[1].hit_blocks, 2)
        self.assertEqual(result.request_metrics[2].hit_blocks, 1)


if __name__ == "__main__":
    unittest.main()
