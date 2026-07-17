"""Tests for the generate-trace CLI command."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.cli.main import main


class CLIGenerateTraceTest(unittest.TestCase):
    """Tests for the generate-trace CLI subcommand."""

    def test_generates_jsonl_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "trace.jsonl"
            import sys
            original_argv = sys.argv
            try:
                sys.argv = [
                    "kvcache",
                    "generate-trace",
                    "--sessions", "3",
                    "--turns", "2",
                    "--shared-prefix-blocks", "4",
                    "--new-blocks-per-turn", "2",
                    "--seed", "42",
                    "--output", str(output_path),
                ]
                result = main()
            finally:
                sys.argv = original_argv

            self.assertEqual(result, 0)
            self.assertTrue(output_path.exists())

            # Verify JSONL content
            lines = output_path.read_text().strip().split("\n")
            self.assertEqual(len(lines), 6)  # 3 sessions * 2 turns

            for line in lines:
                record = json.loads(line)
                self.assertIn("request_id", record)
                self.assertIn("hash_ids", record)
                self.assertIn("chat_id", record)
                self.assertIn("turn", record)
                self.assertIn("input_length", record)

    def test_correct_record_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "trace.jsonl"
            import sys
            original_argv = sys.argv
            try:
                sys.argv = [
                    "kvcache",
                    "generate-trace",
                    "--sessions", "5",
                    "--turns", "4",
                    "--shared-prefix-blocks", "2",
                    "--new-blocks-per-turn", "3",
                    "--output", str(output_path),
                ]
                result = main()
            finally:
                sys.argv = original_argv

            self.assertEqual(result, 0)
            lines = output_path.read_text().strip().split("\n")
            self.assertEqual(len(lines), 20)  # 5 * 4

    def test_prefix_diversity_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "trace.jsonl"
            import sys
            original_argv = sys.argv
            try:
                sys.argv = [
                    "kvcache",
                    "generate-trace",
                    "--sessions", "4",
                    "--turns", "1",
                    "--shared-prefix-blocks", "3",
                    "--new-blocks-per-turn", "1",
                    "--prefix-diversity", "0.0",
                    "--seed", "10",
                    "--output", str(output_path),
                ]
                result = main()
            finally:
                sys.argv = original_argv

            self.assertEqual(result, 0)
            lines = output_path.read_text().strip().split("\n")
            records = [json.loads(line) for line in lines]

            # All sessions should share the same prefix
            prefixes = set()
            for r in records:
                prefixes.add(tuple(r["hash_ids"][:3]))
            self.assertEqual(len(prefixes), 1)

    def test_block_size_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "trace.jsonl"
            import sys
            original_argv = sys.argv
            try:
                sys.argv = [
                    "kvcache",
                    "generate-trace",
                    "--sessions", "2",
                    "--turns", "1",
                    "--shared-prefix-blocks", "2",
                    "--new-blocks-per-turn", "1",
                    "--block-size", "32",
                    "--seed", "42",
                    "--output", str(output_path),
                ]
                result = main()
            finally:
                sys.argv = original_argv

            self.assertEqual(result, 0)
            lines = output_path.read_text().strip().split("\n")
            record = json.loads(lines[0])
            # 2 prefix + 1 new = 3 blocks * 32 = 96
            self.assertEqual(record["input_length"], 3 * 32)

    def test_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "subdir" / "nested" / "trace.jsonl"
            import sys
            original_argv = sys.argv
            try:
                sys.argv = [
                    "kvcache",
                    "generate-trace",
                    "--sessions", "1",
                    "--turns", "1",
                    "--shared-prefix-blocks", "1",
                    "--new-blocks-per-turn", "1",
                    "--output", str(output_path),
                ]
                result = main()
            finally:
                sys.argv = original_argv

            self.assertEqual(result, 0)
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
