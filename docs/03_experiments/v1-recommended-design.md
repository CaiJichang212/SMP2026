# V1：结算器驱动的响应感知 Greedy 方案

## 结论先行

V1 最推荐的方向不是增加 LLM 调用、继续搜索固定 `shield` / `cut` 阈值，或直接引入 GNN/RL；而是实现**结算器驱动的响应感知 Greedy**（Calibrated Marginal-Gain Greedy, CMG）。

它在每一步只在 Python 枚举、预算、步数余量和公开 API 校验均已通过的候选中，按保守的预测边际得分/成本选择 `communicate`、`cut` 或 `shield`；游说后立刻用环境返回的真实 `new_w` 修正**同一节点后续游说**的响应预测。结算器必须在开发期的留出微图上预先校准并通过门禁；线上单个隐藏 seed 不拟合、不验证，也不调用 `trigger_eval()`。若预校准未通过，CMG 不假装知道最终得分，而是使用与当前 `v0_deterministic` 完全相同的确定性回退。

这保留 V0 已验证的安全边界和确定性，同时直接修正当前“中心性 + 固定阈值”不能衡量实际边际收益的问题。

## 证据与本次新增本地探针

### V0 正式矩阵（已完成，不重复运行）

正式矩阵是 6 个 50 节点 seed × 8 个变体。可重复性门禁稳定，48 个主 session 均可比。主指标为同 seed 相对 `scan_only` 的增量，95% CI 是按 seed 区组的 10,000 次 bootstrap。

| 变体 | 平均 Δ | 最差 seed Δ | 95% CI |
| --- | ---: | ---: | --- |
| `v0_deterministic` | **+560.140** | +429.340 | [+468.540, +692.872] |
| `v0_llm3` | +560.140 | +429.340 | [+468.540, +692.872] |
| `risk_loose` | +552.295 | +461.350 | [+477.395, +677.015] |
| `risk_strict` | +495.728 | +383.470 | [+428.452, +570.533] |
| `mixed_raw_roi` | +480.135 | +433.030 | [+455.275, +512.985] |
| `communicate_only` | +450.792 | +353.540 | [+398.897, +511.018] |
| `risk_only` | +157.315 | +0.000 | [+27.940, +345.892] |

`v0_llm3` 在全部 6 个 seed 上与 `v0_deterministic` 产生**相同的动作序列和最终分数**，却每局多调用 3 次 LLM。因此 V1 的默认路径不调用 LLM。

完整统计见 [`experiments/reports/v0-matrix-summary.md`](../../experiments/reports/v0-matrix-summary.md)。以上区间在不同变体间有重叠，不能把 V0 与 `risk_loose` 的点估计差异解释为已证实的性能差异。

### 新增：V1 本地机制探针

为避免重复 V0 的 6×8 策略排名，本次只运行了 V1 尚未验证的两个机制参数：游说的 `prompt_id` / 重复次数，以及负面桥接图上的动作类型。测试通过官方“本地调试”方式发送自定义种子到测试服务器；每个 probe 均使用新 session、只调用公开的 `scan_node`、`communicate`、`cut_link`、`shield_node` 和 `trigger_eval`。这不是纯内存 simulator，也不应被误称为隐藏 seed 的性能评测。

命令和可复现参数清单：

```bash
uv run python scripts/run_v1_local_probes.py --resume
```

- 清单：[`experiments/manifests/v1-local-probes.json`](../../experiments/manifests/v1-local-probes.json)
- 原始结果：`experiments/raw/v1-local-probes/7360deb234e10498/`（按仓库约定忽略，不提交）
- 完成状态：10/10 可比、0 次动作失败、0 个协议异常。

#### 游说参数：单个孤立和平节点

初值为 `w=10`、三次可游说、各 prompt 的成本均为 2；扫描成本在各行均相同，表中的增量相对“不游说”。

