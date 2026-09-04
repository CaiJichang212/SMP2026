# V0 强 Baseline 实施计划

> 预计工期：2–3h
> 目标版本：初赛可提交 V0，同时保留复赛 100 节点适配能力

## 1. 目标与验收口径

实现一套“确定性全量扫描 + NetworkX 图分析 + 规则候选生成 + LLM 批次仲裁”的强基线，替换当前逐回合依赖 LLM 的 Starter Kit 策略。

完成后应满足：

- 初赛依次扫描 `1..50`，复赛依次扫描 `1..100`；扫描阶段不调用 LLM，不重复扫描。
- 初赛全量扫描固定消耗 25 精神力，复赛固定消耗 50 精神力。
- 扫描结果中的 `w`、`persona`、`comm_left` 和邻接边全部按环境响应保存，不重置 `comm_left`。
- 使用 NetworkX 计算 degree、PageRank、k-core、节点/边 betweenness、VoteRank 和社区划分。
- 生成 shield、cut、communicate 三类合法候选；任何环境动作都必须先通过预算、节点、边、次数和 `prompt_id` 校验。
- LLM 只能返回候选 ID 的有序批次，不能自行创造动作或参数；每个种子最多调用 3 次。
- LLM 超时、异常、非法 JSON、未知候选、空结果时，自动采用确定性排序，不中止评测。
- 不调用 `_deduct_budget()`、`end_turn()` 或其他环境私有方法。
- 保持赛方入口不变：`ParticipantSquadModel(host_env, person_list, llm)`、`step()`、`casevo` 导入名以及 ZIP 根目录三项契约。
- 通过单元测试、模拟环境集成测试、提交目录校验和打包检查；真实远程沙盒结果与本地结构检查分开记录。

## 2. 总体架构与状态机

采用三个已注册的 CaseVO Agent，但把精确计算留在 Python：

```text
ParticipantSquadModel
│
├── ScoutAgent
│   └── 按固定节点范围返回下一个未扫描 ID，不调用 LLM
│
├── GraphAnalystAgent
│   ├── 构建 NetworkX Graph
│   ├── 计算结构特征、社区和联合评分
│   └── 生成并排序合法候选
│
└── CommanderAgent
    └── 使用 JsonStep 在 Python 给出的候选 ID 中做批次仲裁
```

模型状态机固定为：

```text
INIT
  ↓
SCAN_ALL：每个 step 扫描一个 ID，不调用 LLM
  ↓
ANALYZE：构图、计算特征、生成当前候选
  ↓
PLAN_BATCH：有调用额度时让 LLM 排序，否则确定性排序
  ↓
EXECUTE：每个 step 重新校验并执行一个动作
  ↓
REANALYZE：环境状态改变后重新计算
  ├── 队列仍有效 → EXECUTE
  ├── 队列过期或耗尽、仍有动作 → PLAN_BATCH
  └── 无合法候选或预算不足 → STOP
```

运行约束：

- 每个 `step()` 最多调用一个环境动作。
- `schedule.time` 每个有效回合只增加一次。
- 拓扑动作成功后立即重算指标；communicate 成功后更新 `w` 和 `comm_left`，再重算与该节点有关的候选。
- 队列动作执行前必须仍在当前合法候选集合中；已经失效的动作直接丢弃，不发送环境请求。
- 连续三个候选均失效或环境拒绝时，重新生成候选；没有新候选则停止，避免死循环。
- 精确动作失败后，将该动作 ID 加入本种子的失败集合，避免反复请求；`max_comm_reached` 还要把对应节点 `comm_left` 同步为 0。

## 3. 图状态与公开内部接口

复用现有 `Blackboard`、`Action`、`is_legal_action()` 和 `apply_action()`，补充以下测试友好的内部接口：

```python
@dataclass(frozen=True)
class NodeMetrics:
    degree: float
    pagerank: float
    core: float
    betweenness: float
    voterank: float
    influence: float
    positive_influence: float
    danger: float
    community_id: int

@dataclass(frozen=True)
class EdgeMetrics:
    edge_betweenness: float
    cross_community: bool
    negative_flow: float

@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    action: Action
    priority: int
    score: float
    roi: float
    reason: str
```

核心函数：

```python
build_graph(blackboard) -> nx.Graph
analyze_graph(blackboard) -> GraphAnalysis
generate_candidates(analysis, blackboard, budget, failed_actions) -> list[Candidate]
select_deterministic_batch(candidates, budget, limit) -> list[str]
parse_llm_batch(payload, candidate_map, budget) -> list[str]
infer_node_count(initial_budget) -> int
```

约束如下：

