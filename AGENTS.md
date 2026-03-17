# kvcache-upper-bound-oracle

## 目录结构

```text
kvcache-upper-bound-oracle/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── docs/
│   ├── correctness_guide.md
│   └── design_guide.md
├── configs/
├── outputs/
├── src/
│   └── kvcache_upper_bound/
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   └── models.py
│       ├── ingest/
│       │   ├── __init__.py
│       │   ├── normalizer.py
│       │   └── trace_loader.py
│       └── oracle/
│           ├── __init__.py
│           ├── capacity.py
│           ├── content.py
│           └── prefix_trie.py
│       ├── reporting/
│       │   ├── __init__.py
│       │   └── buckets.py
│       ├── verification/
│       │   ├── __init__.py
│       │   ├── audit.py
│       │   └── reference.py
│       ├── cli/
│       │   ├── __init__.py
│       │   └── main.py
│       └── __main__.py
└── tests/
    ├── _bootstrap.py
    ├── __init__.py
    ├── conftest.py
    ├── test_bucket_reporting.py
    ├── test_capacity_oracle.py
    ├── test_content_oracle.py
    ├── test_normalizer.py
    ├── test_trace_loader.py
    └── test_verification_reference.py
```

## 文件职责

- `README.md`：项目入口，只讲目标、范围、启动顺序。
- `pyproject.toml`：本地可安装入口；保证 `kvcache-upper-bound` 命令可直接运行。
- `docs/design_guide.md`：需求、口径、算法、阶段计划的单一事实来源。
- `docs/correctness_guide.md`：解释哪些结果已被 reference 证明，哪些仍然只是 relaxed 上界。
- `src/kvcache_upper_bound/core/models.py`：稳定数据模型；这里定义请求、窗口化请求、模型配置等核心对象。
- `src/kvcache_upper_bound/ingest/trace_loader.py`：读取 JSONL trace，做字段解析、时间标准化和稳定排序。
- `src/kvcache_upper_bound/ingest/normalizer.py`：把原始请求转成 window-aware 的 `EffectiveRequest`，并解析 session root。
- `src/kvcache_upper_bound/oracle/prefix_trie.py`：前缀路径状态机；只负责匹配和插入，不混入聚合逻辑。
- `src/kvcache_upper_bound/oracle/content.py`：内容上限分析；对每请求输出 hit/miss，并汇总 block/token/byte 指标。
- `src/kvcache_upper_bound/oracle/capacity.py`：空间上限分析；基于离线 Belady 对 HBM 或扩展空间预算做最优命中上界估计。
- `src/kvcache_upper_bound/reporting/buckets.py`：按业务长度桶和部署规格生成汇总表，直接对接“机器数/规格/TPS/HBM/命中率”视图。
- `src/kvcache_upper_bound/cli/main.py`：命令行入口；负责把 trace、配置、输出目录串成完整离线分析流程。
- `src/kvcache_upper_bound/verification/reference.py`：朴素 reference、暴力验证器和 strict-prefix 反例搜索器。
- `src/kvcache_upper_bound/verification/audit.py`：把 reference 结果、trace 样本对账和 bucket 诊断写成 correctness report，并同时输出中英文 Markdown 报告。
- `src/kvcache_upper_bound/`：分析器实现根目录；后续继续扩展 `oracle/`, `reporting/`, `cli/`。
- `tests/`：面向口径和边界条件的测试，不写和实现细节强绑定的脆弱测试。
- `configs/`：样例机器配置、模型配置、实验矩阵。
- `outputs/`：本地产出目录，只放实验结果，不承载源码语义。

## 架构原则

- 第一版先做离线 oracle，不做在线 serving runtime。
- 统一以 block 为主粒度，默认 block size 为 16；token 粒度只做换算层。
- 核心口径固定为：`strict_prefix_window`、`prefill only`、`content -> capacity -> system` 三级上限。
- `hash_ids` 必须按前缀路径解释，不能退化成裸 block 频次统计。
- `ModelProfile.kv_bytes_per_token()` 表示整套部署的总 KV 占用，不是单卡 shard 占用；预算字段必须和它保持同一口径。
- 混合注意力模型必须显式提供 `kv_cache_layer_count`；不能拿总层数硬套 KV 公式。
- 纯计算逻辑放 `src/`，文件 IO 和命令行入口后置，避免副作用污染核心算法。
- `core/` 不依赖 `ingest/`；数据结构必须比解析逻辑更稳定。
- `normalizer.py` 只做窗口化和 scope 解析，不提前引入缓存策略。
- `prefix_trie.py` 必须保持纯前缀语义；不要把计数、报告和缓存层策略塞进去。
- `content.py` 只回答“历史上是否已有这段前缀”，不回答容量和带宽问题。
- `capacity.py` 只回答“空间够不够”，不回答搬运带宽和系统调度问题。
- `verification/` 负责证明与揭示边界：能证明的就输出证据，证明不了的就输出反例。
- `reporting/` 负责把算法结果翻译成业务表格；不要反向污染 oracle 的数据结构。

## 开发规范

- 先让数据模型稳定，再写缓存模拟；不要把解析、策略、报告耦在一起。
- 每个阶段先补最小测试：口径边界、单调性、总量守恒。
- 每次改动命中率口径，必须同步更新 `docs/correctness_guide.md`，不能只改代码不改证明口径。
- 文档先行：新增模块或目录时，先更新本文件和 `docs/design_guide.md`。
- 保持函数短小；三个以上显式分支时，优先重构数据流而不是继续堆逻辑。

## 变更记录

- `2026-03-17`：初始化项目骨架，落地设计指导文档。
- `2026-03-17`：新增 `core/` 与 `ingest/`，开始实现 M1 trace 规范化路径。
- `2026-03-17`：新增 `oracle/`，开始实现 M2 content upper bound。
- `2026-03-17`：新增 `capacity/reporting/cli`，开始支持按业务分桶输出 HBM 与扩展空间命中率。
- `2026-03-17`：新增 `verification/`、`correctness_guide.md` 和 `audit-buckets`，开始显式输出 reference 证明与 strict-prefix 反例。
