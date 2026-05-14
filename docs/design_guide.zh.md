# 窗口感知 KVCache 上限分析器：设计指导文档

> **“先把可复用内容的天花板算清楚，再谈缓存系统怎么做；否则你只是在精确模拟一个定义不清的问题。”**
> 这份文档不是介绍材料，而是实现指南。后续代码、测试、CLI 和实验输出，都必须服从这里定义的口径和阶段边界。

---

## 背景：项目真正要解决什么

这个项目面向 `qwen-bailian-usagetraces-anon` 公开 trace。数据里保留了请求时间、会话树关系、输入输出长度，以及按 16 token 切块后的 `hash_ids`。这已经足够回答一个关键问题：

**在给定 window size、模型结构和机器资源的前提下，一个 workload 理论上最多能复用多少 KVCache？**

对外展示时，主线可以收缩成 `容量 -> 命中 -> TPS -> 机器需求` 的简化模型，见 `docs/four_layer_model.md`。内部实现则继续保持更细的分层与正确性约束。
当前这份文档聚焦内部实现口径。在内部实现里，框架固定拆成四层：

| 层级 | 要回答的问题 | 依赖输入 |
|------|--------------|----------|
| **内容上限** | 请求本身有多少前缀内容可复用？ | trace |
| **容量上限** | 有限 GPU/CPU KV 预算下还能保住多少复用？ | trace + model + kv budget |
| **策略基线** | 如果采用简单在线策略，例如 LRU，和上界差多远？ | trace + model + kv budget |
| **冷启动估计** | 没有 trace 时，怎样先粗估 `容量 -> 命中 -> TPS`？ | model + deployment + heuristic assumptions |

**决策**：

- `content / exact strict-prefix / LRU baseline` 都属于 trace 驱动的结果。
- `TPS / 机器数` 仍然是报表层后处理，不伪装成系统级 oracle。
- `multi-agent heuristic` 是第四层冷启动估计，只在缺少 trace 时使用，必须明确标注为 heuristic，不得和 oracle 结果混用。

---

## 项目目标与非目标

### 目标

- 输入 Bailian trace、模型信息、机器信息和 window size 列表。
- 输出不同 window 下的 `content / relaxed / exact strict-prefix / LRU` 主层结果。
- 输出可复用 KV bytes、工作集大小、预算敏感性曲线。
- 支持按 `type/turn/input bucket/session scope` 做切片分析。
- 在没有 trace 的场景下，支持基于 `shared prefix + private working set + curve shape` 的多 Agent 冷启动估计。

### 非目标

- 不恢复原始 prompt 文本。
- 不在第一版模拟 decode kernel 或完整 serving runtime。
- 不把 HiSim 作为入口实现。
- 不把所有策略问题提前混进上限计算里。

---

## 正确性策略

当前项目把“证明正确”拆成三类动作：

1. **定义证明**
   - 先冻结 window、scope、hit rate 和模型公式，避免实现时偷偷换口径。
2. **reference 对账**
   - 对 `content upper bound` 用朴素 reference 做逐例对账。
   - 对当前 `capacity upper bound` 用暴力 reference 对账同一个 relaxed 目标，并允许 `no-admit`。
   - 对 `strict-prefix capacity oracle` 用暴力 reference 对账 exact 目标。
3. **证书与等价校验**
   - 显式输出 `replay == content` / `relaxed == replay` 两类 exact certificate。
   - 在当前穷举验证空间里，验证 `relaxed == replay == exact strict-prefix` 是否成立。

这套策略的目的不是粉饰结果，而是把“已经被证明的部分”“用证书直接夹出的部分”“仍然需要搜索的部分”切开。

详细说明见 `docs/correctness_guide.md`。

---

## 无 trace heuristic：第四层冷启动引擎

第四层不追求证明“真实线上一定如此”，而是给出一个结构清晰、参数少于完整 replay、又比单条经验曲线更可解释的冷启动估计。

### 结构假设

定义：

- `n`：并发 Agent 数
- `S`：所有 Agent 共享前缀 token 数
- `Delta`：每轮新增 token 数
- `T`：平均会话轮数
- `W`：单 Agent 私有窗口

在 append-only 会话假设下，单 Agent 平均可复用私有前缀：

