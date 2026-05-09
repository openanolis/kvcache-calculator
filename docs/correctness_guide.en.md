# Result Correctness Guide

This document covers only four things: what each result represents, how planning results are derived, what is actually proven today, and where the boundaries of the without-trace heuristic lie.

## Result Layering

The project currently divides hit results into 5 layers:

| Result | Meaning | Role |
|--------|---------|------|
| `content upper bound` | Content reuse ceiling without considering capacity | Highest upper bound |
| `relaxed upper bound` | Event-level offline optimal upper bound at fixed capacity | Capacity upper bound |
| `LRU baseline` | Result of the standard LRU online policy at fixed capacity | Policy baseline |
| `strict-prefix replay` | Achievable result obtained by re-evaluating the relaxed schedule under strict-prefix semantics | Certificate lower bound |
| `exact strict-prefix` | True optimum under strict-prefix semantics | Core conclusion |

Equivalently:

```text
LRU baseline <= exact strict-prefix <= relaxed upper bound <= content upper bound
strict-prefix replay <= exact strict-prefix <= relaxed upper bound
```

Notes:

- `LRU baseline` is a simple online policy, not an upper bound.
- `exact strict-prefix` is currently the most important capacity result.
- `relaxed upper bound` and `strict-prefix replay` are mainly used to explain how the exact value is obtained.

## Definition of strict-prefix

`strict-prefix` only counts the contiguous segment of hits starting from the first block of a request.

Example:

```text
request blocks: [b0, b1, b2, b3]
hit pattern:    [ 1,  1,  0,  1]
strict-prefix hit = 2
```

The reason is straightforward:

- `b3` is hit.
- But `b2` is already a miss.
- Prefix contiguity is broken at `b2`, so the truly reusable prefix is only the first two blocks.

## Position of LRU in the Project

LRU is now wired into the main reports, but its identity is clear:

- It is a `policy baseline`.
- It represents "if KV cache is managed only with standard LRU online, how much strict-prefix hit can be achieved at the current capacity".
- It does not participate in upper-bound definitions, but it independently drives the machine-count computation in `planning_lru.csv`.

There are therefore two planning tables:

- `planning_strict_prefix.csv`: planning under the `exact strict-prefix` upper bound.
- `planning_lru.csv`: planning under the `LRU` policy.

## alpha and Planning Results

`alpha` is the `Prefill saving coefficient`. It represents the fraction of the hit benefit that can be converted into throughput gain.

The project currently has two sets of planning post-processing:

### 1. Compute-Equivalent Values at Fixed Hit Rate

These values are now retained only in `details.json` and are no longer shown in the main CSVs. They remain useful explanatory auxiliary values, with fixed formulas:

```text
TPS Gain = 1 / (1 - alpha * h)
Estimated Total TPS = Input Total TPS * TPS Gain
Estimated Card Count For Same Load = Current Card Count / TPS Gain
Estimated Machine Count For Same Load = Estimated Card Count / Cards Per Machine
```

Where:

- `h` depends on the planning table you are looking at.
- `alpha` is neither a trace statistic nor a model-intrinsic constant.
- `planning_strict_prefix.csv` plugs in the `exact strict-prefix` hit rate.
- `planning_lru.csv` plugs in the `LRU` hit rate.

These values do not feed back the fact that "shrinking capacity also reduces hit rate", so they can only be treated as local compute-equivalent values, not as final deployment answers.

### 2. Self-Consistent Planning Under a Target Total TPS

If the configuration provides:

- `baseline_per_card_tps`
- `planning_target_total_tps`

The report additionally outputs truly comparable planning columns:

- `Current Config Sustained Total TPS`
- `Target Total TPS Min Cards`
- `Target Total TPS Min Machines`

The computation of these columns is closed-loop:

```text
machine/card count
-> total KV budget
-> hit rate
-> cluster total TPS
-> whether target_total_tps is satisfied
```

So "min cards / min machines" here is not a simple division, but a monotonic search over candidate deployment scales until the first integer deployment that satisfies the target total TPS is found.

## How to Read the Reports

The recommended reading order:

1. Look at `Content Upper Bound Hit Rate` and judge how high the content ceiling is.
2. Look at `HBM Strict-Prefix Hit Rate` to judge how much reuse is actually preserved at the current HBM capacity.
3. Look at `HBM LRU Hit Rate` to judge how far the simple online policy is from the optimum.
4. Look at the three columns `HBM Strict-Prefix Reaches Content Upper Bound / HBM LRU Reaches Strict-Prefix / HBM Current Primary Bottleneck` to first separate "capacity bottleneck" from "policy bottleneck".
5. If you also want to compare expansion tiers like `HBM / 1T / 10T`, go directly to `tier_summary.csv` and focus on `Strict-Prefix Gain Over Previous Tier / LRU Gain Over Previous Tier`.
6. Finally look at the planning tables: prioritize `Target Total TPS Min Cards / Min Machines`; if you also want the local equivalent values "without feeding back capacity changes at fixed hit rate", consult `details.json`.

The responsibilities of each file are fixed as:

| File | What It Answers Only |
|------|----------------------|
| `hit_summary.csv` | What is the current HBM hit rate, and is the main bottleneck capacity or policy |
| `planning_strict_prefix.csv` | Under the exact strict-prefix upper bound, how much TPS can the current configuration sustain; if a target TPS is given, also the min cards / machines |
| `planning_lru.csv` | Under the LRU policy, how much TPS can the current configuration sustain; if a target TPS is given, also the min cards / machines |
| `tier_summary.csv` | The differences in hit rate, TPS, and diagnostics between different capacity tiers |
| `details.json` | Detailed summary and intermediate statistics for each bucket |
| `correctness_report.zh.md` / `correctness_report.en.md` | Proof scope and side evidence for the current results |
| `heuristic_report.zh.md` / `heuristic_report.en.md` | Assumptions, parameters, and boundaries of the without-trace heuristic |
| `calibration.json` / `calibration_trials.csv` | Trace calibration results; only describes parameter fit, not "proof of correctness" |
| `recommended_heuristic_config.json` | Trace-driven structural-template suggestion; only describes "structural assumptions closer to the sample" |

## What Is Currently Proven

### 1. content is exact

The `content upper bound` is defined over prefix paths, not over raw block frequency statistics. The project includes a trie implementation and a naive reference cross-check, so under the current definition this is an exact result.

### 2. relaxed is the exact optimum for its own objective

The objective of `relaxed upper bound` is:

- Expand requests into a sequence of block access events.
- At fixed capacity, maximize event hits using offline optimal scheduling that allows `no-admit`.

The project performs a reference cross-check against this objective, so it is exact for its own objective.

### 3. strict-prefix is a true exact oracle

`exact strict-prefix` is no longer an estimate; it is now a truly exact result:

- When the certificate is sufficient, it goes through the `certificate` path.
- When the certificate is insufficient, it enters exact search, and the report records `search`.

Therefore:

- `HBM Strict-Prefix Hit Rate` is an exact value.
- `HBM Strict-Prefix Solve Path` describes how this exact value was obtained.

## What Is Currently Not Proven

The following are not yet oracle conclusions:

- Whether the chosen `alpha` matches a particular production system.
- Whether the values `TPS Gain / Estimated Total TPS / same-load equivalents in details.json` equal real production gains.
- Whether `baseline_per_card_tps` equals the real per-card baseline throughput in production.
- Whether bandwidth, transfer latency, and cross-tier storage hit overhead are fully modeled.
- Whether the without-trace hit-rate estimates in `heuristic_summary.csv / heuristic_tier_summary.csv` equal the real workload's exact strict-prefix or real LRU.

## Positioning of the Without-Trace Heuristic

The project additionally supports a cold-start path:

```text
shared prefix + private working set + curve shape -> hit rate estimate -> TPS estimate -> machine count estimate
```

The positioning of this path must be clearly stated:

- It is a `heuristic`, not an `oracle`.
- It does not depend on a trace, so it cannot output `proof source`.
- It is suitable for "no profile yet, but a first-pass resource estimate is needed".

The current heuristic layer does three things:

1. Construct the working set from `shared_prefix_tokens + avg_new_tokens_per_turn + avg_turns_per_session + private_window_tokens + concurrent_agents`.
2. Map capacity to private-working-set coverage ratio using one of three curve shapes: `linear / power_law_fit / zipf_harmonic`.
3. Compress the online-policy loss into a single effective-capacity discount coefficient via `policy_efficiency.lru_like`.

If trace calibration is also performed, there is a fourth thing:

4. With the structural parameters fixed, calibrate `zipf_s` and `lru_like` against a small piece of real trace, and explicitly output the error rather than only the parameters.

The most important boundaries here are:

- `power_law_fit` only absorbs the common Zipf simplified formula into the estimator.
- `zipf_harmonic` is only closer to the discrete Zipf cumulative mass than the power-law fit.
- `LRU-like` is only a policy approximation, not equivalent to a trace-driven real LRU simulation.
- Trace calibration can only state "this parameter set fits this sample better"; it cannot state "all future workloads will look like this".
- The trace structure suggester can only state "this set of `shared/private` assumptions is closer to the sample"; the recommended config must not be presented as the workload's ground truth.

You should therefore understand them this way:

| Result | Positioning |
|--------|-------------|
| `exact strict-prefix` | Exact oracle when a trace is available |
| `LRU baseline` | Real policy simulation when a trace is available |
| `multi-agent heuristic strict-prefix` | Cold-start upper-bound estimate without a trace |
| `multi-agent heuristic lru-like` | Cold-start policy estimate without a trace |

So the most stable main line of the project is currently:

```text
trace + model + capacity -> hit rate result
hit rate result + alpha -> planning estimate
```

Without a trace, it degrades to:

```text
heuristic assumptions + model + deployment -> hit rate estimate
hit rate estimate + alpha -> planning estimate
```

When the first half is an oracle, we provide proofs or certificates; when the first half is a heuristic, we only provide assumptions, parameters, and results, never a fake proof.
