# SMP2026 星网干预任务解读和上手文档

> 本文以更新后的 [`任务文档`](../00_rules/task-spec.md) 和仓库内 [`SMP_Starter_Kit`](../../SMP_Starter_Kit/) 为准，说明如何基于 casevo（Starter Kit 中的导入名为 `agent_mesa`）开发并提交参赛程序。它针对当前随仓库提供的 SDK 和基线代码，而不是对未公开评测实现的猜测。若天池公告、评测镜像或赛方新样例与本文不一致，应始终以赛方最新要求为准。

## 1. 任务全貌：受预算约束的部分可观测图决策

星网在开始时处于战争迷雾中。初赛每个隐藏种子有 50 个节点、100 点精神力，复赛扩展为 100 个节点、200 点精神力。程序不能直接读取全图，只能在循环中扫描、更新已知子图、选择干预动作、读取环境反馈，再进行下一轮决策。

最终得分不是某次动作的即时收益，而是环境对干预后的图执行共识演化收敛后，按存活节点稳态倾向与度数权重计算的全网综合援助意愿。因此，好的策略同时要考虑节点倾向、人设、拓扑位置、未探索不确定性、精神力和 LLM 调用数。

| 操作 | 精神力成本 | 当前 Starter Kit 中的调用 | 可获得/改变的信息 | 必须维护的本地状态 |
| --- | ---: | --- | --- | --- |
| 查询预算 | 0 | `env.get_remaining_budget()` | 当前剩余预算 | 预算镜像，仅以环境响应为准 |
| 扫描 | 0.5 | `env.scan_node(node_id)` | `w`、`persona`、`comm_left`、全部有效邻居 | 已知节点、已知边、扫描过的 ID |
| 游说 | 2.0 | `env.communicate(node_id, prompt_id)` | 成功时返回 `status`、`new_w` | 当前 `w`、`comm_left`、`prompt_id` |
| 断链 | 3.0 | `env.cut_link(u, v)` | 布尔成功状态 | 有效已知边集合 |
| 屏蔽 | 5.0 | `env.shield_node(node_id)` | 布尔成功状态 | 存活节点、死节点、关联边 |
| 结束/结算 | 不再动作 | 本地 SDK 为 `env.trigger_eval()` | 最终分数 | 完整行动轨迹 |

### 1.1 必须遵守的约束

- 只能经 `host_env` / `self.env` 暴露的公开方法感知和干预；访问或篡改环境内部内存属于违规。
- 节点 ID 为整数：初赛范围 `1..50`，复赛范围 `1..100`。不要保留基线提示词中的 `1..5` 或“全局最多 5 节点”。
- 同一节点最多游说 3 次，第二次收益衰减为 50%，第三次衰减为 25%；应以扫描返回的 `comm_left` 和沟通返回状态双重校验。
- `prompt_id` 仅能取官方给定的话术编号；当前文档/基线展示 `1、2、3`，不要让 LLM 编造其他编号。
- 断链仅对已知且当前有效的边有意义；屏蔽后须从已知存活图中删除该节点和关联边。
- 初赛单个种子 LLM 调用次数硬上限为 50 次，超限会熔断并判负。并列时还比较剩余精神力和 API 调用数。
- 评测对多个隐藏种子取平均，禁止为 `custom_seeds/my_test_network.json` 的 4 节点玩具图硬编码策略。

### 1.2 正确的任务抽象

将真实环境视为隐藏图 \(G\)，将本地已知部分视为 \(\hat{G}\)。任意时刻策略只能基于 \(\hat{G}\) 选动作：

```text
读取预算
  → 更新黑板（已知节点、已知边、死节点、沟通余量）
  → 规则/图算法产生少量合法候选
  → 必要时让 LLM 在候选中选择
  → 程序校验后调用 self.env
  → 用返回值回写黑板
  → 继续下一次 step() 或结束
```

这正是赛题要求的“侦察—反馈—再决策”动态状态机，而不是预先生成固定动作列表的单向脚本。

## 2. Starter Kit、casevo 与提交边界

仓库结构如下：