```text
P = (1 / T) * sum_{i=0}^{T-1} min(W, i * Delta)
```

于是总私有工作集与总工作集为：

```text
W_private_total = n * P
W_total = S + n * P
```

单请求平均长度与内容天花板为：

```text
L_request = S + Delta + P
h_content = (S + P) / L_request
```

### 容量到命中率的估计

当总容量为 `C` 时：

1. 先假设共享前缀 `S` 优先被覆盖。
2. 其余容量用来覆盖私有工作集。
3. 私有部分不直接假设线性增长，而交给一个形状函数 `g(r)`，其中：

```text
r = clip((C - S) / (n * P), 0, 1)
```

于是 strict-prefix 上界估计写成：

```text
h_strict_est(C) = min(h_content, (S + g(r) * P) / L_request)
```

当前代码支持三种 `g(r)`：

| 模式 | 公式 | 作用 |
|------|------|------|
| `linear` | `g(r) = r` | 最简单的线性近似 |
| `power_law_fit` | `g(r) = r^(1 - 1/s)` | 直接吸收 Zipf-inspired 简化公式 |
| `zipf_harmonic` | `g(r) = H_{floor(rN), s} / H_{N, s}` | 用离散 Zipf 累积质量做更稳的形状函数 |

这里的 `power_law_fit` 就是把外部常见的：

```text
h(C) ~= (C / W_total)^(1 - 1/s)
```

吸收到私有工作集覆盖阶段里。它有用，但只能叫 Zipf-inspired heuristic，不能当严格证明。

### 在线策略近似

无 trace 时没法精确 replay LRU，因此第四层只输出 `LRU-like` 近似：

```text
r_lru = clip(eta * (C - S) / (n * P), 0, 1)
```

其中 `eta in (0, 1]` 是 `policy_efficiency.lru_like`。它表示在线策略因为淘汰顺序、局部冲突和 admission 不完美而损失掉的有效容量比例。

于是：

```text
h_lru_like_est(C) = min(h_content, (S + g(r_lru) * P) / L_request)
```

**硬约束**：

- `LRU-like` 只能是估计，不能叫 `LRU oracle`。
- `LRU-like` 的效率系数必须不超过 `strict-prefix upper bound`。
- 任何 heuristic 结果都必须和 trace oracle 分开输出。

### trace 回标

第四层允许再多做一步：用一小段真实 trace 去回标 `zipf_s` 和 `lru_like`，但口径必须固定为：

- 只回标形状参数和策略效率参数。
- 不把回标结果说成“证明正确”。
- 如果 `content ceiling` 仍然明显对不齐，就明确指出问题在结构参数，而不是继续假装 `zipf_s` 能解决一切。

回标目标来自 trace oracle 的聚合结果：

```text
observed content hit rate
observed strict-prefix hit curve
observed LRU hit curve
```

当前实现对 `zipf_s × lru_like` 做网格搜索，输出：

- `calibration.json`
- `calibration_trials.csv`
- `calibrated_config.json`
- `recommended_heuristic_config.json`

并在 `heuristic_report.zh.md / heuristic_report.en.md` 里显式写出：

- 样本来源
- trace 结构建议
- 最佳参数
- 分层误差
- `content_gap`

其中 `content_gap` 是最重要的诊断值之一：

```text
content_gap = heuristic_content_ceiling - observed_content_ceiling
```

如果它很大，说明应该先改 `shared/private` 结构假设，而不是继续细抠曲线参数。

### trace 结构建议

除了 `zipf_s / lru_like` 回标，第四层现在还支持一条“结构建议器”路径：

- 用 root 请求的两两公共前缀估计共享前缀规模。
- 用 session 生命周期重叠估计并发 agent 数。
- 用观测私有复用量反推 `avg_turns_per_session / private_window_tokens`。
- 如果已经有 trace content ceiling，再把 `Delta` 回代到能对齐 content ceiling 的位置。

它输出的是一份 `recommended_heuristic_config.json`，目的不是替代 oracle，而是把 heuristic 的结构模板先摆正。

---

## 冻结口径：先把定义钉死

### 1. Window 语义

第一版采用 `strict_prefix_window`：

