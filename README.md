# KVCache Upper Bound Oracle

一个面向 Bailian 匿名 trace 的离线分析器，用来在不同 window size、模型配置和机器约束下估计 KVCache 命中率上限。

当前已经实现：

- trace 读取：支持本地 JSONL 和 `http(s)` URL
- window 规范化：按 `strict_prefix_window` 生成 `EffectiveRequest`
- `content upper bound`：前缀复用极限命中率
- `capacity upper bound`：HBM 或 HBM+扩展空间下、允许 `no-admit` 的 Belady relaxed 上限
- `strict-prefix capacity oracle`：真正的严格前缀容量最优值；优先走证书快路，不够时再做精确搜索
- 业务分桶报表：输出 `分桶 / 机器数 / 规格 / 总 TPS / HBM KVCache 总大小 / 极限命中率 / HBM relaxed upper bound / HBM strict-prefix replay / HBM strict-prefix / proof source / HBM+1T / HBM+10T`
- 正确性审计：输出 exhaustive reference 校验、`relaxed == replay == exact strict-prefix` 的小规模穷举对账、真实 trace 采样对账，以及 strict-prefix exact proof path

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
- `correctness_report.md`：中文正确性说明
- `correctness_report.zh.md`：中文正确性说明
- `correctness_report.en.md`：英文正确性说明

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
- `HBM Relaxed Upper Bound 命中率` 是允许 `no-admit` 的离线 Belady 上界
- `HBM Strict-Prefix Replay 命中率` 是把 relaxed-optimal 调度按 strict-prefix 语义重计后的结果；在当前穷举验证空间里，它与 exact strict-prefix oracle 一致
- `HBM Strict-Prefix 命中率` 来自真正的 exact strict-prefix oracle
- `HBM Strict-Prefix 求解路径` 为 `certificate` 或 `search`；前者表示被 `replay == content` 或 `relaxed == replay` 直接夹出，后者表示证书不足时进入精确搜索
- audit 报告会显式给出 `strict-prefix` 的穷举等价校验结论
- 概念解释、直观例子和当前已验证的等价关系见 `docs/correctness_guide.md`
