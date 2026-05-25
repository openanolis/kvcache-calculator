## Why

The KVCache Upper Bound Oracle currently requires Python installation and CLI usage to estimate cache hit rates and capacity planning. A browser-based interactive calculator would let users experiment with parameters (model profile, deployment config, multi-agent heuristic settings) instantly without any backend or installation — making the tool accessible to product managers, architects, and anyone evaluating KVCache sizing.

## What Changes

- Add a new interactive web page (`website/calculator.html`) that runs the full `estimate-multi-agent` heuristic analysis entirely in the browser using JavaScript
- Port the core calculation logic (hit rate curves, TPS gain estimation, capacity planning) from Python to JavaScript
- Provide preset configurations (e.g., Qwen3-27B on H20) selectable via dropdown, with all parameters editable
- Display results as interactive tables and charts (hit rate vs. capacity, TPS gains per tier)
- Link the new calculator page from the existing results dashboard

## Capabilities

### New Capabilities
- `browser-calculator`: Interactive browser-based KVCache heuristic calculator that ports the `estimate-multi-agent` analysis to client-side JavaScript, with parameter controls and visual result display

### Modified Capabilities
<!-- No existing spec-level requirements are changing -->

## Impact

- **New files**: `website/calculator.html` (single-page app with embedded JS/CSS)
- **Modified files**: `website/index.html` (add navigation link to calculator)
- **Dependencies**: Chart.js (already used by existing dashboard), no server-side dependencies
- **No breaking changes**: existing CLI and Python library behavior is unchanged