- NetworkX 图和节点均按 ID 升序插入，边使用 `(min_id, max_id)`，保证相同输入得到稳定结果。
- `Blackboard` 是环境事实的唯一来源；NetworkX Graph 是可随时重建的派生结构，不能反向覆盖黑板。
- 图中保留已扫描存活节点；成功 shield 后删除节点和全部关联边。
- `normalize_edge()` 继续拒绝自环；重复边由集合去重。
- 对单节点、无边图、非连通图和全零特征不得产生异常、NaN 或除零。
- 特征统一归一化到 `[0,1]`。若一列全部为 0，则归一化结果为 0；若全部相等且非零，则全部记为 1。

节点数按当前公开赛制推断：

```python
node_count = 100 if initial_budget >= 150.0 else 50
```

这覆盖初赛 100 预算和复赛 200 预算。纯算法测试允许显式传入 4、50 或 100；正式 `ParticipantSquadModel` 不读取未经确认的环境私有属性。当前 4 节点自定义种子只用于小图测试，不用于决定正式节点范围。

## 4. 图特征与联合评分

### 4.1 结构影响力

计算并归一化：

- `degree_centrality`
- `pagerank`
- `core_number`
- `betweenness_centrality`
- `voterank`

VoteRank 返回的有序节点列表转换为分数：

```text
第 1 名 = 1.0
第 m 名 = 1 / m
未入选 = 0.0
```

结构影响力采用固定权重：

\[
I_i =
0.25D_i +
0.25PR_i +
0.20K_i +
0.20B_i +
0.10V_i
\]

社区使用 `greedy_modularity_communities()`：

- 有边图执行模块度社区划分。
- 无边图把每个节点视为独立社区。
- 社区按其中最小节点 ID 排序并分配稳定的 `community_id`。

### 4.2 Positive influence score

V0 只把和平、中文标记为中立的节点视为正向游说对象：

```text
persona_response_prior：
和平 = 1.00
中立 = 0.70
暴力 = 0.00
未知值 = 0.00
```

按照当前剩余沟通次数估算边际衰减：

```text
comm_left = 3 → 1.00
comm_left = 2 → 0.50
comm_left = 1 → 0.25
comm_left = 0 → 0.00
```

定义：

\[
Positive_i =
I_i
\times PersonaPrior_i
\times MarginalFactor_i
\]

communicate 的启发式 ROI：

\[
ROI^{comm}_i = \frac{Positive_i}{2}
\]

V0 默认只使用 `prompt_id=1` 作为正向话术。该默认来自当前 Starter Kit 自定义种子；正式提交前必须用最新赛方说明或远程沙盒确认。未确认前不让 LLM自由选择 `2`、`3`。

### 4.3 Danger score

先计算图内相对负面强度：

\[
N_i =
\frac{\max(-w_i,0)}
{\max_j \max(-w_j,0)}
\]

人设风险系数：

```text
暴力 = 1.00
中立 = 0.50
和平 = 0.25
未知值 = 0.50
```

定义：

\[
Danger_i =
N_i
\times PersonaRisk_i
\times
(0.70I_i + 0.30B_i)
\]

其中 \(B_i\) 是归一化节点 betweenness。

shield 候选必须同时满足：

- `persona == "暴力"`；
- `w < 0`；
- `Danger >= 0.55`；
- 节点存活且已扫描；
- 当前预算至少 5。

其启发式 ROI 为：

\[
ROI^{shield}_i = \frac{Danger_i}{5}
\]

### 4.4 跨社区负面桥

对每条边计算归一化 edge betweenness。仅在以下条件成立时生成 cut 候选：

- 两端属于不同社区；
- 至少一端 `Danger > 0`；
- 高风险端连接到非暴力节点，或连接到 `w >= 0` 的节点；
- 边仍存在且预算至少 3。

定义：

\[
NegativeFlow_{uv}
=
\max
\left(
Danger_u(1-N_v),
Danger_v(1-N_u)
\right)
\]

\[
CutScore_{uv}
=
NegativeFlow_{uv}
\times EdgeBetweenness_{uv}
\]

只有 `CutScore >= 0.20` 才进入候选，且：

\[
ROI^{cut}_{uv}=\frac{CutScore_{uv}}{3}
\]

## 5. 候选生成与规则优先级

候选 ID 使用稳定、可直接复核的格式：

```text
shield:<node>
cut:<min_node>-<max_node>
comm:<node>:<prompt_id>
```

每轮候选分层：

1. `P0 shield`：高危负面暴力核心，最多保留 4 个。
2. `P1 cut`：未达到屏蔽条件、但向和平/中立社区传播负面影响的跨社区桥，最多保留 4 条。
3. `P2 communicate`：高影响、仍可游说的和平/中立节点，最多保留 8 个。

决策规则：

