# kvcache-upper-bound-oracle

## 目录结构

```text
kvcache-upper-bound-oracle/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── docs/
│   ├── correctness_guide.md
│   ├── design_guide.md
│   └── four_layer_model.md
├── configs/
│   ├── public_trace_qwen3_5_27b.json
│   ├── public_trace_qwen3_5_27b_1x1_h20.json
│   ├── public_trace_qwen3_5_27b_1x1_h20_planning_norm.json
│   ├── public_trace_qwen3_5_27b_planning_norm.json
│   ├── public_multi_agent_qwen3_5_27b.json
│   └── public_multi_agent_qwen3_5_27b_1x1_h20.json
├── outputs/
├── src/
│   └── kvcache_upper_bound/
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   └── models.py
│       ├── heuristic/
│       │   ├── __init__.py
│       │   ├── calibration.py
│       │   ├── config_loader.py
│       │   ├── multi_agent.py
│       │   ├── output.py
│       │   ├── report.py
│       │   └── structure.py
│       ├── ingest/
│       │   ├── __init__.py
│       │   ├── normalizer.py
│       │   └── trace_loader.py
│       ├── oracle/
│       │   ├── __init__.py
│       │   ├── capacity.py
│       │   ├── content.py
│       │   ├── lru.py
│       │   ├── prefix_trie.py
│       │   └── strict_prefix.py
│       ├── reporting/
│       │   ├── __init__.py
│       │   ├── buckets.py
│       │   ├── config_loader.py
│       │   ├── hit_output.py
│       │   ├── inputs.py
│       │   ├── planning_output.py
│       │   ├── planning_search.py
│       │   ├── output.py
│       │   └── table_common.py
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
    ├── test_bucket_output_files.py
    ├── test_bucket_reporting.py
    ├── test_capacity_oracle.py
    ├── test_content_oracle.py
    ├── test_lru_oracle.py
    ├── test_multi_agent_calibration.py
    ├── test_multi_agent_heuristic.py
    ├── test_multi_agent_structure.py
    ├── test_normalizer.py
    ├── test_strict_prefix_oracle.py
    ├── test_trace_loader.py
    └── test_verification_reference.py
```

## 文件职责

