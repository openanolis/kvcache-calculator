# kvcache-upper-bound-oracle

## Directory Structure

```text
kvcache-upper-bound-oracle/
├── AGENTS.md
├── README.md
├── README.zh.md
├── pyproject.toml
├── docs/
│   ├── correctness_guide.en.md
│   ├── correctness_guide.zh.md
│   ├── design_guide.en.md
│   ├── design_guide.zh.md
│   ├── four_layer_model.en.md
│   └── four_layer_model.zh.md
├── configs/
├── outputs/
├── src/kvcache_upper_bound/
└── tests/
```

## File Responsibilities

- `README.md`: English project entry point. Covers goals, scope, startup order, and why the main tables focus on the current HBM tier while extra capacity tiers live in the long-form `tier_summary.csv` table.
- `README.zh.md`: Explicit Chinese project entry point.
- `pyproject.toml`: Local install entry point; ensures the `kvcache-upper-bound` command can run directly.
- `docs/design_guide.zh.md` / `docs/design_guide.en.md`: Single source of truth for requirements, semantics, algorithms, and phase plans.
- `docs/correctness_guide.zh.md` / `docs/correctness_guide.en.md`: Explains which results are reference-proven and which metrics are supporting evidence for exact strict-prefix reasoning.
- `docs/four_layer_model.zh.md` / `docs/four_layer_model.en.md`: External-facing documentation for the simplified `Capacity -> Hit Rate -> TPS -> Machine Demand` model and trace-free estimates.
- `src/kvcache_upper_bound/core/models.py`: Stable data models for requests, effective requests, model profiles, and weight-footprint derivation.
- `src/kvcache_upper_bound/heuristic/multi_agent.py`: Trace-free multi-agent cold-start estimator based on shared/private working sets, curve shapes, and `policy_efficiency`.
- `src/kvcache_upper_bound/heuristic/calibration.py`: Trace-backed calibration engine that aggregates bucket oracle results into one target, grid-searches `zipf_s × lru_like`, and emits calibrated configs and per-tier errors.
- `src/kvcache_upper_bound/heuristic/config_loader.py`: Parser and validator for trace-free heuristic configs; fixes the semantics of `curve_mode`, `zipf_s`, `policy_efficiency`, and deployment budgets.
- `src/kvcache_upper_bound/heuristic/output.py`: Output layer for trace-free heuristic runs; writes `heuristic_summary.csv`, `heuristic_tier_summary.csv`, `details.json`, and normalized input summaries.
- `src/kvcache_upper_bound/heuristic/report.py`: Bilingual heuristic report renderer. Default `heuristic_report.md` is English; `heuristic_report.zh.md` is the explicit Chinese variant.
- `src/kvcache_upper_bound/heuristic/structure.py`: Trace structure recommender that extracts candidate `shared prefix / Delta / T / W / n` templates and writes `recommended_heuristic_config.json`.
- `src/kvcache_upper_bound/ingest/trace_loader.py`: Loads JSONL traces, parses fields, normalizes time, and provides stable ordering.
- `src/kvcache_upper_bound/ingest/normalizer.py`: Converts raw requests into window-aware `EffectiveRequest` objects and resolves session roots.
- `src/kvcache_upper_bound/oracle/prefix_trie.py`: Prefix-path state machine for matching and insertion only.
- `src/kvcache_upper_bound/oracle/content.py`: Content upper-bound analysis; emits per-request hits/misses and block/token/byte aggregates.
- `src/kvcache_upper_bound/oracle/capacity.py`: Capacity upper-bound analysis using an offline Belady model with `no-admit` support.
- `src/kvcache_upper_bound/oracle/lru.py`: Online LRU baseline under the same prefix-path semantics; useful for comparison but not an upper bound.
- `src/kvcache_upper_bound/oracle/strict_prefix.py`: Exact strict-prefix capacity oracle. It uses certificate fast paths when possible and falls back to exact request-boundary DP search.
- `src/kvcache_upper_bound/reporting/buckets.py`: Core bucketed analysis loop; keeps bucket execution, hit-rate aggregation, and target-TPS planning evaluation separate from config parsing.
- `src/kvcache_upper_bound/reporting/config_loader.py`: Bucket config parser and semantic validator for machines, cards, TPS, budgets, and planning anchors.
- `src/kvcache_upper_bound/reporting/inputs.py`: Normalized input summaries for `metadata.json` and correctness reports.
- `src/kvcache_upper_bound/reporting/table_common.py`: Shared table column names, formatting helpers, bottleneck diagnostics, and row-range utilities.
- `src/kvcache_upper_bound/reporting/hit_output.py`: Hit-result views for `summary.csv` and `hit_summary.csv`, including HBM main columns and bottleneck diagnostics.
- `src/kvcache_upper_bound/reporting/planning_output.py`: Planning-result views for exact strict-prefix upper-bound planning and LRU policy planning.
- `src/kvcache_upper_bound/reporting/planning_search.py`: Target-TPS planning search and TPS math.
- `src/kvcache_upper_bound/reporting/output.py`: Output orchestration for `summary.csv`, `hit_summary.csv`, `planning_strict_prefix.csv`, `planning_lru.csv`, `tier_summary.csv`, and `details.json`.
- `src/kvcache_upper_bound/cli/main.py`: CLI entry point that connects traces, configs, output directories, metadata, and report generation.
- `src/kvcache_upper_bound/verification/reference.py`: Naive reference implementation, brute-force validators, strict-prefix reconciliation, and exhaustive equivalence checks.
- `src/kvcache_upper_bound/verification/audit.py`: Writes reference results, trace-sample checks, strict-prefix diagnostics, proof sources, and bilingual correctness reports. Default `correctness_report.md` is English; `correctness_report.zh.md` is the explicit Chinese variant.
- `tests/`: Tests for semantics and boundary conditions. Avoid brittle tests coupled to implementation details.
- `configs/`: Sample machine configs, model configs, and experiment matrices.
- `outputs/`: Local experiment outputs only; it does not carry source semantics.