| 参数 | 最终分 | 相对增量 | 本次新增边际增量 | 解释 |
| --- | ---: | ---: | ---: | --- |
| `prompt=1`, 0 次 | 10.000 | 0.000 | — | 对照 |
| `prompt=1`, 1 次 | 32.500 | +22.500 | +22.500 | 第一轮 |
| `prompt=1`, 2 次 | 43.750 | +33.750 | +11.250 | 第一轮的 1/2 |
| `prompt=1`, 3 次 | 49.380 | +39.380 | +5.630 | 第一轮的约 1/4 |
| `prompt=2`, 1 次 | 25.000 | +15.000 | +15.000 | 弱于 `prompt=1` |

结论：该受控条件下，`prompt=1` 的第一次游说优于 `prompt=2`；对同一节点的增益呈 `1, 0.5, 0.25` 衰减，这也与赛题公开规则一致。V1 应将“该节点已成功游说次数”和真实已观测的首次 `Δw` 纳入后续边际收益，而不是把三次游说当作同等候选。该单一和平节点不足以证明不同人设或隐藏 seed 上 `prompt=1` 总是最佳，故线上不能据此自适应切换 prompt。

#### 动作类型：两节点负面桥接图

节点 1 为暴力负面节点（`w=-40`），节点 2 为和平节点（`w=10`），二者由唯一边相连。表中的动作成本不含两次固定扫描成本。

| 参数 | 干预成本 | 最终分 | 相对对照 Δ | 机制含义 |
| --- | ---: | ---: | ---: | --- |
| 无动作 | 0 | -30.000 | 0.000 | 对照 |
| 游说节点 2，`prompt=1` | 2 | -7.500 | +22.500 | 正向节点游说有效 |
| 切边 `(1, 2)` | 3 | -30.000 | 0.000 | 单独移边未移除负节点分数 |
| 屏蔽节点 1 | 5 | 10.000 | +40.000 | 移除负节点的直接贡献 |
| 屏蔽节点 1，再游说节点 2 | 7 | 32.500 | +62.500 | 两项增益在此图上相加 |

结论：`cut` 在这个极小图中没有即时价值，不表示切边无效；它说明切边的价值只能通过更大图上的后续共识传播来估计，不能由“负面边”标签或固定阈值直接替代。屏蔽和游说的边际收益也取决于状态与结构，不能设置全局固定优先级。

### 证据边界

上述 10 个 probe 都是单次、小图、机制辨识实验。它们证明了本环境中响应衰减与若干动作的局部结算行为；它们**不能**估计隐藏 seed 的平均得分、不能证明切边在大图中无效，也不足以单独拟合全局结算器。策略排名仍以配对、多 seed 的正式矩阵为准。

## 当前 V0 的问题

1. **排序目标不等于结算目标。** V0 的 `danger`、`positive_influence` 和负桥分数来自图中心性，未预测“执行该动作后的最终得分”。探针中的 `cut` 是反例：它满足负面桥直觉，却没有带来即时得分。
2. **固定阈值脆弱。** `risk_loose`、`risk_strict`、默认阈值在不同 seed 上的相对优势改变，且 V0 与 loose 的区间重叠；没有单一阈值已经被证明能泛化。
3. **P0 独占会隐藏跨动作的更高 ROI。** 当前出现高危屏蔽候选时会先只暴露 P0；这可保证保守性，却可能推迟收益更高的游说，或把“屏蔽 + 游说”拆成没有比较过的顺序。
4. **游说没有响应模型。** 当前每次只固定选 `prompt_id=1`，并在重分析后依旧以静态中心性排序。它知道额度会减少，但没有用真实 `new_w-old_w` 预测第二、三次游说的递减收益。
5. **LLM 是纯成本。** 已验证的 3 次 LLM 调用没有改变任何动作或分数，继续扩大调用上限没有证据支持。
6. **全扫是稳定基线，但占 25% 预算。** 50/100 节点分别花 25/50 预算；在尚未隔离“结算器误差”和“探索误差”以前，不应同时改扫描方案。V1 先保持全扫，主动扫描留到后续独立消融。

## V1 设计：Calibrated Marginal-Gain Greedy（CMG）

### 设计原则和非目标

