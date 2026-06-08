# Implementation Plan: Guided Calculator for Industry Adoption

## Task 1: Add Hero Answer Section

1. Add CSS styles for `.hero-answer` card: large font primary line, secondary line, bottleneck badge, gradient ring
2. Add HTML for the hero card between the export bar and metrics grid:
   ```html
   <div class="card hero-answer" id="hero-answer" style="display:none">...</div>
   ```
3. Add `renderHeroAnswer(summary, config)` function that:
   - Computes TPS gain from `tpsGain(summary.contentHitRate, config.prefill_savings_alpha)`
   - Computes effective GPU equivalent = `config.deployment.accelerator_count * tpsGain`
   - Determines bottleneck: compare `summary.strictSatGb` vs `summary.hbmKvGbPerCard * config.deployment.accelerator_count`
   - Renders primary answer text, secondary savings line, and bottleneck badge
4. Call `renderHeroAnswer()` from `computeAndRender()` after computing summary
5. **Verify**: Load page, select a preset, confirm hero section appears with sensible text

## Task 2: Add Recommendation Panel

1. Add CSS for `.recommendation-panel` card with icon + advice text
2. Add HTML for recommendation card after hero section
3. Add `renderRecommendation(summary, config)` function with bottleneck logic:
   - Capacity-bound: suggest more GPUs or higher-HBM cards
   - Policy-bound: note LRU vs optimal gap
   - Well-balanced: positive feedback
   - Low hit rate (<20%): warn about limited reuse
   - High hit rate (>80%): positive feedback
4. Call from `computeAndRender()`
5. **Verify**: Test with different presets (capacity-bound vs policy-bound scenarios)

## Task 3: Add Metric Tooltips

1. Define `METRIC_TOOLTIPS` object mapping metric labels to plain-language descriptions
2. Update `renderMetrics()` to add an info icon `(i)` after each label
3. Add CSS for tooltip hover behavior (absolute positioned, max-width 250px)
4. **Verify**: Hover over each metric, confirm tooltip appears with correct text

## Task 4: Add Wizard Step 4 (Results)

1. Add `wizardStep === 4` branch in `renderWizardStep()`
2. In step 3, change "Apply & Close" to compute results and go to step 4
3. Step 4 renders:
   - Hero answer (reuse `renderHeroAnswer` logic but into wizard box)
   - Three "What if?" buttons (back to step 2, back to step 3, close to full view)
   - Share button
4. Update step indicator to show "Step 4 of 4"
5. **Verify**: Complete wizard, confirm step 4 shows results, "What if?" buttons work

## Task 5: Visual Polish

1. Add fade-in animation to hero and recommendation cards (CSS transition on opacity)
2. Add color coding to metrics: green for hit rate >60%, yellow for 20-60%, red for <20%
3. Add subtle gradient border to hero card
4. **Verify**: Visual inspection across dark and light themes

## Task 6: Final Validation

1. Run JS parity tests: `node tests/validate_js_parity.mjs`
2. Test all preset selections (deployment presets + dataset presets)
3. Test wizard flow end-to-end
4. Test shareable URL generation and loading
5. Test dark/light theme toggle
6. Test responsive layout (narrow viewport)
