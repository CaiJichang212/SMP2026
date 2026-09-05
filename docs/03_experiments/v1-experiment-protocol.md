# V1.0 实验方案：响应感知 CMG 的校准、门禁与晋级

## 目的与边界

本方案检验的对象是 `Calibrated Marginal-Gain Greedy (CMG)`：它仅根据公开扫描结果、公开动作反馈和预先冻结的参数，对合法 `communicate`、`cut`、`shield` 候选按保守边际收益/成本排序。它不是对隐藏 seed 在线拟合的模型，也不是一次本地小图分数的竞赛策略排名。

实验分为“机制辨识 → 结算器校准 → 端到端配对验证”三层；上一层没有通过，下一层不产生晋级结论。实验和提交严格分离：只有本地 runner 在回合结束后调用 `trigger_eval()`；提交代码不得调用它，也不得读取实验文件或自定义 seed 的私有字段（尤其是 `r`）。

截至 2026-09-05，默认 `CalibrationProfile` 仍为未验证状态。因此 `v1_cmg` 的运行路径必须 fail-closed 回退到与 `v0_deterministic` 相同的安全候选生成和合法性检查；在完成以下门禁前，绝不切换提交默认策略。

## 研究问题与预注册判据

| 层级 | 研究问题 | 单位与主指标 | 通过条件 |
| --- | --- | --- | --- |
| P0 可用性 | 官方本地调试服务能否稳定执行预注册 session？ | 每个 session 的扫描快照、终态哈希、分数、协议/动作失败 | 完整执行、0 协议异常、0 动作失败；固定终态的相对分数波动 ≤2% |
| P1 响应 | 首次游说及重复游说的 `new_w` 如何随 persona、prompt、初值变化？ | 公开返回的逐轮 `Δw` | 每个预注册 cell 有 5 个可比 session；仅据此构造冻结先验与方差 |
| P2 结算器 | 纯 Python 的局部结算器能否排序单步动作的真实终态收益？ | 按图、按动作均值的 Spearman；每图 action-range 归一化 MAE | 留出 gate 上 Spearman ≥0.90，归一化 MAE 中位数 ≤5%，并满足 P0 稳定性 |
| P3 策略 | 已冻结的 CMG 是否稳定优于 V0？ | 同 `(seed_id, repetition)` 的 `score_v1 - score_v0` | 6 个 seed × 3 次均完整；按 seed 区组 10,000 次 bootstrap 的 95% CI 下界 >0；任一 seed 平均差不为负；0 新增失败，0 LLM 调用 |

所有阈值和选择规则在采集前固定。缺失、协议异常、动作失败、扫描快照不匹配或非数值分数均为**不可比较**，不插补、不以旧结果替代，也不进入任何均值、相关系数或置信区间。

## 实验设计

### P0：服务可用性与结算稳定性门禁

使用 `v0-matrix` 的四节点固定 fixture，运行 5 个区组；每区组交错执行 `scan_only`、`shield_2`、`communicate_1_3_4`、`historical_v0_terminal`，共 20 个新 session。每个 session 使用新 session ID，只调用公开 API。

检查每个固定动作序列的扫描快照哈希、终态哈希、最终分数及预算消耗。任何固定终态的哈希不一致、不可比较，或相对分数波动超过 2%，均停止 P1–P3；先排查服务可用性，不能把波动解释为策略差异。

### P1：响应表校准（135 个 session）

在孤立单节点微图上完全平衡以下因素：persona `{和平, 暴力, 中立}` × `prompt_id` `{1,2,3}` × 初始 `w` `{-30,0,30}`，共 27 个 cell。每个 cell 5 个独立 session，每局对同一节点最多连续游说 3 次，合计 `27 × 5 = 135` session 和至多 405 条公开响应记录。每局先扫描，记录每次返回的 `new_w` 与 `Δw`、`comm_left`、成本、最终分数、动作/终态哈希。

随机化由 manifest 的固定种子生成，并以区组交错 persona/prompt/初值，避免服务时间漂移与单一因素混淆。首轮与第二、三轮响应分别估计均值和总体标准差；响应表只从**校准 split**生成，selection/gate 数据不得用于填写缺失先验。一个 persona/prompt/轮次的任一 cell 不完整时，CMG 不可启用；它只能退回 V0。

### P2：结算器模型的图留出校准（420 个 session）

构造 21 个预注册基础图：7 个结构族 `{isolated, edge, path3, path5, triangle, star5, disconnected}` 各 3 个权重/符号布局（正向、混合、负桥）。每个结构族的三个基础图分别且唯一地分配到 `calibration`、`selection`、`gate`；绝不让同一基础图的其他动作进入另一 split。

