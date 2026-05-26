## ADDED Requirements

### Requirement: Interactive parameter input form
The calculator page SHALL present a form with all parameters needed for multi-agent heuristic analysis, grouped into logical sections: Model Profile, Multi-Agent Heuristic, Deployment Configuration, and Analysis Settings.

#### Scenario: Page loads with default preset
- **WHEN** user opens the calculator page
- **THEN** all form fields SHALL be populated with the first preset configuration (Qwen3-27B on H20)

#### Scenario: User selects a different preset
- **WHEN** user selects a preset from the configuration dropdown
- **THEN** all form fields SHALL update to reflect that preset's values
- **AND** results SHALL recalculate immediately

#### Scenario: User modifies a parameter
- **WHEN** user changes any numeric input field
- **THEN** the results SHALL recalculate within 200ms of the last keystroke

### Requirement: Model Profile parameters
The form SHALL include editable fields for: n_layers, kv_cache_layer_count, n_kv_heads, head_dim, dtype_bytes, parameter_count, weight_dtype_bytes, tp_size, pp_size, block_size.

#### Scenario: All model profile fields present
- **WHEN** user views the Model Profile section
- **THEN** all fields listed above SHALL be visible and editable as numeric inputs

### Requirement: Multi-Agent Heuristic parameters
The form SHALL include editable fields for: concurrent_agents, shared_prefix_tokens, avg_new_tokens_per_turn, avg_turns_per_session, private_window_tokens, curve_mode (dropdown: linear/power_law_fit/zipf_harmonic), zipf_s, zipf_population_blocks, lru_like efficiency, strict_prefix_upper_bound efficiency.

#### Scenario: Curve mode selection affects visible fields
- **WHEN** user selects curve_mode "zipf_harmonic"
- **THEN** zipf_s and zipf_population_blocks fields SHALL be visible
- **WHEN** user selects curve_mode "linear"
- **THEN** zipf_s and zipf_population_blocks fields MAY be hidden or grayed out

### Requirement: Deployment Configuration parameters
The form SHALL include editable fields for: label, accelerator_count, cards_per_machine, machine_spec, gpu_memory_gb_per_card, total_tps, total_tps_unit (dropdown), baseline_per_card_tps, planning_target_total_tps, and at least one extra_capacity_tier with label and kv_gb_per_machine.

#### Scenario: Add extra capacity tier
- **WHEN** user clicks "Add Tier" button
- **THEN** a new tier row SHALL appear with label and kv_gb_per_machine fields

#### Scenario: Remove extra capacity tier
- **WHEN** user clicks remove button on a tier row
- **THEN** that tier SHALL be removed and results recalculated

### Requirement: Prefill savings alpha parameter
The form SHALL include an editable field for prefill_savings_alpha with default value 0.8.

#### Scenario: Alpha value affects TPS gain
- **WHEN** user sets prefill_savings_alpha to 0.5
- **THEN** all TPS gain values in results SHALL reflect the updated alpha

### Requirement: Calculation parity with Python implementation
The JavaScript calculator SHALL produce hit rate values within 0.001 absolute tolerance of the Python `analyze_multi_agent_heuristic` function for identical inputs.

#### Scenario: Preset config produces matching results
- **WHEN** calculator runs with the embedded Qwen3-27B preset
- **THEN** strict_prefix_hit_rate and lru_like_hit_rate SHALL match Python CLI output within 0.001

#### Scenario: Generalized harmonic sum correctness
- **WHEN** calculating zipf_harmonic curve with zipf_s=1.3 and population_blocks=4096
- **THEN** the generalized harmonic partial sums SHALL match Python's `_generalized_harmonic` within float64 precision

### Requirement: Results table display
The calculator SHALL display a results table showing per-tier rows with columns: Tier Label, Total KV GB, Total KV Tokens, Strict Prefix Hit Rate, LRU-like Hit Rate, Content Hit Rate, Strict Prefix TPS Gain, LRU-like TPS Gain, and bottleneck indicator.

#### Scenario: Multiple tiers displayed
- **WHEN** deployment has HBM tier plus 2 extra capacity tiers
- **THEN** results table SHALL show 3 rows (HBM, tier1, tier2) with all columns populated

#### Scenario: Hit rates displayed as percentages
- **WHEN** results are calculated
- **THEN** hit rates SHALL be displayed as percentages with 2 decimal places (e.g., "85.32%")

### Requirement: Hit rate chart visualization
The calculator SHALL display a Chart.js line chart plotting hit rate (y-axis, 0-100%) versus total KV capacity in GB (x-axis) for both strict_prefix and lru_like policies.

#### Scenario: Chart updates on recalculation
- **WHEN** user changes any parameter
- **THEN** the chart SHALL update to reflect new hit rate curves

#### Scenario: Content ceiling line shown
- **WHEN** chart renders
- **THEN** a horizontal dashed line SHALL indicate the content_hit_rate ceiling

### Requirement: Summary metrics panel
The calculator SHALL display key summary metrics: content_hit_rate, working_set_tokens, saturation_capacity_gb (strict and LRU), average_request_tokens, and kv_bytes_per_token.

#### Scenario: Summary updates on recalculation
- **WHEN** any parameter changes
- **THEN** summary metrics SHALL reflect the recalculated values

### Requirement: No server dependency
The calculator SHALL run entirely in the browser with no backend API calls, server-side processing, or database access. All computation MUST happen in client-side JavaScript.

#### Scenario: Works from file:// protocol
- **WHEN** user opens calculator.html directly from filesystem
- **THEN** all functionality SHALL work (presets load, calculation runs, chart renders)

### Requirement: Navigation integration
The existing dashboard page (`website/index.html`) SHALL include a visible link/button to the calculator page.

#### Scenario: User navigates from dashboard to calculator
- **WHEN** user is on the results dashboard
- **THEN** a navigation element (link or button) SHALL be visible that opens calculator.html
