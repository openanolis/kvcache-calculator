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
    CalibrationTierTarget,
    CalibrationTraceTarget,
    CurveShapeConfig,
    HeuristicAnalysisConfig,
    HeuristicCapacityTier,
    HeuristicDeploymentConfig,
    MultiAgentHeuristicConfig,
    PolicyEfficiency,
    analyze_multi_agent_heuristic,
    build_calibration_grid_from_ranges,
    calibrate_multi_agent_parameters,
)


def _model_profile() -> ModelProfile:
    return ModelProfile(
        n_layers=128,
        n_kv_heads=128,
        head_dim=256,
        dtype_bytes=2,
        block_size=16,
    )


class MultiAgentCalibrationTest(unittest.TestCase):
    def test_calibration_recovers_known_zipf_s_and_lru_like_from_synthetic_target(self) -> None:
        model_profile = _model_profile()
        true_config = HeuristicAnalysisConfig(
            model_profile=model_profile,
            heuristic=MultiAgentHeuristicConfig(
                concurrent_agents=8,
                shared_prefix_tokens=32,
                avg_new_tokens_per_turn=32,
                avg_turns_per_session=4,
                private_window_tokens=128,
                curve_shape=CurveShapeConfig(
                    mode="zipf_harmonic",
                    zipf_s=1.35,
                    zipf_population_blocks=1024,
                ),
                policy_efficiency=PolicyEfficiency(
                    strict_prefix_upper_bound=1.0,
                    lru_like=0.58,
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
                    extra_capacity_tiers=(
                        HeuristicCapacityTier(label="HBM+2G", kv_gb_per_machine=2.0),
                        HeuristicCapacityTier(label="HBM+4G", kv_gb_per_machine=4.0),
                    ),
                ),
            ),
            prefill_savings_alpha=0.8,
        )
        true_result = analyze_multi_agent_heuristic(true_config)
        summary = true_result.scenario_summaries[0]
        target = CalibrationTraceTarget(
            bucket_count=1,
            bucket_labels=("all",),
            machine_count=summary.machine_count,
            card_count=summary.card_count,
            cards_per_machine=summary.cards_per_machine,
            machine_spec=summary.machine_spec,
            total_tps=summary.total_tps,
            total_tps_input_unit=summary.total_tps_input_unit,
            planning_target_total_tps=summary.planning_target_total_tps,
            baseline_per_card_tps=summary.baseline_per_card_tps,
            hbm_kv_gb_per_card=summary.hbm_kv_gb_per_card,
            content_hit_rate=summary.content_hit_rate,
            tiers=tuple(
                CalibrationTierTarget(
                    tier_label=row.tier_label,
                    total_kv_gb=row.total_kv_gb,
                    strict_prefix_hit_rate=row.strict_prefix_hit_rate,
                    lru_like_hit_rate=row.lru_like_hit_rate,
                )
                for row in true_result.tier_rows
            ),
        )

        wrong_guess = HeuristicAnalysisConfig(
            model_profile=model_profile,
            heuristic=MultiAgentHeuristicConfig(
                concurrent_agents=8,
                shared_prefix_tokens=32,
                avg_new_tokens_per_turn=32,
                avg_turns_per_session=4,
                private_window_tokens=128,
                curve_shape=CurveShapeConfig(
                    mode="zipf_harmonic",
                    zipf_s=1.10,
                    zipf_population_blocks=1024,
                ),
                policy_efficiency=PolicyEfficiency(
                    strict_prefix_upper_bound=1.0,
                    lru_like=0.72,
                ),
            ),
            deployments=true_config.deployments,
            prefill_savings_alpha=0.8,
        )
        grid = build_calibration_grid_from_ranges(
            curve_mode="zipf_harmonic",
            zipf_s_min=1.20,
            zipf_s_max=1.40,
            zipf_s_step=0.05,
            lru_like_min=0.50,
            lru_like_max=0.60,
            lru_like_step=0.02,
        )

        calibrated = calibrate_multi_agent_parameters(
            base_config=wrong_guess,
            target=target,
            grid=grid,
        )

        self.assertAlmostEqual(calibrated.best_trial.zipf_s, 1.35)
        self.assertAlmostEqual(calibrated.best_trial.lru_like, 0.58)
        self.assertAlmostEqual(calibrated.best_trial.rmse_total, 0.0)

    def test_cli_calibrate_multi_agent_writes_outputs(self) -> None:
        trace_lines = [
            {
                "chat_id": "c0",
                "parent_chat_id": -1,
                "turn": 1,
                "type": "text",
                "timestamp": 1,
                "input_length": 32,
                "output_length": 1,
                "hash_ids": ["a", "b"],
            },
            {
                "chat_id": "c1",
                "parent_chat_id": -1,
                "turn": 1,
                "type": "text",
                "timestamp": 2,
                "input_length": 32,
                "output_length": 1,
                "hash_ids": ["a", "b"],
            },
            {
                "chat_id": "c2",
                "parent_chat_id": -1,
                "turn": 1,
                "type": "text",
                "timestamp": 3,
                "input_length": 48,
                "output_length": 1,
                "hash_ids": ["a", "b", "c"],
            },
        ]
        bucket_config = {
            "model_profile": {
                "n_layers": 1,
                "n_kv_heads": 1,
                "head_dim": 1,
                "dtype_bytes": 1,
                "block_size": 16,
            },
            "scope": "global",
            "block_size": 16,
            "bucket_deployments": [
                {
                    "label": "all",
                    "lower_tokens": 0,
                    "upper_tokens": None,
                    "accelerator_count": 1,
                    "cards_per_machine": 1,
                    "machine_spec": "toy",
                    "hbm_kv_gb_per_card": 1.0,
                    "extra_capacity_tiers": [
                        {
                            "label": "HBM+2G",
                            "kv_gb_per_machine": 2.0,
                        }
                    ],
                }
            ],
        }
        heuristic_config = {
            "model_profile": {
                "n_layers": 128,
                "n_kv_heads": 128,
                "head_dim": 256,
                "dtype_bytes": 2,
                "block_size": 16,
            },
            "prefill_savings_alpha": 0.8,
            "heuristic_multi_agent": {
                "concurrent_agents": 4,
                "shared_prefix_tokens": 16,
                "avg_new_tokens_per_turn": 16,
                "avg_turns_per_session": 4,
                "private_window_tokens": 64,
                "curve_mode": "zipf_harmonic",
                "zipf_s": 1.2,
                "policy_efficiency": {
                    "strict_prefix_upper_bound": 1.0,
                    "lru_like": 0.5,
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
                        }
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            trace_path = Path(tmpdir) / "trace.jsonl"
            bucket_config_path = Path(tmpdir) / "bucket.json"
            heuristic_config_path = Path(tmpdir) / "heuristic.json"
            output_dir = Path(tmpdir) / "out"
            trace_path.write_text(
                "\n".join(json.dumps(line, ensure_ascii=False) for line in trace_lines),
                encoding="utf-8",
            )
            bucket_config_path.write_text(json.dumps(bucket_config), encoding="utf-8")
            heuristic_config_path.write_text(json.dumps(heuristic_config), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout), patch.object(
                sys,
                "argv",
                [
                    "kvcache-upper-bound",
                    "calibrate-multi-agent",
                    "--trace",
                    str(trace_path),
                    "--bucket-config",
                    str(bucket_config_path),
                    "--heuristic-config",
                    str(heuristic_config_path),
                    "--output-dir",
                    str(output_dir),
                    "--zipf-s-min",
                    "1.1",
                    "--zipf-s-max",
                    "1.2",
                    "--zipf-s-step",
                    "0.1",
                    "--lru-like-min",
                    "0.5",
                    "--lru-like-max",
                    "0.6",
                    "--lru-like-step",
                    "0.1",
                ],
            ):
                exit_code = main()

            metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
            calibration = json.loads((output_dir / "calibration.json").read_text(encoding="utf-8"))
            report_zh = (output_dir / "heuristic_report.zh.md").read_text(encoding="utf-8")
            report_en = (output_dir / "heuristic_report.en.md").read_text(encoding="utf-8")
            recommended_config = json.loads(
                (output_dir / "recommended_heuristic_config.json").read_text(encoding="utf-8")
            )
            with (output_dir / "calibration_trials.csv").open(
                "r",
                encoding="utf-8",
                newline="",
            ) as handle:
                trials = list(csv.DictReader(handle))

        self.assertEqual(exit_code, 0)
        self.assertEqual(metadata["mode"], "multi_agent_calibration")
        self.assertIn("best_trial", metadata)
        self.assertIn("structure_recommendation", metadata)
        self.assertIn("best_trial", calibration)
        self.assertIn("structure_recommendation", calibration)
        self.assertGreaterEqual(len(trials), 2)
        self.assertIn("heuristic_multi_agent", recommended_config)
        self.assertIn("\u57fa\u4e8e\u771f\u5b9e trace \u7684\u56de\u6807", report_zh)
        self.assertIn("Trace \u7ed3\u6784\u5efa\u8bae", report_zh)
        self.assertIn("Trace-backed calibration", report_en)
        self.assertIn("Trace Structure Hints", report_en)
        self.assertIn('"mode": "multi_agent_calibration"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
