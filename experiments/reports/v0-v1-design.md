# V0 实验报告与 V1 决策设计

## 当前证据状态

`290.75` 与 `124.61` 两次先导分数具有相同种子、动作序列与终态，却相差 2.33 倍。因此它们只用于提出“远程结算可能不可复现”的假设，绝不进入参数排名。本报告不会把未完成的主矩阵伪装为结论；正式表由 `scripts/analyze_experiments.py` 从 `experiments/raw/` 生成。

复现基线记录为项目 `c26e6f3`、CaseVO `d3b8d1f`、Python 3.12.3、uv 0.12.9。运行清单在 `experiments/manifests/v0-matrix.json`。每个记录包括 seed/config/哈希、预算、动作构成、step、LLM 调用、扫描快照/终态哈希、失败和协议异常；原始文件已被 Git 忽略。

## 可重复性门禁与 V0 矩阵

先在四节点 fixture 上按五个随机区组交错运行四种固定终态：仅扫描、仅屏蔽 2、对 1/3/4 各游说三次、以及屏蔽 2 后的九次游说。每组的扫描快照和终态哈希必须一致。已完成的 20 个门禁 session 中，四种固定终态的哈希均一致、相对分数波动均为 `0.0%`，故判定该门禁稳定并执行 `6 × 8` 单重复主矩阵；若后续门禁重跑超过 2%，runner 会自动切换到三种激活性强的种子、每格双重复。两种路径均为 48 个主 session，合计 68 个正式 session。

八个变体为 `scan_only`、`v0_deterministic`、`v0_llm3`、`risk_loose`、`risk_strict`、`mixed_raw_roi`、`communicate_only`、`risk_only`。主指标是同 seed 相对 `scan_only` 的配对增量。报告将给出均值、中位数、标准差、最差 seed、预算效率、动作构成、剩余预算、step/LLM 数和按 seed 10,000 次 bootstrap 的 95% CI；不使用孤立 p 值。若终态相同仍大幅漂移，所有结论必须标为“不确定”，并附 CI。

`v0_llm3` 只有在动作序列或得分稳定优于 `v0_deterministic` 时才有策略价值；动作相同即为“增加调用成本但无策略贡献”。同时检查 loose/strict 阈值是否出现跨 seed 排名反转，以识别固定阈值脆弱性。

## V0 已知问题清单

- 远程结算的同终态分数可能漂移，必须先通过门禁。
- 默认 P0 独占和固定 shield/cut 阈值可能压制更高 ROI 的游说。
- LLM 只能重排已经合法的候选；若序列不变，它没有可观察决策增益。
- 扫描成本和干预次数占用 step 额度；控制器保留 115/245 的本地安全熔断，低于公开 120/250 上限。

## V1：结算器驱动、响应感知的动态 Greedy

V1 不引入 GNN/RL。先用孤立点、两节点、path/triangle、star、断连分量和权重缩放微图辨识黑盒结算，比较 Degree-weighted、DeGroot 与 Friedkin–Johnsen。仅当留出微图上动作排序 Spearman ≥0.90 且中位相对误差 ≤5% 时启用拟合结算器；否则回退当前确定性 V0。

每轮用 Python 枚举并校验所有 communicate/cut/shield，复制当前状态，按 `(predicted_score_after - predicted_score_before) / action_cost` 统一选择跨动作边际收益。P0 与绝对阈值只作候选剪枝，不再必然优先。首次游说后以真实 `new_w-old_w` 更新响应估计，并以已知 `1/0.5/0.25` 衰减后续收益；预测非正或低于模型误差边界即停止、保留预算。LLM 最多只在一次高不确定近似并列时从合法 ID 中仲裁。Beam、CELF、主动扫描和 GNN/RL 留给 V2。
