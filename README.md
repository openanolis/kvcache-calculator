# KVCache Upper Bound Oracle

一个离线分析框架：既支持基于 trace 的精确上界分析，也支持不依赖 trace 的多 Agent heuristic 估计。输入模型信息和机器约束后，可以输出 KVCache 的内容天花板、容量上界、LRU 基线、规划结果，以及冷启动场景下的命中率估计。

## 项目产出

项目当前固定输出 5 类结果：

| 结果 | 含义 | 用途 |
|------|------|------|
| `content upper bound` | 不看容量时，内容本身最多能复用多少 | 判断 workload 值不值得做 KV cache |
| `relaxed upper bound` | 固定容量下，允许离线最优调度时的 event-level 上界 | 判断空间约束压掉了多少内容天花板 |
| `LRU baseline` | 固定容量下，标准 LRU 在线策略能做到多少 strict-prefix 命中 | 给出一个简单、可实现的策略基线 |
| `exact strict-prefix` | 固定容量下，strict-prefix 语义的真正最优值 | 核心结果；后续规划统一基于它 |
| `planning metrics` | 把 `exact strict-prefix` 和 `LRU` 命中率分别换算成 `TPS Gain`，并在提供目标 TPS 锚点后求最小卡数 / 机器数 | 分开看理论上界、策略落地成本和目标吞吐下的资源需求 |
| `multi-agent heuristic` | 无 trace 时，基于 `shared prefix + private working set + curve shape` 的冷启动估计 | 在没有 profile 的时候先粗估“容量 -> 命中 -> TPS -> 机器需求” |

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

kvcache-upper-bound estimate-multi-agent \
  --config configs/public_multi_agent_qwen3_5_27b.json \
  --output-dir outputs/heuristic_qwen_1x8

kvcache-upper-bound calibrate-multi-agent \
  --trace https://media.githubusercontent.com/media/alibaba-edu/qwen-bailian-usagetraces-anon/main/qwen_traceA_blksz_16.jsonl \
  --bucket-config configs/public_trace_qwen3_5_27b.json \
  --heuristic-config configs/public_multi_agent_qwen3_5_27b.json \
  --output-dir outputs/heuristic_qwen_1x8_calibrated \
  --max-records 5000