## Architecture Principles

- The first version is an offline oracle, not an online serving runtime.
- Use blocks as the primary unit. The default block size is 16; token-level values are conversion-layer outputs.
- The core semantics are `strict_prefix_window`, `prefill only`, and the `content -> capacity -> policy -> heuristic` four-layer framework. The first three layers can be trace-driven; the fourth layer is trace-free cold-start estimation.
- Keep the broader analysis framework as `Oracle -> Policy -> Economics -> Heuristic`; do not collapse the layers into one formula.
- Interpret `hash_ids` as prefix paths, never as flat block-frequency statistics.
- `ModelProfile.kv_bytes_per_token()` describes the total KV footprint of the whole deployment, not a per-card shard. Budget fields must stay in the same convention.
- Deployment configs must explicitly provide `accelerator_count` and `cards_per_machine`. Legacy `machine_count` and implicit labels such as `8*h20` are invalid.
- `Machine Count` is always derived from `accelerator_count / cards_per_machine`. `Total TPS` is always normalized to cluster-total TPS, while the raw input unit is recorded separately as `TPS Input Unit`.
- `ModelProfile.parameter_count` is only used to derive theoretical KV budget from GPU memory. If it is absent, configs must provide `hbm_kv_gb_per_card` or utilization explicitly.
- HBM, GPU memory, and runtime-reserve budget fields must use explicit `*_per_card` names. Legacy `*_per_machine` names are invalid inputs.
- Hybrid-attention models must explicitly provide `kv_cache_layer_count`; do not apply KV formulas to all layers blindly.
- Keep pure computation under `src/`. File IO and CLI orchestration should stay at the edges.
- `core/` must not depend on `ingest/`; data structures should be more stable than parsing logic.
- `normalizer.py` only performs windowing and scope resolution; it must not introduce cache policies early.
- `prefix_trie.py` must stay purely prefix-semantic. Do not put counters, reports, or cache-tier policy into it.
- `content.py` answers whether a prefix has existed historically. It does not answer capacity or bandwidth questions.
- `capacity.py` answers whether event-level space is enough. It does not answer transfer-bandwidth or scheduling questions.
- `strict_prefix.py` answers the best achievable value under strict-prefix semantics. It must not read traces or assemble reports.
- `verification/` proves what can be proved and exposes boundaries for everything else. New certificate semantics must include an upper/lower-bound chain.
- `reporting/` translates algorithm results into tables and files; it must not contaminate oracle data structures.
- Reporting may post-process hit rates into `TPS / Machine Count`, but machine counts, scheduling, and bandwidth must not leak back into oracle definitions.
- Keep outputs focused: hit-rate estimates are primary results, while `TPS / Machine Count` columns are derived planning results.
- Main CSV files should focus on the current HBM tier. Extra capacity tiers belong in the long-form `tier_summary.csv` table.
- Upper-bound planning and policy planning must remain separate: `planning_strict_prefix.csv` represents exact strict-prefix planning, and `planning_lru.csv` represents LRU planning.
- `heuristic/` is the fourth-layer cold-start engine, not an oracle. It emits estimates, not proof sources.
- `heuristic/calibration.py` performs parameter fitting only. Calibration must always emit errors and boundary notes, and must not be presented as proof.
- `heuristic/structure.py` may infer a recommended structure template from a trace, but the output is a recommendation, not workload truth.
- Absolute planning requires anchors: `baseline_per_card_tps` for no-hit per-card baseline throughput and `planning_target_total_tps` for target cluster TPS.
- `Estimated Card Count For Same Load / Estimated Machine Count For Same Load` are fixed-hit-rate compute-equivalence diagnostics and should stay in `details.json`, not the main CSV files.
- Hit tables must explicitly report whether the current bottleneck is `Capacity` or `Policy`.
- `LRU` is both a hit-rate baseline and a policy-planning input, but it cannot replace exact strict-prefix as the upper bound.

