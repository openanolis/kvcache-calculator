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

## 概念速查

第一次看这个项目时，最容易混淆的不是代码，而是“这些命中率到底各自代表什么”。可以先按下面这张表记：

| 概念 | 一句话解释 | 应该怎么理解 |
|------|------------|--------------|
| `block` | 默认 `16 tokens` 一个分析单位 | 项目主粒度；命中率先按 block 算 |
| `prefix path` | 从请求第 1 个 block 开始的连续前缀路径 | 真正可复用的 KV 对象，不是“单独某个相同 block” |
| `极限命中率` | 不考虑空间限制时，内容本身最多能复用多少 | 对应 `content upper bound`，是内容天花板 |
| `HBM Relaxed Upper Bound 命中率` | 考虑 HBM 空间，但放松 strict-prefix 连续约束后的 event-level 最优值 | 是一个容量上界，用来解释“空间最优调度最多能保住多少命中” |
| `HBM Strict-Prefix Replay 命中率` | 把 relaxed 最优调度按 strict-prefix 语义重新计数后的结果 | 是一个可实现下界/证书，帮助解释 exact 值 |
| `HBM Strict-Prefix 命中率` | 真正的 strict-prefix capacity oracle 最优值 | 当前最重要的容量结果；后续规划统一基于它 |
| `HBM Strict-Prefix 求解路径` | `certificate` 或 `search` | 表示 exact 值是被证书直接夹出，还是通过精确搜索得到 |
| `Prefill 节省系数 alpha` | 命中收益能兑现成吞吐收益的比例 | 不是命中率本身，而是“命中 -> TPS” 的折算参数 |
| `TPS Gain` | 命中率折算后的吞吐放大倍数 | 当前用 `1 / (1 - alpha * h)` 计算，其中 `h` 是 exact strict-prefix 命中率 |
| `同负载估算卡数/机器数` | 在同样总负载下，理论上需要多少卡/机器 | 当前卡数或机器数除以 `TPS Gain` |
| `估算总 TPS` | 在不缩容时，理论上能跑到多少总 TPS | 当前 `总 TPS * TPS Gain` |
| `TPS 输入口径` | 配置里的 `total_tps` 原本是按集群、按机器还是按卡填写 | 报表里的 `总 TPS` 永远会先归一到集群总 TPS |

一个最短主线是：

```text
内容天花板 -> 容量上限 -> exact strict-prefix 命中率 -> TPS Gain -> 卡数/机器数规划
```

如果你只看结果表，建议这样读：

1. 先看 `极限命中率`，判断 workload 本身有没有复用空间。
2. 再看 `HBM Strict-Prefix 命中率`，判断在当前 HBM 下真正能保住多少。
3. 再看 `HBM+单机 1T / 10T`，判断额外 host/SSD 容量还能带来多少提升。
4. 最后再看 `TPS Gain / 同负载估算卡数 / 同负载估算机器数`，把命中率翻译成资源规划语言。

## 配置说明

配置文件示例见：

- `configs/public_trace_qwen3_5_27b.json`

核心输入：

- `model_profile`：层数、KV heads、head dim、dtype、TP/PP
- 混合注意力模型要额外提供 `kv_cache_layer_count`，例如 `Qwen/Qwen3.5-27B` 用 `64` 层总层数，但只有 `16` 层 full attention 进入 token-linear KV cache
- `model_profile.parameter_count` + `weight_dtype_bytes`：可选；如果要从显存反推 KV 预算，就需要它们
- `bucket_deployments[].accelerator_count`：必填，总卡数
- `bucket_deployments[].cards_per_machine`：必填，单机卡数；报表里的 `机器数 = accelerator_count / cards_per_machine`
- `bucket_deployments[].machine_spec`：必填，纯规格标签，例如 `h20`；不要再把数量编码进 `machine_spec`
- `bucket_deployments[].total_tps`：可选；原始 TPS 输入值
- `bucket_deployments[].total_tps_unit`：可选，`cluster_total / per_machine / per_card` 三选一；报表里的 `总 TPS` 永远是换算后的集群总 TPS，同时保留 `TPS 输入口径`
- `bucket_deployments[].hbm_kv_gb_per_machine`：当前按“单卡可分给 KV 的 HBM 容量”解释
- `bucket_deployments[].gpu_memory_gb_per_machine`：当前按“单卡显存大小”解释；项目会按 `单卡显存 - 模型权重分片 - runtime reserve` 推出理论 KV HBM 容量
- `bucket_deployments[].runtime_reserve_gb_per_machine`：可选；当前按“单卡 runtime 预留显存”解释，默认 `0`
- `bucket_deployments[].extra_capacity_tiers`：每台机器可追加的 host/SSD 容量，例如 1T 或 10T
- `prefill_savings_alpha`：命中后可节省的 prefill 比例，默认 `0.8`
- `bucket_deployments[].actual_hit_rate`：实测命中率，可选

约束：

- `machine_count` 不再接受；必须显式提供 `accelerator_count` 和 `cards_per_machine`
- `machine_spec` 不再接受 `8*h20` 这类隐式写法；数量只能放在显式字段里

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
- `Prefill 节省系数 alpha` 是命中收益兑现系数：命中率本身不直接等于 TPS 提升，项目当前用 `TPS Gain = 1 / (1 - alpha * h)` 把 exact strict-prefix 命中率 `h` 折算成吞吐收益
- `planning_summary.csv` 里的 `HBM TPS Gain / HBM 同负载估算卡数 / HBM 同负载估算机器数 / HBM 估算总 TPS` 统一基于 exact strict-prefix 命中率计算；额外容量层的 TPS 列也采用相同公式
- audit 报告会显式给出 `strict-prefix` 的穷举等价校验结论
- 概念解释、直观例子和当前已验证的等价关系见 `docs/correctness_guide.md`
