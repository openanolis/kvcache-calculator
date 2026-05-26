#!/usr/bin/env python3
"""Generate test vectors for JS parity validation.

Requires Python 3.11+ (same as the main package).
Run: python3 scripts/generate_test_vectors.py

Outputs: tests/test_vectors_heuristic.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kvcache_upper_bound.heuristic import (
    analyze_multi_agent_heuristic,
    load_multi_agent_heuristic_config,
)


def extract_vector(config_path: str, preset_name: str) -> dict:
    config = load_multi_agent_heuristic_config(config_path)
    result = analyze_multi_agent_heuristic(config)

    summary = result.scenario_summaries[0]
    tier_rows = [
        {
            "tier_label": row.tier_label,
            "total_kv_gb": row.total_kv_gb,
            "total_kv_tokens": row.total_kv_tokens,
            "strict_prefix_hit_rate": row.strict_prefix_hit_rate,
            "lru_like_hit_rate": row.lru_like_hit_rate,
            "content_hit_rate": row.content_hit_rate,
            "bottleneck": row.current_bottleneck,
            "strict_tps_gain": row.strict_prefix_tps_gain,
            "lru_tps_gain": row.lru_like_tps_gain,
            "strict_estimated_total_tps": row.strict_prefix_estimated_total_tps,
            "lru_estimated_total_tps": row.lru_like_estimated_total_tps,
            "strict_cluster_capacity_tps": row.strict_prefix_current_cluster_capacity_tps,
            "strict_min_cards": row.strict_prefix_min_card_count_for_target_total_tps,
            "strict_min_machines": row.strict_prefix_min_machine_count_for_target_total_tps,
            "lru_cluster_capacity_tps": row.lru_like_current_cluster_capacity_tps,
            "lru_min_cards": row.lru_like_min_card_count_for_target_total_tps,
            "lru_min_machines": row.lru_like_min_machine_count_for_target_total_tps,
        }
        for row in result.tier_rows
    ]

    return {
        "name": preset_name,
        "config_path": config_path,
        "summary": {
            "content_hit_rate": summary.content_hit_rate,
            "average_request_tokens": summary.average_request_tokens,
            "total_working_set_tokens": summary.total_working_set_tokens,
            "avg_reusable_private_tokens_per_agent": summary.avg_reusable_private_tokens_per_agent,
            "hbm_kv_gb_per_card": summary.hbm_kv_gb_per_card,
            "strict_prefix_saturation_capacity_gb": summary.strict_prefix_saturation_capacity_gb,
            "lru_like_saturation_capacity_gb": summary.lru_like_saturation_capacity_gb,
            "hbm_strict_prefix_hit_rate": summary.hbm_strict_prefix_hit_rate,
            "hbm_lru_like_hit_rate": summary.hbm_lru_like_hit_rate,
        },
        "tier_rows": tier_rows,
    }


def main():
    configs = [
        ("configs/public_multi_agent_qwen3_5_27b.json", "qwen3-27b-8xh20"),
        ("configs/public_multi_agent_qwen3_5_27b_1x1_h20.json", "qwen3-27b-1xh20"),
    ]

    vectors = []
    for config_path, name in configs:
        print(f"Generating vector: {name} ({config_path})")
        vectors.append(extract_vector(config_path, name))

    output_path = Path(__file__).resolve().parent.parent / "tests" / "test_vectors_heuristic.json"
    output_path.write_text(json.dumps(vectors, indent=2) + "\n")
    print(f"\nWritten {len(vectors)} test vectors to {output_path}")


if __name__ == "__main__":
    main()