```text
SMP2026/
└── SMP_Starter_Kit/
    ├── local_test.py                     # 当前实际本地测试入口
    ├── api_client.py                     # 本地 HTTP 沙盒客户端
    ├── zhipu.py                          # 本地 GLM-4-Plus / embedding 适配器
    ├── custom_seeds/my_test_network.json # 仅供本地测试的玩具种子
    └── team_submission/                  # 唯一需要修改和打包的工作区
        ├── config.json
        ├── prompt/
        │   ├── commander_react.txt
        │   ├── scout_react.txt
        │   ├── executor_react.txt
        │   └── reflect.txt
        └── starnet_model.py
```

当前提交契约为：

| 项目 | 硬性要求 | 当前基线位置 |
| --- | --- | --- |
| 主文件 | ZIP 根目录中的 `starnet_model.py` | `team_submission/starnet_model.py` |
| 主类 | 必须叫 `ParticipantSquadModel`，继承赛方提供的 `ModelBase` | 第 61 行 |
| 构造函数 | 接收 `(host_env, person_list, llm)` | 第 62 行 |
| 主循环 | 在 `step(self)` 内执行“感知—规划—动作” | 第 83 行 |
| 智能体配置 | `config.json` 中的 `person` 列表 | 3 个角色 |
| 提示词 | ZIP 根目录的 `prompt/` 文件夹 | 3 个决策模板 + 反思模板 |
| 打包 | ZIP 打开后直接看到上述文件/文件夹，不能多套 `team_submission/` 外层 | Starter Kit README |

当前规则只明确列出这三类提交内容（`config.json`、`prompt/`、`starnet_model.py`）。若计划拆分辅助 Python 模块、额外依赖文件或资源文件，先确认官方评测器是否会将其一并导入；在未确认前，最稳妥的方式是将策略代码收敛在 `starnet_model.py` 中。

### 2.1 casevo 在此项目中的职责

casevo 是基于 Mesa 的多智能体框架。当前源码的关键能力为：

- `ModelBase`：保存模型级上下文、调度器、LLM、提示词工厂、记忆工厂和 Agent 网络；
- `AgentBase`：保存每个角色的人设/上下文/记忆，子类实现具体行为；
- `ThoughtChain` 与 `JsonStep`：将提示词调用包装为可重试的链，并将 JSON 响应解析为字典；
- `PromptFactory`：从 `prompt/` 加载 Jinja2 模板，使模板可读取 `agent.description` 和 `extra`；
- `Memory`：提供短期记忆、检索和反思能力；在此赛题中应只保留真正会改善策略的记忆，避免无效 LLM 调用。

Starter Kit 用一个内部的 3 节点 `agent_graph` 表示“指挥官—侦察兵—执行官”的协作关系；真实星网不应直接塞入该图。真实星网的已知部分由 `local_nodes`、`local_edges` 和 `dead_nodes` 维护，这种“智能体协作图 + 环境已知图”分离的设计是合理的。

### 2.2 `agent_mesa` 与本仓库 `casevo` 的命名差异

赛题文字称指定框架为 casevo，但 Starter Kit 的 `starnet_model.py` 和 `zhipu.py` 使用：

```python
from agent_mesa import AgentBase, JsonStep, ModelBase
from agent_mesa import LLM_INTERFACE
```

本仓库附带源码的导入名则是 `casevo`，例如 `from casevo import AgentBase, JsonStep, ModelBase`。在当前工作区的实际解释器中，`casevo` 可找到，而 `agent_mesa` 不可找到；同时 `chromadb` 也尚未安装。因此 Starter Kit 不能在本机直接启动，并不是策略本身的错误。

处理原则如下：

1. **提交时优先遵循官方评测镜像和 Starter Kit 的导入约定**。若赛方镜像提供 `agent_mesa`，不要擅自改名。
2. **本地调试前先确认赛方依赖说明**。若官方确认 `agent_mesa` 是旧包名或要求使用本仓库 casevo，再一致地修改本地测试文件与提交文件的导入；不要只修改其中一处。
3. 不要把“本机能导入 casevo”误当成评测镜像的依赖契约。依赖/命名未澄清时，应向赛方咨询，而不是在 ZIP 中捆绑非官方框架替代品。

## 3. 本地上手：先跑通最短闭环

### 3.1 环境准备

Starter Kit README 写的是 Python 3.8+ 与 `requests networkx zhipuai`，但仓库内 casevo 0.3.19 的 `pyproject.toml` 要求 Python 3.11+，并依赖 Mesa 2.4.0 和 ChromaDB。为避免版本不匹配，建议使用 Python 3.11 或更高版本，并以赛方公布的安装方式为最终依据。

