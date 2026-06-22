#!/usr/bin/env node
/**
 * Validates the JavaScript calculator engine against Python-generated test vectors.
 *
 * Usage: node tests/validate_js_parity.mjs
 *
 * Extracts the calculation engine from website/calculator.html,
 * runs it against test vectors in tests/test_vectors_heuristic.json,
 * and reports any divergence beyond tolerance (0.001 for rates, 0.01 for GB).
 */
import { readFileSync } from "fs";
import { createContext, Script } from "vm";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");

// Extract the JS engine portion from calculator.html (everything between <script> and "// UI Logic")
const html = readFileSync(join(ROOT, "website", "calculator.html"), "utf-8");
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) {
  console.error("FAIL: Could not extract <script> from calculator.html");
  process.exit(1);
}

const fullScript = scriptMatch[1];
const uiMarker = "// ═══════════════════════════════════════════════════════════════════\n  // UI Logic";
const engineEnd = fullScript.indexOf(uiMarker);
const engineCode = engineEnd > 0 ? fullScript.substring(0, engineEnd) : fullScript;

// Create a sandbox to run the engine
const sandbox = {};
const ctx = createContext(sandbox);
new Script(engineCode).runInContext(ctx);

// Load test vectors
const vectors = JSON.parse(readFileSync(join(ROOT, "tests", "test_vectors_heuristic.json"), "utf-8"));

// Tolerance thresholds
const RATE_TOL = 0.001;       // hit rates
const GB_TOL = 0.01;          // GB values
const TOKEN_TOL = 1.0;        // token counts
const TPS_TOL = 0.01;         // TPS values
const INT_TOL = 0;            // integer values (exact)

let totalChecks = 0;
let failures = 0;

function check(label, actual, expected, tolerance) {
  totalChecks++;
  if (expected === null && actual === null) return;
  if (expected === null || actual === null) {
    if (expected === null && actual === undefined) return;
    if (expected === null && actual === null) return;
    console.error(`  FAIL ${label}: expected=${expected}, actual=${actual}`);
    failures++;
    return;
  }
  if (!isFinite(expected) && !isFinite(actual)) return;
  const diff = Math.abs(actual - expected);
  if (diff > tolerance) {
    console.error(`  FAIL ${label}: expected=${expected}, actual=${actual}, diff=${diff.toExponential(3)} (tol=${tolerance})`);
    failures++;
  }
}

// Additional test configs not in the HTML's PRESETS (edge cases)
const EXTRA_CONFIGS = {
  "edge-linear-small": {
    model_profile: { n_layers: 32, kv_cache_layer_count: null, n_kv_heads: 8, head_dim: 128, dtype_bytes: 2, parameter_count: 7000000000, weight_dtype_bytes: 2, tp_size: 1, pp_size: 1, block_size: 16 },
    prefill_savings_alpha: 0.7,
    heuristic_multi_agent: { concurrent_agents: 512, shared_prefix_tokens: 2048, avg_new_tokens_per_turn: 1024, avg_turns_per_session: 4, private_window_tokens: 8192, curve_mode: "linear", zipf_s: 1.3, zipf_population_blocks: 4096, policy_efficiency: { strict_prefix_upper_bound: 1.0, lru_like: 0.7 } },
    deployment: { label: "1x1-a100", accelerator_count: 1, cards_per_machine: 1, machine_spec: "a100", gpu_memory_gb_per_card: 80, total_tps: 2.0, total_tps_unit: "cluster_total", baseline_per_card_tps: 2.0, planning_target_total_tps: 16.0, extra_capacity_tiers: [{ label: "HBM+512G", kv_gb_per_machine: 512 }] }
  },
  "edge-saturated": {
    model_profile: { n_layers: 64, kv_cache_layer_count: 16, n_kv_heads: 4, head_dim: 256, dtype_bytes: 2, parameter_count: 27781419504, weight_dtype_bytes: 2, tp_size: 8, pp_size: 1, block_size: 16 },
    prefill_savings_alpha: 0.8,
    heuristic_multi_agent: { concurrent_agents: 64, shared_prefix_tokens: 8192, avg_new_tokens_per_turn: 2048, avg_turns_per_session: 3, private_window_tokens: 16384, curve_mode: "zipf_harmonic", zipf_s: 1.5, zipf_population_blocks: 2048, policy_efficiency: { strict_prefix_upper_bound: 1.0, lru_like: 0.8 } },
    deployment: { label: "4x8-h20", accelerator_count: 32, cards_per_machine: 8, machine_spec: "h20", gpu_memory_gb_per_card: 96, total_tps: 32.0, total_tps_unit: "cluster_total", baseline_per_card_tps: 1.0, planning_target_total_tps: 32.0, extra_capacity_tiers: [{ label: "HBM+2T", kv_gb_per_machine: 2048 }] }
  }
};

