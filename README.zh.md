# KVCache Upper Bound Oracle

一个用来回答"我这套部署，KV cache 到底能帮上多少忙"的离线分析工具。

给它一段真实流量 trace（或者只给模型规格和 Agent 场景描述），它会告诉你：

- 这份流量里**有多少内容是值得复用的**——也就是命中率的天花板在哪里。
- 你现在的显存预算下，**实际能拿到多少**——以及缺的那部分到底是被显存卡住了，还是被策略（比如 LRU）卡住了。
- 把命中率换算成吞吐之后，**为了打到目标 TPS，至少需要多少张卡、多少台机器**。
- 如果还没有 trace，只有"几个 Agent 共享一段系统提示词"这种粗略描述，**也能先给一个冷启动估计**，方便提前做容量规划。

它不是 serving runtime，不参与在线调度；纯离线算账。

## 适合什么场景

- **新业务上线前估容量**：还没有真实流量，但知道大概的 Agent 数、共享 prompt 长度、对话轮数，想先估出"上 1 机 8 卡 H20 够不够"。
- **已有流量做规划**：手头有一段 JSONL trace，想看清楚换更大显存 / 加一层 host KV / 换部署形态之后，吞吐能提多少。
- **对比策略损失**：想知道"理论最优"和"实际跑 LRU"之间差多少——也就是策略带来的损失值不值得为它做优化。
- **回标参数**：手上有一小段 trace，但更想用一组通用公式推到其他场景；这里支持用 trace 把 heuristic 的关键参数（Zipf 形状、LRU 效率系数）回标到更贴近现实的位置。

## 它会算出什么

无论是 trace 模式还是 heuristic 模式，结果都围绕同一组指标展开。理解这几个指标，就能看懂所有输出表：

- **内容天花板（content upper bound）**：假设容量无限大，这份流量里最多能复用多少。这是判断"这个 workload 值不值得做 KV cache"的第一道门槛。
- **容量上界（relaxed upper bound）**：固定显存下，允许"上帝视角"做离线最优调度时能拿到的命中率。代表了空间被吃掉之后剩下的最优值。
- **严格前缀最优（exact strict-prefix）**：在容量上界之上，再加一个"必须按前缀语义命中"的约束——这才是真正可实现的最优。**后续所有 TPS 和机器数规划都基于它**。
- **LRU 基线**：同样的容量下，老老实实跑标准 LRU 能拿到多少。一个简单、可落地的策略下限。
- **TPS / 机器数规划**：把命中率乘上 alpha（命中收益兑现成吞吐的系数），换算成吞吐增益；再结合"无命中时的单卡基线 TPS"和"目标总 TPS"，反推最小需要多少卡、多少台机器。

四者的关系永远满足：

```text
LRU 基线  ≤  严格前缀最优  ≤  容量上界  ≤  内容天花板
```

读结果时盯住两个差值就够了：

- **内容天花板 − 严格前缀最优**：差距大 → 被显存卡住，加容量有用。
- **严格前缀最优 − LRU 基线**：差距大 → 被策略卡住，换更聪明的缓存策略才有用。

## 快速开始

先安装：

```bash
python3 -m pip install -e .
```

工具提供了 4 个子命令，用途各不相同。**新人建议从 `estimate-multi-agent` 开始**，它不需要任何 trace 数据，最容易跑起来。

### 1. 没 trace，先做冷启动估计

只要写一份 Agent 场景描述（共享 prompt 多长、多少并发 Agent、每轮新增多少 token 等），就能得到一份命中率和机器数估算。

```bash
kvcache-upper-bound estimate-multi-agent \
  --config configs/public_multi_agent_qwen3_5_27b.json \
  --output-dir outputs/heuristic_qwen_1x8
```

适合：还没有真实流量，但要先给 PRD 或容量评审一个数。

### 2. 有 trace，做精确分析

给一段 JSONL 流量 trace，工具会按 prompt token 数把请求划分到若干长度桶（在配置里通过 `lower_tokens` / `upper_tokens` 定义，例如 `0–32K`、`32K–64K`、`64K–128K` 等），每个桶都独立算出内容天花板、容量上界、严格前缀最优、LRU 基线，以及对应的 TPS / 机器数规划。

```bash
kvcache-upper-bound analyze-buckets \
  --trace https://media.githubusercontent.com/media/alibaba-edu/qwen-bailian-usagetraces-anon/main/qwen_traceA_blksz_16.jsonl \
  --config configs/public_trace_qwen3_5_27b.json \
  --output-dir outputs/run_traceA \
  --max-records 5000
```

