"""Tests for the parametric synthetic trace generator."""

from __future__ import annotations

import json
import unittest

from tests import _bootstrap  # noqa: F401

from kvcache_upper_bound.synthetic import SyntheticTraceConfig, generate_synthetic_trace


class SyntheticGeneratorBasicTest(unittest.TestCase):
    """Basic generation tests."""

    def test_basic_generation_record_count(self) -> None:
        config = SyntheticTraceConfig(
            num_sessions=4,
            turns_per_session=3,
            shared_prefix_blocks=2,
            avg_new_blocks_per_turn=2,
            seed=42,
        )
        records = generate_synthetic_trace(config)
        self.assertEqual(len(records), 4 * 3)

    def test_record_fields_present(self) -> None:
        config = SyntheticTraceConfig(
            num_sessions=2,
            turns_per_session=2,
            shared_prefix_blocks=1,
            avg_new_blocks_per_turn=1,
            seed=0,
        )
        records = generate_synthetic_trace(config)
        required_fields = {
            "request_id", "chat_id", "parent_chat_id", "turn",
            "type", "timestamp", "input_length", "output_length", "hash_ids",
        }
        for record in records:
            self.assertTrue(required_fields.issubset(record.keys()), f"Missing fields in {record}")

    def test_timestamps_monotonically_increase(self) -> None:
        config = SyntheticTraceConfig(
            num_sessions=3,
            turns_per_session=4,
            shared_prefix_blocks=2,
            avg_new_blocks_per_turn=2,
            seed=7,
        )
        records = generate_synthetic_trace(config)
        timestamps = [r["timestamp"] for r in records]
        for i in range(1, len(timestamps)):
            self.assertGreater(timestamps[i], timestamps[i - 1])

    def test_deterministic_with_seed(self) -> None:
        config = SyntheticTraceConfig(
            num_sessions=3,
            turns_per_session=2,
            shared_prefix_blocks=2,
            avg_new_blocks_per_turn=2,
            seed=123,
        )
        records_a = generate_synthetic_trace(config)
        records_b = generate_synthetic_trace(config)
        self.assertEqual(records_a, records_b)

    def test_input_length_matches_hash_ids(self) -> None:
        config = SyntheticTraceConfig(
            num_sessions=2,
            turns_per_session=3,
            shared_prefix_blocks=3,
            avg_new_blocks_per_turn=2,
            block_size=16,
            seed=42,
        )
        records = generate_synthetic_trace(config)
        for record in records:
            expected_length = len(record["hash_ids"]) * config.block_size
            self.assertEqual(record["input_length"], expected_length)


class SyntheticGeneratorPrefixSharingTest(unittest.TestCase):
    """Tests for prefix sharing behavior."""

    def test_zero_diversity_all_same_prefix(self) -> None:
        """With diversity=0.0, all sessions share the same prefix."""
        config = SyntheticTraceConfig(
            num_sessions=5,
            turns_per_session=2,
            shared_prefix_blocks=4,
            avg_new_blocks_per_turn=1,
            prefix_diversity=0.0,
            session_interleave=False,
            seed=42,
        )
        records = generate_synthetic_trace(config)
        # Extract prefix portion (first shared_prefix_blocks items) from each record
        prefixes = set()
        for record in records:
            prefix = tuple(record["hash_ids"][:config.shared_prefix_blocks])
            prefixes.add(prefix)
        # All sessions should share the same prefix (1 group)
        self.assertEqual(len(prefixes), 1)

    def test_high_diversity_multiple_prefixes(self) -> None:
        """With diversity=1.0, each session gets its own prefix group."""
        config = SyntheticTraceConfig(
            num_sessions=5,
            turns_per_session=2,
            shared_prefix_blocks=4,
            avg_new_blocks_per_turn=1,
            prefix_diversity=1.0,
            session_interleave=False,
            seed=42,
        )
        records = generate_synthetic_trace(config)
        # Each session should have a unique prefix
        session_prefixes = {}
        for record in records:
            sid = record["chat_id"]
            prefix = tuple(record["hash_ids"][:config.shared_prefix_blocks])
            if sid not in session_prefixes:
                session_prefixes[sid] = prefix
            else:
                # Same session should always have same prefix
                self.assertEqual(session_prefixes[sid], prefix)
        # Number of unique prefixes should equal number of sessions
        unique_prefixes = set(session_prefixes.values())
        self.assertEqual(len(unique_prefixes), 5)

    def test_medium_diversity_groups(self) -> None:
        """With diversity=0.5, sessions are split into groups."""
        config = SyntheticTraceConfig(
            num_sessions=10,
            turns_per_session=1,
            shared_prefix_blocks=2,
            avg_new_blocks_per_turn=1,
            prefix_diversity=0.5,
            session_interleave=False,
            seed=42,
        )
        records = generate_synthetic_trace(config)
        prefixes = set()
        for record in records:
            prefix = tuple(record["hash_ids"][:config.shared_prefix_blocks])
            prefixes.add(prefix)
        # groups = max(1, floor(0.5 * 10)) = 5
        self.assertEqual(len(prefixes), 5)


class SyntheticGeneratorAccumulationTest(unittest.TestCase):
    """Tests for block accumulation across turns."""

    def test_blocks_accumulate_across_turns(self) -> None:
        config = SyntheticTraceConfig(
            num_sessions=1,
            turns_per_session=3,
            shared_prefix_blocks=2,
            avg_new_blocks_per_turn=2,
            session_interleave=False,
            seed=42,
        )
        records = generate_synthetic_trace(config)
        # Turn 1: prefix(2) + new(2) = 4 blocks
        self.assertEqual(len(records[0]["hash_ids"]), 4)
        # Turn 2: prefix(2) + accumulated(2) + new(2) = 6 blocks
        self.assertEqual(len(records[1]["hash_ids"]), 6)
        # Turn 3: prefix(2) + accumulated(4) + new(2) = 8 blocks
        self.assertEqual(len(records[2]["hash_ids"]), 8)

    def test_turn_numbers_sequential(self) -> None:
        config = SyntheticTraceConfig(
            num_sessions=1,
            turns_per_session=4,
            shared_prefix_blocks=1,
            avg_new_blocks_per_turn=1,
            session_interleave=False,
            seed=42,
        )
        records = generate_synthetic_trace(config)
        for i, record in enumerate(records):
            self.assertEqual(record["turn"], i + 1)


class SyntheticGeneratorSerializationTest(unittest.TestCase):
    """Tests for JSONL serialization compatibility."""

    def test_jsonl_serializable(self) -> None:
        config = SyntheticTraceConfig(
            num_sessions=3,
            turns_per_session=2,
            shared_prefix_blocks=2,
            avg_new_blocks_per_turn=2,
            seed=42,
        )
        records = generate_synthetic_trace(config)
        # Each record should be JSON-serializable
        for record in records:
            line = json.dumps(record)
            parsed = json.loads(line)
            self.assertEqual(parsed["request_id"], record["request_id"])
            self.assertEqual(parsed["hash_ids"], record["hash_ids"])

    def test_hash_ids_are_strings(self) -> None:
        config = SyntheticTraceConfig(
            num_sessions=2,
            turns_per_session=2,
            shared_prefix_blocks=2,
            avg_new_blocks_per_turn=2,
            seed=42,
        )
        records = generate_synthetic_trace(config)
        for record in records:
            for block_id in record["hash_ids"]:
                self.assertIsInstance(block_id, str)
                self.assertEqual(len(block_id), 16)  # sha256 hex truncated to 16


if __name__ == "__main__":
    unittest.main()