// Map preset names to config objects matching the JS engine's format
function buildJsConfig(vector) {
  const name = vector.name;
  if (EXTRA_CONFIGS[name]) return EXTRA_CONFIGS[name];
  const presets = new Script("PRESETS").runInContext(ctx);
  return presets[name];
}

// Run the analysis function from the sandbox
function runAnalysis(config) {
  const runScript = new Script(`
    (function(cfg) {
      harmonicCache.clear();
      return analyzeMultiAgentHeuristic(cfg);
    })
  `);
  const fn = runScript.runInContext(ctx);
  return fn(config);
}

console.log("KVCache Calculator JS Parity Validation");
console.log("=".repeat(50));

for (const vector of vectors) {
  console.log(`\nTesting: ${vector.name}`);

  const config = buildJsConfig(vector);
  if (!config) {
    console.error(`  SKIP: No matching preset found for "${vector.name}"`);
    continue;
  }

  const result = runAnalysis(config);
  const summary = result.summary;
  const expected = vector.summary;

  // Summary checks
  check("content_hit_rate", summary.contentHitRate, expected.content_hit_rate, RATE_TOL);
  check("average_request_tokens", summary.avgRequest, expected.average_request_tokens, TOKEN_TOL);
  check("total_working_set_tokens", summary.totalWorkingSet, expected.total_working_set_tokens, TOKEN_TOL);
  check("avg_private_tokens", summary.avgPrivate, expected.avg_reusable_private_tokens_per_agent, TOKEN_TOL);
  check("hbm_kv_gb_per_card", summary.hbmKvGbPerCard, expected.hbm_kv_gb_per_card, GB_TOL);
  check("strict_saturation_gb", summary.strictSatGb, expected.strict_prefix_saturation_capacity_gb, GB_TOL);
  check("lru_saturation_gb", summary.lruSatGb, expected.lru_like_saturation_capacity_gb, GB_TOL);

  // Tier row checks
  const expectedRows = vector.tier_rows;
  if (result.rows.length !== expectedRows.length) {
    console.error(`  FAIL tier_row count: expected=${expectedRows.length}, actual=${result.rows.length}`);
    failures++;
    continue;
  }

  for (let i = 0; i < expectedRows.length; i++) {
    const er = expectedRows[i];
    const ar = result.rows[i];
    const prefix = `tier[${i}](${er.tier_label})`;

    check(`${prefix}.total_kv_gb`, ar.totalKvGb, er.total_kv_gb, GB_TOL);
    check(`${prefix}.strict_hit_rate`, ar.strictPrefixHitRate, er.strict_prefix_hit_rate, RATE_TOL);
    check(`${prefix}.lru_hit_rate`, ar.lruLikeHitRate, er.lru_like_hit_rate, RATE_TOL);
    check(`${prefix}.content_hit_rate`, ar.contentHitRate, er.content_hit_rate, RATE_TOL);
    check(`${prefix}.bottleneck`, ar.bottleneck === er.bottleneck ? 0 : 1, 0, 0);
    check(`${prefix}.strict_tps_gain`, ar.strictTpsGain, er.strict_tps_gain, TPS_TOL);
    check(`${prefix}.lru_tps_gain`, ar.lruTpsGain, er.lru_tps_gain, TPS_TOL);
    check(`${prefix}.strict_est_tps`, ar.strictEstimatedTotalTps, er.strict_estimated_total_tps, TPS_TOL);
    check(`${prefix}.lru_est_tps`, ar.lruEstimatedTotalTps, er.lru_estimated_total_tps, TPS_TOL);
    check(`${prefix}.strict_cluster_tps`, ar.strictClusterCapacityTps, er.strict_cluster_capacity_tps, TPS_TOL);
    check(`${prefix}.lru_cluster_tps`, ar.lruClusterCapacityTps, er.lru_cluster_capacity_tps, TPS_TOL);

    if (er.strict_min_cards !== null) check(`${prefix}.strict_min_cards`, ar.strictMinCards, er.strict_min_cards, INT_TOL);
    if (er.strict_min_machines !== null) check(`${prefix}.strict_min_machines`, ar.strictMinMachines, er.strict_min_machines, INT_TOL);
    if (er.lru_min_cards !== null) check(`${prefix}.lru_min_cards`, ar.lruMinCards, er.lru_min_cards, INT_TOL);
    if (er.lru_min_machines !== null) check(`${prefix}.lru_min_machines`, ar.lruMinMachines, er.lru_min_machines, INT_TOL);
  }
}

console.log("\n" + "=".repeat(50));
if (failures === 0) {
  console.log(`PASS: All ${totalChecks} checks passed.`);
  process.exit(0);
} else {
  console.error(`FAIL: ${failures}/${totalChecks} checks failed.`);
  process.exit(1);
}