```bash
cd /Users/lzc/TNTprojectZ/AprojectZ/SMP2026casevo
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

# Starter Kit 的网络与本地测试依赖
python -m pip install requests networkx zhipuai

# 仅当赛方确认本地使用本仓库 casevo 命名空间时安装
python -m pip install ./casevo

# 先检查评测/本地所需的命名空间，而不是直接修改示例代码
python -c "import agent_mesa; print('agent_mesa OK')"
```

最后一条若报 `ModuleNotFoundError`，说明缺少赛方提供的 `agent_mesa` 运行时或存在命名迁移问题。应先确认官方说明。不要仅为绕过导入错误而在提交包中硬编码环境替身；这既不能验证真实评测契约，也可能违反框架接入要求。

### 3.2 本地配置与运行

1. 进入 [`SMP_Starter_Kit`](../../SMP_Starter_Kit/)。
2. 在 `local_test.py` 的 `YOUR_KEY` 位置填入**本地调试**用的个人智谱 Key；该 Key 绝不能出现在 `team_submission/` 或最终 ZIP。比赛评测会注入 `llm`，`ParticipantSquadModel` 不应自行创建或替换 Key。
3. 初次理解 API 时可保留 `local_test.py` 的“基础 API 接口调用演示”；开始做公平策略评估时，应注释该区块，因为它已经扫描、游说、断链和屏蔽了测试图，会污染后续智能体得分。
4. 从该目录运行实际存在的入口：

```bash
cd /Users/lzc/TNTprojectZ/AprojectZ/SMP2026casevo/SMP2026/SMP_Starter_Kit
python local_test.py
```

注意 README 中写作 `local_test_run.py`，而当前仓库实际文件为 `local_test.py`；以上命令以文件系统为准。

5. 本地脚本连接的远程沙盒地址和 `custom_seeds/my_test_network.json` 仅用于调试。该 JSON 只有 4 个节点、预算为 60，不能代表正式的 50/100 节点评测。

### 3.3 API 返回值与本地黑板

只在一个地方封装/执行每一种环境调用，并在每次返回后同步黑板。推荐的数据不变量：

```python
local_nodes: dict[int, dict]      # 已扫描且仍存活：w、persona、comm_left
local_edges: set[tuple[int, int]] # 已知且仍有效；端点始终按 (min, max) 规范化
dead_nodes: set[int]              # 扫描为空或已成功屏蔽；不可再作为目标
```

安全的扫描回写逻辑应使用环境的真实返回值，而不是重置沟通次数：

```python
result = self.env.scan_node(node_id)
if result is None:
    self.dead_nodes.add(node_id)
    return

self.local_nodes[node_id] = {
    "w": result["w"],
    "persona": result["persona"],
    "comm_left": result["comm_left"],
}
for neighbor in result["neighbors"]:
    self.local_edges.add(tuple(sorted((node_id, neighbor))))
```

对照当前基线：它将 `res["comm_left"]` 强行改写为 `3`。这会在非初始状态或环境返回变化时令黑板失真，应改为保留环境返回值。`local_edges` 使用 `set[tuple[int, int]]` 也比列表查找更适合做去重和删除。

## 4. 读懂并改造官方基线

### 4.1 基线的回合机制

[`team_submission/starnet_model.py`](../../SMP_Starter_Kit/team_submission/starnet_model.py) 建立了三个 Agent：

```text
CommanderAgent ──宏观 intent（explore / intervene）──► ExecutorAgent
       │                                                   │
       └──────── explore ──► ScoutAgent ──► self.env 动作 ─┘
```

一个 `step()` 中依次发生：

1. 读取剩余预算、已知节点/边、死节点和暴力节点数；
2. 指挥官调用一次 `commander_react.txt`，输出 `explore` 或 `intervene`；
3. 探索时侦察兵调用一次 `scout_react.txt`，输出节点 ID，随后扫描；干预时执行官调用一次 `executor_react.txt`，输出动作与目标；
4. 程序调用环境、把结果同步到黑板，最后 `self.schedule.time += 1`。

这已满足“多角色 + 环境反馈 + 后续重规划”的基本结构，但每个回合最多会调用 2 次 LLM。按初赛 50 次上限，连续运行 25 回合就会触顶；在 100 精神力预算下，这通常远早于预算耗尽。因此基线应当作为架构示范，而非可直接提交的高分策略。

