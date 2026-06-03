## ADDED Requirements

### Requirement: Enriched GPU hardware definitions
The system SHALL define GPU hardware entries in `GPU_SPECS` with the following fields: `id`, `name`, `memory_gb`, `typical_cards_per_machine`, `max_cards_per_machine`, and `baseline_tps_per_card`.

The system SHALL include at minimum these GPU types:
- H20 (96GB)
- H100 (80GB)
- H100 NVL (94GB)
- H200 (141GB)
- A100 (80GB)
- A100 (40GB)
- A800 (80GB)
- L40S (48GB)
- L20 (48GB)

#### Scenario: GPU entry has all required fields
- **WHEN** a GPU entry exists in `GPU_SPECS`
- **THEN** it SHALL have `id`, `name`, `memory_gb`, `typical_cards_per_machine`, `max_cards_per_machine`, and `baseline_tps_per_card` fields

#### Scenario: All listed GPU types are present
- **WHEN** the page loads
- **THEN** `GPU_SPECS` SHALL contain entries for H20, H100, H100 NVL, H200, A100 (80GB), A100 (40GB), A800, L40S, and L20

### Requirement: GPU selector in Deployment form
The system SHALL provide a GPU hardware dropdown in the Deployment form section. Selecting a GPU SHALL auto-fill `machine_spec`, `gpu_memory_gb_per_card`, `cards_per_machine`, and `baseline_per_card_tps` from the selected GPU's metadata.

#### Scenario: User selects GPU from deployment dropdown
- **WHEN** user selects "H100 (80GB)" from the GPU dropdown in the Deployment form
- **THEN** `machine_spec` SHALL be set to "h100", `gpu_memory_gb_per_card` to 80, `cards_per_machine` to 8, and `baseline_per_card_tps` to the H100's defined baseline

#### Scenario: User selects Custom GPU
- **WHEN** user selects "Custom" from the GPU dropdown
- **THEN** no deployment fields SHALL be auto-filled and all fields SHALL remain editable

### Requirement: Wizard uses enriched GPU data
The wizard's Step 2 (Hardware Configuration) SHALL use the enriched `GPU_SPECS` to auto-fill `cards_per_machine` and `baseline_per_card_tps` in addition to the existing `gpu_memory_gb_per_card`.

#### Scenario: Wizard GPU selection fills topology
- **WHEN** user selects "A100 (80GB)" in the wizard's GPU type dropdown
- **THEN** the wizard SHALL use `typical_cards_per_machine` from GPU_SPECS when computing deployment defaults

### Requirement: Model×Hardware deployment presets
The system SHALL provide combined deployment presets that pair popular models with common GPU configurations. The PRESETS object SHALL include configurations for at least 3 different GPU types (not just H20).

#### Scenario: User selects a non-H20 preset
- **WHEN** the preset dropdown includes "Llama 3.1 70B (8×A100-80G)"
- **THEN** selecting it SHALL fill all model profile and deployment fields with A100-specific values

#### Scenario: Preset uses correct GPU-specific values
- **WHEN** a preset using H100 GPUs is loaded
- **THEN** `gpu_memory_gb_per_card` SHALL be 80, `machine_spec` SHALL be "h100", and `baseline_per_card_tps` SHALL match the H100 entry in GPU_SPECS
