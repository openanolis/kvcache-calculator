from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from kvcache_upper_bound.reporting.table_common import format_delta_pp, format_number, format_rate

if TYPE_CHECKING:
    from .calibration import CalibrationResult
    from .multi_agent import HeuristicAnalysisConfig, HeuristicAnalysisResult


@dataclass(frozen=True)
class HeuristicReportContext:
    mode: str
    config_path: str
    output_dir: str
    trace: str | None = None
    bucket_config_path: str | None = None
    loaded_records: int | None = None
    max_records: int | None = None


def write_multi_agent_report_outputs(
    *,
    config: HeuristicAnalysisConfig,
    result: HeuristicAnalysisResult,
    output_dir: str | Path,
    context: HeuristicReportContext,
    calibration: CalibrationResult | None = None,
) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    zh_content = _render_heuristic_report_zh(
        config=config,
        result=result,
        context=context,
        calibration=calibration,
    )
    en_content = _render_heuristic_report_en(
        config=config,
        result=result,
        context=context,
        calibration=calibration,
    )
    (output_path / "heuristic_report.md").write_text(en_content, encoding="utf-8")
    (output_path / "heuristic_report.zh.md").write_text(zh_content, encoding="utf-8")
    (output_path / "heuristic_report.en.md").write_text(en_content, encoding="utf-8")