- 对每个请求，只保留最后 `W` tokens 对应的有效输入。
- 截断后仍然按前缀复用计算命中率。
- 不假设位置平移、窗口重定位或 RoPE-aware 变换后的复用。

| 方案 | 含义 | 结论 |
|------|------|------|
| `strict_prefix_window` ⭐ | 截断后仍要求前缀路径一致 | ✅ 第一版默认 |
| `window_shift_oracle` | 允许窗口化后做位置重映射复用 | ❌ 第二版再研究 |

### 2. 粒度

- 主粒度：`block`
- 默认 `block_size = 16`
- token 命中率只作为 block 命中率的换算结果

### 3. 命中率定义

必须同时输出三种指标：

| 指标 | 定义 | 用途 |
|------|------|------|
| `block_hit_rate` | 命中 block / 总有效 block | 主指标 |
| `token_hit_rate_est` | 估算命中 token / 有效输入 token | 面向上下文长度解释 |
| `kv_byte_hit_rate` | 命中 KV bytes / 总 KV bytes | 面向机器资源解释 |

### 4. Prefill / Decode 边界

默认只统计 **prefill 复用**：

- 输入前缀的 KV 是否可复用，算 hit
- decode 产生的新 token KV 不计入主命中率

#### Output KV Cache 扩展（`include_output_kvcache`）

在 PD 不分离（prefill 和 decode 共用同一套 GPU 显存）的部署场景下，decode 阶段产生的 output KV cache 会驻留在 GPU 上，占用缓存空间，进而影响后续请求的缓存命中率。此特性默认开启（`true`）；如需关闭，可在配置中设置 `"include_output_kvcache": false`。

**核心机制**：

trace 只记录了每个请求的 input `hash_ids`，不包含 output 的 block hashes。但在多轮会话中，后续请求的 `hash_ids` 天然包含了前一轮的 output 内容：

```text
child.hash_ids = [parent_input_blocks | parent_output_blocks | new_user_input_blocks]
```

因此，当子请求出现时，父请求 output 的真实 block hashes 可以从子请求的 `hash_ids` 中**反向提取**：

```text
parent_output_hashes = child.hash_ids[parent.block_count : parent.block_count + parent_output_blocks]
```

parent-child 配对通过 `parent_chat_id` 字段确定，有多个 child 时按 `turn` 排序取最早的。

**对各层的影响**：

| 层级 | 行为 |
|------|------|
| **内容上限** | 父请求完成后，将 `input + output` 的完整路径注入 trie；后续请求的 prefix match 能覆盖 output 部分 |
| **容量上限** | 真实 output hashes 注入 trie 后与子请求共享 node id，同时占用缓存空间参与 Belady/LRU 淘汰 |
| **策略基线** | 同容量上限 |
| **最后一轮** | 没有子请求，output blocks 仍为未知，使用虚拟占位符只占空间、不产生命中 |

**效果**：

- 容量充足时：output blocks 被缓存后，下一轮请求的 strict-prefix 命中深度增加（因为 output 也能 prefix match）
- 容量紧张时：output blocks 额外占用显存空间，挤压其他请求的缓存容量，降低整体命中率
- 默认关闭（`false`），保持与原有口径一致

### 5. Scope

第一版固定输出两个 oracle scope：

- `session_oracle`：仅允许同一会话树内复用
- `global_oracle`：允许全局历史请求复用

---

## 核心公式：模型信息怎么进入计算

对标准 Transformer / GQA，单 token KV 体积按下面计算：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ModelProfile:
    n_layers: int
    n_kv_heads: int
    head_dim: int
    dtype_bytes: int
    kv_cache_layer_count: int | None = None
    tp_size: int = 1
    pp_size: int = 1
    block_size: int = 16

    def kv_bytes_per_token(self) -> int:
        layers = self.n_layers if self.kv_cache_layer_count is None else self.kv_cache_layer_count
        return 2 * layers * self.n_kv_heads * self.head_dim * self.dtype_bytes

    def kv_bytes_per_block(self) -> int:
        return self.block_size * self.kv_bytes_per_token()