每个基础图执行 `{control, comm, cut, shield}` 四个预注册动作（不可用动作记录为设计性缺失，不临时换动作），每个动作 5 个独立 session。因此共有 `21 × 4 × 5 = 420` session。动作和重复在固定随机种子下交错执行；每条记录包含扫描后的公开 `Blackboard` 快照、动作、游说反馈、最终分、终态哈希、预算、失败与协议字段。

候选结算器严格限定为已有三类：degree-weighted、DeGroot、Friedkin–Johnsen；其参数格点以 [`v1-calibration.json`](../../experiments/manifests/v1-calibration.json) 的 `rho/gamma/a/b` 为准。

1. 只用 `calibration` 拟合每个模型族的候选参数。
2. 只在 `selection` 中，从已冻结的各族候选选择模型；不能查看 `gate`。
3. 只在 `gate` 上计算每张图动作均值的 Spearman，以及 `MAE / max(1, 该图动作分数最大值 - 最小值)` 的中位数。
4. 同一 `(graph_id, action, repetition)` 的终态哈希、分数稳定性也必须符合 P0 标准。

脚本生成的报告须包含 manifest/data/profile 哈希。满足门禁后，才把经过复核的字面 `CalibrationProfile` 写入源码；运行时不得读 JSONL 或报告文件。

### P3：端到端配对主矩阵（54 个 session）

仅在 P0–P2 全部通过后，执行 [`v1-matrix.json`](../../experiments/manifests/v1-matrix.json)：6 个固定生成 seed × `{scan_only, v0_deterministic, v1_cmg}` × 3 次独立重复，合计 54 个 session。三种变体在每个 seed/repetition 区组中交错随机运行，所有变体均先全扫描，`v1_cmg` 的校准档案哈希固定写入 session spec。

主要比较是 `v1_cmg - v0_deterministic`，而非各自相对 `scan_only` 的差。按 seed 先对三个重复取均值，再做 10,000 次有放回 seed bootstrap；报告均值差、95% CI、每个 seed 均值差、动作构成、预算/step、LLM 次数、异常数。`scan_only` 只作为绝对收益的辅助参照。任何 LLM 版本必须另设变体、完整重复 P3，不能和无 LLM 的 CMG 混合。

## 执行与产物

| 资产 | 位置 | 用途 |
| --- | --- | --- |
| 已完成的首轮小图 manifest | [`experiments/manifests/v1-local-probes.json`](../../experiments/manifests/v1-local-probes.json) | P1/P2 前的机制核验，不替代完整 P1/P2 |
| 校准和主矩阵 manifest | [`experiments/manifests/v1-calibration.json`](../../experiments/manifests/v1-calibration.json)、[`experiments/manifests/v1-matrix.json`](../../experiments/manifests/v1-matrix.json) | P1–P3 的预注册参数与样本量 |
| 本地探针 runner | [`scripts/run_v1_local_probes.py`](../../scripts/run_v1_local_probes.py) | 每个 probe 使用新 session、公开 API 与 resumable 原始记录 |
| 本地探针分析器 | [`scripts/analyze_v1_local_probes.py`](../../scripts/analyze_v1_local_probes.py) | fail-closed 汇总，拒绝异常/不可比较数据 |
| 原始记录 | `experiments/raw/`（Git 忽略） | 不提交，按 manifest hash 隔离 |
| 受版本控制的汇总 | `experiments/reports/` | 可审阅的表、汇总 JSON 与结论 |

推荐顺序是：先运行 P0，恢复服务后复跑首轮 10-probe，再运行 P1/P2、冻结档案，最后运行 P3。可恢复命令为：

```bash
uv run python scripts/run_v1_local_probes.py --resume
uv run python scripts/analyze_v1_local_probes.py \
  --raw experiments/raw/v1-local-probes/<manifest-hash>/results.jsonl \
  --report experiments/reports/v1-local-mechanism-probes.md
```

## 当前实验状态与决策

历史首轮小图记录有 10/10 个可比较结果，说明该受控条件下首次游说、重复游说和两节点桥图的局部结算可被测得；详细表见 [`v1-local-mechanism-probes-reference.md`](../../experiments/reports/v1-local-mechanism-probes-reference.md)。

2026-09-05 对同一 manifest 的新 session 复跑为 0/10 可比较、10/10 `RemoteProtocolError`；安全诊断均为在 `/api/start_session` 的 `ConnectionError`。这只能证明当时无法建立本地调试会话，不能区分本机网络与服务端可用性，也不能把历史结果当作本次重跑的替身；详见 [`v1-local-mechanism-probes-rerun-20260905.md`](../../experiments/reports/v1-local-mechanism-probes-rerun-20260905.md)。当前结论是：**保持 `v0_deterministic` 默认路径，不冻结 CMG 档案，不运行/解释 V1 主矩阵，也不增加 LLM 调用。**