def _render_heuristic_report_zh(
    *,
    config: HeuristicAnalysisConfig,
    result: HeuristicAnalysisResult,
    context: HeuristicReportContext,
    calibration: CalibrationResult | None,
) -> str:
    heuristic = config.heuristic
    assumptions_table = _markdown_table(
        headers=("参数", "值", "说明"),
        rows=(
            ("并发 Agent 数", str(heuristic.concurrent_agents), "冷启动场景下同时活跃的 agent 数"),
            ("共享前缀 tokens", format_number(heuristic.shared_prefix_tokens), "所有 agent 共用的前缀"),
            ("每轮新增 tokens", format_number(heuristic.avg_new_tokens_per_turn), "单轮新增上下文"),
            ("平均会话轮数", str(heuristic.avg_turns_per_session), "append-only 会话深度"),
            ("私有窗口 tokens", format_number(heuristic.private_window_tokens), "单 agent 私有上下文窗口"),
            ("曲线模型", heuristic.curve_shape.mode, "linear / power_law_fit / zipf_harmonic"),
            ("Zipf s", format_number(heuristic.curve_shape.zipf_s), "曲线形状参数"),
            (
                "Power-Law beta",
                format_number(heuristic.curve_shape.resolved_power_law_beta()),
                "当 mode=power_law_fit 时使用",
            ),
            (
                "LRU-like 效率",
                format_number(heuristic.policy_efficiency.lru_like),
                "在线策略折损成的有效容量比例",
            ),
            ("alpha", format_number(config.prefill_savings_alpha), "Prefill 节省系数"),
        ),
    )
    scenario_rows = tuple(
        (
            row.scenario_label,
            f"{row.machine_count}/{row.card_count}/{row.cards_per_machine}",
            f"{row.hbm_total_kv_gb:.2f}",
            format_rate(row.content_hit_rate),
            format_rate(row.hbm_strict_prefix_hit_rate),
            format_rate(row.hbm_lru_like_hit_rate),
            row.hbm_current_bottleneck,
        )
        for row in result.scenario_summaries
    )
    scenario_table = _markdown_table(
        headers=("场景", "机/卡/单机卡", "HBM GB", "极限命中率", "Strict-Prefix 估计", "LRU-like 估计", "当前瓶颈"),
        rows=scenario_rows,
    )
    tier_rows = tuple(
        (
            row.scenario_label,
            row.tier_label,
            f"{row.total_kv_gb:.2f}",
            format_rate(row.strict_prefix_hit_rate),
            format_rate(row.lru_like_hit_rate),
            format_delta_pp(row.strict_prefix_gain_from_previous_tier),
            format_delta_pp(row.lru_like_gain_from_previous_tier),
            row.current_bottleneck,
        )
        for row in result.tier_rows
    )
    tier_table = _markdown_table(
        headers=("场景", "容量层", "KV GB", "Strict-Prefix 估计", "LRU-like 估计", "Strict 增益", "LRU-like 增益", "瓶颈"),
        rows=tier_rows,
    )
    calibration_section = ""
    structure_section = ""
    if calibration is not None:
        structure_section = _render_structure_recommendation_zh(calibration)
        comparison_rows = tuple(
            (
                item.tier_label,
                format_rate(item.observed_strict_prefix_hit_rate),
                format_rate(item.predicted_strict_prefix_hit_rate),
                format_delta_pp(item.strict_prefix_error),
                format_rate(item.observed_lru_like_hit_rate),
                format_rate(item.predicted_lru_like_hit_rate),
                format_delta_pp(item.lru_like_error),
            )
            for item in calibration.best_tier_comparisons
        )
        comparison_table = _markdown_table(
            headers=(
                "容量层",
                "观测 Strict",
                "估计 Strict",
                "Strict 误差",
                "观测 LRU",
                "估计 LRU",
                "LRU 误差",
            ),
            rows=comparison_rows,
        )
        calibration_section = f"""
## 基于真实 trace 的回标

**输入来源**

- `trace`: `{context.trace or ""}`
- `bucket_config`: `{context.bucket_config_path or ""}`
- `loaded_records`: `{context.loaded_records if context.loaded_records is not None else ""}`
- `max_records`: `{context.max_records if context.max_records is not None else ""}`
- `bucket_count`: `{calibration.target.bucket_count}`
- `trial_count`: `{calibration.grid.trial_count}`

**最佳参数**

| 参数 | 值 |
|------|----|
| `zipf_s` | {format_number(calibration.best_trial.zipf_s)} |
| `power_law_beta` | {format_number(calibration.best_trial.power_law_beta)} |
| `lru_like` | {format_number(calibration.best_trial.lru_like)} |
| `rmse_total` | {format_delta_pp(calibration.best_trial.rmse_total)} |
| `rmse_strict` | {format_delta_pp(calibration.best_trial.rmse_strict)} |
| `rmse_lru_like` | {format_delta_pp(calibration.best_trial.rmse_lru_like)} |
| `max_abs_error` | {format_delta_pp(calibration.best_trial.max_abs_error)} |
| `content_gap` | {format_delta_pp(calibration.best_trial.content_gap)} |

{comparison_table}

**解释**

- 这一步只是在给定结构假设下，让 `zipf_s` 和 `lru_like` 更贴近一小段真实 trace。
- 如果 `content_gap` 很大，说明问题主要在结构参数，而不在 `zipf_s / lru_like`。
- 回标结果只能说明“这组参数更贴近这个样本”，不能把它当成 oracle 证明。
"""
    return f"""# Heuristic 结果报告

> **“Heuristic 的价值不在于伪装成证明，而在于在没有 trace 时先给出一版结构清晰、参数可解释的冷启动估计。”**
> 这份报告说明当前无 trace 多 Agent 估计使用了哪些假设、得出了什么结果，以及这些结果的边界是什么。

## 运行上下文

- `mode`: `{context.mode}`
- `config`: `{context.config_path}`
- `output_dir`: `{context.output_dir}`

```mermaid
flowchart LR
    A["Shared Prefix / Private Working Set"] --> B["Hit Curve"]
    B --> C["TPS Gain"]
    C --> D["Machines / Cards"]

    style A fill:#e3f2fd
    style B fill:#c8e6c9
    style C fill:#fff3cd
    style D fill:#ffe0b2
```

## 核心假设

{assumptions_table}

## 计算链路

```mermaid
flowchart TD
    A["S, Delta, T, W, n"] --> B["Average Reusable Private Tokens P"]
    B --> C["Content Ceiling h_content"]
    C --> D["Curve Shape g(r)"]
    D --> E["Strict-Prefix Estimate"]
    D --> F["LRU-like Estimate"]
    E --> G["TPS Gain"]
    F --> G

    style C fill:#e3f2fd
    style E fill:#c8e6c9
    style F fill:#fff3cd
```

对应公式：

```text
P = (1 / T) * sum_{{i=0}}^{{T-1}} min(W, i * Delta)
L_request = S + Delta + P
h_content = (S + P) / L_request
h_strict_est(C) = min(h_content, (S + g(r) * P) / L_request)
h_lru_like_est(C) = min(h_content, (S + g(eta * r) * P) / L_request)
```

## HBM 主结果

{scenario_table}

## 容量层展开

{tier_table}

{structure_section}

{calibration_section}

## 结果边界

- 这些结果是 `heuristic estimate`，不是 `exact strict-prefix oracle`。
- `LRU-like` 只是在线策略近似，不等于真实 trace 驱动的 LRU 模拟。
- `alpha` 只负责把命中率映射成吞吐收益，不代表真实线上一定能兑现同等收益。
- 如果后续拿到了 trace，应优先用 `analyze-buckets / audit-buckets` 跑 oracle 路径，并把这份 heuristic 报告当作冷启动先验。
"""


