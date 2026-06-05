# Builtin Dataset Registry

## Context

The kvcache-calculator currently only references one public trace dataset (qwen-bailian-usagetraces-anon) and requires users to manually write JSON config files with model profiles and deployment parameters. There is no way to quickly try the tool against known-good datasets without assembling all configuration by hand.

## Goals

- Create a shared JSON dataset registry that both the Python CLI and web calculator consume
- Add builtin shortcuts (`--dataset <name>`) to the CLI so users can run analysis with zero config
- Add a "Load Public Dataset" UI to the web calculator
- Include production traces, conversation datasets, and agent workload datasets

## Non-Goals

- Bundling actual trace data in the repo (we link to external URLs)
- Auto-downloading HuggingFace datasets that require authentication
- Building new converter formats for agent trajectories (future scope — Tier 3 datasets are listed for reference but conversion support is deferred)

## Design

### 1. Registry File: `datasets/registry.json`

A single JSON file at the repo root. Each entry:

```json
{
  "datasets": [
    {
      "id": "bailian-traceA",
      "name": "Qwen-Bailian Trace A",
      "description": "Production Qwen3-27B serving trace from Alibaba Bailian platform",
      "source": "alibaba-edu/qwen-bailian-usagetraces-anon",
      "trace_url": "https://media.githubusercontent.com/media/alibaba-edu/qwen-bailian-usagetraces-anon/main/qwen_traceA_blksz_16.jsonl",
      "format": "native",
      "tier": "production-traces",
      "model_id": "qwen3-27b",
      "model_profile": {
        "n_layers": 64,
        "kv_cache_layer_count": 16,
        "n_kv_heads": 4,
        "head_dim": 256,
        "dtype_bytes": 2,
        "parameter_count": 27781419504,
        "weight_dtype_bytes": 2,
        "block_size": 16
      },
      "default_deployment": {
        "label": "8xH20",
        "accelerator_count": 8,
        "cards_per_machine": 8,
        "machine_spec": "h20",
        "gpu_memory_gb_per_card": 96,
        "baseline_per_card_tps": 1.0
      },
      "default_heuristic": {
        "concurrent_agents": 2048,
        "shared_prefix_tokens": 4096,
        "avg_new_tokens_per_turn": 4096,
        "avg_turns_per_session": 8,
        "private_window_tokens": 65536,
        "curve_mode": "zipf_harmonic",
        "zipf_s": 1.3,
        "zipf_population_blocks": 4096,
        "policy_efficiency": {
          "strict_prefix_upper_bound": 1.0,
          "lru_like": 0.6
        }
      },
      "tags": ["production", "MLA", "multi-turn"],
      "request_count": null,
      "paper": null
    }
  ]
}
```

Fields:
- `id` — CLI shortcut name
- `format` — `"native"` (has hash_ids), `"conversation"` (needs conversion), `"agent-trajectory"` (needs agent converter)
- `tier` — `"production-traces"`, `"conversation-datasets"`, `"agent-workloads"`
- `model_id` — links to MODEL_LIBRARY in the web calculator (nullable)
- `model_profile` — full ModelProfile for the CLI
- `default_deployment` — sensible default deployment config
- `default_heuristic` — default heuristic parameters for estimate-multi-agent
- `tags`, `request_count`, `paper` — metadata for display

### 2. Datasets Included

**Tier 1 — Production Traces (native hash_ids):**
- `bailian-traceA` — Qwen-Bailian production trace (Qwen3-27B, 8xH20)
- `mooncake-kimi` — Mooncake/Kimi production trace (FAST 2025 Best Paper)
- `ragpulse` — RAGPulse university QA trace (structured component-level hash_ids)

**Tier 2 — Conversation Datasets (need conversion):**
- `wildchat-1m` — WildChat-1M real user-ChatGPT conversations
- `oasst2` — OpenAssistant OASST2 tree-structured conversations
- `lmsys-chat-1m` — LMSYS-Chat-1M conversations

**Tier 3 — Agent Workloads (need conversion, listed for reference):**
- `simia-tau-90k` — Simia-Tau customer service agent (91K trajectories, 2-58 turns)
- `swe-smith` — SWE-smith coding agent trajectories (76K rows)
- `toolbench` — ToolBench API orchestration (189K rows, 16K+ APIs)
- `telos-agent` — Telos agent trajectories (19.5K, 23 domains)
- `mcp-agent` — MCP agent benchmark (49 trajectories, real MCP protocol)

### 3. CLI Integration

New module `src/kvcache_upper_bound/datasets/`:
- `registry.py` — loads `datasets/registry.json`, provides `list_datasets()` and `get_dataset(id)`
- `resolver.py` — resolves `--dataset <id>` to full `HeuristicAnalysisConfig` or trace URL + `BucketAnalysisConfig`

New subcommand: `list-datasets` — prints available datasets as a table.

`--dataset` flag added to `estimate-multi-agent` and `analyze-buckets`:
- `estimate-multi-agent --dataset <id>` — builds config from registry (model_profile + default_deployment + default_heuristic)
- `analyze-buckets --dataset <id>` — resolves trace_url + builds bucket config from registry
- `--dataset` and `--config` are mutually exclusive

### 4. Web Calculator Integration

The registry data is inlined into `calculator.html` as a `DATASET_REGISTRY` JS array (same pattern as `MODEL_LIBRARY`, `GPU_SPECS`).

A "Public Datasets" `<optgroup>` is added to the existing preset dropdown, grouped by tier. Selecting a dataset entry:
- Auto-fills model profile fields from `model_profile`
- Auto-fills deployment fields from `default_deployment`
- Auto-fills heuristic parameters from `default_heuristic`
- Shows dataset description, source link, and tags as info text
- For Tier 2/3 datasets, shows a note: "For trace-based analysis, use the CLI"

## Risks / Trade-offs

- **External URLs may break** — trace URLs point to GitHub raw/LFS. If repos move or go private, the shortcut fails. Mitigation: `list-datasets` shows URL status; registry entries can be updated without code changes.
- **Tier 3 datasets need new converters** — agent trajectory formats (OpenAI messages with tool_calls) aren't supported by the current converter. The registry includes them for reference and heuristic estimation, but trace-based analysis is deferred.
- **Registry JSON duplicates MODEL_LIBRARY data** — the model_profile in each dataset entry overlaps with MODEL_LIBRARY entries. This is intentional: the CLI should not depend on the web calculator's data, and the registry is the single source of truth for dataset configs.
