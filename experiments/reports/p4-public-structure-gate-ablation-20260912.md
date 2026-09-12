# P4 公开结构候选门消融（2026-09-12）

对同一个 50 节点合成种子分别运行当前 `PUBLIC_GREEDY`、仅保留高正向图门的宽松候选，以及允许所有正终局增益结构动作的候选。每块每拓扑族 3 次重复；策略只收到公开扫描与动作返回，隐含响应系数仍由本地环境内部使用。三臂共享当前 ROI 余量、全扫描和终局替代模型。运行命令：

```bash
uv run python scripts/run_public_structure_gate_ablation.py --block existing --repetitions 3 --output experiments/reports/p4-public-structure-gate-existing-20260912.json
uv run python scripts/run_public_structure_gate_ablation.py --block holdout --repetitions 3 --output experiments/reports/p4-public-structure-gate-holdout-20260912.json
```

两个宽松臂在这批样本上产生完全相同的终局结果。相对当前策略，既有六族仅 `three_sparse_components` 有族均 `+2.135`，其他五族为 `0`，总体配对平均 `+0.356`；留出三族仅 `double_bridge_communities` 为 `−1.462`，其他两族为 `0`，总体 `−0.487`。两块全部零动作失败。逐种子数据见 [既有块](p4-public-structure-gate-existing-20260912.json) 和 [留出块](p4-public-structure-gate-holdout-20260912.json)。

结论：候选门放宽没有通过预设的每族非负门禁，不能晋级。该实验也表明当前策略距平台 `>900` 的差距不太可能仅由单动作语义门造成。后续检验多动作互补与预算浪费；本地终局分不能换算为平台排行榜分数。
