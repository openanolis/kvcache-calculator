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


def _record(
    request_id: str,
    *,
    timestamp_ms: int,
    input_length: int,
    hash_ids: tuple[str, ...],
    source_index: int,
    turn: int = 1,
    chat_id: str | None = None,
) -> RequestRecord:
    return RequestRecord(
        request_id=request_id,
        source_index=source_index,
        timestamp_ms=timestamp_ms,
        chat_id=chat_id or request_id,
        parent_chat_id=None,
        turn=turn,
        request_type="text",
        input_length=input_length,
        output_length=1,
        hash_ids=hash_ids,
    )


class BucketOutputFilesTest(unittest.TestCase):
    def test_bucket_reporting_can_distinguish_machine_count_from_card_count(self) -> None:
        records = [
            _record(
                "r0",
                source_index=0,
                timestamp_ms=1000,
                input_length=16,
                hash_ids=("a",),
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
                    "accelerator_count": 8,
                    "cards_per_machine": 8,
                    "machine_spec": "h20",
                    "hbm_kv_gb_per_card": 1,
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
            planning_strict_prefix_csv = (
                output_dir / "planning_strict_prefix.csv"
            ).read_text(encoding="utf-8")

        self.assertEqual(result.rows[0].machine_count, 1)
        self.assertEqual(result.rows[0].card_count, 8)
        self.assertEqual(result.rows[0].cards_per_machine, 8)
        self.assertIn("机器数,卡数,单机卡数,规格", planning_strict_prefix_csv)

    def test_bucket_reporting_outputs_requested_columns(self) -> None:
        records = [
            _record(
                "r0",
                source_index=0,
                timestamp_ms=1000,
                input_length=24,
                hash_ids=("a", "b"),
            ),
            _record(
                "r1",
                source_index=1,
                timestamp_ms=2000,
                input_length=40,
                hash_ids=("x", "y", "z"),
            ),
            _record(
                "r2",
                source_index=2,
                timestamp_ms=3000,
                input_length=24,
                hash_ids=("a", "b"),
                turn=2,
                chat_id="c2",
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
                    "accelerator_count": 8,
                    "cards_per_machine": 4,
                    "machine_spec": "h20",
                    "total_tps": 500,
                    "total_tps_unit": "per_machine",
                    "hbm_kv_gb_per_card": 0.00000001,
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
            hit_summary_csv = (output_dir / "hit_summary.csv").read_text(encoding="utf-8")
            planning_strict_prefix_csv = (
                output_dir / "planning_strict_prefix.csv"
            ).read_text(encoding="utf-8")
            planning_lru_csv = (output_dir / "planning_lru.csv").read_text(encoding="utf-8")
            details_json = json.loads((output_dir / "details.json").read_text(encoding="utf-8"))

        self.assertIn("分桶", summary_csv)
        self.assertIn("HBM Relaxed Upper Bound 命中率", summary_csv)
        self.assertIn("HBM LRU 命中率", summary_csv)
        self.assertIn("HBM Strict-Prefix Replay 命中率", summary_csv)
        self.assertIn("HBM Strict-Prefix 命中率", summary_csv)
        self.assertIn("HBM Strict-Prefix 求解路径", summary_csv)
        self.assertIn("HBM Strict-Prefix TPS Gain", summary_csv)
        self.assertIn("HBM Strict-Prefix 同负载估算卡数", summary_csv)
        self.assertIn("HBM Strict-Prefix 估算总 TPS", summary_csv)
        self.assertIn("HBM Strict-Prefix 同负载估算机器数", summary_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix 命中率", summary_csv)
        self.assertIn("HBM+单机 1T Relaxed Upper Bound 命中率", summary_csv)
        self.assertIn("HBM+单机 1T LRU 命中率", summary_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix Replay 命中率", summary_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix 求解路径", summary_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix TPS Gain", summary_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix 同负载估算卡数", summary_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix 估算总 TPS", summary_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix 同负载估算机器数", summary_csv)
        self.assertIn("HBM+单机 10T Strict-Prefix 命中率", summary_csv)
        self.assertIn("HBM Relaxed Upper Bound 命中率", hit_summary_csv)
        self.assertIn("HBM LRU 命中率", hit_summary_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix 命中率", hit_summary_csv)
        self.assertIn("HBM+单机 1T LRU 命中率", hit_summary_csv)
        self.assertIn("TPS 输入口径", hit_summary_csv)
        self.assertNotIn("HBM Strict-Prefix TPS Gain", hit_summary_csv)
        self.assertNotIn("HBM LRU TPS Gain", hit_summary_csv)
        self.assertIn("Prefill 节省系数 alpha", planning_strict_prefix_csv)
        self.assertIn("TPS 输入口径", planning_strict_prefix_csv)
        self.assertIn("HBM Strict-Prefix TPS Gain", planning_strict_prefix_csv)
        self.assertIn("HBM Strict-Prefix 同负载估算卡数", planning_strict_prefix_csv)
        self.assertIn("HBM Strict-Prefix 估算总 TPS", planning_strict_prefix_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix TPS Gain", planning_strict_prefix_csv)
        self.assertIn("HBM+单机 1T Strict-Prefix 同负载估算卡数", planning_strict_prefix_csv)
        self.assertNotIn("HBM Relaxed Upper Bound 命中率", planning_strict_prefix_csv)
        self.assertNotIn("HBM Strict-Prefix Replay 命中率", planning_strict_prefix_csv)
        self.assertIn("Prefill 节省系数 alpha", planning_lru_csv)
        self.assertIn("HBM LRU TPS Gain", planning_lru_csv)
        self.assertIn("HBM LRU 同负载估算卡数", planning_lru_csv)
        self.assertIn("HBM LRU 估算总 TPS", planning_lru_csv)
        self.assertIn("HBM+单机 1T LRU TPS Gain", planning_lru_csv)
        self.assertIn("HBM+单机 1T LRU 同负载估算卡数", planning_lru_csv)
        self.assertNotIn("HBM Strict-Prefix 求解路径", planning_lru_csv)
        self.assertEqual(details_json["rows"][0]["bucket_label"], "0-32K")
        self.assertEqual(details_json["rows"][0]["machine_spec"], "h20")
        self.assertEqual(details_json["rows"][0]["machine_count"], 2)
        self.assertEqual(details_json["rows"][0]["card_count"], 8)
        self.assertEqual(details_json["rows"][0]["cards_per_machine"], 4)
        self.assertEqual(details_json["rows"][0]["total_tps_input_unit"], "per_machine")
        self.assertAlmostEqual(details_json["rows"][0]["total_tps"], 1000.0)
        self.assertAlmostEqual(details_json["rows"][0]["prefill_savings_alpha"], 0.5)
        self.assertAlmostEqual(details_json["rows"][0]["actual_hit_rate"], 0.69)
        self.assertIn("hbm_kv_gb_per_card", details_json["rows"][0])
        self.assertIn("model_weight_gb_per_card", details_json["rows"][0])
        self.assertNotIn("hbm_kv_gb_per_machine", details_json["rows"][0])
        self.assertIn("hbm_strict_prefix_replay_hit_rate", details_json["rows"][0])
        self.assertIn("hbm_lru_hit_rate", details_json["rows"][0])
        self.assertIn("hbm_strict_prefix_hit_rate", details_json["rows"][0])
        self.assertIn("hbm_strict_prefix_proof_source", details_json["rows"][0])
        self.assertIn("hbm_strict_prefix_tps_gain", details_json["rows"][0])
        self.assertIn("hbm_strict_prefix_estimated_total_tps", details_json["rows"][0])
        self.assertIn("hbm_strict_prefix_estimated_card_count_for_same_load", details_json["rows"][0])
        self.assertIn(
            "hbm_strict_prefix_estimated_machine_count_for_same_load",
            details_json["rows"][0],
        )
        self.assertIn("hbm_lru_tps_gain", details_json["rows"][0])
        self.assertIn("hbm_lru_estimated_total_tps", details_json["rows"][0])
        self.assertIn("hbm_lru_estimated_card_count_for_same_load", details_json["rows"][0])
        self.assertIn("hbm_lru_estimated_machine_count_for_same_load", details_json["rows"][0])
        self.assertIn("extra_tier_relaxed_upper_bound_hit_rates", details_json["rows"][0])
        self.assertIn("extra_tier_lru_hit_rates", details_json["rows"][0])
        self.assertIn("extra_tier_strict_prefix_replay_hit_rates", details_json["rows"][0])
        self.assertIn("extra_tier_strict_prefix_hit_rates", details_json["rows"][0])
        self.assertIn("extra_tier_strict_prefix_proof_sources", details_json["rows"][0])
        self.assertIn("extra_tier_strict_prefix_tps_gains", details_json["rows"][0])
        self.assertIn("extra_tier_strict_prefix_estimated_total_tps", details_json["rows"][0])
        self.assertIn(
            "extra_tier_strict_prefix_estimated_card_counts_for_same_load",
            details_json["rows"][0],
        )
        self.assertIn(
            "extra_tier_strict_prefix_estimated_machine_counts_for_same_load",
            details_json["rows"][0],
        )
        self.assertIn("extra_tier_lru_tps_gains", details_json["rows"][0])
        self.assertIn("extra_tier_lru_estimated_total_tps", details_json["rows"][0])
        self.assertIn(
            "extra_tier_lru_estimated_card_counts_for_same_load",
            details_json["rows"][0],
        )
        self.assertIn(
            "extra_tier_lru_estimated_machine_counts_for_same_load",
            details_json["rows"][0],
        )
        self.assertEqual(details_json["rows"][0]["hbm_strict_prefix_proof_source"], "certificate")
        self.assertEqual(
            details_json["details"]["0-32K"]["hbm_strict_prefix_summary"]["proof_source"],
            "certificate",
        )
        self.assertIn("hbm_lru_summary", details_json["details"]["0-32K"])
        self.assertIn("extra_lru_summaries", details_json["details"]["0-32K"])
        self.assertEqual(
            details_json["rows"][0]["extra_tier_strict_prefix_proof_sources"]["HBM+单机 1T 命中率"],
            "certificate",
        )
        self.assertEqual(
            details_json["rows"][0]["extra_tier_strict_prefix_proof_sources"]["HBM+单机 10T 命中率"],
            "certificate",
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["hbm_lru_hit_rate"],
            details_json["details"]["0-32K"]["hbm_lru_summary"]["strict_prefix_block_hit_rate"],
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["hbm_strict_prefix_hit_rate"],
            details_json["rows"][0]["extra_tier_strict_prefix_hit_rates"]["HBM+单机 1T 命中率"],
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["extra_tier_lru_hit_rates"]["HBM+单机 1T 命中率"],
            details_json["details"]["0-32K"]["extra_lru_summaries"]["HBM+单机 1T 命中率"][
                "strict_prefix_block_hit_rate"
            ],
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
            1.0
            - details_json["rows"][0]["prefill_savings_alpha"]
            * details_json["rows"][0]["hbm_strict_prefix_hit_rate"]
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["hbm_strict_prefix_tps_gain"],
            expected_hbm_tps_gain,
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["hbm_strict_prefix_estimated_total_tps"],
            details_json["rows"][0]["total_tps"] * expected_hbm_tps_gain,
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["hbm_strict_prefix_estimated_card_count_for_same_load"],
            details_json["rows"][0]["card_count"] / expected_hbm_tps_gain,
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["hbm_strict_prefix_estimated_machine_count_for_same_load"],
            details_json["rows"][0]["machine_count"] / expected_hbm_tps_gain,
        )
        expected_hbm_lru_tps_gain = 1.0 / (
            1.0
            - details_json["rows"][0]["prefill_savings_alpha"]
            * details_json["rows"][0]["hbm_lru_hit_rate"]
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["hbm_lru_tps_gain"],
            expected_hbm_lru_tps_gain,
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["hbm_lru_estimated_total_tps"],
            details_json["rows"][0]["total_tps"] * expected_hbm_lru_tps_gain,
        )
        expected_extra_tier_gain = 1.0 / (
            1.0
            - details_json["rows"][0]["prefill_savings_alpha"]
            * details_json["rows"][0]["extra_tier_strict_prefix_hit_rates"]["HBM+单机 1T 命中率"]
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["extra_tier_strict_prefix_tps_gains"]["HBM+单机 1T 命中率"],
            expected_extra_tier_gain,
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["extra_tier_strict_prefix_estimated_total_tps"][
                "HBM+单机 1T 命中率"
            ],
            details_json["rows"][0]["total_tps"] * expected_extra_tier_gain,
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["extra_tier_strict_prefix_estimated_card_counts_for_same_load"][
                "HBM+单机 1T 命中率"
            ],
            details_json["rows"][0]["card_count"] / expected_extra_tier_gain,
        )
        self.assertAlmostEqual(
            details_json["rows"][0][
                "extra_tier_strict_prefix_estimated_machine_counts_for_same_load"
            ][
                "HBM+单机 1T 命中率"
            ],
            details_json["rows"][0]["machine_count"] / expected_extra_tier_gain,
        )
        expected_extra_tier_lru_gain = 1.0 / (
            1.0
            - details_json["rows"][0]["prefill_savings_alpha"]
            * details_json["rows"][0]["extra_tier_lru_hit_rates"]["HBM+单机 1T 命中率"]
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["extra_tier_lru_tps_gains"]["HBM+单机 1T 命中率"],
            expected_extra_tier_lru_gain,
        )
        self.assertAlmostEqual(
            details_json["rows"][0]["extra_tier_lru_estimated_total_tps"]["HBM+单机 1T 命中率"],
            details_json["rows"][0]["total_tps"] * expected_extra_tier_lru_gain,
        )

    def test_bucket_reporting_omits_actual_hit_rate_column_when_absent(self) -> None:
        records = [
            _record(
                "r0",
                source_index=0,
                timestamp_ms=1000,
                input_length=24,
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
                    "accelerator_count": 8,
                    "cards_per_machine": 8,
                    "machine_spec": "h20",
                    "hbm_kv_gb_per_card": 1,
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
            hit_summary_csv = (output_dir / "hit_summary.csv").read_text(encoding="utf-8")
            planning_strict_prefix_csv = (
                output_dir / "planning_strict_prefix.csv"
            ).read_text(encoding="utf-8")
            planning_lru_csv = (output_dir / "planning_lru.csv").read_text(encoding="utf-8")

        self.assertNotIn("实际命中率", summary_csv)
        self.assertNotIn("总 TPS", summary_csv)
        self.assertNotIn("HBM Strict-Prefix 估算总 TPS", summary_csv)
        self.assertIn("HBM Strict-Prefix TPS Gain", summary_csv)
        self.assertIn("HBM Strict-Prefix 同负载估算卡数", summary_csv)
        self.assertIn("HBM Strict-Prefix 同负载估算机器数", summary_csv)
        self.assertNotIn("HBM Strict-Prefix TPS Gain", hit_summary_csv)
        self.assertIn("HBM Strict-Prefix TPS Gain", planning_strict_prefix_csv)
        self.assertIn("HBM Strict-Prefix 同负载估算卡数", planning_strict_prefix_csv)
        self.assertNotIn("HBM Strict-Prefix 估算总 TPS", planning_strict_prefix_csv)
        self.assertIn("HBM LRU TPS Gain", planning_lru_csv)
        self.assertNotIn("HBM LRU 估算总 TPS", planning_lru_csv)


if __name__ == "__main__":
    unittest.main()
