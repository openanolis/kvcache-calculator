## Why

The web calculator's deployment presets only include H20 GPU configurations. Users deploying on A100, H100, L40S, or other hardware must manually configure every deployment field. The wizard has a GPU type dropdown but lacks per-GPU baseline TPS estimates and typical machine topologies, making the "guided setup" less useful for non-H20 hardware.

## What Changes

- Expand `GPU_SPECS` with richer metadata: typical cards_per_machine, baseline TPS per card, common machine labels
- Add full deployment presets combining each model with popular GPU configurations (e.g., Llama 3.1 70B on 4×A100-80G, Qwen3-27B on 1×H100)
- Update the wizard's Step 2 (Hardware Configuration) to auto-fill deployment fields from enriched GPU_SPECS
- Add GPU selection dropdown to the main Deployment form section (not just the wizard) so users can pick hardware without going through the wizard

## Capabilities

### New Capabilities
- `hardware-presets`: Enriched GPU hardware definitions with per-GPU metadata (memory, typical topology, baseline TPS) and model×hardware deployment preset combinations

### Modified Capabilities

## Impact

- `website/calculator.html`: GPU_SPECS data, PRESETS object, wizard Step 2, Deployment form section
- No backend changes — all client-side
- No calculation engine changes — deployment parameters are input-only