### 4.2 基线中应优先修正的点

| 位置/行为 | 风险 | 建议处理 |
| --- | --- | --- |
| 三个提示词写死“1 到 5”“全局最多 5 节点” | 正式节点范围为 50/100，LLM 会停止探索或只扫描前 5 个节点 | 将总节点数、ID 范围、已知/未探索集合通过 `extra` 动态传入 |
| 指挥官 + 侦察/执行官每轮各调一次 LLM | 约 25 回合即可能耗尽 50 次限制 | 使用规则决定探索/干预和候选，LLM 只在少数难以区分的候选间选择；每步最多一次 |
| `_execute_scan` 中调用 `self.env._deduct_budget(0.1)` | 这是私有环境成员，且违反只使用公开 API 的要求 | 移除该调用；重复扫描应由本地校验直接跳过并换候选 |
| 预算结束时调用 `self.env.end_turn()` | 当前 `RemoteStarNetEnv` 并未实现该公开方法 | 仅 `return 1`（如果平台按返回值结束）或按照赛方后续公布的公开结束 API；本地结算由 `trigger_eval()` 完成 |
| 复制基线时把 `comm_left` 固定为 3 | 本地状态可能与环境不一致 | 保存扫描结果；每次沟通成功/失败后以响应更新 |
| LLM 的 JSON 直接转成环境动作 | 可能产生未知节点、死节点、非法边、非法 `prompt_id` 或超预算请求 | 生成候选集，严格解析和校验后才调用 `self.env` |
| `config.json` 可配置角色，但模型代码硬编码访问前三项 | 角色数一变会越界或角色—提示词错配 | 要么保持恰好 3 个角色，要么同步重构实例化与编排逻辑 |
| `local_test.py` 先做手动 API 演示 | 测试种子状态已被修改，无法与未干预基线比较 | 正式评估时关闭演示区，每次使用新 session |

## 5. 建议的最小可交付策略：程序保证合法，LLM 仅做增益判断

### 5.1 先写确定性候选生成器

所有候选都必须由 Python 根据黑板生成，LLM 不拥有“发明动作”的权限。每次最多列出若干个高价值候选，例如：

- **扫描候选**：未扫描且未死亡的 ID；优先已知边界附近、能够揭露更多邻居或降低决策不确定性的节点。无边界信息时，可在合法未扫描 ID 中按固定/可复现顺序选取少量候选。
- **游说候选**：存活、已扫描、`comm_left > 0` 且预算至少 2 的节点；枚举合法 `prompt_id`，依据已知人设与剩余次数估计边际收益。
- **断链候选**：`local_edges` 内当前有效的边，优先连接低倾向/暴力节点与高影响区域的桥边；预算至少 3。
- **屏蔽候选**：存活、已扫描且风险足够高的节点；预算至少 5。屏蔽会删除节点及其所有影响，必须比较其负面风险和该节点可能被游说的正面潜力。

以下是可直接嵌入 `starnet_model.py` 的**校验思想**（字段仍须以赛方 API 为准）：

```python
VALID_PROMPT_IDS = {1, 2, 3}

def is_valid_action(self, action, u, v=None, prompt_id=None):
    budget = self.env.get_remaining_budget()
    if action == "scan":
        return isinstance(u, int) and 1 <= u <= self.node_count \
            and u not in self.local_nodes and u not in self.dead_nodes and budget >= 0.5
    if action == "comm":
        node = self.local_nodes.get(u)
        return node is not None and node["comm_left"] > 0 \
            and prompt_id in VALID_PROMPT_IDS and budget >= 2.0
    if action == "cut":
        return tuple(sorted((u, v))) in self.local_edges and budget >= 3.0
    if action == "shield":
        return u in self.local_nodes and budget >= 5.0
    return False
```

`node_count` 应由赛方阶段配置或明确的运行参数设置为 50/100；不要根据当前扫描到的节点数推断全图规模。若赛方未向模型注入阶段参数，需在官方允许的配置项中显式声明，并在切换赛段时更新。

### 5.2 再让 LLM 在候选中选择

保留 `JsonStep` 很合适，但输出应改为候选 ID，而不是自由形式的节点和边。提示词示例：

