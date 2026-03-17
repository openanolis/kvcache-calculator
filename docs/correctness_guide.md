# 结果正确性说明

这份文档只回答一件事：这个项目当前到底证明了什么，没有证明什么。

## 三层结论

- `content upper bound`：对当前定义是精确值。
- `HBM KVCache 空间命中率`：当前实现是 `relaxed space upper bound`，不是严格前缀语义下的最终最优值。
- `system upper bound`：尚未实现。

换句话说，项目现在最硬的结论是：

1. 给定 `strict_prefix_window`、`scope` 和模型配置，trace 里到底有多少前缀内容理论上可复用，这个数是精确的。
2. 给定 HBM/扩展空间预算，按 block access event 做离线 Belady 可以得到一个合法且可验证的空间放松上界。
3. 这个空间上界对“真实前缀可复用命中率”是乐观的；它不能直接等同于严格前缀语义下的最优值。

## 为什么 content 是精确的

`content upper bound` 的定义是：

- 请求按 `(timestamp_ms, source_index)` 稳定排序。
- 每个 scope 各自维护一棵前缀树。
- 当前请求的命中块数，等于历史请求中已出现过的最长前缀路径长度。

实现入口在：

- `src/kvcache_upper_bound/oracle/content.py`
- `src/kvcache_upper_bound/oracle/prefix_trie.py`

它是精确的原因有两个：

1. 可复用对象被定义为“前缀路径节点”，不是裸 block hash。
2. 前缀树匹配和朴素 reference 实现可以逐请求对齐。

项目内置了两个证明层级：

- 单元测试：覆盖重复前缀、不同父前缀下同 block、session/global scope。
- 穷举 reference 校验：对小规模 toy trace，把快速 trie 实现和朴素 `O(N^2 * L)` 实现逐例对比。

默认 audit 会输出：

- `content cases verified = 41370`

这表示在 `max_requests=4`、`max_blocks_per_request=3`、字母表 `{"a","b"}` 的小规模空间里，快速实现与 reference 完全一致。

## 为什么 HBM 空间结果要叫 relaxed

当前 `capacity.py` 的 resident set 优化目标是：

- 把每个前缀节点访问看成一个 block access event
- 在固定 block capacity 下，用离线 Belady 最大化 event hit 数

这件事本身是对的；项目也会做穷举校验：

- `relaxed capacity cases verified = 165338`

这表示 Belady 实现与同一目标下的暴力 reference 完全一致。

问题在于，这个目标和业务最终关心的指标不是同一个东西。

业务关心的是：

- 一个请求从第 1 个 block 开始，能连续复用多少前缀 block

而 relaxed Belady 优化的是：

- 整个访问序列里，总共有多少个 block event 命中

后者允许一个请求出现类似 `[hit, miss, hit]` 的模式；但在严格前缀复用语义下，最后那个 hit 对 prefill 复用没有意义。

## 最小反例

项目 audit 会自动给出一个严格前缀语义与 relaxed space 上界之间的最小反例。

一个典型反例是：

- requests: `("a","a","a")`, `("a","a","a")`
- resident block capacity: `2`

在这个例子里：

- `content hit blocks = 3`
- `relaxed capacity hit blocks = 2`
- `strict prefix hit blocks = 1`

说明：

- relaxed 空间上界依然是合法上界
- 但它高估了严格前缀可复用命中率

所以当前报表的正确理解应该是：

- `极限命中率`：精确 content ceiling
- `HBM KVCache 空间命中率`：离线 Belady relaxed ceiling

## 真实 trace 怎么做侧证

项目当前提供三类侧证：

1. `sample fast == naive`
   - 对每个 bucket 的前 `N` 个请求，快速 content 实现与朴素 reference 逐请求对比。
2. `unique_prefix_nodes / resident_block_capacity / max_request_blocks`
   - 展示输入工作集大小与空间预算的相对尺度。
3. `content_hit_blocks / relaxed_hbm_hit_blocks`
   - 展示 relaxed 空间模型是否进一步压低了 content ceiling。

这些信息会写入：

- `correctness_report.json`
- `correctness_report.md`

## 当前最诚实的口径

如果你要对外解释当前项目，请用下面这段话：

> 这个分析器已经精确实现了窗口感知的 content upper bound，并用 reference 校验了结果；同时它还给出一个基于离线 Belady 的空间放松上界。公开 trace 的结果应优先理解为内容复用天花板分析，而不是严格前缀容量 oracle 的最终答案。

## 下一步

要把空间结果也做成严格 oracle，后面需要单独实现：

- strict-prefix-aware capacity objective
- 请求边界上的最优策略求解
- 对大 trace 可落地的近似或分层算法

在那之前，项目会继续保留并输出 relaxed 上界，但不会再把它误写成“已被严格证明的最终容量结果”。
