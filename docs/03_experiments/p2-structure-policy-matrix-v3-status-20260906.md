# P2.3 结构策略配对矩阵：当前状态（2026-09-06）

## 状态：未完成，不作策略结论

P2.3 用于检验结构策略的真实终局收益，主比较为 `B3 - B1`、`B4 - B1` 与 `B4 - B3`。截至本记录，固定终态复核已完成，但主矩阵只完成一个会话，持久 runner 已停止。不得从该单条记录推断 B3/B4 优于、劣于或等同于 B1。

| 区块 | 计划 | 已完成且可比 | 失败 | 状态 |
| --- | ---: | ---: | ---: | --- |
| P0 固定终态复核 | 20 | 20 | 0 | 通过，四组分数跨度均为 0 |
| P2.3 主矩阵 | 216 | 1 | 0 | 未完成，runner 已停止 |
| 合计 | 236 | 21 | 0 | 不可进入配对统计 |

已完成主会话为 `b3_single_structure / ba_negative_hubs-50-r1 / repetition=1`。该会话扫描 50 个节点，执行 1 次切边、9 次屏蔽、13 次游说，终局分 `530.23`。其可比性通过，但缺少同 seed、同重复的 B1 与 B4，因此仅构成运行路径证据。

## 冻结的恢复规则

清单 [`p2-structure-policy-matrix-v3.json`](../../experiments/manifests/p2-structure-policy-matrix-v3.json) 已固定六个拓扑族、50/100 节点、两个 seed、三个 fresh repetition，以及 B1/B3/B4 三变体，主矩阵为 `24 × 3 × 3 = 216` 会话。恢复时只允许以相同 manifest、相同 P2.2 实验档案、相同结果根目录和 `--resume` 补跑缺失会话；不得改变 seed、变体、重复数、结构深度/宽度或门槛。

完整后，每个比较须在 24 个 seed block（先对三次重复求均值）做 10,000 次 bootstrap，95% CI 下界大于 0、任何拓扑族均值不为负、零新增协议/动作失败，且 B3/B4 实际执行过结构动作。完成前，默认仍为无 LLM 的 B1，`DEFAULT_CALIBRATION_PROFILE` 不冻结。

原始记录在忽略目录 `experiments/raw/p2-structure-policy-matrix-v3-20260906/f2fb152130f13ead/`。机器可读状态见 [`p2-structure-policy-matrix-v3-status-20260906.json`](../../experiments/reports/p2-structure-policy-matrix-v3-status-20260906.json)。

> 已知运行限制：修复前的结构规划会保留大量完整图反事实状态，4GB 服务器可能卡死。修复与低内存恢复命令见 [`p2-structure-policy-memory-remediation-20260906.md`](p2-structure-policy-memory-remediation-20260906.md)。修复后会改变实验执行代码版本；恢复主矩阵前应建立新的计划命名空间，不能把修复前 1 条主记录与修复后的新记录混作同一统计 cohort。
