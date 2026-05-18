from __future__ import annotations

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
from kvcache_upper_bound.core.models import Scope
from kvcache_upper_bound.ingest import (
    build_effective_requests,
    convert_benchmark_results,
    convert_conversation_dataset,
    load_request_records,
)


class DatasetConvertersTest(unittest.TestCase):
    def test_convert_lmsys_conversation_dataset_emits_session_chain_and_loader_compatible_trace(
        self,
    ) -> None:
        payload = {
            "conversation_id": "conv-1",
            "created_at": "2024-03-09T16:00:00+00:00",
            "conversation": [
                {"role": "system", "content": "You are concise."},
                {"role": "user", "content": "hello there"},
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "hello there again"},
                {"role": "assistant", "content": "welcome back"},
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "lmsys.jsonl"
            output_path = Path(tmpdir) / "converted_trace.jsonl"
            input_path.write_text(json.dumps(payload), encoding="utf-8")

            result = convert_conversation_dataset(
                input_path,
                output_path,
                source_format="lmsys-chat-1m",
            )
            trace_result = load_request_records(output_path)
            normalized = build_effective_requests(
                trace_result.records,
                window_tokens=10_000,
                scope=Scope.SESSION,
            )
            metadata = json.loads((output_path.parent / "metadata.json").read_text(encoding="utf-8"))

        self.assertEqual(result.stats.emitted_records, 2)
        self.assertEqual(trace_result.stats.loaded_records, 2)
        self.assertEqual([record.turn for record in trace_result.records], [1, 2])
        self.assertEqual(
            [(record.chat_id, record.parent_chat_id) for record in trace_result.records],
            [("conv-1/turn-1", None), ("conv-1/turn-2", "conv-1/turn-1")],
        )
        self.assertIsNone(trace_result.records[0].parent_chat_id)
        self.assertEqual(trace_result.records[1].parent_chat_id, "conv-1/turn-1")
        self.assertEqual(
            [request.scope_root_id for request in normalized.requests],
            ["conv-1/turn-1", "conv-1/turn-1"],
        )
        self.assertLess(
            len(trace_result.records[0].hash_ids),
            len(trace_result.records[1].hash_ids),
        )
        self.assertEqual(metadata["mode"], "conversation_dataset_conversion")
        self.assertIn("converted trace is derived", metadata["limitations"][0])

    def test_convert_sharegpt_via_cli_uses_synthetic_timestamps_when_missing(self) -> None:
        payload = {
            "id": "sharegpt-1",
            "conversations": [
                {"from": "human", "value": "alpha beta gamma delta"},
                {"from": "gpt", "value": "ok"},
                {"from": "human", "value": "alpha beta gamma delta epsilon"},
                {"from": "gpt", "value": "nice"},
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "sharegpt.jsonl"
            output_dir = Path(tmpdir) / "out"
            input_path.write_text(json.dumps(payload), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout), patch.object(
                sys,
                "argv",
                [
                    "kvcache-upper-bound",
                    "convert-conversation-dataset",
                    "--input",
                    str(input_path),
                    "--format",
                    "sharegpt",
                    "--output-dir",
                    str(output_dir),
                ],
            ):
                exit_code = main()

            trace_result = load_request_records(output_dir / "converted_trace.jsonl")
            metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(trace_result.stats.loaded_records, 2)
        self.assertEqual(metadata["source_format"], "sharegpt")
        self.assertEqual(metadata["stats"]["synthetic_timestamps"], 1)
        self.assertIn('"mode": "conversation_dataset_conversion"', stdout.getvalue())

    def test_convert_benchmark_results_rejects_missing_hash_ids_without_flag(self) -> None:
        payloads = [
            {
                "request_id": "req-a",
                "timestamp_ms": 1000,
                "input_length": 20,
                "output_length": 5,
            },
            {
                "request_id": "req-b",
                "timestamp_ms": 2000,
                "input_length": 32,
                "output_length": 6,
                "hash_ids": ["h1", "h2"],
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "benchmark.jsonl"
            output_path = Path(tmpdir) / "converted_trace.jsonl"
            input_path.write_text(
                "\n".join(json.dumps(item) for item in payloads),
                encoding="utf-8",
            )

            result = convert_benchmark_results(input_path, output_path)
            trace_result = load_request_records(output_path)
            metadata = json.loads((output_path.parent / "metadata.json").read_text(encoding="utf-8"))

        self.assertEqual(result.stats.skipped_items, 1)
        self.assertEqual(trace_result.stats.loaded_records, 1)
        self.assertEqual(trace_result.records[0].request_id, "req-b")
        self.assertIn("records without hash_ids are rejected", metadata["limitations"][-1])

    def test_convert_benchmark_results_with_synthetic_hash_ids_degrades_to_standalone_requests(
        self,
    ) -> None:
        payload = {
            "id": "bench-1",
            "time": 12.5,
            "input_length": 33,
            "output_length": 3,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "benchmark.jsonl"
            output_dir = Path(tmpdir) / "out"
            input_path.write_text(json.dumps(payload), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout), patch.object(
                sys,
                "argv",
                [
                    "kvcache-upper-bound",
                    "convert-benchmark-results",
                    "--input",
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                    "--allow-synthetic-hash-ids",
                ],
            ):
                exit_code = main()

            trace_result = load_request_records(output_dir / "converted_trace.jsonl")
            normalized = build_effective_requests(
                trace_result.records,
                window_tokens=10_000,
                scope=Scope.SESSION,
            )
            metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(trace_result.stats.loaded_records, 1)
        self.assertTrue(trace_result.records[0].hash_ids[0].startswith("__synthetic__"))
        self.assertEqual(trace_result.records[0].turn, 1)
        self.assertEqual(trace_result.records[0].chat_id, "bench-1")
        self.assertEqual(normalized.requests[0].scope_root_id, "bench-1")
        self.assertEqual(metadata["stats"]["synthetic_hash_records"], 1)
        self.assertEqual(metadata["stats"]["degraded_session_records"], 1)
        self.assertIn("replay-only unique prefixes", metadata["limitations"][-1])
        self.assertIn('"mode": "benchmark_replay_conversion"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