`--max-records` 在调试期可以先取一小段（比如 5000 条）跑通流程，确认配置无误后再去掉它跑全量。

适合：手上已有真实 trace，要做容量规划或者部署形态对比。

### 3. 想顺便核对结果是否可信

`audit-buckets` 做的事和 `analyze-buckets` 完全一样，但会**额外**抽取一段小样本用朴素实现重算一遍，并比对 strict-prefix 的几种解法是否互相吻合。最终把"哪些结果已被严格证明、哪些只是辅助证据"写进 `correctness_report.zh.md` / `.en.md`。

```bash
kvcache-upper-bound audit-buckets \
  --trace https://media.githubusercontent.com/media/alibaba-edu/qwen-bailian-usagetraces-anon/main/qwen_traceA_blksz_16.jsonl \
  --config configs/public_trace_qwen3_5_27b.json \
  --output-dir outputs/run_traceA_audit
```

`--sample-request-limit` 控制对账采样的请求数（默认 256）。这个值只影响穷举对账的覆盖范围，不影响主分析的命中率结果——主分析永远走全量。

适合：第一次接手项目，或者改了 oracle 的实现，想确认结果没跑偏。

### 4. 用 trace 回标 heuristic 参数

如果你的目标是"用一组通用公式去外推到很多场景"，但又怀疑 heuristic 默认参数不够贴合实际，可以拿一段小 trace 把 heuristic 里的两个关键参数（Zipf 形状 `zipf_s` 和 LRU 效率系数 `lru_like`）回标到更接近观测值的位置。

```bash
kvcache-upper-bound calibrate-multi-agent \
  --trace https://media.githubusercontent.com/media/alibaba-edu/qwen-bailian-usagetraces-anon/main/qwen_traceA_blksz_16.jsonl \
  --bucket-config configs/public_trace_qwen3_5_27b.json \
  --heuristic-config configs/public_multi_agent_qwen3_5_27b.json \
  --output-dir outputs/heuristic_qwen_1x8_calibrated \
  --max-records 5000
```

这条命令会同时输出两份建议：

- 一份回标后的 heuristic 配置 `calibrated_config.json`，参数已经按观测值微调。
- 一份基于 trace 反推出来的"结构模板" `recommended_heuristic_config.json`，告诉你共享前缀长度、私有窗口、并发 Agent 数这些**结构性参数**该怎么设。如果发现回标后的命中率和观测值差距还很大（在报告里体现为 `content_gap` 偏大），那应该优先调结构模板，而不是继续拧 `zipf_s` / `lru_like`。

适合：希望把 heuristic 参数稳定下来，之后用它去推到没 trace 的场景。

## 配置怎么写

`configs/` 目录下放了一批可以直接照抄的样例。挑一份最接近你场景的复制出来改即可。

### 样例一览

| 样例 | 用途 |
|------|------|
| `public_trace_qwen3_5_27b.json` | 1 机 8 卡 H20 的 trace 分析样例。容量基本不构成约束，适合先看上界。 |
| `public_trace_qwen3_5_27b_1x1_h20.json` | 1 机 1 卡 H20 的 trace 分析样例。专门用来放大单卡显存约束，看 HBM 怎么压低命中率。 |
| `public_trace_qwen3_5_27b_planning_norm.json` | 在 1 机 8 卡基础上把基线 TPS 设为 1、目标 TPS 设为 8，做归一化规划演示。 |
| `public_trace_qwen3_5_27b_1x1_h20_planning_norm.json` | 在 1 机 1 卡基础上做同样的归一化规划演示。和上一份对比能直接看出部署形态差异。 |
| `public_multi_agent_qwen3_5_27b.json` | 1 机 8 卡 H20 的无 trace heuristic 样例，基于 Qwen3.5-27B 的公开模型参数。 |
| `public_multi_agent_qwen3_5_27b_1x1_h20.json` | 同上但是 1 机 1 卡，看冷启动估计在显存受限时的表现。 |

> 归一化规划样例里的 `baseline_per_card_tps = 1`、`planning_target_total_tps = 8` 只是为了演示，不是真实线上数字。换成你自己的部署时，请填实际的基线 TPS 和目标 TPS。

### 关键字段

**模型信息（`model_profile`）** —— 描述 KV cache 的形状和模型权重的占用：