- 当前存在 `P0` 时，本轮只向 LLM 提供 `P0`，确保高危节点不会被普通增益动作跳过。
- 没有 `P0` 时，向 LLM 提供 `P1 + P2`，允许在阻断风险和提升正向影响之间取舍。
- 同类候选按 `ROI` 降序，其次按动作成本升序，最后按候选 ID 字典序排列。
- 候选总数最多 12；超过时按上述稳定顺序截断。
- 同一批次不得同时包含 `shield:x` 和任何关联 `cut:x-y`。
- 批次累计成本不得超过当前环境预算。
- 批次最多返回 10 个动作；未入选候选在下轮重新计算，不永久丢弃。
- 三次 LLM 调用耗尽后，剩余回合全部使用确定性排序。

## 6. LLM 批次仲裁

Commander 的输入只包含：

- 当前阶段、预算和 LLM 已用次数；
- 节点数、边数、社区数及正负节点摘要；
- 最多 12 个候选的 ID、动作、成本、priority、ROI 和简短原因；
- 明确禁止创建新动作、新节点、新边或新 `prompt_id`。

输出协议固定为：

```json
{
  "mode": "risk_first",
  "candidate_ids": [
    "shield:17",
    "cut:8-19",
    "comm:4:1"
  ],
  "reason": "先清理负面核心，再扩大正向影响"
}
```

其中：

- `mode` 仅允许 `risk_first`、`growth_first`、`balanced`。
- `candidate_ids` 必须是输入候选的子集，不得重复，最多 10 个。
- Python 忽略 LLM 返回的任何额外动作字段。
- 解析后再次执行候选存在性、冲突、预算和动作合法性校验。
- 部分合法时保留合法前缀；完全非法、异常、超时或空输出时直接使用确定性批次。
- 每次准备调用前检查 `llm_calls < 3`，在实际发起请求前递增计数，异常同样计入。
- 队列耗尽、超过一半动作因状态变化失效，或剩余预算仍允许动作时可重新规划，但总调用数不得超过 3。

提示词只负责候选排序，不再承担扫描 ID、自由生成动作或直接解释整张图的职责。

## 7. 提交收敛与工程改造

研发代码继续放在 `src/starnet/`，复用现有可测试模块；最终提交仍必须收敛为单个 `starnet_model.py`。

实施内容：

- 在策略核心中增加图分析、联合评分、候选生成、批次校验和控制器模块。
- 将提交入口改为调用上述控制器，并把现有 Commander/Scout/Executor 重构为 Scout、GraphAnalyst、Commander 三角色。
- 更新 `config.json` 与仲裁提示词，移除所有“最多 5 节点”和“1 到 5”硬编码。
- 扩展 `scripts/build_submission.py`：按固定顺序把纯 Python 策略模块组装进生成的单文件，去掉 `from starnet...` 内部导入，并在写入交付目录前执行 `ast.parse()`。
- 生成文件不得依赖 ZIP 中不存在的本地包；允许的外部依赖只有官方运行时和 NetworkX。
- 在项目依赖中明确 Python `>=3.11` 与 NetworkX；不修改同级 `casevo` 仓库，并使用 `casevo` 作为提交与本地调试的统一导入名。
- 更新文档导航，加入 `04_plan/`，并保存本计划文件。
- 构建后仍由现有校验和打包脚本产生根目录仅含 `config.json`、`prompt/`、`starnet_model.py` 的 ZIP。

## 8. 测试计划

### 8.1 单元测试

图分析：

- path、triangle、star、两个连通分量、单节点和无边图均能计算全部指标。
- star 的中心节点 influence、betweenness 和 danger 高于叶节点。
- 相同输入重复运行，社区编号、VoteRank 分数、候选顺序完全一致。
- 所有指标有限且位于 `[0,1]`。

候选规则：

- 负面暴力中心达到阈值时生成 shield，和平正节点不生成 shield。
- 高负面跨社区桥生成 cut；社区内部普通边不生成 cut。
- `comm_left == 0`、暴力人设、未知节点和预算不足时不生成 communicate。
- P0 存在时不会把 P1/P2 交给 LLM。
- shield 与关联 cut 不会同时进入可执行批次。
- 动作成本累计不会超过预算。

LLM 仲裁：

- 正常 JSON 返回合法有序批次。
- 未知 ID、重复 ID、冲突动作、超预算批次和错误类型被过滤。
- 非 JSON、空输出、异常和超时触发确定性回退。
- 每个种子调用数永远不超过 3。

黑板与环境适配：

- 全量扫描保留真实 `comm_left` 并规范化边。
- communicate 只有 `status == "success"` 才更新 `w` 并减少次数。
- cut/shield 失败不修改成功状态。
- shield 成功删除节点和关联边，并加入 `dead_nodes`。
- 所有动作在环境调用前完成合法性校验。

### 8.2 模拟环境集成测试

至少建立以下场景：