```

其中：

- `2` 表示 `K + V`
- `n_kv_heads` 必须用 KV 头数，而不是 attention 头总数
- 这里的 `kv_bytes_per_token` 表示**整套 TP/PP 部署的总 KV 占用**，用于和“总 HBM/总扩展空间预算”直接对比
- 对混合注意力模型，`kv_cache_layer_count` 必须只统计真正产生 token-linear KV 的层，例如 `Qwen/Qwen3.5-27B` 为 `16` 而不是 `64`
- 第一版默认每个 block 的 KV bytes 恒定，不额外建模 padding 和对齐损耗

---

## 架构总览：离线 Oracle 三段式

```mermaid
graph TB
    A["Trace Loader"] --> B["Window Adapter"]
    B --> C["Prefix Trie Builder"]
    C --> D["Content Oracle"]
    C --> E["Capacity Oracle"]
    D --> F["Report Generator"]
    E --> F
    G["Model Profile"] --> E
    H["Machine Profile"] --> E

    style A fill:#e3f2fd
    style C fill:#c8e6c9
    style D fill:#c8e6c9
    style E fill:#fff9c4
    style F fill:#e3f2fd
```

这套设计有一个明确哲学：

- 先回答“有没有可复用内容”
- 再回答“这些内容留不留得住”
- 最后才回答“搬不搬得动”

不要把三个问题混成一个黑盒模拟器。黑盒最省事，也最容易把错误藏起来。

---

## 数据模型：实现时必须先稳定这些对象

### RequestRecord

```python
from dataclasses import dataclass
from typing import Optional, Tuple

@dataclass(frozen=True)
class RequestRecord:
    request_id: str
    timestamp_ms: int
    chat_id: str
    parent_chat_id: Optional[str]
    turn: int
    request_type: str
    input_length: int
    output_length: int
    hash_ids: Tuple[str, ...]
```

### EffectiveRequest

- `request_id`
- `timestamp_ms`
- `scope_root_id`
- `effective_hash_ids`
- `effective_blocks`
- `effective_tokens`
- `turn`
- `request_type`

### TrieNode

- `node_id`
- `parent_id`
- `block_hash`
- `depth`
- `first_seen_ts`
- `accesses[]`
- `future_accesses[]`
- `size_bytes`

**约束**：实现时，`TrieNode` 表示的是“前缀路径节点”，不是“裸内容块”。这一点不能退。

---

## 为什么必须用 Prefix Trie

如果只按 block hash 做计数，你会把“相同内容块”误当成“相同可复用 KV 实体”。这是错的。

```mermaid
graph LR
    R["root"] --> A["x"]
    A --> B["x/y"]
    R --> C["z"]
    C --> D["z/y"]

    style B fill:#c8e6c9
    style D fill:#ffccbc
