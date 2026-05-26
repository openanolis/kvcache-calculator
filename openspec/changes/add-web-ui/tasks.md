## 1. Core Calculation Engine (JavaScript)

- [x] 1.1 Implement `generalizedHarmonic(n, s)` function matching Python's `_generalized_harmonic`
- [x] 1.2 Implement `shapeFraction(ratio, curveShape)` supporting linear, power_law_fit, and zipf_harmonic modes
- [x] 1.3 Implement `hitRateForCapacityTokens(capacityTokens, heuristic, efficiency)` matching Python logic
- [x] 1.4 Implement helper functions: `gbToTokens`, `tokensToGb`, `kvBytesPerToken`, `tpsGain`, `estimatedTotalTps`, `clusterCapacityTps`
- [x] 1.5 Implement `MultiAgentHeuristic` class with methods: `averageReusablePrivateTokensPerAgent`, `averageRequestTokens`, `contentHitRate`, `totalWorkingSetTokens`, `strictSaturationCapacityTokens`, `policySaturationCapacityTokens`
- [x] 1.6 Implement `analyzeMultiAgentHeuristic(config)` that produces tier rows and scenario summaries
- [x] 1.7 Validate JS output against Python preset config output (Qwen3-27B) to confirm parity within 0.001

## 2. Page Structure and Styling

- [x] 2.1 Create `website/calculator.html` with HTML boilerplate, Chart.js CDN, and CSS matching existing dashboard theme (dark mode, same color tokens)
- [x] 2.2 Build page layout: header with nav link back to dashboard, main content with form panel and results panel side-by-side
- [x] 2.3 Style form sections (Model Profile, Multi-Agent Heuristic, Deployment, Analysis Settings) with card styling matching existing dashboard

## 3. Parameter Input Form

- [x] 3.1 Add preset configuration dropdown with embedded JSON presets (Qwen3-27B default, Qwen3-27B-H20)
- [x] 3.2 Build Model Profile form section: n_layers, kv_cache_layer_count, n_kv_heads, head_dim, dtype_bytes, parameter_count, weight_dtype_bytes, tp_size, pp_size, block_size
- [x] 3.3 Build Multi-Agent Heuristic form section: concurrent_agents, shared_prefix_tokens, avg_new_tokens_per_turn, avg_turns_per_session, private_window_tokens, curve_mode dropdown, zipf_s, zipf_population_blocks, policy efficiencies
- [x] 3.4 Build Deployment form section: label, accelerator_count, cards_per_machine, machine_spec, gpu_memory_gb_per_card, total_tps, total_tps_unit, baseline_per_card_tps, planning_target_total_tps
- [x] 3.5 Build extra capacity tiers UI with dynamic add/remove buttons
- [x] 3.6 Add prefill_savings_alpha input field with default 0.8

## 4. Results Display

- [x] 4.1 Build summary metrics panel showing: content_hit_rate, working_set_tokens, saturation capacities, avg_request_tokens, kv_bytes_per_token
- [x] 4.2 Build results table with columns: Tier, Total KV GB, KV Tokens, Strict Prefix Hit Rate, LRU Hit Rate, Content Ceiling, TPS Gain (Strict), TPS Gain (LRU), Bottleneck
- [x] 4.3 Implement Chart.js line chart: hit rate vs. capacity GB with strict_prefix and lru_like lines plus content ceiling dashed line
- [x] 4.4 Add TPS capacity planning results (estimated total TPS, min cards/machines for target)

## 5. Interactivity and Integration

- [x] 5.1 Wire up debounced recalculation (100ms) on any form input change event
- [x] 5.2 Implement preset loading: populate all form fields when dropdown changes
- [x] 5.3 Handle curve_mode toggle: show/hide zipf-specific fields based on selection
- [x] 5.4 Add navigation link from existing `website/index.html` dashboard to calculator page
- [x] 5.5 Test full flow: load page, switch presets, modify parameters, verify chart and table update correctly