- 50 节点初赛：恰好扫描 50 次、扫描成本 25、扫描阶段 LLM 调用数为 0。
- 100 节点复赛：恰好扫描 100 次、扫描成本 50。
- 负面 star：优先 shield 中心。
- 两社区桥：优先 cut 负面社区到和平社区的高 edge-betweenness 边。
- 无高危节点：优先 communicate 高 influence 的和平/中立节点。
- 混合场景：先执行 P0，再重算并进入 P1/P2。
- 环境随机拒绝动作：黑板不虚构成功状态，且不会无限重试。
- LLM 始终故障：仅靠确定性策略也能完成评测。
- 预算边界分别为 `0.49/0.5/1.99/2/2.99/3/4.99/5`，不发生超预算调用。
- 4 节点玩具种子仅验证规则方向，不作为节点范围、阈值或权重的依据。

### 8.3 构建与交付测试

依次验证：

```bash
python -m unittest discover -s tests -v
python scripts/build_submission.py
python scripts/validate_submission.py
python scripts/package_submission.py --name v0-baseline.zip
```

额外断言：

- 生成的 `starnet_model.py` 可被 `ast.parse()`。
- 文件中不存在 `from starnet`、私有环境方法、硬编码 API Key 和 `end_turn()`。
- ZIP 根目录直接包含三项赛方契约内容，没有外层目录。
- `ParticipantSquadModel` 类名、继承关系、构造参数和 `step()` 保持不变。
- 在具备官方 `casevo` 的干净 Python 3.11+ 环境中完成一次导入烟雾测试。
- 远程沙盒测试必须使用新 session，关闭 `local_test.py` 的手工 API 演示，记录最终分、剩余预算、环境动作数和 LLM 调用数。

## 9. 执行安排

### step1：确定性扫描与图分析

- 建立 Python 3.11+ 可编辑安装环境并显式安装 NetworkX。
- 完成节点数推断、全量扫描状态机和黑板接入。
- 完成 NetworkX 建图、六类图特征、稳定归一化和社区划分。
- 完成 path、star、triangle、断连图和无边图测试。

当天出口：扫描阶段不调用 LLM，50/100 节点扫描数量正确，图特征测试通过。

### step2：联合评分、候选与 LLM 仲裁

- 实现 influence、positive influence、danger 和 cut score。
- 实现 P0/P1/P2 候选生成、阈值、Top-K、冲突处理和确定性排序。
- 重构三个 CaseVO Agent 的职责。
- 实现批次仲裁协议、最大 3 次调用、解析校验和故障回退。
- 完成候选与 LLM 异常路径测试。

当天出口：在模拟环境中能完成“全扫—分析—仲裁—执行—重算—停止”的闭环。

### step3：提交收敛与回归

- 完成单文件组装，更新配置和提示词。
- 跑 50/100 节点模拟集成测试和预算边界测试。
- 构建、校验并打包 V0 ZIP。
- 在官方运行时可用时进行远程沙盒烟雾测试；否则明确记录为待验证项，不把本地结构检查表述为端到端成功。
- 保存实验摘要：最终分、相对无干预增益、消耗预算、剩余预算、LLM 调用数、失败动作数。

当天出口：形成可提交 ZIP、全套回归结果和一份明确区分“本地通过/官方待验证”的验收记录。

## 10. 完成定义与默认假设

V0 只有在以下条件全部满足时才算完成：

- 全量扫描、图指标、联合评分、三类候选和批次仲裁全部落地。
- 所有环境请求均来自 Python 合法候选，并在请求前再次校验。
- LLM 完全不可用时策略仍能正常结束并产生有效提交结果。
- 模拟环境中的 50/100 节点、异常响应和预算边界测试全部通过。
- 提交构建、校验、打包和单文件导入检查通过。
- 至少在多个不同拓扑种子上比较“无干预、旧 baseline、V0”，而不是只观察 4 节点玩具种子。
- 正式远程沙盒尚未通过时，状态必须标记为“提交结构已验证、真实评测待验证”。

默认假设：

- 当前优先服务初赛：50 节点、100 精神力、每种子最多 50 次 LLM 调用。
- 同时按 200 初始预算自动适配复赛 100 节点，但复赛调用上限仍需届时重新确认。
- `prompt_id=1` 暂作唯一正向话术；正式提交前必须复核。
- 当前公开信息不足以实现精确稳态模拟，因此 V0 使用联合启发式评分；真实 `ΔScore/cost` 模拟器属于 V1。
- 当前系统 `python3` 为 3.9 且没有安装 NetworkX，不能作为项目验收环境；实施与测试统一使用 Python 3.11+。
- Starter Kit 提交校验当前已通过，但现有策略单元测试尚未在正确安装的项目环境中完整运行；实施开始时先建立干净、可重复的开发环境。
