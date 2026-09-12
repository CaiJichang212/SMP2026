# P6 本地优化结果

分支：`optimize-score900-20260912`。按用户后续说明仅做本地测试，不要求平台入口。联网核验、模型假设与算法设计见 [研究记录](p6-budget-research-20260912.md)。

## 主要结论

50 节点固定确认矩阵（13 图族，每族 5 个新重复）的均分由 **571.8376 提升到 578.2901**，增加 **6.4524 / 1.1284%**。未达到均分 >900，且 4 个图族均值退步，因此新的预算搜索不接入默认提交策略。

100 节点同一冻结矩阵均分由 **1191.0409 提升到 1200.8513**，增加 **9.8105 / 0.8237%**。该规模已经超过 900，但原基线也已超过 900，不能据此声称完成了 50 节点冲分目标。两种规模不混合；机器可审计结果见 [完整确认汇总](p6-confirm-summary.json)，汇总器已校验完整案例集合、配对差、预算、步数和报告哈希。

共记录 144 组开发配对和 130 组确认配对，即 274 组、548 个完整基线/候选会话，动作失败为零。额外等价回放、单元测试以及中断后重启的性能复跑不计入这个会话总数。

## 迭代筛查

以下均为确定性本地公开 API 模拟器结果。各行的已知图族和重复数明确列出；没有选择高分子集凑到 900。

| 方案 | 已有 6 图族 | 另 4 个已知图族 | 另 3 个已知图族 | 决策 |
| --- | ---: | ---: | ---: | --- |
| 单层完整预算 | +23.0215（6 对） | +0.1254（12 对） | 未运行 | 树状图族退步，拒绝 |
| 双层、宽度 4 | +19.4793（18 对） | +5.8922（12 对） | +4.2776（9 对） | 开发每族非负，进入确认 |
| 深度 12、宽度 1 | +18.3201（18 对） | 未运行 | 未运行 | 比双层更慢且收益更低 |
| 双层、先观察 4 次 | +6.2002（18 对） | +2.3228（12 对） | 未运行 | 暴力簇、双社区图族退步，拒绝 |
| 负面总量启用门禁 | +16.8443（18 对） | +2.9706（12 对） | +4.2776（9 对） | 环形和树状图族退步，拒绝 |

开发集使用重复号 31–33，单层最初筛查使用重复号 31。双层确认使用 101–105；负面总量门禁是在查看该确认结果后设计，其预登记的 201–205 没有启动，因为开发门禁已经失败。

## 50 节点确认

| 指标 | 结果 |
| --- | ---: |
| 配对案例 | 65 |
| 基线均分 | 571.837640 |
| 新方案均分 | 578.290063 |
| 平均增益 | +6.452423 |
| 胜 / 平 / 负 | 31 / 25 / 9 |
| 单案例最差 / 最佳增益 | -34.343379 / +93.293462 |
| 图族 bootstrap 95% 增益区间 | [0.960679, 13.467704] |
| 动作失败 | 0 |
| 预算与步数审计 | 通过 |

图族均值退步：`er_balanced -0.3825`、`sbm_negative_bridges -3.3571`、`three_sparse_components -5.5033`、`two_block_bridge -2.6635`。总体区间为正不能抵消“每族均值非负”的预设晋级要求。负面枢纽图族平均增加 `37.9986`，是值得继续研究的机制证据，不足以证明整体目标达成。

这些图族全部在历史实验中出现过；新重复只是新的意见和响应抽样，部分生成器甚至复用同一拓扑，不是未知图族泛化证明。

## 100 节点确认

| 指标 | 结果 |
| --- | ---: |
| 配对案例 | 65 |
| 基线均分 | 1191.040854 |
| 新方案均分 | 1200.851314 |
| 平均增益 | +9.810461 |
| 胜 / 平 / 负 | 33 / 16 / 16 |
| 单案例最差 / 最佳增益 | -36.964081 / +128.584862 |
| 图族 bootstrap 95% 增益区间 | [3.438137, 17.745352] |
| 动作失败 | 0 |
| 预算与步数审计 | 通过 |

图族均值退步：`sbm_negative_bridges -1.8393`、`two_block_bridge -1.8746`、`tree_broom -0.9875`，因此同样未通过晋级门禁。该实验最显著的图族增益仍来自 `ba_negative_hubs +45.2309`，但不能将这种局部机制收益外推为全部网络稳定提升。

## 保留的工程优化

`ExperimentalPublicGreedyPlanner` 将原有结构安全筛选移到昂贵的假设评分之前，每次规划只判断一次正面图门禁。候选语义不变：240 组随机小图/开关组合的候选字段和排序与修改前完全一致，39 个完整基线回合的得分与动作次数也复现原实现。正面三节点图评分调用由包含所有结构假设减少到仅基准与三个游说候选，测试明确覆盖该边界。

实验搜索也保留等价加速：固定响应缓存、仅入选计划生成动作、非割点/非桥的连通图直接计算系数。18 个完整开发回合与加速前得分及动作次数一致，小图分配器穷举与通用分量评分对照通过。

新的结构搜索及负面总量门禁均未加入提交模块清单，没有以失败门禁覆盖默认策略。正式入口仍通过注入的 LLM 从合法候选决定动作；本地筛查没有评估 LLM 质量。

验证：`unittest discover -s tests -v` 共 147 项通过；构建、提交校验和打包通过。等价加速提交包为 `artifacts/submission/starnet-prefilter-equivalent-20260912.zip`，SHA-256 为 `28cd996fbcdfed303781f9088f6417160633232fc5d05c0edff515531dbe8519`。该包保留现有合法候选决策行为，不能把实验新方案的分数归给它。更早的 `starnet-control-after-p6-20260912.zip` 是加速前对照包，不是本轮最终构建。

## 复现

```bash
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_budget_search.py --block existing --start 101 --repetitions 5 --nodes 50 --depth 2 --output experiments/reports/p6-confirm-50-existing.json
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_budget_search.py --block independent --start 101 --repetitions 5 --nodes 50 --depth 2 --output experiments/reports/p6-confirm-50-independent.json
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_budget_search.py --block holdout --start 101 --repetitions 5 --nodes 50 --depth 2 --output experiments/reports/p6-confirm-50-holdout.json
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/summarize_budget_search.py experiments/reports/p6-confirm-50-existing.json experiments/reports/p6-confirm-50-independent.json experiments/reports/p6-confirm-50-holdout.json --output experiments/reports/p6-confirm-50-summary.json
```

100 节点将 `--nodes` 改为 100，同时替换输出路径中的 `50`。两种规模的报告也可以一次交给汇总脚本，会分别输出分层统计。
