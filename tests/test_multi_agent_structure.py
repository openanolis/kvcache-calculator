from __future__ import annotations

import unittest

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.core.models import ModelProfile, RequestRecord
from kvcache_upper_bound.heuristic import (
    CurveShapeConfig,
    HeuristicAnalysisConfig,
    HeuristicDeploymentConfig,
    MultiAgentHeuristicConfig,
    PolicyEfficiency,
    build_trace_structure_recommendation,
    estimate_multi_agent_structure_from_trace,
)


def _model_profile() -> ModelProfile:
    return ModelProfile(
        n_layers=128,
        n_kv_heads=128,
        head_dim=256,
        dtype_bytes=2,
        block_size=16,
    )


def _synthetic_records() -> list[RequestRecord]:
    return [
        RequestRecord(
            request_id="a0",
            source_index=0,
            timestamp_ms=1,
            chat_id="a0",
            parent_chat_id=None,
            turn=1,
            request_type="text",
            input_length=48,
            output_length=1,
            hash_ids=("s0", "s1", "a1"),
        ),
        RequestRecord(
            request_id="a1",
            source_index=1,
            timestamp_ms=2,
            chat_id="a1",
            parent_chat_id="a0",
            turn=2,
            request_type="text",
            input_length=64,
            output_length=1,
            hash_ids=("s0", "s1", "a1", "a2"),
        ),
        RequestRecord(
            request_id="b0",
            source_index=2,
            timestamp_ms=2,
            chat_id="b0",
            parent_chat_id=None,
            turn=1,
            request_type="text",
            input_length=48,
            output_length=1,
            hash_ids=("s0", "s1", "b1"),
        ),
        RequestRecord(
            request_id="a2",
            source_index=3,
            timestamp_ms=3,
            chat_id="a2",
            parent_chat_id="a1",
            turn=3,
            request_type="text",
            input_length=80,
            output_length=1,
            hash_ids=("s0", "s1", "a1", "a2", "a3"),
        ),
        RequestRecord(
            request_id="b1",
            source_index=4,
            timestamp_ms=3,
            chat_id="b1",
            parent_chat_id="b0",
            turn=2,
            request_type="text",
            input_length=64,
            output_length=1,
            hash_ids=("s0", "s1", "b1", "b2"),
        ),
        RequestRecord(
            request_id="b2",
            source_index=5,
            timestamp_ms=4,
            chat_id="b2",
            parent_chat_id="b1",
            turn=3,
            request_type="text",
            input_length=80,
            output_length=1,
            hash_ids=("s0", "s1", "b1", "b2", "b3"),
        ),
    ]


class MultiAgentStructureTest(unittest.TestCase):
    def test_structure_hints_recover_append_only_shape(self) -> None:
        hints = estimate_multi_agent_structure_from_trace(_synthetic_records(), block_size=16)

        self.assertEqual(hints.request_count, 6)
        self.assertEqual(hints.session_count, 2)
        self.assertEqual(hints.root_request_count, 2)
        self.assertAlmostEqual(hints.recommended_shared_prefix_tokens, 32.0)
        self.assertAlmostEqual(hints.recommended_avg_new_tokens_per_turn, 16.0)
        self.assertEqual(hints.recommended_avg_turns_per_session, 3)
        self.assertAlmostEqual(hints.observed_average_reusable_private_tokens, 16.0)
        self.assertAlmostEqual(hints.recommended_private_window_tokens, 32.0)
        self.assertEqual(hints.recommended_concurrent_agents, 2)
        self.assertEqual(hints.recommended_zipf_population_blocks, 4)

    def test_structure_recommendation_updates_heuristic_template(self) -> None:
        base_config = HeuristicAnalysisConfig(
            model_profile=_model_profile(),
            heuristic=MultiAgentHeuristicConfig(
                concurrent_agents=8,
                shared_prefix_tokens=128,
                avg_new_tokens_per_turn=64,
                avg_turns_per_session=6,
                private_window_tokens=256,
                curve_shape=CurveShapeConfig(
                    mode="zipf_harmonic",
                    zipf_s=1.3,
                    zipf_population_blocks=4096,
                ),
                policy_efficiency=PolicyEfficiency(
                    strict_prefix_upper_bound=1.0,
                    lru_like=0.6,
                ),
            ),
            deployments=(
                HeuristicDeploymentConfig(
                    label="toy",
                    accelerator_count=1,
                    cards_per_machine=1,
                    machine_spec="toy",
                    total_tps=1.0,
                    total_tps_unit="cluster_total",
                    baseline_per_card_tps=1.0,
                    planning_target_total_tps=2.0,
                    hbm_kv_gb_per_card=1.0,
                ),
            ),
            prefill_savings_alpha=0.8,
        )

        recommendation = build_trace_structure_recommendation(
            base_config,
            records=_synthetic_records(),
            block_size=16,
        )

        heuristic = recommendation.recommended_config.heuristic
        self.assertEqual(heuristic.concurrent_agents, 2)
        self.assertAlmostEqual(heuristic.shared_prefix_tokens, 32.0)
        self.assertAlmostEqual(heuristic.avg_new_tokens_per_turn, 16.0)
        self.assertEqual(heuristic.avg_turns_per_session, 3)
        self.assertAlmostEqual(heuristic.private_window_tokens, 32.0)
        self.assertEqual(heuristic.curve_shape.zipf_population_blocks, 4)
        self.assertEqual(len(recommendation.recommended_analysis.scenario_summaries), 1)

    def test_structure_recommendation_can_align_content_ceiling(self) -> None:
        base_config = HeuristicAnalysisConfig(
            model_profile=_model_profile(),
            heuristic=MultiAgentHeuristicConfig(
                concurrent_agents=8,
                shared_prefix_tokens=128,
                avg_new_tokens_per_turn=64,
                avg_turns_per_session=2,
                private_window_tokens=64,
                curve_shape=CurveShapeConfig(
                    mode="zipf_harmonic",
                    zipf_s=1.3,
                    zipf_population_blocks=1024,
                ),
                policy_efficiency=PolicyEfficiency(
                    strict_prefix_upper_bound=1.0,
                    lru_like=0.6,
                ),
            ),
            deployments=(
                HeuristicDeploymentConfig(
                    label="toy",
                    accelerator_count=1,
                    cards_per_machine=1,
                    machine_spec="toy",
                    total_tps=1.0,
                    total_tps_unit="cluster_total",
                    baseline_per_card_tps=1.0,
                    planning_target_total_tps=2.0,
                    hbm_kv_gb_per_card=1.0,
                ),
            ),
            prefill_savings_alpha=0.8,
        )

        recommendation = build_trace_structure_recommendation(
            base_config,
            records=_synthetic_records(),
            block_size=16,
            observed_content_hit_rate=0.75,
        )

        summary = recommendation.recommended_analysis.scenario_summaries[0]
        self.assertAlmostEqual(summary.content_hit_rate, 0.75)


if __name__ == "__main__":
    unittest.main()
