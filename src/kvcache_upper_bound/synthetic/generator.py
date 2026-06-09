"""Parametric synthetic trace generator.

Generates JSONL-compatible trace records that model multi-session,
multi-turn conversations with configurable prefix sharing.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from typing import List


@dataclass
class SyntheticTraceConfig:
    """Configuration for synthetic trace generation."""

    num_sessions: int
    turns_per_session: int
    shared_prefix_blocks: int
    avg_new_blocks_per_turn: int
    block_size: int = 16
    prefix_diversity: float = 0.3
    session_interleave: bool = True
    seed: int | None = None


def _block_id(label: str, idx: int) -> str:
    """Generate a deterministic block ID using SHA-256."""
    return hashlib.sha256(f"{label}-{idx}".encode()).hexdigest()[:16]


def generate_synthetic_trace(config: SyntheticTraceConfig) -> List[dict]:
    """Generate a synthetic trace from the given configuration.

    Returns a list of JSONL-compatible records, each representing
    a single request in a multi-turn conversation.
    """
    rng = random.Random(config.seed)

    # Determine prefix groups: groups = max(1, floor(diversity * num_sessions))
    num_groups = max(1, math.floor(config.prefix_diversity * config.num_sessions))

    # Assign sessions to prefix groups
    session_groups: List[int] = []
    for i in range(config.num_sessions):
        session_groups.append(i % num_groups)

    # Pre-generate shared prefix block IDs for each group
    group_prefixes: List[List[str]] = []
    for g in range(num_groups):
        prefix_ids = [
            _block_id(f"prefix-{g}", idx)
            for idx in range(config.shared_prefix_blocks)
        ]
        group_prefixes.append(prefix_ids)

    # Build request schedule
    # If session_interleave is True, interleave turns from different sessions
    # Otherwise, complete each session sequentially
    if config.session_interleave:
        # Round-robin across sessions for each turn
        schedule: List[tuple] = []  # (session_idx, turn)
        for turn in range(config.turns_per_session):
            session_order = list(range(config.num_sessions))
            rng.shuffle(session_order)
            for sid in session_order:
                schedule.append((sid, turn))
    else:
        schedule = []
        for sid in range(config.num_sessions):
            for turn in range(config.turns_per_session):
                schedule.append((sid, turn))

    # Track per-session accumulated private blocks
    session_private_blocks: List[List[str]] = [[] for _ in range(config.num_sessions)]

    records: List[dict] = []
    timestamp = 1000  # Start timestamp in ms

    for request_idx, (session_id, turn) in enumerate(schedule):
        group_id = session_groups[session_id]
        prefix_ids = group_prefixes[group_id]

        # Generate new unique blocks for this turn
        new_blocks = [
            _block_id(f"session-{session_id}-turn-{turn}", idx)
            for idx in range(config.avg_new_blocks_per_turn)
        ]

        # The full hash_ids for this request:
        # prefix blocks + accumulated private blocks + new blocks
        accumulated_private = list(session_private_blocks[session_id])
        hash_ids = prefix_ids + accumulated_private + new_blocks

        # Update accumulated private blocks for next turn
        session_private_blocks[session_id].extend(new_blocks)

        # Compute token lengths
        input_length = len(hash_ids) * config.block_size
        output_length = config.block_size  # Minimal output per turn

        record = {
            "request_id": f"req-{request_idx:06d}",
            "chat_id": f"session-{session_id}",
            "parent_chat_id": f"session-{session_id}" if turn > 0 else None,
            "turn": turn + 1,
            "type": "text",
            "timestamp": timestamp,
            "input_length": input_length,
            "output_length": output_length,
            "hash_ids": hash_ids,
        }
        records.append(record)
        timestamp += rng.randint(10, 100)

    return records
