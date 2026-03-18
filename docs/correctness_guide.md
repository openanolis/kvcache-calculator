# 结果正确性说明

这份文档只讲三件事：每个结果代表什么、规划结果怎么来的、当前到底证明了什么。

## 结果分层

项目当前把命中结果分成 5 层：

| 结果 | 含义 | 角色 |
|------|------|------|
| `content upper bound` | 不考虑容量时的内容复用天花板 | 最高上界 |
| `relaxed upper bound` | 固定容量下的 event-level 离线最优上界 | 容量上界 |
| `LRU baseline` | 固定容量下的标准 LRU 在线策略结果 | 策略基线 |
| `strict-prefix replay` | relaxed 调度按 strict-prefix 语义重计后的可实现结果 | 证书下界 |
| `exact strict-prefix` | strict-prefix 语义下的真正最优值 | 核心结论 |

可以直接记成：

```text
LRU baseline <= exact strict-prefix <= relaxed upper bound <= content upper bound
strict-prefix replay <= exact strict-prefix <= relaxed upper bound
```

说明：

- `LRU baseline` 是一个简单在线策略，不是上界。
- `exact strict-prefix` 是当前最重要的容量结果。
- `relaxed upper bound` 和 `strict-prefix replay` 主要用来解释 exact 值是怎么得到的。

## strict-prefix 的定义

`strict-prefix` 只统计从请求第 1 个 block 开始连续命中的那一段。

例子：

```text
request blocks: [b0, b1, b2, b3]
hit pattern:    [ 1,  1,  0,  1]
strict-prefix hit = 2
```

原因很简单：

- `b3` 虽然命中。
- 但 `b2` 已经 miss。
- 前缀连续性在 `b2` 处断掉，所以真正可复用前缀只有前两个 block。

## LRU 在项目里的位置

LRU 现在已经接进主报表，但它的身份很明确：

- 它是 `policy baseline`。
- 它表示“如果只用标准 LRU 在线管理 KV cache，当前容量下能做到多少 strict-prefix 命中”。
- 它不参与上界定义，但它会单独驱动 `planning_lru.csv` 里的机器需求计算。

因此现在有两张规划表：

- `planning_strict_prefix.csv`：`exact strict-prefix` 上界规划
- `planning_lru.csv`：`LRU` 策略规划

## alpha 和规划结果

`alpha` 是 `Prefill 节省系数`。它表示命中收益能有多大比例兑现成吞吐收益。

当前项目有两套规划后处理：

### 1. 固定命中率的算力等效值

这组值现在只保留在 `details.json`，主 CSV 不再展示。它们仍然是有用的辅助解释值，公式固定为：

```text
TPS Gain = 1 / (1 - alpha * h)
Estimated Total TPS = Input Total TPS * TPS Gain
Estimated Card Count For Same Load = Current Card Count / TPS Gain
Estimated Machine Count For Same Load = Estimated Card Count / Cards Per Machine
```

其中：

- `h` 取决于你看的规划表。
- `alpha` 不是 trace 统计值，也不是模型固有常数。
- `planning_strict_prefix.csv` 用 `exact strict-prefix` 命中率代入。
- `planning_lru.csv` 用 `LRU` 命中率代入。

这组值不会回代“缩容后容量变小、命中率也会变”这件事，所以它只能当局部算力等效值，不能直接当最终部署答案。

### 2. 目标总 TPS 下的自洽规划

如果配置里提供：

- `baseline_per_card_tps`
- `planning_target_total_tps`

报表还会输出真正可横向比较的规划列：

- `当前配置可承载总 TPS`
- `目标总 TPS 最小卡数`
- `目标总 TPS 最小机器数`

这组列的计算是闭环的：

```text
machine/card count
-> total KV budget
-> hit rate
-> cluster total TPS
-> whether target_total_tps is satisfied
```

所以这里的“最小卡数 / 最小机器数”不是简单做除法，而是在候选部署规模上做单调搜索，直到找到第一个满足目标总 TPS 的整数部署。

## 报表怎么读

推荐按这个顺序读：

1. 看 `极限命中率`，先判断内容天花板高不高。
2. 看 `HBM Strict-Prefix 命中率`，判断当前 HBM 下真正能保住多少复用。
3. 看 `HBM LRU 命中率`，判断简单在线策略和最优值差多远。
4. 看 `HBM Strict-Prefix 达到内容上界 / HBM LRU 达到 Strict-Prefix / HBM 当前主要瓶颈` 这三列，先把“容量瓶颈”和“策略瓶颈”分开。
5. 如果还要比较 `HBM / 1T / 10T` 这些扩容层，直接看 `tier_summary.csv`，重点读 `相对上一层 Strict-Prefix 增益 / 相对上一层 LRU 增益`。
6. 最后看规划表：优先读 `目标总 TPS 最小卡数 / 最小机器数`；如果还想看“固定命中率不回代容量变化”的局部等效值，再去查 `details.json`。

各文件职责固定如下：

| 文件 | 只回答什么问题 |
|------|----------------|
| `hit_summary.csv` | 当前 HBM 的命中率本身是多少，主要瓶颈是容量还是策略 |
| `planning_strict_prefix.csv` | exact strict-prefix 上界下，当前配置可承载多少 TPS；若给了目标 TPS，再回答最小卡数 / 机器数 |
| `planning_lru.csv` | LRU 策略下，当前配置可承载多少 TPS；若给了目标 TPS，再回答最小卡数 / 机器数 |
| `tier_summary.csv` | 不同容量层之间，命中率、TPS 和诊断到底差多少 |
| `details.json` | 每个桶的详细摘要和中间统计 |
| `correctness_report.zh.md` / `correctness_report.en.md` | 当前结果的证明范围和侧证 |

## 当前已经证明的内容

### 1. content 是精确的

`content upper bound` 基于前缀路径定义，而不是裸 block 频次统计。项目内置了 trie 实现和朴素 reference 对账，当前口径下这是精确结果。

### 2. relaxed 是它自己目标下的精确最优值

`relaxed upper bound` 的目标是：

- 把请求展开成 block access event 序列。
- 在固定容量下，用允许 `no-admit` 的离线最优调度最大化 event hit。

项目对这个目标做了 reference 对账，所以它对自己的目标是精确的。

### 3. strict-prefix 是真正的精确 oracle

`exact strict-prefix` 现在不是估计值，而是真正的精确结果：

- 证书足够时，直接走 `certificate`。
- 证书不够时，进入精确搜索，报表里会写 `search`。

因此：

- `HBM Strict-Prefix 命中率` 是精确值。
- `HBM Strict-Prefix 求解路径` 说明这个精确值是怎么得到的。

## 当前没有证明的内容

下面这些还不是 oracle 结论：

- `alpha` 的取值是否贴合某个线上系统。
- `TPS Gain / 估算总 TPS / details.json` 里的同负载等效值是否等于真实线上收益。
- `baseline_per_card_tps` 是否等于真实线上单卡基线吞吐。
- 带宽、搬运时延、跨层存储命中开销是否已经被完整建模。

所以项目当前最稳的主线是：

```text
trace + model + capacity -> 命中率结果
命中率结果 + alpha -> 规划估算
```

前半段是 oracle，后半段是基于假设的后处理。