- `n_layers` / `n_kv_heads` / `head_dim` / `dtype_bytes` / `block_size`：用来算每个 token 的 KV 占多少字节。
- `kv_cache_layer_count`：**混合注意力模型必填**。只统计真正进 token-linear KV cache 的那部分层；如果硬拿总层数套公式会高估占用。同构注意力模型可以省略，工具会回退到 `n_layers`。
- `tp_size` / `pp_size`：张量并行 / 流水并行切分维度，用来把每 token 的 KV 占用按 rank 切分。默认都是 `1`。
- `parameter_count` / `weight_dtype_bytes`：模型总参数量和权重 dtype 字节数。**只有想用 `gpu_memory_gb_per_card` 反推 KV 预算时才需要填**——工具会用它们算出权重分片占多少显存，再从总显存里扣掉。如果你直接给 `hbm_kv_gb_per_card`，这两个字段可以省略。

**部署信息（`bucket_deployments[]` 或 `deployments[]`）** —— 描述这套部署有多少卡、多少显存：

- `accelerator_count`：总卡数（必填）。
- `cards_per_machine`：单机卡数（必填）。机器数由 `accelerator_count / cards_per_machine` 自动算出。
- `machine_spec`：规格标签，例如 `"h20"`。**只填规格名**，不要写成 `"8*h20"` 这种把数量写进规格里的形式。
- `hbm_kv_gb_per_card` / `gpu_memory_gb_per_card`：**单卡 KV 显存预算，二选一**：
  - 直接知道每张卡留给 KV cache 多少 GB，就填 `hbm_kv_gb_per_card`。
  - 只知道整卡显存大小，就填 `gpu_memory_gb_per_card`，工具会自动减去模型权重分片和 runtime 预留来反推。
- `runtime_reserve_gb_per_card`：单卡上 runtime 杂项要预留的显存（可选）。

> 所有显存预算字段统一是**单卡口径**，名字以 `_per_card` 结尾。不要再用 `*_per_machine` 的写法。

**TPS 与规划锚点** —— 想拿到"最小卡数 / 最小机器数"这种结论，必须填规划锚点：

- `total_tps` + `total_tps_unit`：原始吞吐输入。`total_tps_unit` 取值 `cluster_total` / `per_machine` / `per_card`，工具会统一换算成集群总 TPS。
- `baseline_per_card_tps`：单卡在**无命中**时能跑多少 TPS。规划的起点；想拿到"最小卡数 / 最小机器数"必须填这个。
- `planning_target_total_tps`：希望整个集群跑到的目标总 TPS。
- `extra_capacity_tiers`：除了 HBM，每台机器还可以叠加的 host / SSD 容量层（可选，是个数组）。每一项填两个字段：`label`（这一层在报表里的显示名，例如 `"HBM+单机 1T 命中率"`）和 `kv_gb_per_machine`（**每台机器**额外能放多少 GB 的 KV，例如 `1024` 表示 1T）。

**全局参数**：

- `prefill_savings_alpha`：命中节省的 prefill 算力，能转化成多少吞吐增益。默认 `0.8`。
- `include_output_kvcache`：PD 不分离时，是否把 output 阶段产生的 KV cache 也算进占用和命中率。默认 `false`。

### 无 trace heuristic 专属字段

无 trace 模式还要在 `heuristic_multi_agent` 下填一组**场景描述**字段——这些字段是冷启动估计的核心输入：

- `concurrent_agents`：并发的 Agent 数。
- `shared_prefix_tokens`：所有 Agent 共享的那段前缀有多长（例如系统提示词 + 工具描述）。
- `avg_new_tokens_per_turn`：每一轮对话平均新增多少 token。
- `avg_turns_per_session`：一个会话平均聊几轮。
- `private_window_tokens`：单个 Agent 私有上下文窗口的大小。
- `curve_mode`：用什么曲线形状描述命中率随容量增长的趋势。可选 `linear` / `power_law_fit` / `zipf_harmonic`，默认 `power_law_fit`。
- `zipf_s`：Zipf 形状参数，`power_law_fit` 和 `zipf_harmonic` 都会用到。
- `policy_efficiency.lru_like`：在线策略相对理论最优的效率系数（≤ 1.0），用来近似 LRU 这类策略的损失。

> 这五个场景字段就是 `recommended_heuristic_config.json` 想帮你回填的目标——`calibrate-multi-agent` 跑完后，可以照着它给的建议把这几个值改写到自己的配置里。

## 输出文件怎么读

每次运行都会在 `--output-dir` 下生成一组文件。第一次看的时候不需要全部打开——按下面这个顺序找你关心的那张表就行。

### 想看命中率 → 先看这些

