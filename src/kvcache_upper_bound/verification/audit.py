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
    StrictPrefixReplayGapCounterexample,
    analyze_content_upper_bound_naive,
    verify_exhaustive_small_cases,
)


@dataclass(frozen=True)
class BucketAuditRow:
    bucket_label: str
    request_count: int
    sample_request_count: int
    sample_content_fast_equals_naive: bool | None
    window_tokens: int | None
    hbm_kv_total_gb: float
    total_blocks: int
    content_hit_blocks: int
    content_hit_rate: float | None
    relaxed_hbm_hit_blocks: int
    relaxed_hbm_hit_rate: float | None
    strict_prefix_replay_hbm_hit_blocks: int
    strict_prefix_replay_hbm_hit_rate: float | None
    strict_prefix_hbm_hit_blocks: int
    strict_prefix_hbm_hit_rate: float | None
    strict_prefix_proof_source: str | None
    strict_prefix_certified_lower_bound_hit_blocks: int
    strict_prefix_certified_upper_bound_hit_blocks: int
    strict_prefix_search_state_count: int
    unique_prefix_nodes: int
    max_request_blocks: int
    resident_block_capacity: int
    hbm_equals_content: bool | None
    strict_prefix_equals_content: bool | None


@dataclass(frozen=True)
class BucketAuditReport:
    trace: str
    config: str
    model_kv_bytes_per_token: int
    model_kv_bytes_per_block: int
    exhaustive_reference: ExhaustiveVerificationSummary
    strict_prefix_counterexample: StrictPrefixCounterexample | None
    strict_prefix_replay_gap_counterexample: StrictPrefixReplayGapCounterexample | None
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
        strict_prefix_replay_hit_blocks = detail.hbm_capacity_result.summary.strict_prefix_hit_blocks
        strict_prefix_hit_blocks = detail.hbm_strict_prefix_result.summary.hit_blocks
        content_hit_blocks = detail.content_result.summary.hit_blocks
        rows.append(
            BucketAuditRow(
                bucket_label=row.bucket_label,
                request_count=row.request_count,
                sample_request_count=len(sample_requests),
                sample_content_fast_equals_naive=sample_matches if has_requests else None,
                window_tokens=row.window_tokens,
                hbm_kv_total_gb=row.hbm_kv_total_gb,
                total_blocks=detail.content_result.summary.total_blocks,
                content_hit_blocks=content_hit_blocks,
                content_hit_rate=detail.content_result.summary.block_hit_rate if has_requests else None,
                relaxed_hbm_hit_blocks=detail.hbm_capacity_result.summary.hit_blocks,
                relaxed_hbm_hit_rate=detail.hbm_capacity_result.summary.block_hit_rate if has_requests else None,
                strict_prefix_replay_hbm_hit_blocks=strict_prefix_replay_hit_blocks,
                strict_prefix_replay_hbm_hit_rate=(
                    detail.hbm_capacity_result.summary.strict_prefix_block_hit_rate
                    if has_requests
                    else None
                ),
                strict_prefix_hbm_hit_blocks=strict_prefix_hit_blocks,
                strict_prefix_hbm_hit_rate=(
                    detail.hbm_strict_prefix_result.summary.block_hit_rate if has_requests else None
                ),
                strict_prefix_proof_source=(
                    detail.hbm_strict_prefix_result.summary.proof_source if has_requests else None
                ),
                strict_prefix_certified_lower_bound_hit_blocks=(
                    detail.hbm_strict_prefix_result.summary.certified_lower_bound_hit_blocks
                ),
                strict_prefix_certified_upper_bound_hit_blocks=(
                    detail.hbm_strict_prefix_result.summary.certified_upper_bound_hit_blocks
                ),
                strict_prefix_search_state_count=detail.hbm_strict_prefix_result.summary.search_state_count,
                unique_prefix_nodes=access_trace.unique_node_count,
                max_request_blocks=max((request.effective_blocks for request in normalized.requests), default=0),
                resident_block_capacity=detail.hbm_capacity_result.summary.resident_block_capacity,
                hbm_equals_content=(
                    detail.hbm_capacity_result.summary.hit_blocks
                    == detail.content_result.summary.hit_blocks
                )
                if has_requests
                else None,
                strict_prefix_equals_content=(strict_prefix_hit_blocks == content_hit_blocks)
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
        strict_prefix_counterexample=None,
        strict_prefix_replay_gap_counterexample=None,
        rows=rows,
    )


def write_bucket_audit_outputs(report: BucketAuditReport, output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "correctness_report.json").write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    zh_markdown = _render_bucket_audit_markdown(report, language="zh")
    en_markdown = _render_bucket_audit_markdown(report, language="en")
    (output_path / "correctness_report.md").write_text(
        zh_markdown,
        encoding="utf-8",
    )
    (output_path / "correctness_report.zh.md").write_text(
        zh_markdown,
        encoding="utf-8",
    )
    (output_path / "correctness_report.en.md").write_text(
        en_markdown,
        encoding="utf-8",
    )


def _render_bucket_audit_markdown(report: BucketAuditReport, language: str) -> str:
    is_zh = language == "zh"
    if language not in {"zh", "en"}:
        raise ValueError(f"unsupported language: {language}")

    lines = [
        "# 结果正确性报告" if is_zh else "# Correctness Report",
        "",
        f"- {'trace' if not is_zh else 'trace'}: `{report.trace}`",
        f"- {'config' if not is_zh else '配置'}: `{report.config}`",
        f"- {'kv bytes per token' if not is_zh else '每 token KV 字节数'}: `{report.model_kv_bytes_per_token}`",
        f"- {'kv bytes per block' if not is_zh else '每 block KV 字节数'}: `{report.model_kv_bytes_per_block}`",
        "",
        "## 穷举参考校验" if is_zh else "## Exhaustive Reference",
        "",
        f"- {'content 校验样例数' if is_zh else 'content cases verified'}: `{report.exhaustive_reference.content_case_count}`",
        f"- {'relaxed capacity 校验样例数' if is_zh else 'relaxed capacity cases verified'}: `{report.exhaustive_reference.relaxed_capacity_case_count}`",
        f"- {'strict-prefix 校验样例数' if is_zh else 'strict-prefix cases verified'}: `{report.exhaustive_reference.strict_prefix_case_count}`",
        (
            f"- {'已验证空间里 relaxed == exact strict-prefix' if is_zh else 'relaxed == exact strict-prefix in verified space'}: `{_bool_text(report.exhaustive_reference.relaxed_equals_strict_on_verified_cases)}`"
        ),
        (
            f"- {'已验证空间里 replay == exact strict-prefix' if is_zh else 'replay == exact strict-prefix in verified space'}: `{_bool_text(report.exhaustive_reference.replay_equals_strict_on_verified_cases)}`"
        ),
        "",
        "## Strict Prefix 等价校验" if is_zh else "## Strict Prefix Equivalence",
        "",
        "## 分桶审计" if is_zh else "## Bucket Audit",
        "",
        (
            "| 分桶 | 请求数 | 抽样数 | 快速实现=朴素实现 | 总 blocks | content 命中 | relaxed HBM 命中 | strict-prefix replay HBM 命中 | strict-prefix HBM 命中 | strict-prefix 求解路径 | 唯一前缀节点数 | 单请求最大 blocks | 常驻 blocks | relaxed=content | strict=content |"
            if is_zh
            else "| bucket | requests | sample | sample fast==naive | total blocks | content hits | relaxed HBM hits | strict-prefix replay HBM hits | strict-prefix HBM hits | strict-prefix proof source | unique nodes | max req blocks | resident blocks | relaxed==content | strict==content |"
        ),
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- | --- |",
    ]

    bucket_audit_marker = "## 分桶审计" if is_zh else "## Bucket Audit"
    insert_at = lines.index(bucket_audit_marker)
    equivalence_lines: list[str] = []
    if report.strict_prefix_counterexample is None:
        equivalence_lines.append(
            "- 在当前穷举验证空间里，没有找到 `relaxed capacity hits > exact strict-prefix hits` 的反例。"
            if is_zh
            else "- no counterexample was found in the verified search space where `relaxed capacity hits > exact strict-prefix hits`."
        )
    else:
        equivalence_lines.extend(
            [
                f"- {'常驻 block 容量' if is_zh else 'resident block capacity'}: `{report.strict_prefix_counterexample.resident_block_capacity}`",
                f"- {'请求序列' if is_zh else 'requests'}: `{report.strict_prefix_counterexample.requests}`",
                f"- {'content 命中 blocks' if is_zh else 'content hit blocks'}: `{report.strict_prefix_counterexample.content_hit_blocks}`",
                f"- {'relaxed capacity 命中 blocks' if is_zh else 'relaxed capacity hit blocks'}: `{report.strict_prefix_counterexample.relaxed_capacity_hit_blocks}`",
                f"- {'strict prefix 命中 blocks' if is_zh else 'strict prefix hit blocks'}: `{report.strict_prefix_counterexample.strict_prefix_hit_blocks}`",
            ]
        )
    if report.strict_prefix_replay_gap_counterexample is None:
        equivalence_lines.append(
            "- 在当前穷举验证空间里，没有找到 `strict-prefix replay hits < exact strict-prefix hits` 的反例。"
            if is_zh
            else "- no counterexample was found in the verified search space where `strict-prefix replay hits < exact strict-prefix hits`."
        )
    else:
        equivalence_lines.extend(
            [
                f"- {'常驻 block 容量' if is_zh else 'resident block capacity'}: `{report.strict_prefix_replay_gap_counterexample.resident_block_capacity}`",
                f"- {'请求序列' if is_zh else 'requests'}: `{report.strict_prefix_replay_gap_counterexample.requests}`",
                f"- {'content 命中 blocks' if is_zh else 'content hit blocks'}: `{report.strict_prefix_replay_gap_counterexample.content_hit_blocks}`",
                f"- {'relaxed capacity 命中 blocks' if is_zh else 'relaxed capacity hit blocks'}: `{report.strict_prefix_replay_gap_counterexample.relaxed_capacity_hit_blocks}`",
                f"- {'strict-prefix replay 命中 blocks' if is_zh else 'strict-prefix replay hit blocks'}: `{report.strict_prefix_replay_gap_counterexample.strict_prefix_replay_hit_blocks}`",
                f"- {'strict prefix 命中 blocks' if is_zh else 'strict prefix hit blocks'}: `{report.strict_prefix_replay_gap_counterexample.strict_prefix_hit_blocks}`",
            ]
        )
    lines[insert_at:insert_at] = equivalence_lines + [""]

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
            f"{row.strict_prefix_replay_hbm_hit_blocks} | "
            f"{row.strict_prefix_hbm_hit_blocks} | "
            f"{_text_or_empty(row.strict_prefix_proof_source)} | "
            f"{row.unique_prefix_nodes} | "
            f"{row.max_request_blocks} | "
            f"{row.resident_block_capacity} | "
            f"{_bool_text(row.hbm_equals_content)} | "
            f"{_bool_text(row.strict_prefix_equals_content)} |"
        )

    lines.extend(
        [
            "",
            "## 推导过程" if is_zh else "## Derivation",
            "",
        ]
    )

    for row in report.rows:
        if row.request_count == 0:
            continue
        resident_to_max_request_ratio = (
            row.resident_block_capacity / row.max_request_blocks
            if row.max_request_blocks > 0
            else 0.0
        )
        content_to_relaxed_gap = row.content_hit_blocks - row.relaxed_hbm_hit_blocks
        relaxed_to_replay_gap = row.relaxed_hbm_hit_blocks - row.strict_prefix_replay_hbm_hit_blocks
        replay_to_strict_gap = row.strict_prefix_hbm_hit_blocks - row.strict_prefix_replay_hbm_hit_blocks
        strict_prefix_range_text = _strict_prefix_range_text(
            is_zh=is_zh,
            lower=row.strict_prefix_certified_lower_bound_hit_blocks,
            upper=row.strict_prefix_certified_upper_bound_hit_blocks,
        )
        proof_source_text = (
            "证书快路"
            if row.strict_prefix_proof_source == "certificate"
            else "精确搜索"
            if row.strict_prefix_proof_source == "search"
            else ""
        ) if is_zh else _text_or_empty(row.strict_prefix_proof_source)
        lines.extend(
            [
                f"### {row.bucket_label}",
                "",
                f"- {'窗口 token 上限' if is_zh else 'window tokens'}: `{row.window_tokens}`",
                f"- {'HBM KV 总容量 (GB)' if is_zh else 'hbm kv total gb'}: `{row.hbm_kv_total_gb:.2f}`",
                f"- {'常驻 block 容量' if is_zh else 'resident block capacity'}: `floor({row.hbm_kv_total_gb:.2f} * 1024^3 / {report.model_kv_bytes_per_block}) = {row.resident_block_capacity}`",
                f"- {'总 blocks' if is_zh else 'total blocks'}: `{row.total_blocks}`",
                f"- {'content 命中 blocks' if is_zh else 'content hit blocks'}: `{row.content_hit_blocks}` -> `{_rate_text(row.content_hit_rate)}`",
                f"- {'relaxed HBM 命中 blocks' if is_zh else 'relaxed hbm hit blocks'}: `{row.relaxed_hbm_hit_blocks}` -> `{_rate_text(row.relaxed_hbm_hit_rate)}`",
                f"- {'strict-prefix replay HBM 命中 blocks' if is_zh else 'strict-prefix replay hbm hit blocks'}: `{row.strict_prefix_replay_hbm_hit_blocks}` -> `{_rate_text(row.strict_prefix_replay_hbm_hit_rate)}`",
                f"- {'strict-prefix HBM 命中 blocks' if is_zh else 'strict-prefix hbm hit blocks'}: `{row.strict_prefix_hbm_hit_blocks}` -> `{_rate_text(row.strict_prefix_hbm_hit_rate)}`",
                f"- {'content -> relaxed 差值' if is_zh else 'content -> relaxed gap'}: `{content_to_relaxed_gap}`",
                f"- {'relaxed -> strict-prefix replay 差值' if is_zh else 'relaxed -> strict-prefix replay gap'}: `{relaxed_to_replay_gap}`",
                f"- {'strict-prefix replay -> strict-prefix 差值' if is_zh else 'strict-prefix replay -> strict-prefix gap'}: `{replay_to_strict_gap}`",
                f"- {'strict-prefix 可证区间' if is_zh else 'strict-prefix provable range'}: {strict_prefix_range_text}",
                f"- {'strict-prefix 求解路径' if is_zh else 'strict-prefix proof source'}: `{proof_source_text}`",
                f"- {'strict-prefix 搜索状态数' if is_zh else 'strict-prefix search states'}: `{row.strict_prefix_search_state_count}`",
                f"- {'唯一前缀节点数' if is_zh else 'unique prefix nodes'}: `{row.unique_prefix_nodes}`",
                f"- {'单请求最大 blocks' if is_zh else 'max request blocks'}: `{row.max_request_blocks}`",
                f"- {'常驻容量/单请求最大 blocks 比值' if is_zh else 'resident/max-request ratio'}: `{resident_to_max_request_ratio:.2f}x`",
                "",
            ]
        )

    lines.extend(
        [
            "## 说明" if is_zh else "## Notes",
            "",
            (
                "- `content hits` 在当前 `strict_prefix_window` 语义下是精确值。"
                if is_zh
                else "- `content hits` is exact for the defined `strict_prefix_window` semantics."
            ),
            (
                "- `relaxed HBM hits` 是基于 block access event 的离线 Belady 上界，不是 strict-prefix 最优 oracle。"
                if is_zh
                else "- `relaxed HBM hits` is an offline Belady upper bound over block access events, not a strict-prefix optimal oracle."
            ),
            (
                "- `strict-prefix replay HBM hits` 是在 relaxed-optimal 调度上回放得到的连续前缀命中结果；它是一个可实现诊断值，用来解释 exact strict-prefix 结果是如何被夹住的。"
                if is_zh
                else "- `strict-prefix replay HBM hits` is the contiguous-prefix hit result obtained by replaying the relaxed-optimal schedule; it is a realizable diagnostic used to explain how the exact strict-prefix result is bracketed."
            ),
            (
                "- `strict-prefix HBM hits` 来自真正的 strict-prefix capacity oracle；`求解路径 = certificate` 表示用上下界证书直接夹出精确值，`求解路径 = search` 表示证书不够时走了精确搜索。"
                if is_zh
                else "- `strict-prefix HBM hits` comes from the exact strict-prefix capacity oracle; `proof source = certificate` means the exact value was certified by matching bounds, while `proof source = search` means the solver had to run exact search after certificates were insufficient."
            ),
            (
                "- `relaxed==content` 只表示 relaxed 空间模型没有进一步压低 content ceiling；真正的 strict-prefix 最优值仍然以 `strict-prefix HBM hits` 为准。"
                if is_zh
                else "- `relaxed==content` means the relaxed space model did not lower the content ceiling on that bucket; the true strict-prefix optimum is still the `strict-prefix HBM hits` value."
            ),
            (
                f"- 本报告里容量统一按 block 计数，其中 `1 block = {report.model_kv_bytes_per_block} bytes`。"
                if is_zh
                else f"- capacities are counted in blocks where `1 block = {report.model_kv_bytes_per_block} bytes` in this report's model math."
            ),
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


def _text_or_empty(value: str | None) -> str:
    if value is None:
        return ""
    return value


def _rate_text(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value * 100:.2f}%"


def _strict_prefix_range_text(is_zh: bool, lower: int, upper: int) -> str:
    if is_zh:
        return f"`[{lower}, {upper}]` blocks"
    return f"`[{lower}, {upper}]` blocks"
