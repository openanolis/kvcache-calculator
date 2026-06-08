# Design: Guided Calculator for Industry Adoption

## Context

The KVCache Calculator already has a 3-step wizard, comparison mode, shareable URLs, export, charts, and sensitivity analysis. The main barrier to adoption by platform/infra engineers is **conceptual complexity** — users see 8 summary metrics (content hit rate, strict saturation, LRU saturation, KV bytes/token, etc.) and don't know which number answers their question.

**Target user**: Platform/infra engineers who know GPUs and TPS but not cache theory. They want: "How many GPUs do I need?" or "Can my cluster handle this workload?"

## Goals

1. Add a **hero answer section** that shows the answer in one sentence before any detailed metrics
2. Add **plain-language explanations** to key metrics so users understand what they're looking at
3. Improve the **wizard result step** to show the hero answer immediately after completing the wizard
4. Add a **recommendation panel** with actionable advice based on the analysis results

## Non-Goals

- Rewriting the existing calculator form or calculation engine
- Adding trace upload to the web UI (future work)
- Changing the Python CLI
- Adding cost/pricing calculations (future work)

## Design

### 1. Hero Answer Section

A new card inserted **above** the Summary Metrics grid. Contains:

- **Primary answer** in large text: e.g., "Your 8× H20 cluster can serve **2,048 concurrent agents** with **67% KV cache hit rate**"
- **Secondary line**: "KV caching saves ~40% compute → equivalent to having **13.3 GPUs** without caching"
- **Bottleneck indicator**: A colored badge showing whether the main constraint is "Memory" (capacity-bound) or "Policy" (hit-rate-bound) or "Balanced"
- Auto-generated from the existing `summary` object in `computeAndRender()`

The hero section uses the existing calculation results — no new math needed. It simply reformats:
- `summary.contentHitRate` → hit rate percentage
- TPS gain from `tpsGain()` → compute savings %
- Effective GPU equivalent = `accelerator_count * tps_gain`
- Bottleneck = compare `strict saturation GB` vs `HBM KV/card * accelerator_count`

### 2. Plain-Language Metric Tooltips

Each metric in the `metrics-grid` gets an `info` icon that shows a tooltip on hover:

| Metric | Tooltip |
|--------|---------|
| Content Hit Rate | "% of KV cache blocks that can be reused across requests. Higher = more compute saved." |
| Avg Request Tokens | "Average input+output length per request in tokens." |
| Working Set Tokens | "Total unique KV cache data across all concurrent sessions." |
| KV Bytes/Token | "Memory cost of storing one token's KV cache for this model." |
| HBM KV/Card | "GPU memory available for KV cache per card after subtracting model weights." |
| Strict Saturation | "GPU memory needed to achieve maximum possible hit rate." |
| LRU Saturation | "GPU memory at which simple LRU caching stops improving." |
| Avg Private Tokens | "Tokens unique to each session that cannot be shared." |

### 3. Wizard Result Step (Step 4)

After the user completes the current 3-step wizard (model → GPU → workload), add a **Step 4: Results** that shows:

- The hero answer (same format as the hero section)
- Three "What if?" buttons:
  - "Try different GPU" → goes back to step 2
  - "Try different workload" → goes back to step 3
  - "See full details" → closes wizard, scrolls to results
- "Share this analysis" button → generates shareable URL

### 4. Recommendation Panel

A new card below the hero section with actionable advice. Logic:

- **If capacity-bound** (strict saturation > HBM available): "Your GPUs don't have enough memory for optimal caching. Consider: adding more GPUs, using GPUs with more HBM (e.g., H200), or adding a host KV cache tier."
- **If policy-bound** (LRU saturation << strict saturation): "Your memory is sufficient but a smarter cache policy could improve hit rates. The gap between optimal (X%) and LRU (Y%) suggests Z% potential improvement."
- **If well-balanced**: "Your deployment is well-sized. KV caching is working efficiently."
- **If hit rate < 20%**: "This workload has limited KV cache reuse potential. The sessions are too diverse for significant prefix sharing."
- **If hit rate > 80%**: "Excellent cache reuse! This workload benefits significantly from KV caching."

### 5. Visual Improvements

- Add a **gradient progress ring** around the hit rate percentage in the hero section
- Use **color coding** in the metrics grid: green for good utilization, yellow for suboptimal, red for bottlenecked
- Add a subtle **animation** when results update (fade-in)

## Implementation Scope

All changes are in `website/calculator.html` only (single-file architecture). No Python changes, no new files, no build system.

Estimated additions: ~200 lines of HTML/CSS, ~150 lines of JS.

## Risks

- **Hero answer oversimplification**: The "you need X GPUs" framing might mislead users who have more complex constraints. Mitigated by always showing "See details" link.
- **Tooltip text getting stale**: If we add new metrics, tooltips need updating. Mitigated by keeping tooltip text in a single JS object.
