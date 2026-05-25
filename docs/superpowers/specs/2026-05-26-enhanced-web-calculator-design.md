# Enhanced KVCache Web Calculator — Design Spec

## Overview

Redesign the web calculator (`website/calculator.html`) into a comprehensive, guided KVCache sizing tool that serves platform architects, ML engineers, and non-technical stakeholders equally well. All computation remains fully client-side (no backend).

## Goals

- Let users go from "I don't know where to start" to "I have a capacity plan" in under 60 seconds via the Quick-Start Wizard
- Provide pre-built model profiles for 10+ popular models so users never need to look up layer counts
- Enable side-by-side "what-if" scenario comparison with delta highlighting
- Add TPS-vs-machines curves and sensitivity analysis beyond the current hit-rate chart
- Allow exporting and sharing results (markdown, PNG, JSON, URL hash)
- Improve input validation, documentation (tooltips), and responsive layout

## Non-Goals

- No server-side computation or APIs
- No trace-based oracle analysis (future scope)
- No multi-language / i18n for this iteration
- No database or user accounts

---

## Component 1: Model Preset Library

### Data Structure

```javascript
const MODEL_LIBRARY = [
  {
    id: "qwen3-27b",
    family: "Qwen",
    name: "Qwen3-27B (MLA)",
    params: {
      n_layers: 64, kv_cache_layer_count: 16, n_kv_heads: 4,
      head_dim: 256, dtype_bytes: 2, parameter_count: 27781419504,
      weight_dtype_bytes: 2, block_size: 16
    },
    notes: "Multi-head Latent Attention — only 16 KV layers"
  },
  // ... 10+ models
];
```

### Models to Include

| Family | Model | Params (B) | KV Heads | Head Dim | KV Layers | Architecture Note |
|--------|-------|-----------|----------|----------|-----------|-------------------|
| Qwen | Qwen3-27B | 27.8 | 4 | 256 | 16 | MLA |
| Qwen | Qwen2.5-72B | 72.7 | 8 | 128 | 80 | GQA |
| Qwen | Qwen2.5-7B | 7.6 | 4 | 128 | 28 | GQA |
| Llama | Llama 3.1 70B | 70.6 | 8 | 128 | 80 | GQA |
| Llama | Llama 3.1 8B | 8.0 | 8 | 128 | 32 | GQA |
| Llama | Llama 3.3 70B | 70.6 | 8 | 128 | 80 | GQA |
| DeepSeek | DeepSeek-V2 236B | 236 | 128 | 128 | 60 | MLA + MoE (compressed KV — use effective n_kv_heads=16, head_dim=512 for kv_bytes) |
| DeepSeek | DeepSeek-V3 671B | 671 | 128 | 128 | 61 | MLA + MoE (compressed KV — same note) |
| Mistral | Mixtral 8x22B | 141 | 8 | 128 | 56 | MoE, GQA |
| Mistral | Mistral 7B | 7.2 | 8 | 128 | 32 | GQA |
| GLM | GLM-4 9B | 9.4 | 2 | 128 | 40 | MQA |
| Yi | Yi-1.5 34B | 34.4 | 8 | 128 | 60 | GQA |

### UX

- Dropdown at top of Model Profile section, grouped by family
- Type-ahead filter for quick search
- Selecting a model fills all model profile fields
- Fields remain editable after preset selection (badge shows "Modified" if changed)
- "Custom" option leaves fields empty for manual entry

---

## Component 2: Scenario Comparison Mode

### Interaction Flow

1. User clicks "Compare" button (top of results panel)
2. Current configuration snapshots as **Scenario A** (locked, grayed form or collapsed summary)
3. Form becomes **Scenario B** (editable, highlighted border)
4. Results panel splits into two columns: A (frozen) | B (live-updating)
5. Delta row below each metric shows the difference (green = improvement, red = regression)
6. User can click "Swap" to make B the new A, or "Exit Compare" to return to single mode

### Delta Display

```
┌─────────────────────────┬─────────────────────────┐
│   Scenario A (Base)     │   Scenario B (What-if)  │
├─────────────────────────┼─────────────────────────┤
│ Strict Hit: 80.30%      │ Strict Hit: 87.45%      │
│                         │         Δ +7.15pp ▲     │
│ LRU Hit: 79.26%         │ LRU Hit: 84.12%         │
│                         │         Δ +4.86pp ▲     │
│ Min Machines: 4         │ Min Machines: 2         │
│                         │         Δ -2 ▼ (better) │
└─────────────────────────┴─────────────────────────┘
```

### What to Compare

- All summary metrics (hit rates, TPS gains, saturation capacities)
- Tier table rows (matched by tier label)
- Chart overlay (both scenarios on same chart, A as dashed line)

---

## Component 3: Quick-Start Wizard

### Step 1 — Model Selection

- Shows the model preset library as a card grid (logo/icon per family)
- Click to select; shows key stats (param count, KV bytes/token)
- "Skip — I'll configure manually" link at bottom

### Step 2 — Hardware Configuration

