# KVCache Upper Bound Oracle

一个离线分析框架：输入 trace、模型信息和机器约束，输出 KVCache 的内容天花板、容量上界、LRU 基线，以及分别基于 `exact strict-prefix` 和 `LRU` 的规划结果。

## 项目产出

项目当前固定输出 5 类结果：

| 结果 | 含义 | 用途 |
|------|------|------|
| `content upper bound` | 不看容量时，内容本身最多能复用多少 | 判断 workload 值不值得做 KV cache |
| `relaxed upper bound` | 固定容量下，允许离线最优调度时的 event-level 上界 | 判断空间约束压掉了多少内容天花板 |
| `LRU baseline` | 固定容量下，标准 LRU 在线策略能做到多少 strict-prefix 命中 | 给出一个简单、可实现的策略基线 |
| `exact strict-prefix` | 固定容量下，strict-prefix 语义的真正最优值 | 核心结果；后续规划统一基于它 |
| `planning metrics` | 把 `exact strict-prefix` 和 `LRU` 命中率分别换算成 `TPS Gain`，并在提供目标 TPS 锚点后求最小卡数 / 机器数 | 分开看理论上界、策略落地成本和目标吞吐下的资源需求 |

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

如果想故意放大 HBM 约束、观察单卡显存对命中率的限制，可以直接用
`configs/public_trace_qwen3_5_27b_1x1_h20.json`。

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
| `bucket_deployments[].baseline_per_card_tps` | 否 | 绝对规划锚点；表示无命中收益时的单卡基线 TPS |
| `bucket_deployments[].planning_target_total_tps` | 否 | 目标总 TPS；提供后会输出“最小卡数 / 最小机器数” |
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
| `planning_strict_prefix.csv` | 上界规划表；统一基于 exact strict-prefix 命中率 | 想看理论最优下最多能省多少机器 |
| `planning_lru.csv` | 策略规划表；统一基于 LRU 命中率 | 想看如果实际采用 LRU，需要多少机器 |
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

`planning_strict_prefix.csv` 和 `planning_lru.csv` 使用同一套规划公式，但命中率来源不同：

- `planning_strict_prefix.csv`：`h = exact strict-prefix hit rate`
- `planning_lru.csv`：`h = lru hit rate`

如果同时提供 `baseline_per_card_tps` 和 `planning_target_total_tps`，规划表还会额外输出：

- `当前配置可承载总 TPS`
- `目标总 TPS 最小卡数`
- `目标总 TPS 最小机器数`

这组列是自洽的绝对规划结果：搜索时会把“卡数变化 -> HBM/扩展容量变化 -> 命中率变化 -> 集群总 TPS 变化”放进同一个闭环。

`同负载估算卡数 / 机器数` 仍然保留，但它只是“固定当前命中率不变时的算力等效值”，不能替代目标 TPS 下的真实部署规划。

## 文档入口

- `docs/design_guide.md`：实现口径和阶段边界。
- `docs/correctness_guide.md`：结果定义、证明范围和如何读表。
- `docs/four_layer_model.md`：对外展示用的四层框架说明。
