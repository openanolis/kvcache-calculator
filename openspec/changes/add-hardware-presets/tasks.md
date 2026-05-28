## 1. Enrich GPU Hardware Data

- [x] 1.1 Expand `GPU_SPECS` array with new fields (`typical_cards_per_machine`, `max_cards_per_machine`, `baseline_tps_per_card`) and add H100 NVL, H200, A800, L20 entries alongside existing GPUs
- [x] 1.2 Update wizard Step 2 to use enriched GPU data: auto-fill `cards_per_machine` from `typical_cards_per_machine` and show `baseline_tps_per_card` in suggestion text

## 2. GPU Selector in Deployment Form

- [x] 2.1 Add GPU hardware `<select>` dropdown to the Deployment form card (above existing fields), populated from `GPU_SPECS` with a "Custom" option
- [x] 2.2 Wire dropdown change handler to auto-fill `machine_spec`, `gpu_memory_gb_per_card`, `cards_per_machine`, and `baseline_per_card_tps`

## 3. Model×Hardware Deployment Presets

- [x] 3.1 Add deployment presets combining models with non-H20 GPUs (at least: Llama 3.1 70B on 8×A100-80G, Qwen2.5-72B on 8×H100, Mistral 7B on 1×L40S) to the PRESETS object
- [x] 3.2 Update the preset `<select>` dropdown to list the new model×hardware combinations

## 4. Validation

- [x] 4.1 Run JS parity validation (`node tests/validate_js_parity.mjs`) to confirm the calculation engine is unchanged
- [x] 4.2 Verify page loads and new GPU selections correctly fill deployment fields
