from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from kvcache_upper_bound.heuristic import (
    CalibrationResult,
    HeuristicAnalysisConfig,
    HeuristicAnalysisResult,
    HeuristicReportContext,
    analyze_multi_agent_heuristic,
    build_calibration_grid_from_ranges,
    build_multi_agent_input_summaries,
    build_trace_structure_recommendation,
    build_trace_calibration_target,
    calibrate_multi_agent_parameters,
    load_multi_agent_heuristic_config,
    write_calibration_outputs,
    write_multi_agent_outputs,
    write_multi_agent_report_outputs,
)
from kvcache_upper_bound.ingest import load_request_records
from kvcache_upper_bound.reporting import (
    analyze_bucket_deployments,
    build_bucket_input_summaries,
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
    heuristic_parser = subparsers.add_parser(
        "estimate-multi-agent",
        help="Estimate KVCache hit ceilings without trace using a multi-agent heuristic model",
    )
    heuristic_parser.add_argument(
        "--config",
        required=True,
        help="Trace-free multi-agent heuristic JSON config",
    )
    heuristic_parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for CSV/JSON outputs",
    )
    calibrate_parser = subparsers.add_parser(
        "calibrate-multi-agent",
        help="Back-calibrate zipf_s and lru_like against a small trace sample",
    )
    calibrate_parser.add_argument(
        "--trace",
        required=True,
        help="Local JSONL path or http(s) URL used as calibration sample",
    )
    calibrate_parser.add_argument(
        "--bucket-config",
        required=True,
        help="Bucket analysis JSON config used to build the exact trace target",
    )
    calibrate_parser.add_argument(
        "--heuristic-config",
        required=True,
        help="Trace-free heuristic JSON config used as the structural template",
    )
    calibrate_parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for calibration outputs",
    )
    calibrate_parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="Optional cap for quick calibration iteration",
    )
    calibrate_parser.add_argument("--zipf-s-min", type=float, default=None)
    calibrate_parser.add_argument("--zipf-s-max", type=float, default=None)
    calibrate_parser.add_argument("--zipf-s-step", type=float, default=None)
    calibrate_parser.add_argument("--lru-like-min", type=float, default=None)
    calibrate_parser.add_argument("--lru-like-max", type=float, default=None)
    calibrate_parser.add_argument("--lru-like-step", type=float, default=None)
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
    if args.command == "estimate-multi-agent":
        return _run_estimate_multi_agent(args)
    if args.command == "calibrate-multi-agent":
        return _run_calibrate_multi_agent(args)
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


