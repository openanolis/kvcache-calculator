# KVCache Upper Bound Oracle

一个离线分析框架：输入 trace、模型信息和机器约束，输出 KVCache 的内容天花板、容量上界、LRU 基线，以及基于 exact strict-prefix 的规划结果。

## 项目产出

项目当前固定输出 5 类结果：

| 结果 | 含义 | 用途 |
|------|------|------|
| `content upper bound` | 不看容量时，内容本身最多能复用多少 | 判断 workload 值不值得做 KV cache |
| `relaxed upper bound` | 固定容量下，允许离线最优调度时的 event-level 上界 | 判断空间约束压掉了多少内容天花板 |
| `LRU baseline` | 固定容量下，标准 LRU 在线策略能做到多少 strict-prefix 命中 | 给出一个简单、可实现的策略基线 |
| `exact strict-prefix` | 固定容量下，strict-prefix 语义的真正最优值 | 核心结果；后续规划统一基于它 |
| `planning metrics` | 把 exact strict-prefix 命中率换算成 `TPS Gain / 估算总 TPS / 同负载估算卡数 / 机器数` | 做缩容和扩容评估 |

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

## 最少要配什么

配置示例见 `configs/public_trace_qwen3_5_27b.json`。

| 字段 | 必填 | 说明 |
|------|------|------|
| `model_profile` | 是 | `n_layers / n_kv_heads / head_dim / dtype_bytes / block_size` |
| `model_profile.kv_cache_layer_count` | 混合注意力模型必填 | 只统计真正进入 token-linear KV cache 的层 |
| `bucket_deployments[].accelerator_count` | 是 | 总卡数 |
| `bucket_deployments[].cards_per_machine` | 是 | 单机卡数；`机器数 = accelerator_count / cards_per_machine` |
| `bucket_deployments[].machine_spec` | 是 | 纯规格标签，例如 `h20` |
| `bucket_deployments[].hbm_kv_gb_per_card` | 二选一 | 直接给单卡可用 KV 空间 |
| `bucket_deployments[].gpu_memory_gb_per_card` | 二选一 | 按 `显存 - 权重分片 - runtime reserve` 反推单卡 KV 空间 |
| `bucket_deployments[].runtime_reserve_gb_per_card` | 否 | 单卡 runtime 预留显存 |
| `bucket_deployments[].total_tps` | 否 | 原始吞吐输入 |
| `bucket_deployments[].total_tps_unit` | 否 | `cluster_total / per_machine / per_card` |
| `bucket_deployments[].extra_capacity_tiers` | 否 | 每台机器追加的 host/SSD KV 空间 |
| `prefill_savings_alpha` | 否 | 命中收益兑现成吞吐收益的比例，默认 `0.8` |

约束固定如下：

- 不再接受 `machine_count`。
- 不再接受 `8*h20` 这种把数量写进 `machine_spec` 的格式。
- 不再接受 `*_per_machine` 形式的预算字段；预算统一使用单卡口径 `*_per_card`。

## 输出文件

| 文件 | 内容 | 什么时候看 |
|------|------|------------|
| `summary.csv` | 兼容总表，混合展示命中结果和规划结果 | 想快速扫一眼全部结果 |
| `hit_summary.csv` | 只放命中相关列：content / relaxed / LRU / strict-prefix | 只关心 KV 命中估算 |
| `planning_summary.csv` | 只放规划列；统一基于 exact strict-prefix 命中率 | 只关心缩容、扩容和 TPS |
| `details.json` | 每个桶的详细统计摘要 | 想查具体数字和中间结果 |
| `metadata.json` | 输入参数、加载统计、归一化后的桶配置 | 想确认这次运行到底按什么口径算的 |
| `correctness_report.zh.md` | 中文正确性报告 | 想确认结果边界和证明路径 |
| `correctness_report.en.md` | 英文正确性报告 | 对外同步英文结论 |

## 核心术语

| 术语 | 一句话解释 |
|------|------------|
| `content upper bound` | 不看容量时的内容复用天花板 |
| `relaxed upper bound` | 固定容量下的 event-level 离线最优上界 |
| `LRU baseline` | 固定容量下的标准 LRU 在线策略结果 |
| `strict-prefix replay` | 把 relaxed 调度按 strict-prefix 语义重计后的可实现结果 |
| `exact strict-prefix` | strict-prefix 语义下的真正最优值 |
| `alpha` | 命中收益换算成吞吐收益的兑现系数 |

结果关系可以直接记成：

```text
LRU baseline <= exact strict-prefix <= relaxed upper bound <= content upper bound
```

`planning_summary.csv` 里的 `TPS Gain / 估算总 TPS / 同负载估算卡数 / 同负载估算机器数` 统一基于 `exact strict-prefix`，不基于 LRU，也不基于 relaxed。

## 文档入口

- `docs/design_guide.md`：实现口径和阶段边界。
- `docs/correctness_guide.md`：结果定义、证明范围和如何读表。
- `docs/four_layer_model.md`：对外展示用的四层框架说明。
