from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.core.models import EffectiveRequest, RequestRecord, Scope
from kvcache_upper_bound.oracle import analyze_content_upper_bound
from kvcache_upper_bound.reporting import analyze_bucket_deployments, load_bucket_analysis_config
from kvcache_upper_bound.verification import (
    analyze_content_upper_bound_naive,
    build_bucket_audit_report,
    find_smallest_strict_prefix_gap_counterexample,
    find_smallest_strict_prefix_replay_gap_counterexample,
    verify_exhaustive_small_cases,
    write_bucket_audit_outputs,
)


class VerificationReferenceTest(unittest.TestCase):
    def test_naive_content_matches_fast_content(self) -> None:
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
                effective_hash_ids=("a", "b", "c"),
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
                effective_hash_ids=("a", "b", "d"),
            ),
        ]

        fast = analyze_content_upper_bound(requests)
        slow = analyze_content_upper_bound_naive(requests)

        self.assertEqual(fast.summary.hit_blocks, slow.summary.hit_blocks)
        self.assertEqual(
            [metric.hit_blocks for metric in fast.request_metrics],
            [metric.hit_blocks for metric in slow.request_metrics],
        )

    def test_exhaustive_small_cases_returns_positive_counts(self) -> None:
        summary = verify_exhaustive_small_cases(
            max_requests=2,
            max_blocks_per_request=2,
            alphabet=("a", "b"),
        )

        self.assertGreater(summary.content_case_count, 0)
        self.assertGreater(summary.relaxed_capacity_case_count, 0)
        self.assertGreater(summary.strict_prefix_case_count, 0)
        self.assertTrue(summary.relaxed_equals_strict_on_verified_cases)
        self.assertTrue(summary.replay_equals_strict_on_verified_cases)

    def test_find_smallest_strict_prefix_gap_counterexample(self) -> None:
        counterexample = find_smallest_strict_prefix_gap_counterexample()

        self.assertIsNone(counterexample)

    def test_find_smallest_strict_prefix_replay_gap_counterexample(self) -> None:
        counterexample = find_smallest_strict_prefix_replay_gap_counterexample()

        self.assertIsNone(counterexample)

    def test_audit_outputs_write_zh_and_en_markdown(self) -> None:
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
            analysis_result = analyze_bucket_deployments(records, config)
            report = build_bucket_audit_report(
                records,
                config=config,
                analysis_result=analysis_result,
                trace="toy-trace",
                config_path=str(config_path),
                sample_request_limit=2,
            )
            write_bucket_audit_outputs(report, output_dir)

            report_json = json.loads((output_dir / "correctness_report.json").read_text(encoding="utf-8"))
            default_md = (output_dir / "correctness_report.md").read_text(encoding="utf-8")
            zh_md = (output_dir / "correctness_report.zh.md").read_text(encoding="utf-8")
            en_md = (output_dir / "correctness_report.en.md").read_text(encoding="utf-8")

        self.assertTrue(default_md.startswith("# Correctness Report"))
        self.assertEqual(default_md, en_md)
        self.assertTrue(zh_md.startswith("# \u7ed3\u679c\u6b63\u786e\u6027\u62a5\u544a"))
        self.assertIn("normalized_bucket_inputs", report_json)
        self.assertEqual(report_json["normalized_bucket_inputs"][0]["machine_count"], 1)
        self.assertIn("## \u8f93\u5165\u5f52\u4e00\u5316\u6458\u8981", zh_md)
        self.assertIn("## Normalized Inputs", en_md)
        self.assertIn("### \u6269\u5c55\u5bb9\u91cf\u5c42\u5f52\u4e00\u5316", zh_md)
        self.assertIn("### Normalized Extra Capacity Tiers", en_md)
        self.assertIn("## \u7a77\u4e3e\u53c2\u8003\u6821\u9a8c", zh_md)
        self.assertIn("## Exhaustive Reference", en_md)
        self.assertIn("strict-prefix \u6821\u9a8c\u6837\u4f8b\u6570", zh_md)
        self.assertIn("strict-prefix cases verified", en_md)
        self.assertIn("## Strict Prefix \u7b49\u4ef7\u6821\u9a8c", zh_md)
        self.assertIn("## Strict Prefix Equivalence", en_md)
        self.assertIn("strict-prefix replay HBM \u547d\u4e2d", zh_md)
        self.assertIn("strict-prefix replay HBM hits", en_md)
        self.assertIn("strict-prefix HBM \u547d\u4e2d", zh_md)
        self.assertIn("strict-prefix HBM hits", en_md)
        self.assertIn("strict-prefix \u6c42\u89e3\u8def\u5f84", zh_md)
        self.assertIn("strict-prefix proof source", en_md)


if __name__ == "__main__":
    unittest.main()
