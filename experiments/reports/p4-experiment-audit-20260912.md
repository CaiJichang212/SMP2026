# P4 实验审查与 >900 晋级方案（2026-09-12）

## 结论

现有最高公开成绩为 `761.9467`；本地资料无法证明、也不能换算出排行榜 `>900`。本地 `terminal_score` 是 `LocalPublicEnvironment` 中 `component_degree_plus_one` 的离线结算器输出，公开四节点种子分数也只是机制和协议核验。隐藏种子的最终分数由官方后台多个种子的均值决定，且排行榜使用相对评分。因此，任何本地数值（包括大于 900 的数）都不得作为目标达成证据。

当前可复现的提交对照包是 `artifacts/submission/starnet-public-greedy-llm-candidate-20260912.zip`：其配置为 `public_greedy`、`step` LLM 调度，包含一个 `CommanderAgent`。包结构正确，且策略已采用“Python 生成合法候选、LLM 最终选择、非法/超时稳定回退”的形式。

## 可比性审查

| 信号 | 是否可比较排行榜 | 可支持的结论 |
| --- | --- | --- |
| `run_local_policy_matrix.py` | 否 | 在固定、可审计的合成图上比较策略方向、预算、动作失败和模拟 LLM 调用数。|
| `run_response_ablation.py` | 否 | 仅比较公开动作返回驱动的游说响应先验。|
| 官方自定义 seed + runner `trigger_eval()` | 有限 | 可验证公开 API、动作和终局语义；不能代表隐藏种子分布。|
| 平台提交 | 是 | 唯一可检验 `>900` 目标的指标。|

`src/starnet/experiments/seeds.py` 提供六个既有、确定性图族；`run_local_policy_matrix.py` 还提供四个独立族和三个未参与早先选择的 holdout 族。50 节点本地限制为预算 100、LLM/step 120，100 节点为预算 200、LLM/step 250。注意本地 `max_api_calls` 是调试保护；正式限制仍以赛方熔断为准。每一比较应以 `(family, node_count, repetition)` 配对，禁止把 50/100 节点原始终局数混合成“初赛分数”。

## 本次轻量复跑

命令：

```bash
uv run python scripts/run_local_policy_matrix.py --block holdout --node-counts 50 --repetitions 1 --include-llm-mock --output /tmp/p4-holdout-light.json
uv run python scripts/run_response_ablation.py --block independent --node-count 50 --repetitions 2 --output /tmp/p4-response-light.json
```

三组 holdout 上，`public_greedy - B1` 的配对增益为：`double_bridge_communities +86.24`、`negative_hub_spokes +328.10`、`ring_of_cliques +74.04`；三组均零动作失败。三族均值的 bootstrap 95% 区间为 `[+74.04, +328.10]`。确定性 schema-valid LLM 替身与结构策略逐种子轨迹相同，分别调用 `80`、`83`、`77` 次，低于 50 节点的 120 次限额。这个结果支持“当前结构动作在这三个留出场景值得继续作为对照”，不估计真实 LLM 的质量。

响应先验的小样本消融未通过：`pooled` 平均仅 `+1.18`，且 `tree_broom` 族均值 `-1.96`；`persona_shrunk` 平均 `-0.87`，且 `two_block_bridge` `-17.02`。两者都不应进入提交策略。零失败只说明协议正常，不能弥补族级负增益。

## 下一轮

完整预注册矩阵见 [`p4-900-promotion-matrix-20260912.json`](../manifests/p4-900-promotion-matrix-20260912.json)。优先检验切边组合与屏蔽阈值，而不是继续调响应先验：现有 holdout 中结构动作全部为屏蔽，切边的组合收益尚无足够证据。任何代码候选先过 S0/S1 的独立与 holdout 门，再用真实 LLM 和官方终局分进行 S3；只有官方终局的配对门和平台提交成绩共同支持时，才可以声称向 `>900` 推进。
