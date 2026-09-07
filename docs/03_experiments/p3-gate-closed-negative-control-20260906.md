# P3 门禁关闭负对照实验（2026-09-06）

## 实验目的

P3 的正式比较是 `B5-B4`、`B5-step-LLM-B5` 和 `B5-event-LLM-B5`。这些比较只有在 P2 结构资格和独立 `ScenarioProfile` 均通过后才有解释意义。本实验不伪造 scenario profile，而是验证门禁关闭时的安全不变式：B5 必须精确退回 B1，且不得调用 LLM。

## 设计

- 使用代码生成的 6 个拓扑、50/100 节点和 3 个 repetition，共 36 个 seed block。
- 每个 block 运行 `b1_persuasion`、`b5_adaptive`、`b5_step_llm`、`b5_event_llm` 四个本地 session，共 144 个 session。
- 环境只提供控制器使用的公开扫描、游说、切边和屏蔽接口；不读取环境私有成员。
- 所有 B5 变体使用当前 `DEFAULT_CALIBRATION_PROFILE`，其中 `structure_gate_passed=false`、`scenario_gate_passed=false`。
- 比较动作序列、有效策略模式、动作失败数和 LLM/排序器调用数。

## 结果

机器可读结果：[`p3-gate-closed-negative-control-20260906.json`](../../experiments/reports/p3-gate-closed-negative-control-20260906.json)。原始逐 session 记录位于被忽略的 `experiments/raw/`。

| 指标 | 结果 |
| --- | ---: |
| session | 144 |
| seed block | 36 |
| B1/B5 动作序列完全一致 | 是 |
| 有效策略模式 | 全部 `b1_persuasion` |
| 最大 LLM 调用数 | 0 |
| 最大排序器 payload 数 | 0 |
| 动作失败数 | 0 |
| 门禁结果 | 通过 |

## 结论边界

本实验证明了 P3 的 fail-closed 安全行为，不证明自适应扫描或 LLM 的收益。由于 P2.3 结构策略收益矩阵尚未完成，且没有独立验证的 `ScenarioProfile`，P3 正式收益矩阵不能运行或解释；继续运行会得到被门禁强制退回 B1 的负对照，而不是 B5 能力结果。

下一步应在 P2.3 配对门禁通过后，用拓扑不相交的情景验证集构造并验证 `ScenarioProfile`，再运行 B5 无 LLM、step-LLM 和 event-LLM 三个独立消融。