- `README.md`：项目入口，只讲目标、范围、启动顺序，以及为什么主表要收敛到 HBM 当前层、额外容量层要改看 `tier_summary.csv` 长表。
- `pyproject.toml`：本地可安装入口；保证 `kvcache-upper-bound` 命令可直接运行。
- `docs/design_guide.md`：需求、口径、算法、阶段计划的单一事实来源。
- `docs/correctness_guide.md`：解释哪些结果已被 reference 证明，哪些指标只是解释 exact strict-prefix 的辅助证据。
- `docs/four_layer_model.md`：对外展示文档；主线只讲 `容量 -> 命中 -> TPS -> 机器需求` 与无 profile 估计。
- `src/kvcache_upper_bound/core/models.py`：稳定数据模型；这里定义请求、窗口化请求、模型配置，以及从模型参数量推导权重占用所需的核心对象。
- `src/kvcache_upper_bound/heuristic/multi_agent.py`：无 trace 多 Agent 冷启动估计器；用 `shared/private` 工作集分解、曲线形状函数和 `policy_efficiency` 输出 `strict-prefix` 上界估计与 `LRU-like` 估计。
- `src/kvcache_upper_bound/heuristic/calibration.py`：trace 回标引擎；把分桶 trace oracle 聚合成单一观测目标，对 `zipf_s × lru_like` 做网格搜索，并输出最佳参数、分层误差与回标后的配置。
- `src/kvcache_upper_bound/heuristic/config_loader.py`：无 trace heuristic 配置解析与校验；负责把 `curve_mode / zipf_s / policy_efficiency / deployment budgets` 的口径钉死。
- `src/kvcache_upper_bound/heuristic/output.py`：无 trace heuristic 输出层；负责写 `heuristic_summary.csv / heuristic_tier_summary.csv / details.json`，并生成归一化输入摘要。
- `src/kvcache_upper_bound/heuristic/report.py`：无 trace heuristic 双语报告输出；负责生成 `heuristic_report.md / heuristic_report.zh.md / heuristic_report.en.md`，并在有回标时追加 calibration 章节。
- `src/kvcache_upper_bound/heuristic/structure.py`：trace 结构建议器；从 session 形态提取 `shared prefix / Delta / T / W / n` 的候选模板，并生成 `recommended_heuristic_config.json`。
- `src/kvcache_upper_bound/ingest/trace_loader.py`：读取 JSONL trace，做字段解析、时间标准化和稳定排序。
- `src/kvcache_upper_bound/ingest/normalizer.py`：把原始请求转成 window-aware 的 `EffectiveRequest`，并解析 session root。
- `src/kvcache_upper_bound/oracle/prefix_trie.py`：前缀路径状态机；只负责匹配和插入，不混入聚合逻辑。
- `src/kvcache_upper_bound/oracle/content.py`：内容上限分析；对每请求输出 hit/miss，并汇总 block/token/byte 指标。
- `src/kvcache_upper_bound/oracle/capacity.py`：空间上限分析；基于允许 `no-admit` 的离线 Belady，对 HBM 或扩展空间预算做 event-level 最优命中上界估计。
- `src/kvcache_upper_bound/oracle/lru.py`：LRU 策略基线；在相同 prefix-path 语义下输出在线 LRU 的 strict-prefix 命中结果，只用来和 exact strict-prefix 对比，不充当上界。
- `src/kvcache_upper_bound/oracle/strict_prefix.py`：严格前缀容量 oracle；先走 `content` / `relaxed==replay` 证书快路，证书不够时再做请求边界 DP 精确搜索。
- `src/kvcache_upper_bound/reporting/buckets.py`：按长度分桶做核心分析；这里只保留分桶执行、命中率汇总和 target-TPS 规划求值，不再混入配置解析细节。
- `src/kvcache_upper_bound/reporting/config_loader.py`：分桶配置解析与语义校验；这里负责把“机器/卡/TPS/预算/规划锚点”口径钉死。
- `src/kvcache_upper_bound/reporting/inputs.py`：输入归一化摘要；从分桶结果提炼 `metadata.json` 和 correctness report 需要的稳定输入口径。
- `src/kvcache_upper_bound/reporting/table_common.py`：报表公共列名、格式化、诊断判定和行范围工具；统一 `Strict-Prefix / LRU` 列命名，避免多处手写漂移。
- `src/kvcache_upper_bound/reporting/hit_output.py`：命中结果视图；负责 `summary.csv` 和 `hit_summary.csv` 里的 HBM 主列与“容量/策略瓶颈”诊断列拼装。
- `src/kvcache_upper_bound/reporting/planning_output.py`：规划结果视图；负责 exact strict-prefix 上界规划和 LRU 策略规划的字段与载荷生成。
- `src/kvcache_upper_bound/reporting/planning_search.py`：target-TPS 规划搜索与 TPS 数学；把 `TPS Gain`、局部等效值和“最小整数部署”搜索从分析主循环里抽出来。
- `src/kvcache_upper_bound/reporting/output.py`：输出编排与落盘；负责把各视图写成 `summary.csv / hit_summary.csv / planning_strict_prefix.csv / planning_lru.csv / tier_summary.csv / details.json`，并把扩容层结果展开成长表。
- `src/kvcache_upper_bound/cli/main.py`：命令行入口；负责把 trace、配置、输出目录串成完整离线分析流程，并让 `metadata.json` 同时输出报表行镜像和输入归一化摘要。
- `src/kvcache_upper_bound/verification/reference.py`：朴素 reference、暴力验证器、strict-prefix 精确 oracle 对账器，以及 `relaxed == replay == exact` 的穷举等价校验器。
- `src/kvcache_upper_bound/verification/audit.py`：把 reference 结果、trace 样本对账、relaxed/replay/exact strict-prefix 诊断、proof source 写成 correctness report，并同时输出中英文 Markdown 报告。
- `src/kvcache_upper_bound/`：分析器实现根目录；后续继续扩展 `oracle/`, `reporting/`, `cli/`。
- `tests/test_bucket_output_files.py`：报表文件和 `details.json` 的结构测试；专门承接输出层断言，避免 `test_bucket_reporting.py` 继续膨胀。
- `tests/test_lru_oracle.py`：LRU 策略基线测试；覆盖“容量足够可复用”和“不能像 relaxed 一样 skip-admit”两类关键边界。
- `tests/test_multi_agent_heuristic.py`：无 trace 多 Agent heuristic 测试；覆盖私有工作集平均值、Zipf 派生参数、单调性、`LRU-like <= strict-prefix` 和 CLI 输出文件。
- `tests/test_multi_agent_calibration.py`：trace 回标测试；覆盖 synthetic target 参数恢复、`calibrate-multi-agent` CLI 输出文件和双语报告。
- `tests/test_multi_agent_structure.py`：trace 结构建议测试；覆盖 append-only session 结构恢复和推荐模板回填。
- `tests/`：面向口径和边界条件的测试，不写和实现细节强绑定的脆弱测试。
- `configs/public_trace_qwen3_5_27b.json`：公开 `1` 机 `8` 卡 `h20` 样例；适合看“容量基本不构成约束”时的上界结果。
- `configs/public_trace_qwen3_5_27b_1x1_h20.json`：公开 `1` 机 `1` 卡 `h20` 样例；专门用来放大单卡显存约束，观察 HBM 上限如何压低命中率。
- `configs/public_trace_qwen3_5_27b_planning_norm.json`：公开 `1` 机 `8` 卡归一化规划样例；固定 `baseline_per_card_tps = 1`、`planning_target_total_tps = 8`，用于直接演示目标 TPS 规划。
- `configs/public_trace_qwen3_5_27b_1x1_h20_planning_norm.json`：公开 `1` 机 `1` 卡归一化规划样例；和 `1x8` 版本共享同一目标 TPS，专门用来横向比较部署形态。
- `configs/public_multi_agent_qwen3_5_27b.json`：公开 `1` 机 `8` 卡 `h20` 无 trace heuristic 样例；基于 `Qwen/Qwen3.5-27B` 公共模型参数演示冷启动估计。
- `configs/public_multi_agent_qwen3_5_27b_1x1_h20.json`：公开 `1` 机 `1` 卡 `h20` 无 trace heuristic 样例；专门用来放大单卡显存约束在冷启动估计里的影响。
- `configs/`：样例机器配置、模型配置、实验矩阵。
- `outputs/`：本地产出目录，只放实验结果，不承载源码语义。