- 只读取 `Blackboard` 已公开的节点、边、动作反馈和预算；不读取 seed 私有字段，不调用私有环境方法，也不调用 `end_turn()`。
- 先完整扫描作为可比基线；每次公开动作前调用现有合法性、预算和本地 step 熔断余量校验。预测、复制状态与排序只能是纯 Python 计算，不能额外调用环境或 LLM。
- Python 枚举所有合法候选，V1 默认且正式对照中都禁用 LLM。若未来重新研究 LLM，必须是独立、预注册的实验变体，且只可重排 Python 生成的合法 ID 并有确定性回退。
- 不在 V1 引入 GNN、RL、Beam 或 CELF。先证明小而透明的预测器能带来配对增益。

### 状态和可观测估计

V1 在现有 `Blackboard` 之外维护仅由公开结果构造的 `ResponseLedger`：

```text
node_id -> successful_comm_count, observed_deltas, last_w
global -> 离线校准的 prompt / persona 响应区间和不确定度
```

当一次游说成功时，记录 `delta_w = new_w - old_w`。同一节点下一次的预测为：

```text
expected_delta(next) = observed_first_delta * decay(successful_comm_count)
decay = [1.0, 0.5, 0.25]
```

`successful_comm_count` 只计本 session 已成功且有 `new_w` 的请求；不能从 `comm_left` 倒推出任何不可见的历史游说次数。若该节点尚无这类观察，不能从当前 10 个 probe 推断其节点特异响应：只有离线响应实验已覆盖该 persona 与 prompt，且形成有界的保守先验时，CMG 才可预测首次游说。否则首次游说沿用 V0 的确定性候选顺序；在成功返回 `new_w` 后才启用该节点的递减响应预测。绝不使用自定义 seed 中现实评测不可见的 `r` 字段。

当前正式候选仍固定 `prompt_id=1`，这只是与 V0 可比的基线，不是“所有人设上 prompt 1 最优”的结论。要切换或比较 prompt，必须先在和平、暴力、中立三类节点及不同初值上做平衡、重复的离线 probe，并把获胜规则固化为不依赖隐藏字段的 Python 规则。

### 结算器与启用门禁

开发期用自定义微图结果拟合并选择一个**固定参数**的局部结算器，而不是将中心性分数当真值。候选模型至少包括 degree-weighted 聚合、DeGroot 和带保留项的 Friedkin–Johnsen 近似。线上运行时只载入已通过门禁的模型参数；输入只含当前公开的节点权重、已知边与动作后的假设状态。隐藏 seed 上没有最终分标签可用，因此不得在线拟合、选模型或以评估分更新模型。

在隔离点、两节点、path、triangle、star、断连分量、权重缩放等留出微图上，以“单步动作后的最终分”校验它。只有同时满足以下门禁时，才用其做动作排序：

- 按图留出的动作排序 Spearman 相关系数至少 `0.90`；
- 每张图的动作分数 MAE 除以 `max(1, max(score)-min(score))` 后的中位数不超过 `5%`；
- 对照、动作和终态的重复运行稳定。

不通过时进入 **V1-safe fallback**：调用与 `v0_deterministic` 完全相同的候选生成、P0 独占、排序、LLM 配置和完整合法性校验；不使用未验证的 `ResponseLedger` 重排。这使门禁失败时的策略行为可逐 action 与正式 V0 对照，而不是引入另一个未经测量的变体。

### 每步选择规则

仅当结算器和所需的首次游说响应先验均通过离线门禁时，对每个合法的 `communicate`、`cut`、`shield` 候选复制公开状态并构造动作后的预测状态。对游说使用上述响应预测；对屏蔽/切边修改副本中的节点或边。计算：

$$
\operatorname{LCBROI}(a)=
\frac{\widehat F(s \oplus a)-\widehat F(s)-\lambda\sigma(a)}{\operatorname{cost}(a)}
$$

