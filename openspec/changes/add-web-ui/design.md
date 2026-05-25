## Context

The KVCache Upper Bound Oracle has a Python-based CLI that runs heuristic analysis for multi-agent KVCache sizing. There is already a `website/index.html` results dashboard that visualizes pre-computed JSON outputs using Chart.js. The goal is to add an interactive calculator page that performs the same `estimate-multi-agent` analysis entirely in the browser, requiring no backend.

The core calculation (`_hit_rate_for_capacity_tokens`, `_shape_fraction`, `_generalized_harmonic`, TPS gain) is pure math with no I/O dependencies — ideal for client-side porting.

## Goals / Non-Goals

**Goals:**
- Fully client-side calculator: zero backend, works from any static hosting (GitHub Pages, file://)
- Parity with `estimate-multi-agent` CLI output for hit rates, TPS gains, and capacity planning
- Preset configurations loadable from dropdown (matching `configs/public_multi_agent_*.json`)
- All parameters editable with immediate recalculation
- Visual output: results table + Chart.js charts for hit rate curves

**Non-Goals:**
- Porting the trace-based `analyze-buckets` command (requires large JSONL data files)
- Porting the `calibrate-multi-agent` command (requires trace I/O)
- Server-side rendering or API endpoints
- Mobile-first design (desktop-first, responsive as bonus)
- i18n for the calculator page (English only for v1)

## Decisions

### 1. Single HTML file with embedded JS/CSS

**Choice**: One self-contained `website/calculator.html` file.

**Rationale**: Matches the existing `website/index.html` pattern. No build step, no bundler, trivially deployable. The calculation logic is ~200 lines of JS — not enough to warrant modules.

**Alternatives considered**:
- Separate `.js`/`.css` files: adds complexity for marginal benefit at this scale
- React/Vue SPA: massive overkill for a form + table + chart

### 2. Port only the heuristic math to JavaScript

**Choice**: Re-implement `_hit_rate_for_capacity_tokens`, `_shape_fraction`, `_generalized_harmonic`, `tps_gain`, `cluster_capacity_tps`, and the saturation/capacity helpers.

**Rationale**: These are pure functions with clear inputs/outputs. The Python code is the reference implementation; the JS port can be validated against known config outputs.

**Alternatives considered**:
- Pyodide (Python in WASM): 10MB+ download, slow startup — unacceptable for an interactive calculator
- WebAssembly compiled from Python: complex toolchain, same startup penalty

### 3. Preset configs embedded as JSON objects in the HTML

**Choice**: Embed 2-3 preset configs (matching `configs/public_multi_agent_*.json`) as JS objects inside the calculator page.

**Rationale**: Avoids fetch/CORS issues when opening from `file://`. Keeps the page fully self-contained. Configs are small (<2KB each).

### 4. Chart.js for visualization (same as existing dashboard)

**Choice**: Use Chart.js (already loaded by the existing dashboard via CDN).

**Rationale**: Consistency with existing page. Already proven to work. Line chart showing hit rate vs. capacity GB is the primary visualization.

### 5. Real-time recalculation on parameter change

**Choice**: Debounced recalculation (100ms) triggered on any input change.

**Rationale**: The calculation is O(n) where n = zipf_population_blocks (max ~4096 iterations for harmonic sum). This completes in <5ms on any modern device — no need for web workers or lazy evaluation.

## Risks / Trade-offs

- **Numerical drift**: JS uses float64 exclusively vs Python's float64. Risk is minimal for this use case (hit rates are reported to 2-4 decimal places). → Mitigation: validate JS output against Python for all preset configs.
- **Maintenance burden**: Two implementations of the same math (Python + JS). → Mitigation: the JS port is small (~200 LOC), and the Python reference is authoritative. Add a comment in the JS referencing the Python source file.
- **Preset staleness**: If configs change, the embedded presets in HTML diverge. → Mitigation: document which config files each preset mirrors.
