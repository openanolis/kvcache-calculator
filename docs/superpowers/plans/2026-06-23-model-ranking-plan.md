# Model Ranking Feature Implementation Plan

**Date:** 2026-06-23
**Feature:** Model KVCache Size Ranking
**Branch:** feat/model-ranking

## Overview

Implement a model ranking feature that allows users to compare different models by their KV cache size requirements. The feature will be available both in the web UI (calculator.html) and as a CLI command.

## Context

From brainstorming session:
- **Platform:** Both web UI and CLI
- **Metrics:** KV bytes per token AND total KV cache for configurable sequence lengths
- **Model scope:** Existing presets only (Qwen3-27B, Llama3.1-70B, Qwen2.5-72B, Mistral-7B, Llama3.1-8B, DeepSeek-V3-671B)
- **UI presentation:** New section in calculator
- **Deployment config:** Include tp_size/pp_size to show per-rank KV cache size

## Implementation Tasks

### Task 1: Extract Model Registry

**Goal:** Create a single source of truth for model specifications

**Steps:**
1. Extract model profiles from PRESETS into a separate MODELS object
2. Each model entry includes: name, family, model_profile, description
3. Update PRESETS to reference MODELS instead of duplicating model_profile
4. Verify calculator still works with existing presets

**Files:** `website/calculator.html`

**Verification:** Open calculator.html, select different presets, verify model fields populate correctly

---

### Task 2: Add Ranking Calculation Functions (JavaScript)

**Goal:** Implement ranking logic in the web calculator

**Steps:**
1. Add `calculateModelRanking()` function that:
   - Takes sequence_length as input
   - Iterates through all models in MODELS
   - Calculates for each model:
     - `kv_bytes_per_token` (using kvBytesPerToken)
     - `kv_bytes_per_token_per_rank` (using kvBytesPerTokenPerRank)
     - `total_kv_bytes` = kv_bytes_per_token * sequence_length
     - `total_kv_bytes_per_rank` = kv_bytes_per_token_per_rank * sequence_length
     - `total_kv_gb` = total_kv_bytes / BYTES_PER_GB
   - Returns sorted array (default: by total_kv_gb descending)
2. Add `formatBytes()` helper for human-readable byte formatting
3. Add `renderRankingTable(rankingData, sortBy)` function that:
   - Renders HTML table with columns: Rank, Model, KV/Token, KV/Token/Rank, Total KV (X tokens), Total GB
   - Supports sorting by clicking column headers
   - Highlights currently selected model

**Files:** `website/calculator.html`

**Verification:** Open browser console, call `calculateModelRanking(8192)`, verify output structure

---

### Task 3: Add Model Ranking UI Section

**Goal:** Create user-facing ranking interface in calculator

**Steps:**
1. Add new section after "Model Preset" card:
   ```html
   <div class="card">
     <div class="card-title">Model KVCache Ranking</div>
     <div class="card-body">
       <label>Sequence Length (tokens)</label>
       <input type="number" id="ranking-sequence-length" value="8192" />
       <button id="calculate-ranking-btn">Calculate Ranking</button>
       <div id="ranking-table-container"></div>
     </div>
   </div>
   ```
2. Style the section with CSS (add to existing <style> block)
3. Wire up event listeners:
   - "Calculate Ranking" button triggers calculateModelRanking() with input value
   - Render results in #ranking-table-container
4. Add auto-calculate on page load with default 8192 tokens
5. Add sort functionality to table headers

**Files:** `website/calculator.html`

**Verification:**
- Open calculator.html
- Verify ranking section appears
- Click "Calculate Ranking" button
- Verify table renders with all models
- Click column headers to sort
- Change sequence length and recalculate

---

### Task 4: Implement CLI Command

**Goal:** Add `rank-models` subcommand to Python CLI

**Steps:**
1. Create `src/kvcache_upper_bound/cli/rank_models.py`:
   - Add `add_rank_models_parser(subparsers)` function
   - Arguments:
     - `--sequence-length` (required, int, can specify multiple)
     - `--format` (csv or markdown, default: markdown)
     - `--output` (optional file path, default: stdout)
   - Main function `run_rank_models(args)`:
     - Load model profiles from configs/ or hardcoded registry
     - For each model, calculate metrics for each sequence length
     - Format output as markdown table or CSV
     - Write to output or stdout
2. Register command in `src/kvcache_upper_bound/__main__.py`
3. Add model registry to `src/kvcache_upper_bound/core/models.py`:
   - `MODEL_REGISTRY` dict with preset model profiles
   - Helper function `get_all_model_profiles()`

**Files:**
- `src/kvcache_upper_bound/cli/rank_models.py` (new)
- `src/kvcache_upper_bound/__main__.py`
- `src/kvcache_upper_bound/core/models.py`

**Verification:**
```bash
python -m kvcache_upper_bound rank-models --sequence-length 4096 --sequence-length 8192
python -m kvcache_upper_bound rank-models --sequence-length 32768 --format csv
```

---

### Task 5: Test and Polish

**Goal:** Ensure feature works end-to-end and matches existing code quality

**Steps:**
1. Web UI testing:
   - Test with different sequence lengths (1024, 8192, 32768, 131072)
   - Verify sorting works for all columns
   - Test with different model presets selected (should highlight in table)
   - Check responsive design on mobile viewport
2. CLI testing:
   - Test markdown output format
   - Test CSV output format
   - Test with multiple sequence lengths
   - Test output to file
3. Edge cases:
   - Very small sequence length (1 token)
   - Very large sequence length (1M tokens)
   - Models with kv_cache_layer_count set vs null
4. Documentation:
   - Add section to README.md about rank-models command
   - Update README.zh.md with Chinese translation
   - Add inline comments explaining ranking formula

**Files:**
- `README.md`
- `README.zh.md`
- `website/calculator.html` (polish CSS/UX)

**Verification:**
- Run through all test scenarios above
- Verify no console errors
- Verify CLI help text is clear

---

## Success Criteria

1. ✅ Web UI shows ranking table with all preset models
2. ✅ Users can input custom sequence lengths and see total KV cache
3. ✅ Table is sortable by any column
4. ✅ CLI command outputs ranking in both markdown and CSV formats
5. ✅ Metrics include both per-token and total KV cache sizes
6. ✅ Deployment config (tp_size/pp_size) is reflected in per-rank calculations
7. ✅ Currently selected model is highlighted in the ranking table
8. ✅ Documentation updated in both README files

## Technical Notes

- KV bytes per token formula: `2 * layers * n_kv_heads * head_dim * dtype_bytes`
- Use `kv_cache_layer_count` if set, otherwise `n_layers`
- Per-rank calculation divides by `tp_size * pp_size`
- Total KV = per-token * sequence_length
- Sort default: by total KV cache descending (largest first)

## Dependencies

- No new Python dependencies
- No new JavaScript dependencies (uses vanilla JS)
- Reuses existing model profile structure and calculation functions
