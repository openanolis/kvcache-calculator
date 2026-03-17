from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.ingest import load_request_records


class TraceLoaderTest(unittest.TestCase):
    def test_load_request_records_parses_and_sorts_by_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_path = Path(tmpdir) / "trace.jsonl"
            trace_path.write_text(
                "\n".join(
                    [
                        '{"chat_id":"c2","turn":2,"type":"text","timestamp":1710000002,"input_length":18,"output_length":3,"hash_ids":["b1","b2"]}',
                        '{"chat_id":"c1","turn":1,"type":"text","timestamp":"2024-03-09T16:00:00+00:00","input_length":8,"output_length":2,"hash_ids":["a1"]}',
                    ]
                ),
                encoding="utf-8",
            )

            result = load_request_records(trace_path)

        self.assertEqual(result.stats.total_lines, 2)
        self.assertEqual(result.stats.loaded_records, 2)
        self.assertEqual(result.stats.skipped_records, 0)
        self.assertEqual([record.chat_id for record in result.records], ["c1", "c2"])
        self.assertEqual(result.records[0].timestamp_ms, 1710000000000)
        self.assertEqual(result.records[1].request_id, "req-00000000")

    def test_load_request_records_skips_invalid_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_path = Path(tmpdir) / "trace.jsonl"
            trace_path.write_text(
                "\n".join(
                    [
                        '{"chat_id":"ok","turn":1,"type":"text","timestamp":1710000000,"input_length":3,"output_length":1,"hash_ids":["x"]}',
                        '{"chat_id":"bad","turn":1}',
                        "not-json",
                    ]
                ),
                encoding="utf-8",
            )

            result = load_request_records(trace_path)

        self.assertEqual(result.stats.total_lines, 3)
        self.assertEqual(result.stats.loaded_records, 1)
        self.assertEqual(result.stats.skipped_records, 2)
        self.assertEqual([record.chat_id for record in result.records], ["ok"])

    def test_load_request_records_supports_relative_second_timestamps_and_root_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trace_path = Path(tmpdir) / "trace.jsonl"
            trace_path.write_text(
                '{"chat_id":0,"parent_chat_id":-1,"turn":1,"type":"text","timestamp":61.114,"input_length":17,"output_length":1,"hash_ids":[1,2]}',
                encoding="utf-8",
            )

            result = load_request_records(trace_path)

        self.assertEqual(result.records[0].timestamp_ms, 61114)
        self.assertIsNone(result.records[0].parent_chat_id)


if __name__ == "__main__":
    unittest.main()