- **GPU type** dropdown: H20 (96GB) / A100 (80GB) / A100 (40GB) / H100 (80GB) / L40S (48GB)
- **GPU count**: number input (1–128)
- **Auto-suggest TP/PP**: based on model size vs. GPU memory, recommend a TP/PP split
  - Rule: if model_weights_gb > 0.8 × gpu_memory_gb, suggest TP = ceil(model_weights_gb / (0.7 × gpu_memory_gb))
- User can override TP/PP

### Step 3 — Workload Template

- **Template** dropdown with presets:
  - **Multi-agent chat** (default): concurrent_agents=2048, shared_prefix=4096, avg_turns=8, avg_new_tokens=4096, private_window=65536
  - **RAG pipeline**: concurrent_agents=512, shared_prefix=8192, avg_turns=2, avg_new_tokens=2048, private_window=16384
  - **Code assistant**: concurrent_agents=1024, shared_prefix=16384, avg_turns=6, avg_new_tokens=8192, private_window=32768
  - **Light chatbot**: concurrent_agents=4096, shared_prefix=2048, avg_turns=4, avg_new_tokens=1024, private_window=8192
  - **Custom**: all fields editable
- Each template shows a 1-line description

### Completion

- "Calculate" button closes wizard, opens full calculator with all fields pre-filled
- Results appear immediately
- Wizard state not persistent — can be re-opened from a "Guided Setup" button

---

## Component 4: Enhanced Charts

### Chart A: Hit Rate vs. Capacity (existing, enhanced)

- Keep current line chart
- Add: shaded area between strict-prefix and LRU (shows "policy gap")
- Add: vertical annotation line at current HBM capacity
- In comparison mode: overlay Scenario A as dashed lines

### Chart B: TPS vs. Machine Count (new)

- X-axis: number of machines (1 to 2× current)
- Y-axis: cluster TPS capacity
- Lines: strict-prefix policy, LRU policy
- Horizontal dashed line: target TPS
- Intersection point highlighted: "minimum machines needed"

### Chart C: Parameter Sensitivity (new)

- Bar chart or tornado chart
- Shows: if each parameter changes by ±20%, how much does HBM hit rate change?
- Parameters tested: concurrent_agents, shared_prefix, avg_turns, private_window, zipf_s, lru_efficiency
- Helps users understand which lever matters most

---

## Component 5: Export & Share

### Export Options

1. **Copy as Markdown** — button copies the results table + summary as a markdown-formatted text block to clipboard
2. **Download Chart (PNG)** — per-chart download button using Chart.js `toBase64Image()`
3. **Download Results (JSON)** — full analysis output including all tier rows, summary, and input config
4. **Share via URL** — encode full configuration in URL hash:
   ```
   calculator.html#config=eyJtb2RlbF9wcm9maWxlIjp7...}
   ```
   - Base64-encoded JSON of all form parameters
   - Loading page with hash auto-fills all fields and runs calculation
   - Length limit: if config > 2KB encoded, offer "Copy shareable link" that uses compression (lz-string)

### UI Placement

- Export toolbar above results panel: `[📋 Markdown] [📊 PNG] [📄 JSON] [🔗 Share]`
- Tooltip explains each on hover

---

## Component 6: UX Polish

### Input Validation

| Rule | Display |
|------|---------|
| tp_size × pp_size must divide evenly into n_kv_heads | Red border + "TP×PP must divide n_kv_heads" |
| accelerator_count must be divisible by cards_per_machine | Red border + "GPU count must be N × cards_per_machine" |
| Numeric fields must be > 0 | Red border + "Must be positive" |
| parameter_count unrealistically small (< 1B for > 32 layers) | Yellow warning |

### Tooltips

Every input field gets a `title` attribute with a 1-line explanation:
- `concurrent_agents`: "Number of simultaneous agent sessions sharing the cache pool"
- `shared_prefix_tokens`: "System prompt tokens shared identically across all agents"
- etc.

### Responsive Layout

- ≥1200px: side-by-side (form left, results right) — current layout
- 800–1200px: stacked (form top, results bottom), form sections in 2-column grid
- <800px: single column, accordion for form sections

### Dark/Light Mode

- Toggle button in header (sun/moon icon)
- Uses CSS custom properties (already in place) — just swap the `:root` values
- Persist preference in `localStorage`

---

## File Structure

All changes remain in `website/calculator.html` (single file, no build step). The embedded JS grows but stays under 2000 LOC total. If it exceeds this, split into:
- `website/calculator.html` (HTML + CSS)
- `website/js/engine.js` (calculation engine)
- `website/js/models.js` (preset library)
- `website/js/ui.js` (interactivity)

For now, keep everything in one file for simplicity.

---

## Implementation Priority

1. Model Preset Library (immediate value, low complexity)
2. Quick-Start Wizard (onboarding, medium complexity)
3. Enhanced Charts — TPS vs. Machines (high value, low complexity)
4. Export & Share (medium value, low complexity)
5. Scenario Comparison (high value, high complexity)
6. UX Polish (ongoing, can be incremental)
7. Sensitivity Chart (nice-to-have, medium complexity)