## Development Rules

- Stabilize data models before writing cache simulation logic.
- Add minimal tests for each stage: semantic boundaries, monotonicity, and conservation of totals.
- Any hit-rate semantic change must update both `docs/correctness_guide.zh.md` and `docs/correctness_guide.en.md`.
- Documentation comes first when adding modules or directories: update this file and both design guides.
- Keep functions short. When there are more than three explicit branches, prefer restructuring the data flow over adding more conditionals.

## Change Log

- `2026-03-17`: Initialized the project skeleton and design guides.
- `2026-03-17`: Added `core/` and `ingest/` for the M1 trace-normalization path.
- `2026-03-17`: Added `oracle/` and started M2 content upper bound implementation.
- `2026-03-17`: Added `capacity/reporting/cli` support for bucketed HBM and extra-capacity hit-rate outputs.
- `2026-03-17`: Added `verification/`, bilingual correctness guides, and `audit-buckets`.
- `2026-03-17`: Connected exact strict-prefix capacity oracle into reporting and verification.
- `2026-03-17`: Added HBM KV budget derivation from GPU memory, model-weight shards, and runtime reserve.
- `2026-03-18`: Added four-layer model docs for the external `Capacity -> Hit Rate -> TPS -> Machine Demand` story.
- `2026-03-18`: Added `prefill_savings_alpha` and TPS/machine-count post-processing based on exact strict-prefix hit rate.
- `2026-03-18`: Split hit-rate outputs and planning outputs into `hit_summary.csv` and `planning_strict_prefix.csv`.
- `2026-03-18`: Reworked deployment scale semantics from machine-first to card-first.
- `2026-03-18`: Tightened deployment schema around `accelerator_count + cards_per_machine + machine_spec`.
- `2026-03-18`: Standardized HBM budget names to per-card fields.
- `2026-03-18`: Added deployment semantic validation and normalized input summaries.
- `2026-03-18`: Split reporting output orchestration out of `reporting/buckets.py`.
- `2026-03-18`: Added `oracle/lru.py` and LRU baseline tests.
- `2026-03-18`: Split output-layer tests into `tests/test_bucket_output_files.py`.
- `2026-03-18`: Added `reporting/inputs.py` and `planning_lru.csv`.
- `2026-03-18`: Split reporting output code into table, hit, planning, and orchestration layers.
- `2026-03-18`: Renamed strict-prefix planning output to `planning_strict_prefix.csv` and added public 1x1 H20 configs.
- `2026-03-18`: Added config-loader and planning-search modules with closed-loop target-TPS planning.
- `2026-03-18`: Narrowed the main CSV planning columns and added normalized planning sample configs.
- `2026-03-18`: Added `tier_summary.csv` as the long-form capacity-tier comparison table.
- `2026-03-18`: Added trace-free multi-agent heuristic estimation and its output files.
- `2026-03-18`: Added trace-backed multi-agent calibration and bilingual heuristic reports.
- `2026-03-18`: Added trace structure recommendation and `recommended_heuristic_config.json`.
- `2026-04-23`: Added `include_output_kvcache`, which extracts parent output block hashes from child `hash_ids` and injects them into the trie when prefill/decode are not disaggregated.
