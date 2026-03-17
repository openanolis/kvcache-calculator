from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from kvcache_upper_bound.core.models import RequestRecord
from kvcache_upper_bound.ingest.normalizer import build_effective_requests
from kvcache_upper_bound.oracle.capacity import _build_access_trace
from kvcache_upper_bound.reporting.buckets import BucketAnalysisConfig, BucketAnalysisResult
from kvcache_upper_bound.verification.reference import (
    ExhaustiveVerificationSummary,
    StrictPrefixCounterexample,
    analyze_content_upper_bound_naive,
    find_smallest_strict_prefix_gap_counterexample,
    verify_exhaustive_small_cases,
)


@dataclass(frozen=True)
class BucketAuditRow:
    bucket_label: str
    request_count: int
    sample_request_count: int
    sample_content_fast_equals_naive: bool | None
    total_blocks: int
    content_hit_blocks: int
    relaxed_hbm_hit_blocks: int
    unique_prefix_nodes: int
    max_request_blocks: int
    resident_block_capacity: int
    hbm_equals_content: bool | None


@dataclass(frozen=True)
class BucketAuditReport:
    trace: str
    config: str
    model_kv_bytes_per_token: int
    model_kv_bytes_per_block: int
    exhaustive_reference: ExhaustiveVerificationSummary
    strict_prefix_counterexample: StrictPrefixCounterexample
    rows: list[BucketAuditRow]


def build_bucket_audit_report(
    records: Iterable[RequestRecord],
    config: BucketAnalysisConfig,
    analysis_result: BucketAnalysisResult,
    trace: str,
    config_path: str,
    sample_request_limit: int = 256,
) -> BucketAuditReport:
    record_list = list(records)
    rows: list[BucketAuditRow] = []

    for row in analysis_result.rows:
        deployment = next(
            deployment
            for deployment in config.bucket_deployments
            if deployment.label == row.bucket_label
        )
        bucket_records = [record for record in record_list if deployment.contains(record.input_length)]
        window_tokens = deployment.resolved_window_tokens(bucket_records)
        normalized = build_effective_requests(
            bucket_records,
            window_tokens=window_tokens,
            scope=config.scope,
            block_size=config.block_size,
        )
        access_trace = _build_access_trace(normalized.requests)

        sample_requests = normalized.requests[:sample_request_limit]
        if sample_requests:
            from kvcache_upper_bound.oracle import analyze_content_upper_bound

            fast = analyze_content_upper_bound(
                sample_requests,
                model_profile=config.model_profile,
                block_size=config.block_size,
            )
            slow = analyze_content_upper_bound_naive(
                sample_requests,
                model_profile=config.model_profile,
                block_size=config.block_size,
            )
            sample_matches = _request_hit_blocks(fast) == _request_hit_blocks(slow)
        else:
            sample_matches = True

        detail = analysis_result.details[row.bucket_label]
        has_requests = row.request_count > 0
        rows.append(
            BucketAuditRow(
                bucket_label=row.bucket_label,
                request_count=row.request_count,
                sample_request_count=len(sample_requests),
                sample_content_fast_equals_naive=sample_matches if has_requests else None,
                total_blocks=detail.content_result.summary.total_blocks,
                content_hit_blocks=detail.content_result.summary.hit_blocks,
                relaxed_hbm_hit_blocks=detail.hbm_capacity_result.summary.hit_blocks,
                unique_prefix_nodes=access_trace.unique_node_count,
                max_request_blocks=max((request.effective_blocks for request in normalized.requests), default=0),
                resident_block_capacity=detail.hbm_capacity_result.summary.resident_block_capacity,
                hbm_equals_content=(
                    detail.hbm_capacity_result.summary.hit_blocks
                    == detail.content_result.summary.hit_blocks
                )
                if has_requests
                else None,
            )
        )

    return BucketAuditReport(
        trace=trace,
        config=config_path,
        model_kv_bytes_per_token=config.model_profile.kv_bytes_per_token(),
        model_kv_bytes_per_block=config.model_profile.kv_bytes_per_block(),
        exhaustive_reference=verify_exhaustive_small_cases(),
        strict_prefix_counterexample=find_smallest_strict_prefix_gap_counterexample(),
        rows=rows,
    )


def write_bucket_audit_outputs(report: BucketAuditReport, output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "correctness_report.json").write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "correctness_report.md").write_text(
        _render_bucket_audit_markdown(report),
        encoding="utf-8",
    )


def _render_bucket_audit_markdown(report: BucketAuditReport) -> str:
    lines = [
        "# Correctness Report",
        "",
        f"- trace: `{report.trace}`",
        f"- config: `{report.config}`",
        f"- kv bytes per token: `{report.model_kv_bytes_per_token}`",
        f"- kv bytes per block: `{report.model_kv_bytes_per_block}`",
        "",
        "## Exhaustive Reference",
        "",
        f"- content cases verified: `{report.exhaustive_reference.content_case_count}`",
        f"- relaxed capacity cases verified: `{report.exhaustive_reference.relaxed_capacity_case_count}`",
        "",
        "## Strict Prefix Gap",
        "",
        f"- resident block capacity: `{report.strict_prefix_counterexample.resident_block_capacity}`",
        f"- requests: `{report.strict_prefix_counterexample.requests}`",
        f"- content hit blocks: `{report.strict_prefix_counterexample.content_hit_blocks}`",
        f"- relaxed capacity hit blocks: `{report.strict_prefix_counterexample.relaxed_capacity_hit_blocks}`",
        f"- strict prefix hit blocks: `{report.strict_prefix_counterexample.strict_prefix_hit_blocks}`",
        "",
        "## Bucket Audit",
        "",
        "| bucket | requests | sample | sample fast==naive | total blocks | content hits | relaxed HBM hits | unique nodes | max req blocks | resident blocks | hbm==content |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    for row in report.rows:
        lines.append(
            "| "
            f"{row.bucket_label} | "
            f"{row.request_count} | "
            f"{row.sample_request_count} | "
            f"{_bool_text(row.sample_content_fast_equals_naive)} | "
            f"{row.total_blocks} | "
            f"{row.content_hit_blocks} | "
            f"{row.relaxed_hbm_hit_blocks} | "
            f"{row.unique_prefix_nodes} | "
            f"{row.max_request_blocks} | "
            f"{row.resident_block_capacity} | "
            f"{_bool_text(row.hbm_equals_content)} |"
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `content hits` is exact for the defined `strict_prefix_window` semantics.",
            "- `relaxed HBM hits` is an offline Belady upper bound over block access events, not a strict-prefix optimal oracle.",
            "- `hbm==content` means the relaxed space model did not lower the content ceiling on that bucket; it does not, by itself, prove strict-prefix optimality.",
            f"- capacities are counted in blocks where `1 block = {report.model_kv_bytes_per_block} bytes` in this report's model math.",
            "",
        ]
    )
    return "\n".join(lines)


def _request_hit_blocks(result: object) -> list[int]:
    return [metric.hit_blocks for metric in result.request_metrics]


def _bool_text(value: bool | None) -> str:
    if value is None:
        return ""
    return "yes" if value else "no"
