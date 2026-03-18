from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.cli.main import main
from kvcache_upper_bound.core.models import ModelProfile
from kvcache_upper_bound.heuristic import (
    CurveShapeConfig,
    HeuristicAnalysisConfig,
    HeuristicCapacityTier,
    HeuristicDeploymentConfig,
    MultiAgentHeuristicConfig,
    PolicyEfficiency,
    analyze_multi_agent_heuristic,
)


def _model_profile_for_capacity_tests() -> ModelProfile:
    return ModelProfile(
        n_layers=128,
        n_kv_heads=128,
        head_dim=256,
        dtype_bytes=2,
        block_size=16,
    )


class MultiAgentHeuristicTest(unittest.TestCase):
    def test_average_reusable_private_tokens_matches_append_only_session_average(self) -> None:
        heuristic = MultiAgentHeuristicConfig(
            concurrent_agents=8,
            shared_prefix_tokens=1024,
            avg_new_tokens_per_turn=256,
            avg_turns_per_session=4,
            private_window_tokens=4096,
        )

        self.assertEqual(heuristic.average_reusable_private_tokens_per_agent(), 384.0)

    def test_power_law_fit_derives_beta_from_zipf_s(self) -> None:
        curve = CurveShapeConfig(mode="power_law_fit", zipf_s=1.25)

        self.assertAlmostEqual(curve.resolved_power_law_beta(), 0.2)

    def test_zipf_harmonic_is_monotonic_and_lru_like_stays_below_strict(self) -> None:
        model_profile = _model_profile_for_capacity_tests()
        heuristic = MultiAgentHeuristicConfig(
            concurrent_agents=8,
            shared_prefix_tokens=32,
            avg_new_tokens_per_turn=32,
            avg_turns_per_session=4,
            private_window_tokens=128,
            curve_shape=CurveShapeConfig(
                mode="zipf_harmonic",
                zipf_s=1.3,
                zipf_population_blocks=1024,
            ),
            policy_efficiency=PolicyEfficiency(
                strict_prefix_upper_bound=1.0,
                lru_like=0.6,
            ),
        )
        deployment = HeuristicDeploymentConfig(
            label="toy",
            accelerator_count=1,
            cards_per_machine=1,
            machine_spec="toy",
            total_tps=1.0,
            total_tps_unit="cluster_total",
            baseline_per_card_tps=1.0,
            planning_target_total_tps=2.0,
            hbm_kv_gb_per_card=1.0,
            extra_capacity_tiers=(
                HeuristicCapacityTier(label="HBM+2G", kv_gb_per_machine=2.0),
                HeuristicCapacityTier(label="HBM+4G", kv_gb_per_machine=4.0),
            ),
        )

        result = analyze_multi_agent_heuristic(
            HeuristicAnalysisConfig(
                model_profile=model_profile,
                heuristic=heuristic,
                deployments=(deployment,),
                prefill_savings_alpha=0.8,
            )
        )

        tier_rows = result.tier_rows
        self.assertEqual([row.tier_label for row in tier_rows], ["HBM", "HBM+2G", "HBM+4G"])
        strict_rates = [row.strict_prefix_hit_rate for row in tier_rows]
        lru_rates = [row.lru_like_hit_rate for row in tier_rows]
        self.assertLessEqual(strict_rates[0], strict_rates[1])
        self.assertLessEqual(strict_rates[1], strict_rates[2])
        self.assertLessEqual(lru_rates[0], lru_rates[1])
        self.assertLessEqual(lru_rates[1], lru_rates[2])
        for lru_rate, strict_rate in zip(lru_rates, strict_rates):
            self.assertLessEqual(lru_rate, strict_rate)

        summary = result.scenario_summaries[0]
        self.assertLess(
            summary.strict_prefix_saturation_capacity_tokens,
            summary.lru_like_saturation_capacity_tokens,
        )

    def test_cli_writes_multi_agent_outputs_and_metadata(self) -> None:
        config_payload = {
            "model_profile": {
                "n_layers": 128,
                "n_kv_heads": 128,
                "head_dim": 256,
                "dtype_bytes": 2,
                "block_size": 16,
            },
            "prefill_savings_alpha": 0.8,
            "heuristic_multi_agent": {
                "concurrent_agents": 8,
                "shared_prefix_tokens": 32,
                "avg_new_tokens_per_turn": 32,
                "avg_turns_per_session": 4,
                "private_window_tokens": 128,
                "curve_mode": "zipf_harmonic",
                "zipf_s": 1.3,
                "policy_efficiency": {
                    "strict_prefix_upper_bound": 1.0,
                    "lru_like": 0.6,
                },
            },
            "deployments": [
                {
                    "label": "toy",
                    "accelerator_count": 1,
                    "cards_per_machine": 1,
                    "machine_spec": "toy",
                    "total_tps": 1.0,
                    "total_tps_unit": "cluster_total",
                    "baseline_per_card_tps": 1.0,
                    "planning_target_total_tps": 2.0,
                    "hbm_kv_gb_per_card": 1.0,
                    "extra_capacity_tiers": [
                        {
                            "label": "HBM+2G",
                            "kv_gb_per_machine": 2.0,
                        },
                        {
                            "label": "HBM+4G",
                            "kv_gb_per_machine": 4.0,
                        },
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            output_dir = Path(tmpdir) / "out"
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout), patch.object(
                sys,
                "argv",
                [
                    "kvcache-upper-bound",
                    "estimate-multi-agent",
                    "--config",
                    str(config_path),
                    "--output-dir",
                    str(output_dir),
                ],
            ):
                exit_code = main()

            heuristic_summary_csv = output_dir / "heuristic_summary.csv"
            heuristic_tier_summary_csv = output_dir / "heuristic_tier_summary.csv"
            details_json = output_dir / "details.json"
            metadata_json = output_dir / "metadata.json"

            with heuristic_summary_csv.open("r", encoding="utf-8", newline="") as handle:
                summary_rows = list(csv.DictReader(handle))
            with heuristic_tier_summary_csv.open("r", encoding="utf-8", newline="") as handle:
                tier_rows = list(csv.DictReader(handle))
            details = json.loads(details_json.read_text(encoding="utf-8"))
            metadata = json.loads(metadata_json.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(summary_rows), 1)
        self.assertEqual(len(tier_rows), 3)
        self.assertIn("HBM Strict-Prefix 命中率估计", summary_rows[0])
        self.assertIn("HBM LRU-like 命中率估计", summary_rows[0])
        self.assertIn("Strict-Prefix 命中率估计", tier_rows[0])
        self.assertIn("LRU-like 命中率估计", tier_rows[0])
        self.assertEqual(metadata["mode"], "multi_agent_heuristic")
        self.assertEqual(metadata["normalized_heuristic_inputs"][0]["machine_count"], 1)
        self.assertIn("heuristic_multi_agent", details)
        self.assertIn("scenario_summaries", details)
        self.assertIn("toy", details["scenarios"])
        self.assertIn('"mode": "multi_agent_heuristic"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