```jinja2
你是星网策略评审。只能从候选中选择，不得创造节点、边、动作或 prompt_id。
剩余预算：{{ extra.budget }}
已知图摘要：{{ extra.summary }}
候选：{{ extra.candidates }}

仅输出 JSON：{"candidate_id": "C1", "reason": "不超过 25 字"}
```

程序流程应为：

```text
候选为空 → 返回结束
候选只有一个 / 差距足够大 → 不调用 LLM，直接执行
候选接近且调用额度尚有余量 → 调一次 LLM 选 candidate_id
JSON 解析失败、候选 ID 非法、超时 → 用确定性第一候选回退
动作执行后 → 以环境响应更新黑板，不把请求当成功
```

这样仍然是 casevo 智能体链驱动的动态决策，但在 50 次上限内留下足够余量。

### 5.3 图特征如何服务策略

已知图只是局部图，所有指标必须带着“不确定”的意识使用：

| 指标 | 在已知子图上的用途 | 不能据此断言的事 |
| --- | --- | --- |
| 已知度数 | 识别已显露的高连接节点，影响其潜在传播/保留作用 | 未扫描节点一定没有更多连接 |
| 割点/桥边 | 发现可能隔离负向团簇的断链候选 | 删除后一定提升最终得分 |
| 连通分量的人设与 `w` 汇总 | 判断继续探索、游说或屏蔽的优先级 | 它就是完整网络的真实分区 |
| 未扫描邻居比例 | 衡量再次扫描的信息价值 | 未知边不存在 |
| `comm_left` 与 `w` | 为游说收益做边际排序 | 未知的官方人设—话术效果 |

可先实现一个轻量的“每单位成本预期收益”排序：

```text
扫描分数 = 预期新增信息价值 / 0.5
游说分数 = 预期本轮倾向增益 × 拓扑影响 × 衰减系数 / 2
断链分数 = 预期阻断的负向影响 / 3
屏蔽分数 = 预期移除的净负向影响 / 5
```

其中人设作用、话术效果和真实共识更新公式若未被官方明确公开，只能用本地种子进行经验校准，不能伪称为真实环境规则。最终目标是多种子平均表现，而不是单个玩具网络的局部最优。

## 6. 基于当前 SDK 的安全执行与状态同步

### 6.1 执行游说

```python
response = self.env.communicate(node_id, prompt_id)
if response.get("status") == "success":
    self.local_nodes[node_id]["w"] = response["new_w"]
    # 若响应未来提供新的 comm_left，应优先使用；否则仅在本地确定成功后减一。
    self.local_nodes[node_id]["comm_left"] -= 1
elif response.get("status") == "max_comm_reached":
    self.local_nodes[node_id]["comm_left"] = 0
```

无论 LLM 怎么建议，沟通前都检查节点存在、存活、`comm_left > 0`、`prompt_id` 合法和预算至少 2。沟通失败不应再扣减本地次数，除非环境明确返回该次数已经耗尽。

### 6.2 执行断链和屏蔽

```python
edge = tuple(sorted((u, v)))
if self.env.cut_link(*edge):
    self.local_edges.discard(edge)

if self.env.shield_node(node_id):
    self.local_nodes.pop(node_id, None)
    self.local_edges = {e for e in self.local_edges if node_id not in e}
    self.dead_nodes.add(node_id)
```

不要在断链/屏蔽失败时改写本地成功状态。屏蔽成功后，节点应加入 `dead_nodes`，以阻止后续扫描、游说和再次屏蔽。当前本地客户端并未公开 `end_turn()` 或 `_deduct_budget()`；它们不应成为正式逻辑依赖。

### 6.3 何时结束

任务说明称系统会循环调用 `step()` 直至预算耗尽，基线注释也说明非零返回可代表结束。对当前已公开接口，最稳妥的停止策略是：

- 剩余预算低于所有仍可能带来正收益的动作成本；
- 没有合法候选，或所有候选的保守预期收益不为正；
- LLM 调用额度到达队伍设定的安全阈值，且规则策略也无法产生合法动作；
- 通过 `return 1` 交给评测器结束（须在赛方实际评测中确认返回语义）。

本地 `local_test.py` 的结算是循环结束后由外层调用 `env.trigger_eval()`；`ParticipantSquadModel` 不需要、也不应自行请求私有结束方法。

## 7. 提示词与角色配置

`config.json` 中的 `person` 会作为 `AgentBase` 的 `description` 传给模板。例如当前模板中的：

```jinja2
你是星网远征军的 {{ agent.description.role }}。
```

