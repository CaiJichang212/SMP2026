# P2.3 主矩阵内存修复（2026-09-06）

## 原因判断

P2.3 的 50/100 节点结构规划在 4GB 服务器上卡死，主要风险在客户端的反事实规划状态，而不是实验 seed 本身：

1. 每个结构候选都要补全一串游说反事实；旧评分缓存以完整节点/边状态作 key。密图和 100 节点下，大量 key 会保留整张图的副本。
2. B3 对所有已评分结构动作保留完整计划，尽管进入控制器的候选上限仅为 12。
3. B4 每层会保留大量 terminal plan；其后续可扩展的仅是 width=4 的 beam。

这会随候选数、游说次数和重规划叠加，导致数十万级大状态元组长期存活。它解释了小图 P2.2 正常、主矩阵大图卡死的差异。

## 修复

`StructuralPlanner` 已作如下内存上界修复：

| 项目 | 原行为 | 修复后 |
| --- | --- | --- |
| `component_degree_plus_one` 评分缓存 | 缓存完整图状态 | 不缓存；该评分为 O(V+E) 闭式计算，重算比保存图副本更省内存 |
| 其他候选模型缓存 | 无上界 | 最多 256 个状态，达到上限即清空 |
| B3 terminal plans | 保留所有已评分动作的完整游说计划 | 仅保留 baseline 加最多 `candidate_limit=12` 个候选 |
| B4 terminal plans | 随 beam 扩展累积 | 每层立即裁剪至 baseline 加最多 12 个候选 |

评分函数、所有合法结构动作的评分覆盖、beam 宽度、候选排序和 fail-closed 规则均未改变；裁剪只丢弃不可能进入执行队列的完整计划。

## 验证与运行建议

新增测试确认已验证的分量结算器在结构候选生成后不保留完整图状态缓存。结构/控制器/协议聚焦测试 `25/25` 通过，提交构建和校验通过。

4GB 机器重启 P2.3 时，建议每次只跑一个 fresh session，以进程退出释放 Python allocator 保留的 arena；每批后检查 RSS 和原始记录，再以**新的、版本化 manifest 与结果根目录**续跑。不要并发多个 B4 会话，也不要把修复前记录混入新 cohort。

```bash
uv run python scripts/run_experiments.py \
  --manifest <修复后的版本化清单> \
  --experimental-calibration-report experiments/reports/p2-topology-holdout-v2-20260906.json \
  --result-dir <修复后的独立结果目录> \
  --resume --max-new-sessions 1
```

主矩阵当前仍为 `1/216`，不产生 B3/B4 收益结论；修复后须从新的完整 cohort 重启，不能混合修复前后的记录作为同一统计 cohort。
