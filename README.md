# KVCache Upper Bound Oracle

一个面向 Bailian 匿名 trace 的离线分析器，用来在不同 window size、模型配置和机器约束下估计 KVCache 命中率上限。

当前已经实现：

- trace 读取：支持本地 JSONL 和 `http(s)` URL
- window 规范化：按 `strict_prefix_window` 生成 `EffectiveRequest`
- `content upper bound`：前缀复用极限命中率
- `capacity upper bound`：HBM 或 HBM+扩展空间下、允许 `no-admit` 的 Belady relaxed 上限
- `strict-prefix capacity oracle`：真正的严格前缀容量最优值；优先走证书快路，不够时再做精确搜索
- 命中率后处理：用 `TPS(C) = TPS0 / (1 - alpha * h(C))` 把 exact strict-prefix 命中率映射到 `TPS Gain / 同负载估算卡数 / 同负载估算机器数 / 估算总 TPS`
- 分桶报表：兼容输出 `summary.csv`，同时拆出 `hit_summary.csv` 和 `planning_summary.csv`，把核心命中估算与派生规划结果分开
- 正确性审计：输出 exhaustive reference 校验、`relaxed == replay == exact strict-prefix` 的小规模穷举对账、真实 trace 采样对账，以及 strict-prefix exact proof path

设计约束和算法边界见 `docs/design_guide.md`，正确性口径见 `docs/correctness_guide.md`。
如果要看对外展示用的 `容量 -> 命中 -> TPS -> 机器需求` 简化模型，见 `docs/four_layer_model.md`。

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

- `summary.csv`：兼容汇总表，同时包含命中结果和派生规划列
- `hit_summary.csv`：核心命中估算表，只放内容/容量/strict-prefix 命中结果
- `planning_summary.csv`：派生规划表，明确标出它基于 exact strict-prefix 命中率推导
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
- `model_profile.parameter_count` + `weight_dtype_bytes`：可选；如果要从显存反推 KV 预算，就需要它们
- `bucket_deployments[].accelerator_count`：总卡数；建议显式提供
- `bucket_deployments[].cards_per_machine`：单机卡数；提供后报表会把 `机器数` 和 `卡数` 分开
- `bucket_deployments[].hbm_kv_gb_per_machine`：兼容字段名，当前按“每张卡可分给 KV 的 HBM 容量”解释
- `bucket_deployments[].gpu_memory_gb_per_machine`：兼容字段名，当前按“每张卡的显存大小”解释；项目会按 `单卡显存 - 模型权重分片 - runtime reserve` 推出理论 KV HBM 容量
- `bucket_deployments[].runtime_reserve_gb_per_machine`：可选；默认 `0`
- `bucket_deployments[].extra_capacity_tiers`：每台机器可追加的 host/SSD 容量，例如 1T 或 10T
- `prefill_savings_alpha`：命中后可节省的 prefill 比例，默认 `0.8`
- `bucket_deployments[].actual_hit_rate`：实测命中率，可选

兼容说明：

- 老配置里的 `machine_count` 仍然接受，但现在按“总卡数”解释
- 如果要让报表里的 `机器数` 代表真实物理机，请同时提供 `cards_per_machine`

公开配置 `configs/public_trace_qwen3_5_27b.json` 现在走的是推导路径：

- `Qwen/Qwen3.5-27B` 参数量：`27,781,419,504`
- 权重精度：`BF16 = 2 bytes`
- 总权重大小：约 `51.75 GiB`
- `tp_size = 8`，所以每卡权重分片约 `6.47 GiB`
- `h20 = 96 GiB`，默认 `runtime reserve = 0`
- 公开配置现在显式写成 `1` 机 `8` 卡，所以总 HBM KV 预算按 `8 * (96 - 6.47)` 计算
- 理论单卡 KV HBM 预算约为 `96 - 6.47 = 89.53 GiB`

## 正确性口径

- `极限命中率` 对应精确的 `content upper bound`
- `HBM Relaxed Upper Bound 命中率` 是允许 `no-admit` 的离线 Belady 上界
- `HBM Strict-Prefix Replay 命中率` 是把 relaxed-optimal 调度按 strict-prefix 语义重计后的结果；在当前穷举验证空间里，它与 exact strict-prefix oracle 一致
- `HBM Strict-Prefix 命中率` 来自真正的 exact strict-prefix oracle
- `HBM Strict-Prefix 求解路径` 为 `certificate` 或 `search`；前者表示被 `replay == content` 或 `relaxed == replay` 直接夹出，后者表示证书不足时进入精确搜索
- `planning_summary.csv` 里的 `HBM TPS Gain / HBM 同负载估算卡数 / HBM 同负载估算机器数 / HBM 估算总 TPS` 统一基于 exact strict-prefix 命中率计算；额外容量层的 TPS 列也采用相同公式
- audit 报告会显式给出 `strict-prefix` 的穷举等价校验结论
- 概念解释、直观例子和当前已验证的等价关系见 `docs/correctness_guide.md`
