# KVCache Upper Bound Oracle

一个面向 Bailian 匿名 trace 的离线分析器，用来在不同 window size、模型配置和机器约束下估计 KVCache 命中率上限。

当前已经实现：

- trace 读取：支持本地 JSONL 和 `http(s)` URL
- window 规范化：按 `strict_prefix_window` 生成 `EffectiveRequest`
- `content upper bound`：前缀复用极限命中率
- `capacity upper bound`：HBM 或 HBM+扩展空间下的 Belady relaxed 上限
- 业务分桶报表：输出 `分桶 / 机器数 / 规格 / 总 TPS / HBM KVCache 总大小 / 极限命中率 / HBM 空间命中率 / HBM+1T / HBM+10T`
- 正确性审计：输出 exhaustive reference 校验、最小 strict-prefix 反例和真实 trace 采样对账

设计约束和算法边界见 `docs/design_guide.md`，正确性口径见 `docs/correctness_guide.md`。

## 快速开始

```bash
python3 -m pip install -e .

kvcache-upper-bound analyze-buckets \
  --trace https://media.githubusercontent.com/media/alibaba-edu/qwen-bailian-usagetraces-anon/main/qwen_traceA_blksz_16.jsonl \
  --config configs/public_trace_qwen3_5_27b.json \
  --output-dir outputs/run_traceA \
  --max-records 5000

kvcache-upper-bound audit-buckets \
  --trace https://media.githubusercontent.com/media/alibaba-edu/qwen-bailian-usagetraces-anon/main/qwen_traceA_blksz_16.jsonl \
  --config configs/public_trace_qwen3_5_27b.json \
  --output-dir outputs/run_traceA_audit
```

输出目录至少包含：

- `summary.csv`：业务汇总表
- `details.json`：每个桶的 content/capacity 详细摘要
- `metadata.json`：本次运行参数与加载统计
- `correctness_report.json`：reference 校验与 bucket 侧证
- `correctness_report.md`：可直接阅读的正确性说明

## 配置说明

配置文件示例见：

- `configs/public_trace_qwen3_5_27b.json`

核心输入：

- `model_profile`：层数、KV heads、head dim、dtype、TP/PP
- 混合注意力模型要额外提供 `kv_cache_layer_count`，例如 `Qwen/Qwen3.5-27B` 用 `64` 层总层数，但只有 `16` 层 full attention 进入 token-linear KV cache
- `bucket_deployments[].hbm_kv_gb_per_machine`：每台机器可分给 KV 的 HBM 容量
- `bucket_deployments[].extra_capacity_tiers`：每台机器可追加的 host/SSD 容量，例如 1T 或 10T
- `bucket_deployments[].actual_hit_rate`：业务实测命中率，可选

## 正确性口径

- `极限命中率` 对应精确的 `content upper bound`
- `HBM KVCache 空间命中率` 当前是离线 Belady 的 `relaxed space upper bound`
- 详细说明见 `docs/correctness_guide.md`
