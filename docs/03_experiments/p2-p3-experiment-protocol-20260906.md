# P2/P3 实验协议与低内存执行方案（2026-09-06）

## 研究问题

P2 不把“结算器预测准确”误当成“结构策略有效”，分别检验：

1. `B3 - B1`：单结构动作是否稳定改善最终分数。
2. `B4 - B1`：深度 2、宽度 4 的束搜索是否稳定改善最终分数。
3. `B4 - B3`：联合规划是否优于单结构动作。

P3 分两层检验：

1. `B5 - B4`：自适应探索是否在结构策略通过后提高收益。
2. `B5-step-LLM - B5`、`B5-event-LLM - B5`：LLM 调度是否带来净收益，并记录调用数、P95 时间和失败数。

## P2 配对设计

使用六类拓扑、50/100 节点、两个生成 seed、三个 fresh repetition，共 24 个 seed block；每个 block 运行 B1、B3、B4，计划 216 个远端 session。相同 seed、相同 repetition 是唯一配对单位，不可比记录不插补。

晋级要求同时满足：

- 全部 216 条主记录可比，零协议/动作失败；
- 24 个 block 的配对差以 block 为单位进行 10,000 次 bootstrap，95% CI 下界大于 0；
- 每个拓扑族的平均差不为负；
- B3/B4 的所有 block 都实际执行结构动作；
- B4 另报告相对 B3 的配对差。

P2.2 的 `component_degree_plus_one` 报告只作为实验 runner 的离线结算器注入，绝不修改提交默认档案。

## P3 门禁设计

P3 正式收益矩阵只有在 P2.3 通过且 `ScenarioProfile` 通过独立验证后运行。情景验证必须使用不参与结算器选择的拓扑，并证明情景与已扫描事实一致；不能从当前隐藏 seed 直接复制完整图作为线上先验。

在正式门禁未通过时，运行 P3 负对照而不是伪造收益实验：比较 B1、B5 和两种 LLM 调度的动作轨迹，要求 B5 精确回退 B1、LLM 调用为 0、动作失败为 0。负对照通过只说明安全退化成立。

## 4G 内存约束

- `component_degree_plus_one` 不缓存完整图状态，按 O(V+E) 闭式公式重算。
- 其他评分缓存上限为 256；B3/B4 terminal plans 只保留可进入执行队列的有限候选。
- P2.3 v4 使用新 cohort，`scripts/run_lowmem_matrix.py` 每个 session 启动独立子进程，子进程结束后释放 Python allocator。
- 主矩阵可用 `--worker-count 4 --worker-index 0..3` 做固定 hash 分片；worker 之间不共享策略状态，最终由 `scripts/rebuild_experiment_results.py` 从原子 session 文件重建聚合结果。
- 原 v3 的 1 条记录废弃，不与 v4 混合统计。
- 结果目录、manifest hash、profile hash 必须保持固定；暂停后只能 `--resume`。

## 统计与产物

- 原始 session：`experiments/raw/`，不提交。
- P2 manifest：[`p2-structure-policy-matrix-v4-lowmem.json`](../../experiments/manifests/p2-structure-policy-matrix-v4-lowmem.json)。
- P2 分析器：`scripts/analyze_p2_policy_matrix.py`，输出报告和 JSON 到 `experiments/reports/`。
- P3 负对照：[`p3-gate-closed-negative-control-20260906.md`](p3-gate-closed-negative-control-20260906.md) 及对应机器可读报告。

在所有晋级门禁通过前，提交默认保持无 LLM 的 B1；单个 seed 高分、代理模型分数和本地 mock 分数均不能作为策略提升证据。

## 最终状态（2026-09-07）

P2.3 已完成 `216/216` 个可比主 session，零协议/动作失败，但 B3/B4 的族级非负门禁失败，且 B4-B3 置信区间跨过 0；因此结构策略不晋级。P3 的 144 session 负对照通过，但正式 B5/LLM 收益实验因 P2 结构门禁和 scenario profile 门禁未通过而不作收益解释。