def _run_estimate_multi_agent(args: argparse.Namespace) -> int:
    config = load_multi_agent_heuristic_config(args.config)
    analysis_result = analyze_multi_agent_heuristic(config)
    output_dir = Path(args.output_dir)
    write_multi_agent_outputs(config, analysis_result, output_dir)
    write_multi_agent_report_outputs(
        config=config,
        result=analysis_result,
        output_dir=output_dir,
        context=HeuristicReportContext(
            mode="multi_agent_heuristic",
            config_path=str(Path(args.config).resolve()),
            output_dir=str(output_dir.resolve()),
        ),
    )

    payload = _build_heuristic_metadata_payload(
        config_path=args.config,
        output_dir=output_dir,
        config=config,
        analysis_result=analysis_result,
    )
    _write_metadata_file(output_dir, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_calibrate_multi_agent(args: argparse.Namespace) -> int:
    bucket_config = load_bucket_analysis_config(args.bucket_config)
    heuristic_config = load_multi_agent_heuristic_config(args.heuristic_config)
    trace_result = load_request_records(args.trace, max_records=args.max_records)
    bucket_analysis = analyze_bucket_deployments(trace_result.records, bucket_config)
    calibration_target = build_trace_calibration_target(bucket_analysis)
    calibration_grid = None
    if any(
        value is not None
        for value in (
            args.zipf_s_min,
            args.zipf_s_max,
            args.zipf_s_step,
            args.lru_like_min,
            args.lru_like_max,
            args.lru_like_step,
        )
    ):
        calibration_grid = build_calibration_grid_from_ranges(
            curve_mode=heuristic_config.heuristic.curve_shape.mode,
            zipf_s_min=(
                heuristic_config.heuristic.curve_shape.zipf_s
                if args.zipf_s_min is None
                else args.zipf_s_min
            ),
            zipf_s_max=(
                heuristic_config.heuristic.curve_shape.zipf_s
                if args.zipf_s_max is None
                else args.zipf_s_max
            ),
            zipf_s_step=0.05 if args.zipf_s_step is None else args.zipf_s_step,
            lru_like_min=(
                heuristic_config.heuristic.policy_efficiency.lru_like
                if args.lru_like_min is None
                else args.lru_like_min
            ),
            lru_like_max=(
                heuristic_config.heuristic.policy_efficiency.lru_like
                if args.lru_like_max is None
                else args.lru_like_max
            ),
            lru_like_step=0.02 if args.lru_like_step is None else args.lru_like_step,
        )
    calibration_result = calibrate_multi_agent_parameters(
        base_config=heuristic_config,
        target=calibration_target,
        grid=calibration_grid,
    )
    structure_recommendation = build_trace_structure_recommendation(
        heuristic_config,
        records=trace_result.records,
        block_size=bucket_config.block_size,
        observed_content_hit_rate=calibration_target.content_hit_rate,
    )
    calibration_result = replace(
        calibration_result,
        structure_recommendation=structure_recommendation,
    )

    output_dir = Path(args.output_dir)
    write_multi_agent_outputs(
        calibration_result.calibrated_config,
        calibration_result.calibrated_analysis,
        output_dir,
    )
    write_calibration_outputs(calibration_result, output_dir)
    write_multi_agent_report_outputs(
        config=calibration_result.calibrated_config,
        result=calibration_result.calibrated_analysis,
        output_dir=output_dir,
        context=HeuristicReportContext(
            mode="multi_agent_calibration",
            config_path=str(Path(args.heuristic_config).resolve()),
            output_dir=str(output_dir.resolve()),
            trace=args.trace,
            bucket_config_path=str(Path(args.bucket_config).resolve()),
            loaded_records=trace_result.stats.loaded_records,
            max_records=args.max_records,
        ),
        calibration=calibration_result,
    )

    payload = _build_calibration_metadata_payload(
        trace=args.trace,
        bucket_config_path=args.bucket_config,
        heuristic_config_path=args.heuristic_config,
        output_dir=output_dir,
        trace_result=trace_result,
        calibration_result=calibration_result,
    )
    _write_metadata_file(output_dir, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
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
    normalized_bucket_inputs = build_bucket_input_summaries(analysis_result)
    return {
        "trace": trace,
        "config": str(Path(config_path).resolve()),
        "output_dir": str(output_dir.resolve()),
        "loaded_records": trace_result.stats.loaded_records,
        "skipped_records": trace_result.stats.skipped_records,
        "total_lines": trace_result.stats.total_lines,
        "prefill_savings_alpha": None
        if not analysis_result.rows
        else analysis_result.rows[0].prefill_savings_alpha,
        "normalized_bucket_inputs": [asdict(item) for item in normalized_bucket_inputs],
        "rows": [asdict(row) for row in analysis_result.rows],
    }


def _build_heuristic_metadata_payload(
    *,
    config_path: str,
    output_dir: Path,
    config: HeuristicAnalysisConfig,
    analysis_result: HeuristicAnalysisResult,
) -> dict[str, object]:
    normalized_inputs = build_multi_agent_input_summaries(config, analysis_result)
    return {
        "mode": "multi_agent_heuristic",
        "config": str(Path(config_path).resolve()),
        "output_dir": str(output_dir.resolve()),
        "prefill_savings_alpha": config.prefill_savings_alpha,
        "model_profile": asdict(config.model_profile),
        "heuristic_multi_agent": asdict(config.heuristic),
        "normalized_heuristic_inputs": [asdict(item) for item in normalized_inputs],
        "scenario_summaries": [asdict(row) for row in analysis_result.scenario_summaries],
        "tier_rows": [asdict(row) for row in analysis_result.tier_rows],
    }


def _build_calibration_metadata_payload(
    *,
    trace: str,
    bucket_config_path: str,
    heuristic_config_path: str,
    output_dir: Path,
    trace_result: object,
    calibration_result: CalibrationResult,
) -> dict[str, object]:
    normalized_inputs = build_multi_agent_input_summaries(
        calibration_result.calibrated_config,
        calibration_result.calibrated_analysis,
    )
    return {
        "mode": "multi_agent_calibration",
        "trace": trace,
        "bucket_config": str(Path(bucket_config_path).resolve()),
        "heuristic_config": str(Path(heuristic_config_path).resolve()),
        "output_dir": str(output_dir.resolve()),
        "loaded_records": trace_result.stats.loaded_records,
        "skipped_records": trace_result.stats.skipped_records,
        "total_lines": trace_result.stats.total_lines,
        "prefill_savings_alpha": calibration_result.calibrated_config.prefill_savings_alpha,
        "model_profile": asdict(calibration_result.calibrated_config.model_profile),
        "heuristic_multi_agent": asdict(calibration_result.calibrated_config.heuristic),
        "normalized_heuristic_inputs": [asdict(item) for item in normalized_inputs],
        "calibration_target": asdict(calibration_result.target),
        "calibration_grid": asdict(calibration_result.grid),
        "best_trial": asdict(calibration_result.best_trial),
        "best_tier_comparisons": [asdict(item) for item in calibration_result.best_tier_comparisons],
        "structure_recommendation": None
        if calibration_result.structure_recommendation is None
        else {
            "hints": asdict(calibration_result.structure_recommendation.hints),
            "recommended_config": asdict(
                calibration_result.structure_recommendation.recommended_config
            ),
            "recommended_analysis": {
                "scenario_summaries": [
                    asdict(row)
                    for row in calibration_result.structure_recommendation.recommended_analysis.scenario_summaries
                ],
                "tier_rows": [
                    asdict(row)
                    for row in calibration_result.structure_recommendation.recommended_analysis.tier_rows
                ],
            },
        },
        "scenario_summaries": [
            asdict(row) for row in calibration_result.calibrated_analysis.scenario_summaries
        ],
        "tier_rows": [asdict(row) for row in calibration_result.calibrated_analysis.tier_rows],
    }


def _write_metadata_file(output_dir: Path, payload: dict[str, object]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "metadata.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