def _render_heuristic_report_en(
    *,
    config: HeuristicAnalysisConfig,
    result: HeuristicAnalysisResult,
    context: HeuristicReportContext,
    calibration: CalibrationResult | None,
) -> str:
    heuristic = config.heuristic
    assumptions_table = _markdown_table(
        headers=("Parameter", "Value", "Meaning"),
        rows=(
            ("Concurrent agents", str(heuristic.concurrent_agents), "Active agents in the cold-start model"),
            ("Shared prefix tokens", format_number(heuristic.shared_prefix_tokens), "Tokens reused by all agents"),
            ("New tokens per turn", format_number(heuristic.avg_new_tokens_per_turn), "Per-turn context growth"),
            ("Average turns per session", str(heuristic.avg_turns_per_session), "Append-only session depth"),
            ("Private window tokens", format_number(heuristic.private_window_tokens), "Per-agent private context window"),
            ("Curve mode", heuristic.curve_shape.mode, "linear / power_law_fit / zipf_harmonic"),
            ("Zipf s", format_number(heuristic.curve_shape.zipf_s), "Shape parameter"),
            (
                "Power-Law beta",
                format_number(heuristic.curve_shape.resolved_power_law_beta()),
                "Used when mode=power_law_fit",
            ),
            ("LRU-like efficiency", format_number(heuristic.policy_efficiency.lru_like), "Effective-capacity discount for online policies"),
            ("alpha", format_number(config.prefill_savings_alpha), "Prefill savings factor"),
        ),
    )
    scenario_rows = tuple(
        (
            row.scenario_label,
            f"{row.machine_count}/{row.card_count}/{row.cards_per_machine}",
            f"{row.hbm_total_kv_gb:.2f}",
            format_rate(row.content_hit_rate),
            format_rate(row.hbm_strict_prefix_hit_rate),
            format_rate(row.hbm_lru_like_hit_rate),
            row.hbm_current_bottleneck,
        )
        for row in result.scenario_summaries
    )
    scenario_table = _markdown_table(
        headers=("Scenario", "Machines/Cards/Cards per machine", "HBM GB", "Content ceiling", "Strict-Prefix estimate", "LRU-like estimate", "Bottleneck"),
        rows=scenario_rows,
    )
    tier_rows = tuple(
        (
            row.scenario_label,
            row.tier_label,
            f"{row.total_kv_gb:.2f}",
            format_rate(row.strict_prefix_hit_rate),
            format_rate(row.lru_like_hit_rate),
            format_delta_pp(row.strict_prefix_gain_from_previous_tier),
            format_delta_pp(row.lru_like_gain_from_previous_tier),
            row.current_bottleneck,
        )
        for row in result.tier_rows
    )
    tier_table = _markdown_table(
        headers=("Scenario", "Capacity tier", "KV GB", "Strict estimate", "LRU-like estimate", "Strict delta", "LRU-like delta", "Bottleneck"),
        rows=tier_rows,
    )
    calibration_section = ""
    structure_section = ""
    if calibration is not None:
        structure_section = _render_structure_recommendation_en(calibration)
        comparison_rows = tuple(
            (
                item.tier_label,
                format_rate(item.observed_strict_prefix_hit_rate),
                format_rate(item.predicted_strict_prefix_hit_rate),
                format_delta_pp(item.strict_prefix_error),
                format_rate(item.observed_lru_like_hit_rate),
                format_rate(item.predicted_lru_like_hit_rate),
                format_delta_pp(item.lru_like_error),
            )
            for item in calibration.best_tier_comparisons
        )
        comparison_table = _markdown_table(
            headers=(
                "Tier",
                "Observed Strict",
                "Estimated Strict",
                "Strict error",
                "Observed LRU",
                "Estimated LRU",
                "LRU error",
            ),
            rows=comparison_rows,
        )
        calibration_section = f"""
## Trace-backed calibration

**Inputs**

- `trace`: `{context.trace or ""}`
- `bucket_config`: `{context.bucket_config_path or ""}`
- `loaded_records`: `{context.loaded_records if context.loaded_records is not None else ""}`
- `max_records`: `{context.max_records if context.max_records is not None else ""}`
- `bucket_count`: `{calibration.target.bucket_count}`
- `trial_count`: `{calibration.grid.trial_count}`

**Best-fit parameters**

| Parameter | Value |
|-----------|-------|
| `zipf_s` | {format_number(calibration.best_trial.zipf_s)} |
| `power_law_beta` | {format_number(calibration.best_trial.power_law_beta)} |
| `lru_like` | {format_number(calibration.best_trial.lru_like)} |
| `rmse_total` | {format_delta_pp(calibration.best_trial.rmse_total)} |
| `rmse_strict` | {format_delta_pp(calibration.best_trial.rmse_strict)} |
| `rmse_lru_like` | {format_delta_pp(calibration.best_trial.rmse_lru_like)} |
| `max_abs_error` | {format_delta_pp(calibration.best_trial.max_abs_error)} |
| `content_gap` | {format_delta_pp(calibration.best_trial.content_gap)} |

{comparison_table}

**Interpretation**

- This step only makes `zipf_s` and `lru_like` better aligned with a small real trace sample under the current structural assumptions.
- A large `content_gap` means the main mismatch comes from the structural parameters, not from `zipf_s / lru_like`.
- Calibration improves alignment to a sample; it is not a proof and must not be presented as an oracle result.
"""
    return f"""# Heuristic Report

> **"A heuristic is useful when it stays honest: it gives a structured cold-start estimate instead of pretending to be a proof."**
> This report explains the assumptions, outputs, and limits of the trace-free multi-agent estimator.

## Run Context

- `mode`: `{context.mode}`
- `config`: `{context.config_path}`
- `output_dir`: `{context.output_dir}`

```mermaid
flowchart LR
    A["Shared Prefix / Private Working Set"] --> B["Hit Curve"]
    B --> C["TPS Gain"]
    C --> D["Machines / Cards"]

    style A fill:#e3f2fd
    style B fill:#c8e6c9
    style C fill:#fff3cd
    style D fill:#ffe0b2
```

## Core Assumptions

{assumptions_table}

## Computation Flow

```mermaid
flowchart TD
    A["S, Delta, T, W, n"] --> B["Average Reusable Private Tokens P"]
    B --> C["Content Ceiling h_content"]
    C --> D["Curve Shape g(r)"]
    D --> E["Strict-Prefix Estimate"]
    D --> F["LRU-like Estimate"]
    E --> G["TPS Gain"]
    F --> G

    style C fill:#e3f2fd
    style E fill:#c8e6c9
    style F fill:#fff3cd
```

The estimator uses:

```text
P = (1 / T) * sum_{{i=0}}^{{T-1}} min(W, i * Delta)
L_request = S + Delta + P
h_content = (S + P) / L_request
h_strict_est(C) = min(h_content, (S + g(r) * P) / L_request)
h_lru_like_est(C) = min(h_content, (S + g(eta * r) * P) / L_request)
```

## HBM Summary

{scenario_table}

## Capacity Tiers

{tier_table}

{structure_section}

{calibration_section}

## Boundaries

- These outputs are `heuristic estimates`, not `exact strict-prefix` oracle results.
- `LRU-like` is only a policy approximation, not the same thing as trace-driven LRU simulation.
- `alpha` converts hit rate into throughput gain; it does not prove that the same gain will be realized online.
- Once a representative trace is available, the trace-based oracle path should replace this report as the primary source of truth.
"""


