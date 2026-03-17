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
        self.assertIn("HBM KVCache 空间命中率", summary_csv)
        self.assertIn("HBM+单机 1T 命中率", summary_csv)
        self.assertIn("HBM+单机 10T 命中率", summary_csv)
        self.assertEqual(details_json["rows"][0]["bucket_label"], "0-32K")
        self.assertEqual(details_json["rows"][0]["machine_spec"], "h20")
        self.assertEqual(details_json["rows"][0]["machine_count"], 8)
        self.assertAlmostEqual(details_json["rows"][0]["actual_hit_rate"], 0.69)

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


if __name__ == "__main__":
    unittest.main()