```

`x/y` 和 `z/y` 最后一个 block 都是 `y`，但它们不共享同一个前缀状态，所以不能简单视作同一个 KV 节点。

**结论**：

- ✅ 可以复用的是“已出现过的前缀路径”
- ❌ 不是“历史上见过相同 block 内容”

---

## 详细实现步骤

## Phase 0：冻结输入输出口径

交付物：

- `docs/design_guide.md` 完整落盘
- 明确默认参数和边界

默认参数：

| 参数 | 默认值 |
|------|--------|
| `block_size` | `16` |
| `window_policy` | `strict_prefix_window` |
| `scope` | `session + global` |
| `main_metric` | `block_hit_rate` |
| `count_decode` | `false` |

退出标准：

- 后续实现不再对口径做隐式修改
- CLI 和测试直接引用这里的定义

---

## Phase 1：Trace 规范化

任务：

1. 解析 JSONL
2. 生成稳定 `request_id`
3. 校验 `input_length` 和 `hash_ids` 的基本一致性
4. 重建 `chat_id / parent_chat_id` 关系
5. 生成不同 window 下的 `EffectiveRequest`

处理原则：

- 时间按 `timestamp` 排序；相同时间用输入顺序稳定打散
- `effective_blocks = ceil(window / block_size)`
- 有效块序列取 `hash_ids[-effective_blocks:]`
- 如果原始输入比窗口短，保留全部块

建议先产出一个纯中间层文件，例如 `normalized_requests.parquet`，让后续 oracle 不直接读原始 JSONL。

退出标准：

- 给定 trace 和 window，能稳定得到完全相同的 `EffectiveRequest` 集合
- 异常样本有明确计数和日志，而不是静默跳过

---

## Phase 2：Content Oracle

任务：

1. 按时间顺序插入 prefix trie
2. 对每个请求求“历史已存在最长前缀”
3. 输出每请求命中块数和 miss 块数
4. 聚合出窗口曲线和 workload 切片报表

核心算法：

1. 遍历请求有效块序列
2. 从 trie root 开始逐块匹配
3. 已存在节点记为 hit，首次出现节点记为 miss
4. 一个请求处理完后，把完整路径写回 trie

输出指标：

- `content_block_hit_rate`
- `content_kv_byte_hit_rate`
- `reusable_kv_bytes`
- `content_hit_rate_by_type`
- `content_hit_rate_by_turn`

退出标准：

- `global_oracle >= session_oracle`
- 命中数 + miss 数 = 总有效块数
- 在无历史请求的数据子集上，命中率为 0

---

## Phase 3：Capacity Oracle

任务：

1. 为 trie 节点建立未来访问序列
2. 在给定 `gpu_kv_budget_bytes` 下做离线最优淘汰
3. 可选加入二级 `cpu_kv_budget_bytes`
4. 输出预算敏感性分析

算法选择：

| 方案 | 结论 | 原因 |
|------|------|------|
| LRU | ❌ 不适合作为上限 | 只是一种在线启发式 |
| LFU | ❌ 不适合作为上限 | 忽略时间顺序 |
| Belady ⭐ | ✅ 第一版默认 | 离线最优，适合 upper bound |

模拟逻辑：

- 节点第一次进入系统时可装入缓存
- 若超预算，淘汰“下一次访问最远”的节点
- 预算以 `kv_bytes_per_block * resident_blocks` 统计
- 第一版先做单层 GPU；二层 GPU+CPU 作为扩展

输出指标：

- `capacity_block_hit_rate`
- `capacity_kv_byte_hit_rate`
- `required_working_set_bytes`
- `budget_vs_hit_rate`

退出标准：

- `capacity_upper <= content_upper`
- 预算增大时命中率不下降
- 预算足够大时，容量上限逼近内容上限

---

## Phase 4：System Oracle

任务：

1. 对每个未来需要复用的节点建立 `promotion task`
2. 用时间戳和带宽约束判断是否能及时搬运
3. 输出 `gpu resident hit / promoted hit / miss`

建议模型：

- 任务大小：`kv_bytes_per_block`
- 释放时间：当前访问完成时刻
- 截止时间：下次访问时间
- 链路容量：`bandwidth_bytes_per_sec * delta_t`

这个阶段才需要引入：

- `cpu_to_gpu_bandwidth`
- 可选 `remote_to_cpu_bandwidth`
- 可选并发搬运通道数

退出标准：

- `system_upper <= capacity_upper`
- 零带宽时，跨层 promotion 命中应为 0
- 极大带宽时，系统上限逼近容量上限

---

## 推荐模块拆分

第一轮实现建议拆成下面这些模块：

| 模块 | 职责 |
|------|------|
| `ingest/trace_loader.py` | 读取 JSONL，产出原始记录 |
| `ingest/normalizer.py` | 生成 `EffectiveRequest` |
| `core/models.py` | 数据类和公共类型 |
| `oracle/prefix_trie.py` | 前缀路径插入和匹配 |
| `oracle/content.py` | 内容上限计算 |
| `oracle/capacity.py` | Belady 容量上限计算 |
| `oracle/lru.py` | 在线 LRU 策略基线 |
| `heuristic/multi_agent.py` | 无 trace 多 Agent 冷启动估计 |
| `heuristic/output.py` | 无 trace heuristic 输出层 |
| `reporting/buckets.py` | 输出按长度分桶聚合后的部署表 |
| `cli/main.py` | 命令行入口 |

模块之间只允许单向依赖：

```mermaid
graph LR
    A["ingest"] --> B["core"]
    C["oracle"] --> B
    F["heuristic"] --> B
    D["reporting"] --> B
    D --> C
    E["cli"] --> A
    E --> C
    E --> D
    E --> F

    style B fill:#c8e6c9
