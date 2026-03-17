from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvcache_upper_bound.ingest import load_request_records
from kvcache_upper_bound.reporting import (
    analyze_bucket_deployments,
    load_bucket_analysis_config,
    write_bucket_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="KVCache upper bound oracle")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bucket_parser = subparsers.add_parser(
        "analyze-buckets",
        help="Analyze bucketed KVCache upper bounds under HBM and extended capacity budgets",
    )
    bucket_parser.add_argument("--trace", required=True, help="Local JSONL path or http(s) URL")
    bucket_parser.add_argument("--config", required=True, help="Bucket analysis JSON config")
    bucket_parser.add_argument("--output-dir", required=True, help="Directory for CSV/JSON outputs")
    bucket_parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="Optional cap for quick iteration",
    )

    args = parser.parse_args()
    if args.command == "analyze-buckets":
        return _run_analyze_buckets(args)
    raise ValueError(f"unsupported command: {args.command}")


def _run_analyze_buckets(args: argparse.Namespace) -> int:
    config = load_bucket_analysis_config(args.config)
    trace_result = load_request_records(args.trace, max_records=args.max_records)
    analysis_result = analyze_bucket_deployments(trace_result.records, config)
    output_dir = Path(args.output_dir)
    write_bucket_outputs(analysis_result, output_dir)

    summary_payload = {
        "trace": args.trace,
        "config": str(Path(args.config).resolve()),
        "output_dir": str(output_dir.resolve()),
        "loaded_records": trace_result.stats.loaded_records,
        "skipped_records": trace_result.stats.skipped_records,
        "total_lines": trace_result.stats.total_lines,
        "rows": [
            {
                "bucket_label": row.bucket_label,
                "machine_count": row.machine_count,
                "machine_spec": row.machine_spec,
                "total_tps": row.total_tps,
                "hbm_kv_total_gb": row.hbm_kv_total_gb,
                "extreme_hit_rate": row.extreme_hit_rate,
                "actual_hit_rate": row.actual_hit_rate,
                "hbm_space_hit_rate": row.hbm_space_hit_rate,
                "extra_tier_hit_rates": row.extra_tier_hit_rates,
                "request_count": row.request_count,
            }
            for row in analysis_result.rows
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metadata.json").write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary_payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