- **`hit_summary.csv`**：核心命中表。每个长度桶一行，列出当前显存（HBM）下的内容天花板、容量上界、严格前缀最优、LRU 基线，并附一列 `HBM 当前主要瓶颈`，取值是 `容量` / `策略` / `无明显瓶颈`，直接告诉你应该加显存还是换策略。**90% 的情况下你只需要看这一份。**
- **`tier_summary.csv`**：容量层对比表。如果你想知道"再加一层 1T host KV、再加一层 10T SSD 各能涨多少命中"，看这里。它把 HBM、HBM+1T、HBM+10T 这些层展成长表，每一行都给出严格前缀和 LRU 的命中率、`相对上一层 Strict-Prefix 增益` / `相对上一层 LRU 增益`，以及 `当前主要瓶颈` 列（取值同上）。

### 想看机器数 / TPS 规划 → 看这些

- **`planning_strict_prefix.csv`**：基于"严格前缀最优"命中率的规划表。代表理论上界——告诉你**最理想的策略下**至少需要多少卡 / 多少台机器才能打到目标 TPS。
- **`planning_lru.csv`**：基于"LRU 基线"命中率的同款规划表。代表实际落地——告诉你**真用 LRU 跑**需要多少卡 / 多少台机器。两份对比一下就知道"做策略优化的工程量值不值"。
- 两份规划表使用的是同一套换算公式：命中率 → TPS Gain → 集群可承载 TPS → 反推最小卡数 / 机器数。区别只在于命中率取的是哪一档。
- 想拿到"目标 TPS 最小卡数 / 最小机器数"这两列，必须在配置里填 `baseline_per_card_tps` 和 `planning_target_total_tps`；否则只输出基础的 TPS Gain 列。

### `summary.csv` 是干嘛的？

它把 `hit_summary.csv` 的命中率主列和 `planning_strict_prefix.csv` 的主规划列拼在一起，方便快速扫一眼"当前 HBM 下命中率多少 + 至少要多少机器"。如果你只想看一张表，看它即可；如果你要做严肃的对比分析，还是建议拆开看上面三张。

### 无 trace（heuristic）模式专属

- **`heuristic_summary.csv`** / **`heuristic_tier_summary.csv`**：和上面 `hit_summary.csv` / `tier_summary.csv` 同结构，区别是数字来自 heuristic 估计而不是 trace。
- **`heuristic_report.zh.md`** / **`heuristic_report.en.md`**：双语解释报告。讲清楚这次估计用了什么假设、公式、参数，以及结果的不确定性边界。**如果不确定 heuristic 数字到底能不能信，先看这个。**

### 回标（calibrate）模式专属

- **`calibration.json`**：回标摘要。包含 trace 观测的目标值、网格搜索找到的最佳 `zipf_s` / `lru_like`，以及分层误差。
- **`calibration_trials.csv`**：网格搜索的所有尝试。能直观看出参数空间长什么样，误差最小的点在哪。
- **`calibrated_config.json`**：把最佳参数填回去后的 heuristic 配置文件。可以直接拿去跑 `estimate-multi-agent`。
- **`recommended_heuristic_config.json`**：基于 trace 结构反推出来的"场景描述模板"。如果回标后命中率还和观测差很多，说明 `zipf_s` / `lru_like` 怎么调都救不了——根本原因是结构性参数（共享前缀长度、私有窗口、并发数等）写得不准。这时按这份模板把 `heuristic_multi_agent` 下的几个字段改一下，再跑一次。

### 元数据 / 正确性

- **`metadata.json`**：这次运行的"小票"。记录用了哪份配置、加载了多少条记录、归一化后的部署口径是什么。复盘时方便确认"这次到底按什么口径算的"。
- **`details.json`**：每个桶的详细中间结果。想查某个具体数字（例如某个桶的等效卡数）就看这里。
- **`correctness_report.zh.md`** / **`correctness_report.en.md`**：仅 `audit-buckets` 命令会输出。给出每项结果的证明路径和上下界——什么是已经被严格证明的，什么只是辅助证据。

## 文档入口

需要更深入的细节时：

- **`docs/four_layer_model.md`**：对外讲解用的"容量 → 命中 → TPS → 机器需求"四层框架。如果是第一次接触这个工具，**建议先看这一篇**。
- **`docs/design_guide.md`**：实现口径、算法选型和阶段计划。改代码或扩展功能前看。
- **`docs/correctness_guide.md`**：每个结果的精确定义、证明范围、以及结果表该怎么读。对结果有疑问时看。
