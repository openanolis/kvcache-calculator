from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.core.models import RequestRecord
from kvcache_upper_bound.reporting import (
    analyze_bucket_deployments,
    load_bucket_analysis_config,
    write_bucket_outputs,
)


class BucketReportingTest(unittest.TestCase):
    def test_bucket_reporting_can_derive_hbm_kv_budget_from_gpu_memory_and_model_weights(self) -> None:
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
            )
        ]
        half_gib_parameters = (1024**3) // 2
        config_payload = {
            "model_profile": {
                "n_layers": 1,
                "n_kv_heads": 1,
                "head_dim": 1,
                "dtype_bytes": 1,
                "weight_dtype_bytes": 1,
                "parameter_count": half_gib_parameters,
                "tp_size": 1,
                "block_size": 16,
            },
            "scope": "global",
            "block_size": 16,
            "bucket_deployments": [
                {
                    "label": "0-32K",
                    "lower_tokens": 0,
                    "upper_tokens": 32768,
                    "machine_count": 2,
                    "machine_spec": "h20",
                    "gpu_memory_gb_per_machine": 1.25,
                    "runtime_reserve_gb_per_machine": 0.25,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            config = load_bucket_analysis_config(config_path)
            result = analyze_bucket_deployments(records, config)

        self.assertAlmostEqual(result.rows[0].hbm_kv_total_gb, 1.0, places=6)
        self.assertAlmostEqual(config.prefill_savings_alpha, 0.8)

    def test_bucket_reporting_outputs_requested_columns(self) -> None:
        records = [
            RequestRecord(
                request_id="r0",
                source_index=0,
                timestamp_ms=1000,
                chat_id="c0",
                parent_chat_id=None,
                turn=1,
                request_type="text",
                input_length=24,
                output_length=1,
                hash_ids=("a", "b"),
            ),
            RequestRecord(
                request_id="r1",
                source_index=1,
                timestamp_ms=2000,
                chat_id="c1",
                parent_chat_id=None,
                turn=1,
                request_type="text",
                input_length=40,
                output_length=1,
                hash_ids=("x", "y", "z"),
            ),
            RequestRecord(
                request_id="r2",
                source_index=2,
                timestamp_ms=3000,
                chat_id="c2",
                parent_chat_id=None,
                turn=2,
                request_type="text",
                input_length=24,
                output_length=1,
                hash_ids=("a", "b"),
            ),
        ]
        config_payload = {
            "prefill_savings_alpha": 0.5,
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
                    "label": "0-32K",
                    "lower_tokens": 0,
                    "upper_tokens": 32768,
                    "machine_spec": "8*h20",
                    "total_tps": 1000,
                    "hbm_kv_gb_per_machine": 0.00000001,
                    "actual_hit_rate": "69%(2 个部署)",
                    "extra_capacity_tiers": [
                        {"label": "HBM+单机 1T 命中率", "kv_gb_per_machine": 0.00000001},
                        {"label": "HBM+单机 10T 命中率", "kv_gb_per_machine": 0.00000002},
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            output_dir = Path(tmpdir) / "out"
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            config = load_bucket_analysis_config(config_path)
            result = analyze_bucket_deployments(records, config)
            write_bucket_outputs(result, output_dir)
            summary_csv = (output_dir / "summary.csv").read_text(encoding="utf-8")
            details_json = json.loads((output_dir / "details.json").read_text(encoding="utf-8"))

        self.assertIn("分桶", summary_csv)
        self.assertIn("HBM Relaxed Upper Bound 命中率", summary_csv)
        self.assertIn("HBM Strict-Prefix Replay 命中率", summary_csv)
        self.assertIn("HBM Strict-Prefix 命中率", summary_csv)
        self.assertIn("HBM Strict-Prefix 求解路径", summary_csv)
        self.assertIn("HBM TPS Gain", summary_csv)
        self.assertIn("HBM 估算总 TPS", summary_csv)
        self.assertIn("HBM 同负载估算机器数", summary_csv)
        self.assertIn("HBM+单机 1T 命中率", summary_csv)
        self.assertIn("HBM+单机 1T Relaxed Upper Bound 命中率", summary_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix Replay 命中率", summary_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix 求解路径", summary_csv)
        self.assertIn("HBM+单机 1T TPS Gain", summary_csv)
        self.assertIn("HBM+单机 1T 估算总 TPS", summary_csv)
        self.assertIn("HBM+单机 1T 同负载估算机器数", summary_csv)
        self.assertIn("HBM+单机 10T 命中率", summary_csv)
        self.assertEqual(details_json["rows"][0]["bucket_label"], "0-32K")
        self.assertEqual(details_json["rows"][0]["machine_spec"], "h20")
        self.assertEqual(details_json["rows"][0]["machine_count"], 8)
        self.assertAlmostEqual(details_json["rows"][0]["prefill_savings_alpha"], 0.5)
        self.assertAlmostEqual(details_json["rows"][0]["actual_hit_rate"], 0.69)
        self.assertIn("hbm_strict_prefix_replay_hit_rate", details_json["rows"][0])
        self.assertIn("hbm_strict_prefix_hit_rate", details_json["rows"][0])
        self.assertIn("hbm_strict_prefix_proof_source", details_json["rows"][0])
        self.assertIn("hbm_tps_gain", details_json["rows"][0])
        self.assertIn("hbm_estimated_total_tps", details_json["rows"][0])
        self.assertIn("hbm_estimated_machine_count_for_same_load", details_json["rows"][0])
        self.assertIn("extra_tier_relaxed_upper_bound_hit_rates", details_json["rows"][0])
        self.assertIn("extra_tier_strict_prefix_replay_hit_rates", details_json["rows"][0])
        self.assertIn("extra_tier_strict_prefix_hit_rates", details_json["rows"][0])
        self.assertIn("extra_tier_strict_prefix_proof_sources", details_json["rows"][0])
        self.assertIn("extra_tier_tps_gains", details_json["rows"][0])
        self.assertIn("extra_tier_estimated_total_tps", details_json["rows"][0])
        self.assertIn(
            "extra_tier_estimated_machine_counts_for_same_load",
            details_json["rows"][0],
        )
        self.assertEqual(details_json["rows"][0]["hbm_strict_prefix_proof_source"], "certificate")
        self.assertTrue(
            details_json["details"]["0-32K"]["hbm_strict_prefix_summary"]["proof_source"] == "certificate"
        )
        self.assertEqual(
            details_json["rows"][0]["extra_tier_strict_prefix_proof_sources"]["HBM+单机 1T 命中率"],
            "certificate",
        )
        self.assertEqual(
            details_json["rows"][0]["extra_tier_strict_prefix_proof_sources"]["HBM+单机 10T 命中率"],
            "certificate",
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["hbm_strict_prefix_hit_rate"],
            details_json["rows"][0]["extra_tier_strict_prefix_hit_rates"]["HBM+单机 1T 命中率"],
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["extra_tier_relaxed_upper_bound_hit_rates"]["HBM+单机 1T 命中率"],
            details_json["rows"][0]["extra_tier_relaxed_upper_bound_hit_rates"]["HBM+单机 10T 命中率"],
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["extra_tier_strict_prefix_hit_rates"]["HBM+单机 1T 命中率"],
            details_json["rows"][0]["extra_tier_strict_prefix_hit_rates"]["HBM+单机 10T 命中率"],
        )
        expected_hbm_tps_gain = 1.0 / (
            1.0 - details_json["rows"][0]["prefill_savings_alpha"] * details_json["rows"][0]["hbm_strict_prefix_hit_rate"]
        )
        self.assertAlmostEqual(details_json["rows"][0]["hbm_tps_gain"], expected_hbm_tps_gain)
        self.assertAlmostEqual(
            details_json["rows"][0]["hbm_estimated_total_tps"],
            details_json["rows"][0]["total_tps"] * expected_hbm_tps_gain,
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["hbm_estimated_machine_count_for_same_load"],
            details_json["rows"][0]["machine_count"] / expected_hbm_tps_gain,
        )
        expected_extra_tier_gain = 1.0 / (
            1.0
            - details_json["rows"][0]["prefill_savings_alpha"]
            * details_json["rows"][0]["extra_tier_strict_prefix_hit_rates"]["HBM+单机 1T 命中率"]
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["extra_tier_tps_gains"]["HBM+单机 1T 命中率"],
            expected_extra_tier_gain,
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["extra_tier_estimated_total_tps"]["HBM+单机 1T 命中率"],
            details_json["rows"][0]["total_tps"] * expected_extra_tier_gain,
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["extra_tier_estimated_machine_counts_for_same_load"][
                "HBM+单机 1T 命中率"
            ],
            details_json["rows"][0]["machine_count"] / expected_extra_tier_gain,
        )

    def test_bucket_reporting_omits_actual_hit_rate_column_when_absent(self) -> None:
        records = [
            RequestRecord(
                request_id="r0",
                source_index=0,
                timestamp_ms=1000,
                chat_id="c0",
                parent_chat_id=None,
                turn=1,
                request_type="text",
                input_length=24,
                output_length=1,
                hash_ids=("a", "b"),
            )
        ]
        config_payload = {
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
                    "label": "0-32K",
                    "lower_tokens": 0,
                    "upper_tokens": 32768,
                    "machine_count": 8,
                    "machine_spec": "h20",
                    "hbm_kv_gb_per_machine": 1
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            output_dir = Path(tmpdir) / "out"
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            config = load_bucket_analysis_config(config_path)
            result = analyze_bucket_deployments(records, config)
            write_bucket_outputs(result, output_dir)
            summary_csv = (output_dir / "summary.csv").read_text(encoding="utf-8")

        self.assertNotIn("实际命中率", summary_csv)
        self.assertNotIn("总 TPS", summary_csv)
        self.assertNotIn("HBM 估算总 TPS", summary_csv)
        self.assertIn("HBM TPS Gain", summary_csv)
        self.assertIn("HBM 同负载估算机器数", summary_csv)


if __name__ == "__main__":
    unittest.main()