## 架构原则

- 第一版先做离线 oracle，不做在线 serving runtime。
- 统一以 block 为主粒度，默认 block size 为 16；token 粒度只做换算层。
- 核心口径固定为：`strict_prefix_window`、`prefill only`、`content -> capacity -> policy -> heuristic` 四层框架；前 3 层可由 trace 驱动，第四层只做无 trace 冷启动估计。
- 更外层的通用分析框架固定为：`Oracle -> Policy -> Economics -> Heuristic` 四层；不要把四层混成一个公式。
- `hash_ids` 必须按前缀路径解释，不能退化成裸 block 频次统计。
- `ModelProfile.kv_bytes_per_token()` 表示整套部署的总 KV 占用，不是单卡 shard 占用；预算字段必须和它保持同一口径。
- 部署配置必须显式提供 `accelerator_count` 与 `cards_per_machine`；`machine_count` 和 `8*h20` 这类隐式写法都不再接受。
- 报表里的 `机器数` 始终由 `accelerator_count / cards_per_machine` 推导；`总 TPS` 始终归一成集群总 TPS，原始输入单位单独记录在 `TPS 输入口径`。
- `ModelProfile.parameter_count` 只用于从显存反推理论 KV 预算；不提供时，就必须显式给出 `hbm_kv_gb_per_card` 或利用率。
- HBM / 显存 / runtime reserve 预算字段必须使用显式 `*_per_card` 命名；`*_per_machine` 旧名字一律视为错误输入。
- 混合注意力模型必须显式提供 `kv_cache_layer_count`；不能拿总层数硬套 KV 公式。
- 纯计算逻辑放 `src/`，文件 IO 和命令行入口后置，避免副作用污染核心算法。
- `core/` 不依赖 `ingest/`；数据结构必须比解析逻辑更稳定。
- `normalizer.py` 只做窗口化和 scope 解析，不提前引入缓存策略。
- `prefix_trie.py` 必须保持纯前缀语义；不要把计数、报告和缓存层策略塞进去。
- `content.py` 只回答“历史上是否已有这段前缀”，不回答容量和带宽问题。
- `capacity.py` 只回答“event-level 空间够不够”，不回答搬运带宽和系统调度问题。
- `strict_prefix.py` 只回答“严格前缀语义下空间最优能到哪”，不要把 trace 读取、报表拼接塞进去。
- `verification/` 负责证明与揭示边界：能证明的就输出证据，证明不了的就明确上下界，不编造确定性。
- `verification/` 新增任何“证书”口径时，必须同时给出上下界链路，不能只给结论不给夹逼关系。
- `reporting/` 负责把算法结果翻译成汇总表和结果文件；不要反向污染 oracle 的数据结构。
- `reporting/` 内允许做命中率到 `TPS / 机器数` 的纯后处理，但不能把机器数、调度和带宽反向混进 oracle 定义。
- `reporting/` 输出要坚持主次分离：命中估算是主结果，`TPS / 机器数` 是派生结果；不要把派生列淹没主口径。
- 主 CSV 优先服务“当前 HBM 怎么看”；额外容量层不要再横向展开成超宽表，而要放进 `tier_summary.csv` 这种长表里做层间比较。
- 上界规划和策略规划必须显式分开：`planning_strict_prefix.csv` 代表 exact strict-prefix，`planning_lru.csv` 代表 LRU；不要再使用含混的 `HBM TPS Gain` 之类列名。
- `heuristic/` 是第四层冷启动引擎，不是 oracle；它只能输出 `估计`，不能输出 `proof source`，也不能和 exact strict-prefix/LRU 主表混成一张表。
- `heuristic/calibration.py` 只能做“参数贴合”，不能偷换成“结果证明”；凡是回标结果，都必须同时输出误差和边界说明。
- `heuristic/structure.py` 可以用 trace 反推结构模板，但它输出的是“推荐配置”，不是“真实 workload 真相”；一旦和 oracle 不一致，必须让报告显式展示差值。
- 绝对规划必须显式提供锚点：`baseline_per_card_tps` 给出无命中单卡基线吞吐，`planning_target_total_tps` 给出目标总 TPS；只有这两个量到位，`最小卡数 / 最小机器数` 才有可比性。
- `同负载估算卡数 / 机器数` 只能当固定命中率下的算力等效值；它们留在 `details.json` 做诊断，不要再放进主 CSV 干扰部署规划阅读。
- 命中表必须显式回答“是容量瓶颈还是策略瓶颈”；不要让读者自己拿三列数字脑补。
- `LRU` 既是命中基线，也是策略规划输入；但它不能替代 exact strict-prefix 的上界地位。

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
- `2026-03-17`：新增 `capacity/reporting/cli`，开始支持按长度分桶输出 HBM 与扩展空间命中率。
- `2026-03-17`：新增 `verification/`、`correctness_guide.md` 和 `audit-buckets`，开始显式输出 reference 证明、strict-prefix 等价校验与中英双语 correctness report。
- `2026-03-17`：把 exact `strict-prefix capacity oracle` 接入 `reporting/` 与 `verification/` 主路径；主报表和 correctness report 统一输出 exact hit rate 与 proof source。
- `2026-03-17`：支持从 `gpu_memory_gb_per_card - 模型权重分片 - runtime reserve` 推导 HBM KV 预算，公开 `h20` 配置不再写死魔法数字。
- `2026-03-18`：新增 `docs/four_layer_model.md`，定义对外展示用的 `容量 -> 命中 -> TPS -> 机器需求` 简化模型，并保留无 profile 估计入口。
- `2026-03-18`：把 `prefill_savings_alpha` 接入分桶报表和 `metadata.json`，基于 exact strict-prefix 命中率新增 `TPS Gain / 估算总 TPS / 同负载估算机器数` 后处理。
- `2026-03-18`：新增 `hit_summary.csv` 与 `planning_strict_prefix.csv` 输出，显式把核心 KV 命中估算和派生容量规划结果拆开，`summary.csv` 仅作兼容视图保留。
- `2026-03-18`：把部署规模口径从含混的“机器数”修正为“卡数优先、机器数显式推导”；公开配置改成 `1` 机 `8` 卡，报表新增 `卡数 / 单机卡数 / 同负载估算卡数`。
- `2026-03-18`：收紧部署配置 schema：`accelerator_count + cards_per_machine + machine_spec` 成为唯一合法机器描述；`total_tps_unit` 显式落盘并统一换算到集群总 TPS。
- `2026-03-18`：把 HBM 预算命名彻底收紧到单卡口径：`hbm_kv_gb_per_card / gpu_memory_gb_per_card / runtime_reserve_gb_per_card` 成为唯一合法字段，输出 JSON 同步改名。
- `2026-03-18`：新增部署配置语义校验与输入归一化摘要；`metadata.json` 和 `correctness_report` 现在显式写出归一后的卡数、机器数、TPS 与容量口径。
- `2026-03-18`：把 `reporting/buckets.py` 拆出 `reporting/output.py`，避免单文件继续膨胀；分析、校验、输出三类职责重新分层。
- `2026-03-18`：新增 `oracle/lru.py` 与对应测试；主报表开始同时输出 `HBM LRU 命中率` 和扩展容量层的 `LRU` 基线命中率，但规划列仍只基于 exact strict-prefix。
- `2026-03-18`：把输出层测试拆到 `tests/test_bucket_output_files.py`，恢复单文件规模，继续保持测试职责分离。
- `2026-03-18`：新增 `reporting/inputs.py`，把输入归一化摘要从 `buckets.py` 抽离；同时新增 `planning_lru.csv`，把 exact strict-prefix 上界规划和 LRU 策略规划彻底分开。
- `2026-03-18`：继续把 `reporting/output.py` 拆成 `table_common.py / hit_output.py / planning_output.py / output.py` 四层；现在输出编排、命中视图、规划视图、公共列名完全分离，单文件重新回到可维护规模。
- `2026-03-18`：把 strict-prefix 规划文件显式改名为 `planning_strict_prefix.csv`，并新增公开 `1` 机 `1` 卡 `h20` 配置，专门暴露单卡显存约束下的命中率下降。
- `2026-03-18`：新增 `reporting/config_loader.py` 与 `reporting/planning_search.py`；把配置解析/校验和 target-TPS 规划搜索从 `buckets.py` 拆开，同时新增 `baseline_per_card_tps + planning_target_total_tps -> 最小卡数 / 最小机器数` 的闭环规划结果。
- `2026-03-18`：精简主 CSV 规划列：移除 `同负载估算卡数 / 机器数`，只保留 `TPS Gain / 估算总 TPS / 当前配置可承载总 TPS / 目标总 TPS 最小卡数 / 最小机器数`；同时新增两份归一化 planning 样例配置，方便直接比较 `1x8` 与 `1x1` 部署。
- `2026-03-18`：主表继续窄化：`hit_summary.csv / planning_*.csv` 只保留 HBM 当前层主列；新增 `tier_summary.csv` 长表统一承接 `HBM / 1T / 10T` 层间比较，并新增“达到上界 / 达到 strict / 当前主要瓶颈 / 相对上一层增益”诊断列。
- `2026-03-18`：新增 `heuristic/` 包和 `estimate-multi-agent` CLI；现在项目支持不依赖 trace 的多 Agent 冷启动估计，并额外输出 `heuristic_summary.csv / heuristic_tier_summary.csv / metadata.json`。
- `2026-03-18`：新增 `heuristic/calibration.py`、`heuristic/report.py` 和 `calibrate-multi-agent` CLI；现在项目支持用小样本 trace 回标 `zipf_s / lru_like`，并固定输出双语 heuristic 报告与 calibration 工件。
- `2026-03-18`：新增 `heuristic/structure.py` 与 `recommended_heuristic_config.json` 输出；现在 calibration 路径会同时给出 trace 驱动的结构模板建议，并把 content 对齐效果写入双语报告。