def _markdown_table(*, headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "| " + " | ".join("---" for _ in headers) + " |"
    body_lines = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header_line, separator_line, *body_lines])


def _render_structure_recommendation_zh(calibration: CalibrationResult) -> str:
    recommendation = calibration.structure_recommendation
    if recommendation is None:
        return ""

    hints = recommendation.hints
    heuristic = recommendation.recommended_config.heuristic
    summary = recommendation.recommended_analysis.scenario_summaries[0]
    alignment_table = _markdown_table(
        headers=("指标", "观测", "结构建议", "差值"),
        rows=(
            (
                "内容上界",
                format_rate(calibration.target.content_hit_rate),
                format_rate(summary.content_hit_rate),
                format_delta_pp(summary.content_hit_rate - calibration.target.content_hit_rate),
            ),
            (
                "HBM Strict-Prefix",
                format_rate(calibration.target.tiers[0].strict_prefix_hit_rate),
                format_rate(summary.hbm_strict_prefix_hit_rate),
                format_delta_pp(
                    summary.hbm_strict_prefix_hit_rate
                    - calibration.target.tiers[0].strict_prefix_hit_rate
                ),
            ),
            (
                "HBM LRU-like",
                format_rate(calibration.target.tiers[0].lru_like_hit_rate),
                format_rate(summary.hbm_lru_like_hit_rate),
                format_delta_pp(
                    summary.hbm_lru_like_hit_rate
                    - calibration.target.tiers[0].lru_like_hit_rate
                ),
            ),
        ),
    )
    parameter_table = _markdown_table(
        headers=("参数", "建议值", "来源"),
        rows=(
            (
                "并发 Agent 数",
                str(heuristic.concurrent_agents),
                "session 生命周期重叠的 p95 并发",
            ),
            (
                "共享前缀 tokens",
                format_number(heuristic.shared_prefix_tokens),
                "root 两两平均公共前缀",
            ),
            (
                "每轮新增 tokens",
                format_number(heuristic.avg_new_tokens_per_turn),
                "对齐 content ceiling 后的等效每轮新增量",
            ),
            (
                "平均会话轮数",
                str(heuristic.avg_turns_per_session),
                "每 session 请求数均值四舍五入",
            ),
            (
                "私有窗口 tokens",
                format_number(heuristic.private_window_tokens),
                "拟合 avg(min(W, i * Delta)) 到观测私有复用量",
            ),
            (
                "Zipf population blocks",
                str(heuristic.curve_shape.zipf_population_blocks),
                "共享前缀 + 并发私有工作集换算",
            ),
        ),
    )
    notes = "\n".join(f"- {note}" for note in hints.notes) if hints.notes else "- 无额外告警。"
    return f"""
## Trace 结构建议

这一步不调 `zipf_s / lru_like`，只根据 trace 的 session 形态给出更贴近样本的结构模板。

{parameter_table}

**结构对齐效果**

{alignment_table}

**诊断**

- `request_count`: `{hints.request_count}`
- `session_count`: `{hints.session_count}`
- `root_request_count`: `{hints.root_request_count}`
- `平均 root prompt tokens`: `{format_number(hints.average_root_prompt_tokens)}`
- `稳定共享前缀 tokens`: `{format_number(hints.stable_shared_prefix_tokens)}`
- `median 每轮新增 tokens`: `{format_number(hints.median_new_tokens_per_turn)}`
- `观测平均私有复用 tokens`: `{format_number(hints.observed_average_reusable_private_tokens)}`
- `平均活跃 sessions`: `{format_number(hints.average_active_sessions)}`
- `p95 活跃 sessions`: `{format_number(hints.p95_active_sessions)}`
- `最大活跃 sessions`: `{hints.max_active_sessions}`

**边界**

{notes}
"""