```

**规则**：

- `oracle/` 不直接读文件
- `reporting/` 不反向调用 `cli/`
- `core/` 只放稳定对象和纯工具

---

## CLI 设计建议

当前 CLI 保持三条主命令：

```bash
kvcache-upper-bound analyze-buckets \
  --trace /path/to/trace.jsonl \
  --config configs/public_trace_qwen3_5_27b.json \
  --output-dir outputs/run_001

kvcache-upper-bound audit-buckets \
  --trace /path/to/trace.jsonl \
  --config configs/public_trace_qwen3_5_27b.json \
  --output-dir outputs/run_001_audit

kvcache-upper-bound estimate-multi-agent \
  --config configs/public_multi_agent_qwen3_5_27b.json \
  --output-dir outputs/heuristic_run_001

kvcache-upper-bound calibrate-multi-agent \
  --trace https://media.githubusercontent.com/media/alibaba-edu/qwen-bailian-usagetraces-anon/main/qwen_traceA_blksz_16.jsonl \
  --bucket-config configs/public_trace_qwen3_5_27b.json \
  --heuristic-config configs/public_multi_agent_qwen3_5_27b.json \
  --output-dir outputs/heuristic_calibrated_001 \
  --max-records 5000
```

输出最少包含：

| 文件 | 内容 |
|------|------|
| `summary.csv` | 兼容汇总表；同时保留 HBM 主命中结果、诊断列与主规划列 |
| `hit_summary.csv` | 核心命中估算表；只放 HBM 当前层的 `content / relaxed / lru / replay / exact strict-prefix / proof source / 瓶颈诊断` |
| `planning_strict_prefix.csv` | 上界规划表；基础列只保留 exact strict-prefix 的 `TPS Gain`，若配置了 `total_tps` 则再带 `估算总 TPS`，若配置了 `baseline_per_card_tps + planning_target_total_tps` 则再额外输出 `当前配置可承载总 TPS / 目标总 TPS 最小卡数 / 最小机器数` |
| `planning_lru.csv` | 策略规划表；基础列只保留 LRU 的 `TPS Gain`，其余规则与 `planning_strict_prefix.csv` 对齐 |
| `tier_summary.csv` | 容量层长表；把 `HBM / HBM+1T / HBM+10T` 等层级展开成多行，统一输出 `Strict-Prefix / LRU / 增益 / 诊断 / 规划` |
| `details.json` | 每个桶的 content / relaxed / exact strict-prefix 详细摘要 |
| `metadata.json` | 输入参数、加载统计、报表行镜像 |
| `correctness_report.{json,md,zh.md,en.md}` | reference 校验、trace 采样对账、strict-prefix 求解路径说明 |
| `heuristic_summary.csv` | 无 trace 主表；只保留 HBM 当前层的 cold-start 估计与主规划列 |
| `heuristic_tier_summary.csv` | 无 trace 容量层长表；统一比较 `HBM / HBM+1T / HBM+10T` 等层级 |
| `heuristic_report.{md,zh.md,en.md}` | 无 trace heuristic 说明报告；固定解释假设、参数、公式、结果边界 |
| `calibration.json` | trace 回标摘要；固定记录样本来源、最佳参数和分层误差 |
| `calibration_trials.csv` | trace 回标网格搜索结果 |
| `calibrated_config.json` | 回标后的 heuristic 配置 |
| `recommended_heuristic_config.json` | trace 结构建议模板；固定记录更贴近样本的 `shared/private` 假设 |

其中：

- `同负载估算卡数 / 机器数` 只保留在 `details.json`，用于解释局部算力等效值。
- `目标总 TPS 最小卡数 / 机器数` 才是闭环回代容量约束后的绝对规划结果。
- `tier_summary.csv` 的 `相对上一层 Strict-Prefix / LRU 增益` 用来回答“加这一层容量到底值不值”。
- `heuristic_summary.csv / heuristic_tier_summary.csv` 只能代表冷启动估计，不得和 oracle 主表混读成“已证明结果”。
- `calibration.json` 只能说明“这组参数更贴近这段样本”，不能自动升级成 `oracle proof`。

---

## 测试与校验

### 单元测试

必须先覆盖这几类边界：

- 空 trace
- 单请求 trace
- 完全相同前缀重复
- 同 block 不同前缀路径
- window 小于输入长度
- 预算为 0 / 足够大

### 性质测试

必须验证：

| 性质 | 期望 |
|------|------|
| `global >= session` | 恒成立 |
| `content >= capacity >= system` | 恒成立 |
| 预算增加 | 命中率不下降 |
| 零历史 | 命中率为 0 |

### 外部验证

后续可选：

- 用 `trace-replayer` 回放小样本
- 对比真实 prefix cache 命中趋势和 oracle 曲线关系
- 只验证趋势，不要求数值完全重合

---

## 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| `hash_ids` 只到 block 粒度 | token 精度有限 | 主指标保持 block 粒度 |
| window 语义不统一 | 曲线无法解释 | 第一版只保留一个默认语义 |
| 把相同 block 当同一节点 | 系统性高估 | 强制使用 prefix trie |
| 直接用总显存估算 KV 预算 | 容量结论失真 | 显式输入 `gpu_kv_budget_bytes` |
| 把 heuristic 当 oracle | 决策被伪精度误导 | 报表、列名、文档都显式标 `估计` |
| 过早接 HiSim | 问题域混乱 | 先做离线 oracle |

---

## 里程碑与验收

| 里程碑 | 交付物 | 验收标准 |
|--------|--------|----------|
| **M0** | 文档与骨架 | 口径冻结，目录稳定 |
| **M1** | Trace 规范化 | 可生成 `EffectiveRequest` |
| **M2** | Content Oracle | 可输出窗口命中率曲线 |
| **M3** | Capacity Oracle | 可输出预算敏感性曲线 |
| **M4** | System Oracle | 可输出带宽约束后的上限 |
| **M5** | 实验与对比 | 能解释窗口、预算、带宽三组曲线 |

当前目标是先完成 `M1 + M2`，也就是：

- 把 trace 变成稳定中间表示
- 把内容上限命中率曲线算出来

这是整个项目最重要的地基。地基不稳，后面的容量模拟和系统模拟都会漂。

---

## 实施顺序建议

按下面的顺序做，复杂度最低：

1. 先实现 `core/models.py`
2. 再实现 `ingest/trace_loader.py`
3. 再实现 `ingest/normalizer.py`
4. 然后做 `oracle/prefix_trie.py`
5. 最后接 `oracle/content.py` 和最小 `cli`

不要一开始就做图表、并发、远端 tier 或 HiSim 对接。

---

## 当前实现状态

截至 `2026-03-17`，项目已经完成：

- `M1`：trace 规范化
- `M2`：content upper bound
- `M3`：单层/扩展总容量下、允许 `no-admit` 的 Belady capacity upper bound
- `M4`：真正的 strict-prefix capacity oracle，以及 request-level exact search
- 面向通用结果输出的分桶报表：可直接产出 `分桶 / 机器数 / 卡数 / 单机卡数 / 规格 / 总 TPS / TPS 输入口径 / HBM / 极限命中率 / HBM relaxed upper bound / HBM strict-prefix replay / HBM strict-prefix / proof source`

尚未实现：

- `system upper bound`：带宽与 deadline 约束
- 真实多机放置与路由策略
- HiSim 或 trace-replayer 的性能映射层

---

## 总结

| 维度 | 指导结论 |
|------|----------|
| **问题定义** | 这是上限分析器，不是 serving runtime |
| **核心数据结构** | 前缀路径 trie，而不是 block 频次表 |
| **主实现顺序** | 规范化 trace -> 内容上限 -> 容量上限 -> 系统上限 |
| **第一版边界** | `strict_prefix_window` + `prefill only` + `block` 粒度 |
| **最重要输出** | window 曲线、预算曲线、工作集大小 |

一句话收尾：

**先把“什么可以复用”算对，再去优化“怎么把它缓存住”。这是这个项目唯一正确的起点。**

---

## 参考资料

- Bailian Trace：`https://github.com/alibaba-edu/qwen-bailian-usagetraces-anon`
- Trace Replayer：`https://github.com/blitz-serving/trace-replayer`
- Tair KVCache / HiSim：`https://github.com/alibaba/tair-kvcache`

---

**文档生成时间**: 2026-03-17  
**作者**: OpenCode
