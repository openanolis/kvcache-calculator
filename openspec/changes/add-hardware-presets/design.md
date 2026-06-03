## Context

The web calculator (`website/calculator.html`) currently defines GPU hardware in two places:
1. `GPU_SPECS` — a minimal array used by the Quick-Start Wizard with only `id`, `name`, and `memory_gb`
2. `PRESETS` — two full deployment configurations, both using H20 GPUs

Users on A100, H100, L40S, or other GPUs must manually fill every deployment field. The wizard picks a GPU type but doesn't know typical machine topologies or baseline TPS, so it fills in generic defaults (e.g., `baseline_per_card_tps: 1.0`).

## Goals / Non-Goals

**Goals:**
- Enrich `GPU_SPECS` with typical topology, baseline TPS, and common machine configurations
- Add model×hardware deployment presets covering the most common combinations
- Add a GPU hardware selector to the main Deployment form (not just the wizard)
- Auto-fill deployment fields when a GPU is selected from either the wizard or the main form

**Non-Goals:**
- Custom/user-defined GPU profiles (future scope)
- Benchmark-validated TPS numbers (we use reasonable estimates, clearly labeled)
- Changes to the calculation engine

## Decisions

**1. Enrich GPU_SPECS rather than creating a separate HARDWARE_LIBRARY**

Extend the existing `GPU_SPECS` array with additional fields. This avoids a second data structure and keeps the wizard integration simple.

New fields per GPU entry:
- `typical_cards_per_machine`: common topology (e.g., 8 for H100 DGX, 1 for L40S workstations)
- `baseline_tps_per_card`: estimated decode TPS without caching (rough, labeled as estimate)
- `max_cards_per_machine`: upper bound for validation

Alternative: Separate `HARDWARE_PROFILES` object — rejected because it would duplicate memory_gb and require cross-referencing.

**2. Model×Hardware deployment presets as a generated combination, not a static list**

Instead of manually writing N×M preset entries, create a `DEPLOYMENT_TEMPLATES` array keyed by GPU id. When a user selects both a model preset and a GPU type, the deployment fields auto-fill by combining model weight requirements with GPU capabilities.

Alternative: Static preset matrix — rejected because it scales as O(models × GPUs) and becomes hard to maintain.

**3. GPU selector in Deployment form section**

Add a `<select>` dropdown at the top of the Deployment card. Selecting a GPU auto-fills `machine_spec`, `gpu_memory_gb_per_card`, `cards_per_machine`, and `baseline_per_card_tps`. User can still override any field.

## Risks / Trade-offs

- **Baseline TPS estimates may mislead users** → Label clearly as "estimated baseline, actual performance varies by workload and framework". Use conservative values.
- **GPU market moves fast, specs become stale** → Keep the data structure simple so adding a new GPU is a 3-line change. Add a comment with date of last update.
- **cards_per_machine varies by deployment** → Use `typical_cards_per_machine` as a default but don't lock it — the field remains editable.