会取到“最高指挥官”“首席侦察兵”等配置。改变角色文案不会自动改变程序行为；只有 `starnet_model.py` 实例化、`setup_chain()` 和调用顺序也同步调整，角色分工才真正成立。

提示词设计应强调以下边界：

- 输入仅包含经过程序整理的已知信息，不带任何环境私有字段；
- 明确节点范围、剩余预算、候选 ID 和 `comm_left`；
- 要求严格 JSON，字段少、理由短；
- 明示“只能选择候选、不得编造目标”；
- 不在模板里写死 `1..5`、固定节点数或只适配某个本地种子的规则。

`JsonStep` 采用正则提取 JSON 并执行 `json.loads`，链失败时会重试。即使解析成功，也必须在 Python 中进行上述合法性校验；模型输出永远不是环境权限凭证。

## 8. 测试、日志和调参顺序

### 8.1 推荐的迭代顺序

1. **跑通**：不调用 LLM，写一个确定性策略，完成一次扫描、一次合法动作、结束和结算。
2. **对账**：对每次环境调用记录预算前后、请求、响应、黑板变化；确认扫描/沟通/断链/屏蔽失败也不会破坏状态。
3. **扩图**：改掉所有 4/5 节点常数，测试 50 与 100 节点合法 ID 边界。
4. **图算法**：加入已知子图的度数、割点、桥边和连通分量特征，比较多个人工/自建种子上的平均分。
5. **LLM 增强**：只让 LLM 处理接近候选，启用调用计数、超时和确定性回退。
6. **提交演练**：清空 Key、缓存和 `__pycache__`，按最终 ZIP 结构打包，在干净环境中导入并运行。

### 8.2 最少测试清单

- 扫描过的节点、死节点、ID 越界节点均不会重复发起扫描。
- `comm_left == 0` 的节点不会产生游说候选；第 4 次游说不发请求。
- 非 `local_edges` 的边不产生断链请求；断链成功后边被移除。
- 屏蔽成功后节点及关联边删除；屏蔽失败不改本地存活状态。
- 非法/缺字段 JSON、LLM 超时、环境响应异常都能安全回退或结束，不使进程崩溃。
- 每个种子 LLM 调用数小于 50，并留出安全余量；统计剩余精神力。
- 同一可控种子下，禁用 LLM 后行动序列可复现；与启用 LLM 的版本比较均值和方差。

### 8.3 日志字段

即使不启用 casevo 的 `TotLog`，也应结构化记录：种子标识、回合、预算前后、已知节点/边数、未知节点数、候选列表、选择动作、环境响应、黑板变化、LLM 调用累计数和停止原因。日志不得写入 API Key、Authorization 头或不允许暴露的环境数据。

## 9. 提交前检查清单

- [ ] `ParticipantSquadModel` 名称、继承关系、`__init__(host_env, person_list, llm)` 和 `step()` 均符合最新官方接口。
- [ ] 所有真实图操作只通过公开的 `self.env` 方法完成；没有 `_deduct_budget`、私有字段读取或白盒修改。
- [ ] `local_nodes`、`local_edges`、`dead_nodes` 只反映已公开观察/成功响应；未知不被伪装成不存在。
- [ ] 扫描结果中的 `comm_left` 被保留；游说、断链、屏蔽都在请求前校验、在响应后对账。
- [ ] 不含 `1..5`、节点总数 5、4 节点种子等演示常量；已覆盖当前赛段的 50/100 节点范围。
- [ ] 单种子 LLM 调用数严格低于 50，错误路径也不会无限重试。
- [ ] `team_submission/` 不含个人 API Key、`.env`、日志、缓存、`__pycache__` 或本地测试工具。
- [ ] 最终 ZIP 内没有外层 `team_submission/` 文件夹，根目录直接是 `config.json`、`prompt/`、`starnet_model.py`，并已按最新官方说明复核额外文件的允许性。

## 10. 一句话路线图

先用 casevo 的 `ParticipantSquadModel` 把“环境反馈驱动的状态机”跑稳，再以本地黑板保存**仅已知的局部图**；用图算法生成和校验合法候选，用极少量 LLM 调用进行高层取舍，最后以环境响应不断纠偏。这样既满足 casevo 多智能体编排要求，又能在预算、迷雾、调用上限和多种子泛化的共同约束下逐步优化成绩。