def _render_structure_recommendation_en(calibration: CalibrationResult) -> str:
    recommendation = calibration.structure_recommendation
    if recommendation is None:
        return ""

    hints = recommendation.hints
    heuristic = recommendation.recommended_config.heuristic
    summary = recommendation.recommended_analysis.scenario_summaries[0]
    alignment_table = _markdown_table(
        headers=("Metric", "Observed", "Trace hint", "Delta"),
        rows=(
            (
                "Content ceiling",
                format_rate(calibration.target.content_hit_rate),
                format_rate(summary.content_hit_rate),
                format_delta_pp(summary.content_hit_rate - calibration.target.content_hit_rate),
            ),
            (
                "HBM strict-prefix",
                format_rate(calibration.target.tiers[0].strict_prefix_hit_rate),
                format_rate(summary.hbm_strict_prefix_hit_rate),
                format_delta_pp(
                    summary.hbm_strict_prefix_hit_rate
                    - calibration.target.tiers[0].strict_prefix_hit_rate
                ),
            ),
            (
                "HBM LRU-like",
                format_rate(calibration.target.tiers[0].lru_like_hit_rate),
                format_rate(summary.hbm_lru_like_hit_rate),
                format_delta_pp(
                    summary.hbm_lru_like_hit_rate
                    - calibration.target.tiers[0].lru_like_hit_rate
                ),
            ),
        ),
    )
    parameter_table = _markdown_table(
        headers=("Parameter", "Suggested value", "Derived from"),
        rows=(
            (
                "Concurrent agents",
                str(heuristic.concurrent_agents),
                "p95 overlap of session lifetimes",
            ),
            (
                "Shared prefix tokens",
                format_number(heuristic.shared_prefix_tokens),
                "average pairwise root overlap",
            ),
            (
                "New tokens per turn",
                format_number(heuristic.avg_new_tokens_per_turn),
                "content-aligned effective per-turn growth",
            ),
            (
                "Average turns per session",
                str(heuristic.avg_turns_per_session),
                "rounded mean requests per session",
            ),
            (
                "Private window tokens",
                format_number(heuristic.private_window_tokens),
                "fit avg(min(W, i * Delta)) to observed private reuse",
            ),
            (
                "Zipf population blocks",
                str(heuristic.curve_shape.zipf_population_blocks),
                "shared + concurrent private working set",
            ),
        ),
    )
    notes = "\n".join(f"- {note}" for note in hints.notes) if hints.notes else "- No extra warnings."
    return f"""
## Trace Structure Hints

This step does not tune `zipf_s / lru_like`. It only extracts a structure template from the trace shape.

{parameter_table}

**Alignment**

{alignment_table}

**Diagnostics**

- `request_count`: `{hints.request_count}`
- `session_count`: `{hints.session_count}`
- `root_request_count`: `{hints.root_request_count}`
- `average root prompt tokens`: `{format_number(hints.average_root_prompt_tokens)}`
- `stable shared prefix tokens`: `{format_number(hints.stable_shared_prefix_tokens)}`
- `median new tokens per turn`: `{format_number(hints.median_new_tokens_per_turn)}`
- `observed reusable private tokens`: `{format_number(hints.observed_average_reusable_private_tokens)}`
- `average active sessions`: `{format_number(hints.average_active_sessions)}`
- `p95 active sessions`: `{format_number(hints.p95_active_sessions)}`
- `max active sessions`: `{hints.max_active_sessions}`

**Boundaries**

{notes}
"""
