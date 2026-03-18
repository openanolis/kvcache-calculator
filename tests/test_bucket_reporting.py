from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.cli.main import _build_analysis_metadata_payload
from kvcache_upper_bound.core.models import RequestRecord
from kvcache_upper_bound.reporting import (
    analyze_bucket_deployments,
    build_bucket_input_summaries,
    load_bucket_analysis_config,
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
                    "accelerator_count": 2,
                    "cards_per_machine": 1,
                    "machine_spec": "h20",
                    "gpu_memory_gb_per_card": 1.25,
                    "runtime_reserve_gb_per_card": 0.25,
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
        self.assertEqual(result.rows[0].machine_count, 2)
        self.assertEqual(result.rows[0].card_count, 2)

    def test_bucket_reporting_rejects_legacy_machine_fields(self) -> None:
        base_payload = {
            "model_profile": {
                "n_layers": 1,
                "n_kv_heads": 1,
                "head_dim": 1,
                "dtype_bytes": 1,
                "block_size": 16,
            },
            "scope": "global",
            "block_size": 16,
        }
        cases = [
            (
                {
                    "label": "0-32K",
                    "lower_tokens": 0,
                    "upper_tokens": 32768,
                    "machine_count": 8,
                    "cards_per_machine": 8,
                    "machine_spec": "h20",
                    "hbm_kv_gb_per_card": 1,
                },
                "machine_count is no longer accepted",
            ),
            (
                {
                    "label": "0-32K",
                    "lower_tokens": 0,
                    "upper_tokens": 32768,
                    "accelerator_count": 8,
                    "cards_per_machine": 8,
                    "machine_spec": "8*h20",
                    "hbm_kv_gb_per_card": 1,
                },
                "machine_spec must be a plain spec label",
            ),
            (
                {
                    "label": "0-32K",
                    "lower_tokens": 0,
                    "upper_tokens": 32768,
                    "accelerator_count": 8,
                    "machine_spec": "h20",
                    "hbm_kv_gb_per_card": 1,
                },
                "cards_per_machine is required",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            for deployment_payload, expected_message in cases:
                payload = dict(base_payload)
                payload["bucket_deployments"] = [deployment_payload]
                config_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, expected_message):
                    load_bucket_analysis_config(config_path)

    def test_bucket_reporting_rejects_legacy_budget_field_names(self) -> None:
        base_payload = {
            "model_profile": {
                "n_layers": 1,
                "n_kv_heads": 1,
                "head_dim": 1,
                "dtype_bytes": 1,
                "block_size": 16,
            },
            "scope": "global",
            "block_size": 16,
        }
        cases = [
            {
                "label": "0-32K",
                "lower_tokens": 0,
                "upper_tokens": 32768,
                "accelerator_count": 8,
                "cards_per_machine": 8,
                "machine_spec": "h20",
                "hbm_kv_gb_per_machine": 1,
            },
            {
                "label": "0-32K",
                "lower_tokens": 0,
                "upper_tokens": 32768,
                "accelerator_count": 8,
                "cards_per_machine": 8,
                "machine_spec": "h20",
                "gpu_memory_gb_per_machine": 80,
            },
            {
                "label": "0-32K",
                "lower_tokens": 0,
                "upper_tokens": 32768,
                "accelerator_count": 8,
                "cards_per_machine": 8,
                "machine_spec": "h20",
                "gpu_memory_gb_per_card": 80,
                "runtime_reserve_gb_per_machine": 4,
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            for deployment_payload in cases:
                payload = dict(base_payload)
                payload["bucket_deployments"] = [deployment_payload]
                config_path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError,
                    "legacy per-machine budget fields are no longer accepted",
                ):
                    load_bucket_analysis_config(config_path)

    def test_bucket_reporting_resolves_total_tps_input_units(self) -> None:
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
        base_config = {
            "model_profile": {
                "n_layers": 1,
                "n_kv_heads": 1,
                "head_dim": 1,
                "dtype_bytes": 1,
                "block_size": 16,
            },
            "scope": "global",
            "block_size": 16,
        }
        cases = [
            ("cluster_total", 120.0, 120.0),
            ("per_machine", 120.0, 240.0),
            ("per_card", 120.0, 960.0),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            for total_tps_unit, input_total_tps, expected_total_tps in cases:
                payload = dict(base_config)
                payload["bucket_deployments"] = [
                    {
                        "label": "0-32K",
                        "lower_tokens": 0,
                        "upper_tokens": 32768,
                        "accelerator_count": 8,
                        "cards_per_machine": 4,
                        "machine_spec": "h20",
                        "total_tps": input_total_tps,
                        "total_tps_unit": total_tps_unit,
                        "hbm_kv_gb_per_card": 1,
                    }
                ]
                config_path.write_text(json.dumps(payload), encoding="utf-8")
                config = load_bucket_analysis_config(config_path)
                result = analyze_bucket_deployments(records, config)
                self.assertAlmostEqual(result.rows[0].total_tps or 0.0, expected_total_tps)
                self.assertEqual(result.rows[0].total_tps_input_unit, total_tps_unit)

            payload = dict(base_config)
            payload["bucket_deployments"] = [
                {
                    "label": "0-32K",
                    "lower_tokens": 0,
                    "upper_tokens": 32768,
                    "accelerator_count": 8,
                    "cards_per_machine": 4,
                    "machine_spec": "h20",
                    "total_tps": 120,
                    "total_tps_unit": "per_rack",
                    "hbm_kv_gb_per_card": 1,
                }
            ]
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "total_tps_unit must be one of"):
                load_bucket_analysis_config(config_path)

    def test_bucket_reporting_rejects_ambiguous_budget_config(self) -> None:
        payload = {
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
                    "gpu_memory_gb_per_card": 96,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "provide either hbm_kv_gb_per_card or gpu_memory_gb_per_card, not both",
            ):
                load_bucket_analysis_config(config_path)

    def test_bucket_reporting_rejects_overlapping_bucket_ranges(self) -> None:
        payload = {
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
                },
                {
                    "label": "24-64K",
                    "lower_tokens": 24576,
                    "upper_tokens": 65536,
                    "accelerator_count": 8,
                    "cards_per_machine": 8,
                    "machine_spec": "h20",
                    "hbm_kv_gb_per_card": 1,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError,
                "bucket_deployments must be sorted by lower_tokens without overlap",
            ):
                load_bucket_analysis_config(config_path)

    def test_bucket_reporting_builds_normalized_input_summary_and_metadata(self) -> None:
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
        payload = {
            "prefill_savings_alpha": 0.8,
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
                    "hbm_kv_gb_per_card": 2,
                    "extra_capacity_tiers": [
                        {"label": "HBM+单机 1T 命中率", "kv_gb_per_machine": 1024}
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(payload), encoding="utf-8")
            config = load_bucket_analysis_config(config_path)
            result = analyze_bucket_deployments(records, config)

        summaries = build_bucket_input_summaries(result)
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].machine_count, 2)
        self.assertEqual(summaries[0].card_count, 8)
        self.assertEqual(summaries[0].total_tps_input_unit, "per_machine")
        self.assertAlmostEqual(summaries[0].total_tps_input or 0.0, 500.0)
        self.assertAlmostEqual(summaries[0].total_tps_cluster_total or 0.0, 1000.0)
        self.assertAlmostEqual(summaries[0].hbm_kv_gb_per_card, 2.0)
        self.assertAlmostEqual(summaries[0].hbm_kv_total_gb, 16.0)
        self.assertEqual(len(summaries[0].extra_capacity_tiers), 1)
        self.assertAlmostEqual(
            summaries[0].extra_capacity_tiers[0].extra_kv_total_gb,
            2048.0,
        )
        self.assertAlmostEqual(
            summaries[0].extra_capacity_tiers[0].total_kv_gb,
            2064.0,
        )

        metadata = _build_analysis_metadata_payload(
            trace="toy-trace",
            config_path="/tmp/config.json",
            output_dir=Path("/tmp/out"),
            trace_result=SimpleNamespace(
                stats=SimpleNamespace(loaded_records=1, skipped_records=0, total_lines=1)
            ),
            analysis_result=result,
        )
        self.assertIn("normalized_bucket_inputs", metadata)
        self.assertEqual(metadata["normalized_bucket_inputs"][0]["machine_count"], 2)
        self.assertEqual(metadata["normalized_bucket_inputs"][0]["card_count"], 8)
        self.assertEqual(
            metadata["normalized_bucket_inputs"][0]["extra_capacity_tiers"][0]["total_kv_gb"],
            2064.0,
        )

    def test_extra_capacity_tier_scales_by_machine_count_not_card_count(self) -> None:
        records = [
            RequestRecord(
                request_id="r0",
                source_index=0,
                timestamp_ms=1000,
                chat_id="c0",
                parent_chat_id=None,
                turn=1,
                request_type="text",
                input_length=3,
                output_length=1,
                hash_ids=("a", "b", "c"),
            ),
            RequestRecord(
                request_id="r1",
                source_index=1,
                timestamp_ms=2000,
                chat_id="c1",
                parent_chat_id=None,
                turn=1,
                request_type="text",
                input_length=3,
                output_length=1,
                hash_ids=("a", "b", "c"),
            ),
        ]
        one_block_gb = 2 / (1024**3)
        config_payload = {
            "model_profile": {
                "n_layers": 1,
                "n_kv_heads": 1,
                "head_dim": 1,
                "dtype_bytes": 1,
                "block_size": 1,
            },
            "scope": "global",
            "block_size": 1,
            "bucket_deployments": [
                {
                    "label": "0-32K",
                    "lower_tokens": 0,
                    "upper_tokens": 32768,
                    "accelerator_count": 8,
                    "cards_per_machine": 8,
                    "machine_spec": "h20",
                    "hbm_kv_gb_per_card": 0.0,
                    "extra_capacity_tiers": [
                        {"label": "HBM+单机 1 block 命中率", "kv_gb_per_machine": one_block_gb}
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            config = load_bucket_analysis_config(config_path)
            result = analyze_bucket_deployments(records, config)

        self.assertEqual(result.rows[0].machine_count, 1)
        self.assertEqual(result.rows[0].card_count, 8)
        self.assertAlmostEqual(result.rows[0].hbm_strict_prefix_hit_rate or 0.0, 0.0)
        self.assertAlmostEqual(
            result.rows[0].extra_tier_strict_prefix_hit_rates["HBM+单机 1 block 命中率"],
            1.0 / 6.0,
        )

if __name__ == "__main__":
    unittest.main()
