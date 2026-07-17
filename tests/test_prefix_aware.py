from __future__ import annotations

import unittest

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.core.models import EffectiveRequest, ModelProfile, Scope
from kvcache_upper_bound.oracle import analyze_prefix_aware


class PrefixAwareOracleTest(unittest.TestCase):
    def test_prefix_aware_hits_repeated_prefix(self) -> None:
        """Prefix-aware should hit on repeated access when budget is sufficient."""
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

        result = analyze_prefix_aware(
            requests,
            model_profile=model_profile,
            budget_bytes=2 * bytes_per_block,
        )

        self.assertEqual(result.summary.hit_blocks, 2)
        self.assertEqual(result.summary.strict_prefix_hit_blocks, 2)
        self.assertAlmostEqual(result.summary.block_hit_rate, 0.5)
        self.assertEqual([m.hit_blocks for m in result.request_metrics], [0, 2])

    def test_prefix_aware_protects_parent_blocks(self) -> None:
        """Prefix-aware should not evict a parent block when its child is resident.

        Access: [a, b], then [a, c]. With capacity=2:
        After [a,b]: resident={a,b}, a is parent of b.
        Access a -> hit. Access c -> need to evict. a is parent of b (resident child),
        so a is NOT a leaf. b is a leaf (no children). Evict b. Admit c.
        """
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

        result = analyze_prefix_aware(
            requests,
            model_profile=model_profile,
            budget_bytes=2 * bytes_per_block,
        )

        # r1 accesses [a, c]: a should be a hit (protected as parent of b while b is resident,
        # but also hits because it's still resident)
        self.assertEqual(result.request_metrics[1].hit_blocks, 1)  # 'a' hits

    def test_prefix_aware_evicts_leaf_with_lowest_frequency(self) -> None:
        """Among multiple leaf nodes, prefix-aware evicts the one with lowest frequency."""
        # Access: [a, b], [a, c], [b]
        # After [a, b]: resident={a,b}. a parent of b.
        # [a, c]: a hits (freq=2). c needs space. b is leaf (freq=1), a has child b (not leaf).
        # Evict b. resident={a, c}. a is parent of c now.
        # [b]: b needs space. c is leaf (freq=1), a has child c. Evict c. resident={a, b}.
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

        result = analyze_prefix_aware(
            requests,
            model_profile=model_profile,
            budget_bytes=2 * bytes_per_block,
        )

        # r0: a miss, b miss (both admitted)
        # r1: a hit (freq=2), c evicts b (leaf, freq=1) -> c admitted
        # r2: b miss (c evicted as leaf, b admitted)
        self.assertEqual(result.request_metrics[0].hit_blocks, 0)
        self.assertEqual(result.request_metrics[1].hit_blocks, 1)  # a hits
        self.assertEqual(result.request_metrics[2].hit_blocks, 0)  # b was evicted

    def test_prefix_aware_zero_budget(self) -> None:
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

        result = analyze_prefix_aware(
            requests,
            model_profile=model_profile,
            budget_bytes=0,
        )

        self.assertEqual(result.summary.hit_blocks, 0)
        self.assertEqual(result.summary.total_blocks, 1)

    def test_prefix_aware_single_block_repeated(self) -> None:
        """Single block repeated should always hit after first access."""
        requests = [
            EffectiveRequest(
                request_id=f"r{i}",
                source_index=i,
                timestamp_ms=1000 * (i + 1),
                chat_id=f"c{i}",
                scope=Scope.GLOBAL,
                scope_root_id="__global__",
                turn=i + 1,
                request_type="text",
                input_length=16,
                output_length=1,
                total_blocks=1,
                effective_blocks=1,
                effective_tokens=16,
                effective_hash_ids=("a",),
            )
            for i in range(5)
        ]
        model_profile = ModelProfile(
            n_layers=1,
            n_kv_heads=1,
            head_dim=1,
            dtype_bytes=1,
            block_size=16,
        )
        bytes_per_block = model_profile.kv_bytes_per_block()

        result = analyze_prefix_aware(
            requests,
            model_profile=model_profile,
            budget_bytes=bytes_per_block,
        )

        # First access is a miss, remaining 4 are hits
        self.assertEqual(result.summary.hit_blocks, 4)
        self.assertEqual(result.summary.total_blocks, 5)


if __name__ == "__main__":
    unittest.main()
