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
from kvcache_upper_bound.verification import (
    build_bucket_audit_report,
    write_bucket_audit_outputs,
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
    audit_parser = subparsers.add_parser(
        "audit-buckets",
        help="Generate correctness and trace-shape audits for a bucket analysis config",
    )
    audit_parser.add_argument("--trace", required=True, help="Local JSONL path or http(s) URL")
    audit_parser.add_argument("--config", required=True, help="Bucket analysis JSON config")
    audit_parser.add_argument("--output-dir", required=True, help="Directory for CSV/JSON outputs")
    audit_parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="Optional cap for quick iteration",
    )
    audit_parser.add_argument(
        "--sample-request-limit",
        type=int,
        default=256,
        help="Prefix sample size for fast-vs-naive content cross-checks",
    )

    args = parser.parse_args()
    if args.command == "analyze-buckets":
        return _run_analyze_buckets(args)
    if args.command == "audit-buckets":
        return _run_audit_buckets(args)
    raise ValueError(f"unsupported command: {args.command}")


def _run_analyze_buckets(args: argparse.Namespace) -> int:
    config = load_bucket_analysis_config(args.config)
    trace_result = load_request_records(args.trace, max_records=args.max_records)
    analysis_result = analyze_bucket_deployments(trace_result.records, config)
    output_dir = Path(args.output_dir)
    write_bucket_outputs(analysis_result, output_dir)

    summary_payload = _build_analysis_metadata_payload(
        trace=args.trace,
        config_path=args.config,
        output_dir=output_dir,
        trace_result=trace_result,
        analysis_result=analysis_result,
    )
    _write_metadata_file(output_dir, summary_payload)
    print(json.dumps(summary_payload, ensure_ascii=False, indent=2))
    return 0


def _run_audit_buckets(args: argparse.Namespace) -> int:
    config = load_bucket_analysis_config(args.config)
    trace_result = load_request_records(args.trace, max_records=args.max_records)
    analysis_result = analyze_bucket_deployments(trace_result.records, config)
    output_dir = Path(args.output_dir)
    write_bucket_outputs(analysis_result, output_dir)
    metadata_payload = _build_analysis_metadata_payload(
        trace=args.trace,
        config_path=args.config,
        output_dir=output_dir,
        trace_result=trace_result,
        analysis_result=analysis_result,
    )
    _write_metadata_file(output_dir, metadata_payload)

    audit_report = build_bucket_audit_report(
        trace_result.records,
        config=config,
        analysis_result=analysis_result,
        trace=args.trace,
        config_path=str(Path(args.config).resolve()),
        sample_request_limit=args.sample_request_limit,
    )
    write_bucket_audit_outputs(audit_report, output_dir)

    payload = {
        "trace": args.trace,
        "config": str(Path(args.config).resolve()),
        "output_dir": str(output_dir.resolve()),
        "loaded_records": trace_result.stats.loaded_records,
        "sample_request_limit": args.sample_request_limit,
        "content_case_count": audit_report.exhaustive_reference.content_case_count,
        "relaxed_capacity_case_count": audit_report.exhaustive_reference.relaxed_capacity_case_count,
        "strict_prefix_case_count": audit_report.exhaustive_reference.strict_prefix_case_count,
        "relaxed_equals_strict_on_verified_cases": audit_report.exhaustive_reference.relaxed_equals_strict_on_verified_cases,
        "replay_equals_strict_on_verified_cases": audit_report.exhaustive_reference.replay_equals_strict_on_verified_cases,
        "strict_prefix_counterexample": None
        if audit_report.strict_prefix_counterexample is None
        else {
            "requests": audit_report.strict_prefix_counterexample.requests,
            "resident_block_capacity": audit_report.strict_prefix_counterexample.resident_block_capacity,
            "content_hit_blocks": audit_report.strict_prefix_counterexample.content_hit_blocks,
            "relaxed_capacity_hit_blocks": audit_report.strict_prefix_counterexample.relaxed_capacity_hit_blocks,
            "strict_prefix_hit_blocks": audit_report.strict_prefix_counterexample.strict_prefix_hit_blocks,
        },
        "strict_prefix_replay_gap_counterexample": None
        if audit_report.strict_prefix_replay_gap_counterexample is None
        else {
            "requests": audit_report.strict_prefix_replay_gap_counterexample.requests,
            "resident_block_capacity": audit_report.strict_prefix_replay_gap_counterexample.resident_block_capacity,
            "content_hit_blocks": audit_report.strict_prefix_replay_gap_counterexample.content_hit_blocks,
            "relaxed_capacity_hit_blocks": audit_report.strict_prefix_replay_gap_counterexample.relaxed_capacity_hit_blocks,
            "strict_prefix_replay_hit_blocks": audit_report.strict_prefix_replay_gap_counterexample.strict_prefix_replay_hit_blocks,
            "strict_prefix_hit_blocks": audit_report.strict_prefix_replay_gap_counterexample.strict_prefix_hit_blocks,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _build_analysis_metadata_payload(
    trace: str,
    config_path: str,
    output_dir: Path,
    trace_result: object,
    analysis_result: object,
) -> dict[str, object]:
    return {
        "trace": trace,
        "config": str(Path(config_path).resolve()),
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
                "hbm_relaxed_upper_bound_hit_rate": row.hbm_relaxed_upper_bound_hit_rate,
                "hbm_strict_prefix_replay_hit_rate": row.hbm_strict_prefix_replay_hit_rate,
                "hbm_strict_prefix_hit_rate": row.hbm_strict_prefix_hit_rate,
                "hbm_strict_prefix_proof_source": row.hbm_strict_prefix_proof_source,
                "extra_tier_relaxed_upper_bound_hit_rates": row.extra_tier_relaxed_upper_bound_hit_rates,
                "extra_tier_strict_prefix_replay_hit_rates": row.extra_tier_strict_prefix_replay_hit_rates,
                "extra_tier_strict_prefix_hit_rates": row.extra_tier_strict_prefix_hit_rates,
                "extra_tier_strict_prefix_proof_sources": row.extra_tier_strict_prefix_proof_sources,
                "request_count": row.request_count,
            }
            for row in analysis_result.rows
        ],
    }


def _write_metadata_file(output_dir: Path, payload: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metadata.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