```

## 最少要配什么

配置示例见 `configs/public_trace_qwen3_5_27b.json`。

如果想故意放大 HBM 约束、观察单卡显存对命中率的限制，可以直接用
`configs/public_trace_qwen3_5_27b_1x1_h20.json`。

如果想直接看“统一目标总 TPS 下，1x8 和 1x1 两种部署形态怎么比较”，可以用
`configs/public_trace_qwen3_5_27b_planning_norm.json` 和
`configs/public_trace_qwen3_5_27b_1x1_h20_planning_norm.json`。
这两个样例把 `baseline_per_card_tps = 1.0`、`planning_target_total_tps = 8.0`
写死成归一化规划锚点，方便直接比较部署形态；它们是演示口径，不代表真实线上 TPS。

如果没有 trace、只想先做冷启动估计，可以直接用：

- `configs/public_multi_agent_qwen3_5_27b.json`
- `configs/public_multi_agent_qwen3_5_27b_1x1_h20.json`

这两份样例基于 `Qwen/Qwen3.5-27B` 的公开模型参数，分别演示 `1x8 h20` 和 `1x1 h20` 下的无 trace multi-agent heuristic 估计。

如果想先用一小段真实 trace 回标 `zipf_s` 和 `lru_like`，可以直接用：

- `--bucket-config configs/public_trace_qwen3_5_27b.json`
- `--heuristic-config configs/public_multi_agent_qwen3_5_27b.json`

这条路径会先用 trace 算 exact strict-prefix / LRU 观测值，再把 heuristic 里的 `zipf_s` 和 `lru_like` 回标到更贴近样本的位置，同时保留“这不是 oracle”的边界说明。

现在这条路径还会额外输出一份 `recommended_heuristic_config.json`：

- 它不是回标后的最优参数，而是 trace 结构建议器给出的模板。
- 它优先回答 `shared prefix / Delta / T / W / n` 应该怎么设。
- 如果 `content_gap` 很大，优先看它，而不是继续只调 `zipf_s / lru_like`。

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

无 trace heuristic 配置示例见 `configs/public_multi_agent_qwen3_5_27b.json`，额外字段如下：

| 字段 | 必填 | 说明 |
|------|------|------|
| `heuristic_multi_agent.concurrent_agents` | 是 | 并发 Agent 数 |
| `heuristic_multi_agent.shared_prefix_tokens` | 是 | 所有 Agent 共享前缀的 token 数 |
| `heuristic_multi_agent.avg_new_tokens_per_turn` | 是 | 每轮新增 token 数 |
| `heuristic_multi_agent.avg_turns_per_session` | 是 | 单会话平均轮数 |
| `heuristic_multi_agent.private_window_tokens` | 是 | 单 Agent 私有上下文窗口 |
| `heuristic_multi_agent.curve_mode` | 否 | `linear / power_law_fit / zipf_harmonic` |
| `heuristic_multi_agent.zipf_s` | 否 | Zipf 形状参数；`power_law_fit` 和 `zipf_harmonic` 都会用到 |
| `heuristic_multi_agent.policy_efficiency.lru_like` | 否 | 用一个效率系数近似在线策略损失；必须不超过 `1.0` |
| `deployments` | 是 | 无 trace 模式下的部署列表；字段与 trace 模式一致 |

约束固定如下：

- 不再接受 `machine_count`。
- 不再接受 `8*h20` 这种把数量写进 `machine_spec` 的格式。
- 不再接受 `*_per_machine` 形式的预算字段；预算统一使用单卡口径 `*_per_card`。

## 输出文件

| 文件 | 内容 | 什么时候看 |
|------|------|------------|
| `summary.csv` | 兼容总表，混合展示 HBM 主结果和主规划列 | 想快速扫一眼全部结果 |
| `hit_summary.csv` | HBM 主命中表；只放 `content / relaxed / LRU / strict-prefix` 以及“容量/策略瓶颈”诊断列 | 先判断当前 HBM 到底是被容量卡住，还是被策略卡住 |
| `planning_strict_prefix.csv` | 上界规划表；统一基于 exact strict-prefix 命中率，只保留 `TPS Gain / 估算总 TPS / 当前配置可承载总 TPS / 目标总 TPS 最小卡数 / 最小机器数` 这些主列 | 想看理论最优下的资源规划 |
| `planning_lru.csv` | 策略规划表；统一基于 LRU 命中率，只保留同一组主规划列 | 想看如果实际采用 LRU，需要多少机器 |
| `tier_summary.csv` | 容量层长表；把 `HBM / HBM+1T / HBM+10T ...` 展成多行，统一给出 `Strict-Prefix / LRU / 增益 / 诊断 / 规划` | 想比较扩容层之间到底差多少，不想看超宽表 |
| `heuristic_summary.csv` | 无 trace 主表；只保留 HBM 当前层的 heuristic 估计和主规划列 | 想快速看冷启动场景下当前部署的大致上限 |
| `heuristic_tier_summary.csv` | 无 trace 容量层长表；把 `HBM / HBM+1T / HBM+10T ...` 展成多行 | 想比较冷启动估计里不同容量层的变化 |
| `heuristic_report.zh.md` | 中文 heuristic 报告 | 想看假设、公式、参数和结果边界 |
| `heuristic_report.en.md` | 英文 heuristic 报告 | 想对外同步英文解释 |
| `calibration.json` | trace 回标摘要 | 想看观测目标、最佳参数和分层误差 |
| `calibration_trials.csv` | 参数网格搜索结果 | 想看 `zipf_s / lru_like` 的误差分布 |
| `calibrated_config.json` | 回标后的 heuristic 配置 | 想拿最佳参数直接继续跑冷启动估计 |
| `recommended_heuristic_config.json` | trace 结构建议模板 | 想先把 `shared prefix / Delta / T / W / n` 设到更贴近样本的位置 |
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
| `multi-agent heuristic` | 没有 trace 时，用 `shared/private` 工作集结构和曲线形状做的冷启动估计 |
| `trace-backed calibration` | 用小样本 trace 回标 `zipf_s / lru_like` 的过程；只做参数贴合，不做证明 |

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

`同负载估算卡数 / 机器数` 仍然保留在 `details.json`，但不再放进主 CSV。它只是“固定当前命中率不变时的算力等效值”，不能替代目标 TPS 下的真实部署规划。

主 CSV 现在默认只保留 HBM 当前层的核心结果；额外容量层改放到 `tier_summary.csv` 这张长表里。这样主表不再横向膨胀，而 `tier_summary.csv` 会额外给出：

- `Strict-Prefix 达到内容上界`
- `LRU 达到 Strict-Prefix`
- `当前主要瓶颈`
- `相对上一层 Strict-Prefix / LRU 增益`

所以如果你想回答“为什么 HBM 已经够了，LRU 加 1T 还能继续涨”，直接看 `tier_summary.csv` 就行。

## 文档入口

- `docs/design_guide.md`：实现口径和阶段边界。
- `docs/correctness_guide.md`：结果定义、证明范围和如何读表。
- `docs/four_layer_model.md`：对外展示用的四层框架说明，包含无 profile 时的 multi-agent heuristic 入口。