其中 `σ(a)` 来自按图留出的结算误差与首次游说响应区间，`λ` 取预注册的保守常数 1。选择正 `LCBROI` 最大的动作；同分时按动作 ID 的字典序决定。执行成功后立即更新黑板、`ResponseLedger` 与图分析，再枚举全部候选。预测增益非正、低于误差界、没有合法候选，或下一次外部动作可能触及本地 safety step limit 时停止并保留预算。

因此，`shield` 不再因 P0 身份自动获选，`cut` 也不因“负桥”自动获选；二者必须在相同的、成本归一化的保守目标下胜过游说。

### 计算与框架边界

V1 的所有推演是纯 Python，不增加环境动作或 LLM 调用；`ParticipantSquadModel.step()` 每次最多发送一个公开环境请求，继续复用现有安全熔断（50 节点 115、100 节点 245）。

`communicate` 与 `shield` 最多各有 100 个候选。已知边在最坏情况下可达 4,950 条，不能对每条边都反复做高迭代结算。因而先为所有合法 cut 边计算一次确定性的廉价**筛选**分（负端点权重、端点影响力、桥接特征），仅在边数超过 64 时保留前 64 条；CMG 的最终选择仍只依据 LCBROI。`E <= 64` 时必须评估全部合法 cut。筛选上限、结算迭代上限与收敛阈值均应写入 `PolicyConfig`，在 100 节点高密度图上压力测试；预测器未收敛、超出本地计算时限或候选状态非法时，立即使用精确 V0 fallback，而不发送试探性环境请求。

V1 仍通过既有 CaseVO `ParticipantSquadModel` 和 `step()` 接口运行；它不是绕过框架的批处理脚本。最终分只由实验 runner 或官方评测器在策略停机后调用 `trigger_eval()`。

### 执行流程

```text
scan all public node IDs → validate Blackboard snapshot and step headroom
load pre-registered, offline-validated settlement/response model (or exact V0 fallback)
while budget, step headroom and legal candidates remain:
    enumerate + validate communicate/cut/shield candidates in Python
    predict action state, score, uncertainty and LCBROI
    if no positive robust candidate: stop
    execute one public action
    if communication succeeded: update ResponseLedger from new_w - old_w
    reanalyse graph and repeat
external runner, not submission code, calls trigger_eval
```

日志至少记录候选 ID、预测分、预测增益、标准差、LCBROI、选择原因、真实 `Δw`、预算和回退原因，以便审计“模型为什么选了这一步”。

## V1 验收实验

1. **扩展机制辨识，而非立即调参。** 每类小图至少重复 5 次，增加 path/triangle/star、负桥长度、权重缩放和断连分量；对三种 persona、三种 prompt 与多个初值平衡取样。登记每个动作的终态哈希、分数、动作反馈和拟合误差。
2. **离线冻结模型，再跑结算器门禁。** 按图留出拟合模型参数并冻结；不得用留出图选模型。不满足 Spearman/归一化 MAE 门槛时，主矩阵只能运行精确 V0 fallback，不能把模型预测带入提交策略。
3. **实现专用的 V1 runner 与比较器后再预注册主矩阵。** 现有 `analyze_experiments.py` 只对 `scan_only` 配对，不能验证 V1 相对 V0；新工具必须按 `(seed_id, repetition)` 直接计算 `score_v1 - score_v0`，拒绝混合 plan/branch、动作失败和协议异常。使用同一 6 个生成 seed，交错运行 `scan_only`、`v0_deterministic`、V1；每种至少 3 个重复，记录配对增量、最差 seed、预算/step、动作构成、LLM 调用和协议异常。
4. **决策规则。** 以 seed 为区组、按 `score_v1 - score_v0` 进行 10,000 次 bootstrap；只有均值差的 95% CI 下界大于 0、任一 seed 的平均差不为负、且无新增协议或动作失败时，才替换提交策略。否则保持 `v0_deterministic`。任何 LLM 版本都必须作为独立变体重复同一检验。

## 交付边界

本文件是 V1 设计与实验记录，不改变当前提交策略。真正实现时只修改 `src/starnet/submission/` 作为提交源；实验 runner、原始记录、`.env`、日志和探针资产不得进入提交 ZIP。
