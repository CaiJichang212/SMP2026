# SMP 2026「复杂社会网络中的关键节点识别与动态干预」方向调研报告

> 面向赛题：SMP 2026 星网干预赛题  
> 调研时间：2026-09-01  
> 重点：关键节点识别、未知网络探索、观点动力学、影响力最大化、网络拆解/阻断、预算约束组合优化、GNN/RL 与开源实现

---

## 1. 执行摘要

本赛题表面是 LLM 多智能体决策，算法本质更接近以下四类经典问题的组合：

1. **关键节点识别（Critical Node Identification）**：找出真正决定全局稳态的节点，而不是简单找最大度节点。
2. **影响力/观点最大化（Influence / Opinion Maximization）**：在有限预算下选择最值得游说的节点，使最终全网援助倾向最大。
3. **网络拆解与影响阻断（Network Dismantling / Influence Blocking）**：通过切边、屏蔽高危节点，抑制负面观点扩散。
4. **未知图上的主动探索（Exploratory / Adaptive Influence Maximization）**：图初始不可见，需要花预算扫描节点，并根据已获信息逐步决策。

对比赛最重要的判断是：

- **不要把主方案做成“LLM 看图后凭感觉决策”**。节点只有 50/100 个，NetworkX 图算法 + 本地稳态模拟 + 组合优化更稳定、更便宜、更可解释。
- **不要只用 Degree/PageRank**。应使用“节点属性 × 拓扑影响力 × 社区/桥接作用 × 操作成本”的联合评分，并按真实“边际得分 / 精神力”排序。
- **最值得优先做的并非 GNN/RL，而是反向理解官方结算模型**：利用官方提供的自定义种子调试能力，设计小图进行黑盒系统辨识，尽量恢复共识迭代与得分函数。若能得到近似准确的本地 simulator，就可直接用仿真驱动 Greedy / Beam Search 优化每一步动作。
- **前沿 GNN/RL 更适合作为 v3/v4**：当已有大量自定义图和离线评测数据后，用于学习扫描策略、候选节点剪枝和跨随机种子泛化，而不是比赛初期直接取代可控的图算法。

---

## 2. 赛题的算法抽象

赛题给定：

- 初赛 50 节点、100 精神力；复赛 100 节点、200 精神力；
- 扫描节点：0.5；
- 游说节点：2；
- 切断边：3；
- 屏蔽节点：5；
- 游说最多 3 次，收益衰减为 1、0.5、0.25；
- 最终经过网络共识迭代后，以节点稳态倾向和度数相关权重计算综合援助意愿；
- 多个隐藏随机种子取平均，要求泛化；
- 必须使用 Casevo 多智能体框架；
- 正式评测中，初赛单图 LLM API 调用上限为 **120 次**，复赛为 **250 次**；早期 SDK 的 50 次为本地内测占位保护值。

因此可以形式化为：

$$
\max_{\pi}
\mathbb{E}_{G\sim \mathcal D}
\left[
F\left(G',w'\right)
\right]
$$

其中：

- \(G\) 是隐藏星网；
- \(\pi\) 是“扫描—分析—干预”的自适应策略；
- \(G'\) 为经过 cut/shield 后的网络；
- \(w'\) 为 communicate 后节点倾向；
- \(F\) 是官方未知的稳态推演与评分函数；
- 所有动作满足总预算约束。

更准确地说，这是一个**部分可观测、预算约束的序贯组合优化问题**，而不是单纯“找 Top-K 关键节点”。

### 2.1 一个容易忽视的预算事实

如果直接扫描全部节点：

- 初赛：50 × 0.5 = **25 精神力，占总预算 25%**；
- 复赛：100 × 0.5 = **50 精神力，占总预算 25%**。

因此“全扫”并非不可接受。比赛中应至少同时维护两条路线：

- **Full-scan baseline**：先完整恢复图，再全局优化；
- **Adaptive-scan**：只扫描最有价值的未知区域，把更多预算留给干预。

不要预设“主动探索一定优于全扫”，应该通过多种生成图做消融实验决定。

---

## 3. 研究背景

### 3.1 Influence Maximization：影响力最大化

Kempe、Kleinberg、Tardos 在 KDD 2003 将“选择少量种子节点，使影响扩散最大”形式化为组合优化问题，并证明在 Independent Cascade（IC）和 Linear Threshold（LT）等经典传播模型下具有 NP-hard 性；同时利用单调性和次模性得到 Greedy 的近似保证。

该方向后来形成三条主线：

- **启发式节点排序**：Degree、PageRank、k-core、VoteRank 等；
- **基于扩散模型的 Greedy/CELF/RIS/IMM**；
- **ML/GNN/RL 学习组合优化策略**。

对本赛题而言，游说行为与 Influence Maximization 最接近，但目标不是“激活节点数”，而是“最大化最终稳态观点分数”。

### 3.2 Opinion Dynamics：观点动力学

社会网络的观点演化常用：

- **DeGroot 模型**：节点反复对邻居观点做加权平均；
- **Friedkin–Johnsen（FJ）模型**：在 DeGroot 基础上加入对自身初始观点的 stubbornness / susceptibility（固执度/易受影响程度）；
- Hegselmann–Krause 等有界信任模型。

赛题“节点连接度越高，观点保留能力与影响力越大”“最终迭代收敛”非常接近**带节点异质性的线性/准线性观点动力学**。

2025 年关于复杂网络观点动力学干预的综述已经把研究重点从“分析是否收敛”推进到：

- **节点选择**；
- **干预时机选择**；
- **观点最大化**；
- **拓扑结构干预**。

### 3.3 Critical Nodes / Network Dismantling

另一条直接对应 `shield_node` 和 `cut_link` 的研究线是：

- Critical Node Problem；
- Network Dismantling；
- Network Immunization；
- Influence Blocking Maximization。

Morone & Makse 2015 提出的 **Collective Influence（CI）** 从 optimal percolation（最优渗流）角度寻找少量关键节点；重要结论之一是：**真正的全局关键节点未必是最大度节点**。

FINDER（Nature Machine Intelligence 2020）进一步把节点删除建模为深度强化学习问题，可直接对应赛题的“屏蔽高危核心节点”。

---

## 4. 当前主流方法

### 4.1 传统中心性方法

| 方法 | 核心含义 | 优点 | 缺点 | 赛题价值 |
|---|---|---|---|---|
| Degree | 邻居数量 | 极快 | 只看一跳 | 高：基础特征 |
| PageRank / Eigenvector | 被重要节点连接也更重要 | 可反映全局影响 | 未考虑节点立场 | 中高 |
| Betweenness | 控制最短路径的桥节点 | 适合切边/隔离 | 易受图结构变化影响 | 高 |
| Closeness | 到其他节点平均距离短 | 传播速度快 | 断图时解释复杂 | 中 |
| k-core / k-shell | 是否处于网络核心层 | 对传播核心识别强 | 同一 core 内区分弱 | 高 |
| VoteRank | 逐个选互相分散的影响节点 | 避免候选节点扎堆 | 未直接建模观点正负 | 高 |
| Collective Influence | 看一定半径内的集体结构影响 | 适合拆解网络 | 参数和实现稍复杂 | 高 |

Kitsak 等 Nature Physics 2010 指出，在很多传播场景中，**k-shell 位置比简单 degree 更能识别有影响力的传播者**。

VoteRank 的价值尤其适合比赛：选择一组目标时，会主动削弱已选节点周边节点的得票能力，避免“所有游说资源都集中在同一个局部社区”。

### 4.2 Influence Maximization 主流算法

#### Greedy / CELF

若能写出一个“给定当前图和动作集合，计算最终分数”的本地模拟器，最直接的方法就是：

1. 枚举候选动作；
2. 仿真执行一个动作后的最终分数；
3. 计算边际增益：
   $$
   \Delta(a)=F(S\cup\{a\})-F(S)
   $$
4. 按
   $$
   \frac{\Delta(a)}{cost(a)}
   $$
   选择性价比最高动作；
5. 更新图和状态后重新计算。

如果目标近似次模，可以使用 **CELF（Cost-Effective Lazy Forward）** 缓存上轮边际收益，减少重复模拟。

对于只有 50/100 个节点的赛题，这类“显式仿真 + Greedy”通常比大规模图算法更值得优先实现。

#### Degree Discount

Chen 等 KDD 2009 提出 Degree Discount：一旦某节点已被选中，就降低其邻居作为后续种子的价值，解决高 degree 节点邻域重叠问题。

在赛题中可以直接改造成：

> 已游说/已保护一个核心社区后，相邻节点的新增价值应该下降。

#### RIS / IMM / OPIM

Reverse Influence Sampling（RIS）和 IMM 是大规模 IM 的经典高效方向，适合百万级图。

但本赛题只有 50/100 节点，因此：

- 理论上值得参考；
- 实战中没必要照搬复杂的大规模采样框架；
- 其核心思想“用采样估算动作的全局影响”可以保留。

---

## 5. 与赛题高度相关的未知网络探索研究

### 5.1 Exploratory Influence Maximization

Wilder 等 AAAI 2018 提出 **Maximizing Influence in an Unknown Social Network**：

- 网络未知；
- 查询一个节点可获得其邻接关系；
- 查询有成本；
- 目标是在少量查询下找到接近全局最优的影响节点。

这与 `scan_node` 几乎同构。

其 ARISEN 方法利用**社区结构**：无需完整恢复所有边，而是优先发现不同社区，并寻找各社区中有代表性的节点。

### 5.2 RL 学习 Graph Sampling

Kamarthi 等 AAMAS 2020 进一步提出：

> 不手工写“下一个扫描哪个节点”的规则，而是训练 RL policy，根据当前部分图决定下一个 query。

论文报告其策略在未知社会网络上相对当时手工采样方法有明显提升。

这类研究对本赛题最直接的映射是：

- state：已发现子图、节点属性、预算；
- action：scan 某个未知节点；
- reward：最终干预得分或发现高价值节点的增益。

### 5.3 Adaptive / Partial-feedback Influence Maximization

自适应 IM 研究关注：

> 前一次选择产生反馈后，再决定下一次选择。

这与比赛中“扫描后再决策”“游说后读取 new_w 再更新策略”高度一致。

需要注意：部分反馈条件下，目标未必继续满足严格 adaptive submodularity，因此不要盲目依赖固定 Greedy 的理论保证；更稳妥的是**每次获得真实反馈后重新估值**。

---

## 6. 观点最大化与拓扑干预：2025–2026 前沿方向

### 6.1 Leader Selection for Opinion Optimization（2026）

2026 年 Theoretical Computer Science 的工作直接研究：

- FJ 类观点动力学；
- 选择少量 leader；
- 固定其观点；
- 最大化/最小化网络最终均衡观点。

其意义非常接近比赛的“选择少量节点重点干预，从而改变最终稳态”。

更关键的是，该工作证明某些形式下目标具有 monotonicity / supermodularity，从而 Greedy 可以得到近似保证。

**赛题启示：**  
如果能通过黑盒实验确认官方稳态规则接近 FJ/线性共识，则“直接优化均衡值”比用 PageRank 间接猜测要有效得多。

### 6.2 Opinion Maximization via Link Recommendation（2025）

2025 年 TCS 研究通过增加 leader—follower 边来最大化最终观点，并证明特定模型下目标是单调次模的。

比赛不能加边，但可以**删边**，因此可以构造对偶思路：

- 对正面观点来说，保留/保护高价值传播边；
- 对负面观点来说，删除使负面核心连接到其他社区的关键边。

### 6.3 Topological Intervention（2025/2026）

Peng 等研究竞争观点网络中的拓扑干预，实验表明弱化 echo chamber（回音室）内部连接可以改变观点传播强度。

对比赛的直接启示是：

`cut_link` 不应该只切“暴力节点度最高的边”，而应优先考虑：

- 暴力社区 → 中立/和平社区的桥；
- 高 edge betweenness；
- 跨社区传播通道；
- 切断后能显著降低负面节点的全局可达性，而不会损害正面传播的边。

---

## 7. GNN / Deep RL 前沿方法

### 7.1 FINDER

FINDER 把“逐步删除关键节点”建模为 RL：

- state：当前剩余图；
- action：删除一个节点；
- reward：网络功能下降；
- 用 GNN/structure2vec 类表示学习节点。

优势：

- 能学习多个结构指标组合；
- 可在小图训练后迁移到更大、不同类型图；
- 原论文同时覆盖 Critical Node 和 Network Dismantling。

非常适合借鉴 `shield_node` 策略。

### 7.2 GCOMB

GCOMB（NeurIPS 2020）：

- 先用 GCN 给候选节点估值并剪枝；
- 再通过 Q-learning 做预算约束组合选择。

其真正值得比赛借鉴的是：

> **“学习模型不要直接在全部节点上决策，而是先用便宜图特征筛出候选集，再做复杂决策。”**

例如：

- 100 节点 → 先筛 Top 15 高风险节点；
- 只在 Top 15 内做 shield/communicate 组合搜索。

### 7.3 MaDGNN（2026）

2026 Scientific Reports 提出的 MaDGNN：

- Cascade-aware GNN 捕捉高阶拓扑和级联特征；
- Munchausen DQN 做节点序贯选择；
- 强调不同规模/结构网络上的泛化。

这代表当前 IM 的一条前沿路线：**GNN 表征 + RL 组合决策 + 跨图泛化**。

### 7.4 Dynamic Competitive IM（2026）

2026 年 D2G-DCIM 等工作进一步研究：

- 动态图；
- 竞争性观点/信息扩散；
- GNN + DRL；
- 跨时间邻域聚合。

赛题并不是真正连续时间动态图，因此这些方法不宜直接照搬，但它们的“**同时建模正负两方竞争影响**”比普通单目标 IM 更贴合本题。

---

## 8. 官方 SDK 暴露出的高价值信息

### 8.1 LLM 调用必须极度克制

赛事方已确认正式评测规则：

- 初赛单次图评测 LLM 调用上限为 120 次，复赛为 250 次；
- 早期 SDK README 和 `local_test.py` 中的 50 次是本地内测占位保护值；本地种子的 `max_api_calls` 可随测试规模调整；
- 即使配额提高，仍应结合图论算法精简 LLM 调用。

如果每次扫描都先调用 LLM 决定扫描哪个节点：

- 初赛的 120 次配额会被每次扫描都先询问 LLM 的机械流程快速消耗；
- 应保留调用额度处理真正需要策略比较的候选。

更合理的实现：

```text
Casevo Agent/Model
        │
        ├── Python deterministic scout
        │     └── scan_node + NetworkX
        │
        ├── Local Graph Optimizer
        │     ├── centrality
        │     ├── community
        │     ├── local simulator
        │     └── greedy / beam search
        │
        └── LLM Agent（少量）
              ├── 高层策略切换
              ├── 异常兜底
              └── 必要的多智能体编排
```

也就是说：

> **Casevo 是运行框架，不代表每个 action 都必须由 LLM 生成。**

### 8.2 官方自定义种子暗示存在隐藏响应系数

官方 `my_test_network.json` 示例包含：

```json
{"id": 1, "w": 10.0, "persona": "和平", "r": 1.5}
```

同时：

```json
"prompts": {
  "1": 15.0,
  "2": 10.0,
  "3": -5.0
}
```

官方 `local_test.py` 给出的预期结果：

```text
communicate(node_id=1, prompt_id=1)
=> new_w = 32.5
```

恰好有：

$$
10 + 15\times1.5 = 32.5
$$

因此**官方调试样例强烈暗示**，至少在该测试环境里第一轮游说效果满足：

$$
\Delta w \approx prompt\_value\times r
$$

再叠加第 2、3 次的 0.5 / 0.25 衰减。

但 `scan_node` 返回值里没有 `r`，只有 persona。

这带来一个非常有价值的策略：

> 第一次 communicate 不只是“修改观点”，同时也是一次**探测真实可游说性 r 的实验**。

如果正式环境仍遵循该机制，可由：

$$
\hat r
=
\frac{w_{\text{after}}-w_{\text{before}}}
{\text{prompt base}}
$$

在线估计节点真实响应系数，再决定是否值得第 2、3 次继续游说。

注意：自定义种子的 prompt 数值未必等于正式隐藏种子的固定配置，因此正式比赛前必须通过官方最新文档/调试环境确认。

---

## 9. 推荐的比赛核心算法

## 9.1 节点联合价值函数

不要单独依赖某个 centrality。建议构造两类评分。

### 正向游说价值

$$
V^{comm}_i
=
R_i
\times
I_i
\times
P_i
\times
M_i
$$

其中：

- \(R_i\)：预计游说响应（persona 先验 + 已观测 \(\hat r\)）；
- \(I_i\)：结构影响力；
- \(P_i\)：当前观点可提升空间；
- \(M_i\)：社区覆盖/边际去重修正。

结构影响力可组合：

$$
I_i =
\alpha d_i
+\beta PR_i
+\gamma core_i
+\delta betweenness_i
+\eta CI_i
$$

最后使用：

$$
ROI^{comm}_i=\frac{\Delta Score_i}{2}
$$

而不是只比较 \(\Delta w_i\)。

### 高危屏蔽价值

$$
V^{shield}_i
=
(-w_i)_+
\times I_i
\times H_i
-
C_i
$$

其中：

- \((-w_i)_+\)：负面强度；
- \(I_i\)：全局结构影响；
- \(H_i\)：暴力 persona / 低可游说性；
- \(C_i\)：屏蔽该节点后同时失去的正面连接、度权重等副作用。

最终仍应使用模拟后的：

$$
ROI^{shield}_i=\frac{\Delta Score_i}{5}
$$

### 切边价值

针对边 \((u,v)\)：

$$
V^{cut}_{uv}
\approx
\text{negative-flow}(u,v)
\times
\text{edge-betweenness}(u,v)
\times
\text{cross-community}(u,v)
$$

最值得切的是：

> 高负面核心 → 非负面社区的关键桥，而不是暴力社区内部任意高 degree 边。

---

## 9.2 优先做“本地结算器 + Marginal Gain Optimizer”

最推荐的主方案：

```text
扫描/恢复图
   ↓
构建 NetworkX Graph
   ↓
本地复制当前图
   ↓
模拟候选动作
   ↓
运行本地共识迭代到收敛
   ↓
估计最终 Score
   ↓
计算 ΔScore / cost
   ↓
执行真实动作
   ↓
读取反馈并重新优化
```

候选动作：

- `(comm, node, prompt_id, nth)`
- `(cut, u, v)`
- `(shield, node)`

每一轮选择：

$$
a^*=
\arg\max_a
\frac{
\hat F(s\oplus a)-\hat F(s)
}{
cost(a)
}
$$

这是比赛最自然、最可解释的“动态干预”。

---

## 9.3 黑盒系统辨识：极高优先级

官方 SDK 支持上传 `custom_seed_data` 到调试服务器并 `trigger_eval()`。

因此建议构造一组极小图，系统研究结算规律。

### 实验 A：孤立节点

目的：

- 确认无边时 Score 是否为 \(\sum w_i\)、0，还是其他形式。

### 实验 B：两节点单边

设置：

```text
w1 = +10
w2 = -10
```

改变两个节点的 persona / r，观察最终值。

目的：

- 判断是否为普通平均；
- 判断 degree / persona 是否进入更新权重。

### 实验 C：三节点 path vs triangle

```text
1 - 2 - 3
```

对比：

```text
1
|\
2-3
```

目的：

- 判断 degree 在观点保持/影响中的具体作用。

### 实验 D：star

中心负面，叶子正面：

```text
      +
      |
+ --- - --- +
      |
      +
```

分别执行：

- shield 中心；
- cut 1 条边；
- communicate 中心；
- communicate 叶子。

目的：

- 估计三种动作真实 ROI。

### 实验 E：断开连通分量

目的：

- 确认最终 Score 是各连通分量独立收敛后求和，还是仍有全局归一化。

### 实验 F：同图不同 scale

将所有 \(w\) 同时 ×2。

目的：

- 判断共识方程是否线性。

如果能拟合出：

$$
x^{t+1}=A(G,r)x^t+b
$$

或近似 FJ：

$$
x^{t+1}
=
\Lambda W x^t
+
(I-\Lambda)x^0
$$

则最终稳态可直接解线性方程，而不必迭代：

$$
x^*
=
(I-\Lambda W)^{-1}(I-\Lambda)x^0
$$

这会把比赛从“猜策略”降维成一个明确的组合优化问题。

---

## 10. 组合优化方案

由于节点数只有 50/100，不必局限于单步 Greedy。

推荐逐级升级：

### Level 1：Greedy ROI

每轮选 `ΔScore / cost` 最大动作。

优点：

- 简单；
- 稳定；
- 易做动态更新。

### Level 2：CELF / Lazy Greedy

缓存上轮动作边际收益，只重新评估最可能成为最优的动作。

适合候选动作较多时减少 simulator 调用。

### Level 3：Beam Search

保留前 B 个中间策略：

```text
state_0
  ├─ action A → state_A
  ├─ action B → state_B
  └─ action C → state_C
```

每层只保留 Top-B。

建议：

- candidate node 先压缩到 10–20；
- Beam Width 10–50；
- Search Depth 3–8；
- 之后再回到 Greedy。

这可以捕捉：

- “先屏蔽节点再切边”的交互；
- “连续两次游说同一节点”的边际关系；
- 单步 Greedy 看不到的组合收益。

### Level 4：MCTS / RL

当本地 simulator 足够可信，且有大量随机种子训练数据，再考虑：

- MCTS；
- PPO/DQN；
- GNN + RL。

---

## 11. 扫描策略建议

### Baseline A：全量扫描

优先做，因为：

- 图规模很小；
- 只消耗 25% 总预算；
- 可以获得完整 centrality / community / bridge；
- 泛化稳定。

但**扫描动作应由 Python 状态机决定，不应每次调用 LLM**。

### Baseline B：Frontier Expansion

扫描新节点后，优先扫描：

1. 未扫描邻居中被多个已知节点共同指向的节点；
2. 与高风险节点相邻的未知节点；
3. 可能跨社区的 frontier 节点。

### Baseline C：Explore–Exploit 阈值

定义：

$$
VOI(j)
=
\mathbb E[\text{扫描 j 后最优策略提升}]
$$

当：

$$
VOI(j) < 0.5 \times \lambda
$$

则停止探索，转为干预。

实际实现可使用近似：

- frontier degree；
- 未知邻居数；
- 与负面核心距离；
- 当前图 centrality 不确定性。

---

## 12. Persona 与动作策略

根据赛题说明和官方自定义样例，可以形成以下先验，但必须通过正式环境校准。

### 和平节点

特点：

- 正向话术通常收益高；
- 如果本身已高度正向，继续游说可能浪费；
- 适合作为“正向意见领袖”。

优先：

- 高 centrality；
- 中等正向或中立；
- 高潜在 `r`。

### 中立节点

通常可能是性价比最高的 persuasion target：

- 更容易从 0 附近推成正向；
- 又可能处于不同社区的桥接位置。

### 暴力节点

如果：

- \(w\ll 0\)；
- degree/core/PageRank 高；
- persona 导致游说响应低；

那么 2 精神力游说往往不如 5 精神力 shield。

应比较：

$$
\frac{\Delta Score_{comm}}{2}
\quad vs \quad
\frac{\Delta Score_{shield}}{5}
$$

而不是固定“暴力都屏蔽”。

---

## 13. 多智能体架构建议

官方 baseline 是：

- Commander；
- Scout；
- Executor。

比赛优化版本建议改成：

```text
ParticipantSquadModel
│
├── ScoutAgent
│   └── 仅负责环境探索状态机
│
├── GraphAnalystAgent
│   ├── NetworkX
│   ├── community
│   ├── centrality
│   └── danger / benefit ranking
│
├── SimulatorOptimizer
│   ├── consensus simulator
│   ├── greedy / CELF
│   └── beam search
│
└── CommanderAgent (LLM)
    ├── 少量调用
    ├── 根据结构化摘要选择策略模式
    └── 异常/不确定情况兜底
```

关键原则：

> **LLM 负责“策略层”，图算法负责“计算层”，环境 API 负责“执行层”。**

不建议：

```text
每回合：
Commander LLM
→ Scout LLM
→ Executor LLM
→ API
```

因为这会：

- 消耗调用次数；
- 产生随机性；
- 对精确数值优化没有优势。

---

## 14. 开源项目清单

| 项目 | 方向 | 对比赛的价值 | 推荐级别 |
|---|---|---|---|
| `raoneng26/SMP2026` | 官方 Starter Kit | API、提交规范、自定义种子 | ★★★★★ |
| `rgCASS/casevo` | 官方指定多智能体框架 | Model/Agent/Memory/ToolStep | ★★★★★ |
| NetworkX | 图分析 | centrality、k-core、VoteRank、community | ★★★★★ |
| `GiulioRossetti/ndlib` | 扩散与观点动力学 | 快速测试传播/观点模型 | ★★★★★ |
| `FFrankyy/FINDER` | DRL 关键节点/网络拆解 | shield 策略的重要参考 | ★★★★☆ |
| `idea-iitd/GCOMB` | GNN + Q-learning | 预算约束候选选择 | ★★★★☆ |
| `zwl1985/BiGDN` | GNN + DRL IM | 较新的端到端影响最大化实现 | ★★★☆☆ |
| `lihuixidian/PIANO` | Graph embedding + RL | IM 学习式基线 | ★★★☆☆ |
| `tangj90/OPIM` | 高效 Influence Maximization | Greedy/RIS 类算法参考 | ★★★☆☆ |
| `K-Coconut/MCPBenchmark` | 组合优化 benchmark | 集成 IMM、GCOMB、RL4IM 等 | ★★★★☆ |
| `ucrparlay/Influence-Maximization` | 并行 IM | 高性能算法参考 | ★★☆☆☆ |
| `snowgy/Influence_Maximization` | IMM 简化实现 | 便于快速理解 IMM | ★★☆☆☆ |

### 14.1 最推荐直接复用

#### NetworkX

直接可用：

```python
nx.degree_centrality(G)
nx.pagerank(G)
nx.betweenness_centrality(G)
nx.edge_betweenness_centrality(G)
nx.core_number(G)
nx.voterank(G)
nx.community.greedy_modularity_communities(G)
```

对于 50/100 节点，运行成本几乎可以忽略。

#### NDlib

适合搭建：

- DeGroot/FJ 类近似实验；
- SIR/IC 类扩散对照；
- 不同拓扑上的鲁棒性测试。

#### FINDER

不建议一开始直接集成其旧 TensorFlow 工程，而应：

1. 先理解 reward / sequential node removal 建模；
2. 把其思想移植成 PyTorch/PyG 的小模型；
3. 用官方自定义种子训练。

---

## 15. 2026 前沿方法的实际采用建议

| 方法 | 学术前沿度 | 对比赛直接价值 | 当前建议 |
|---|---:|---:|---|
| Degree/PageRank | 低 | 中 | 必做 baseline |
| k-core/VoteRank/CI | 中 | 高 | 主方案特征 |
| Greedy + simulator | 中 | **极高** | **优先级最高** |
| CELF/Beam Search | 中高 | **极高** | v2 |
| Unknown-graph RL sampling | 高 | 高 | v3 |
| FINDER | 高 | 高 | 候选 shield 模型 |
| GCOMB | 高 | 中高 | 候选剪枝 |
| MaDGNN | 很高 | 中 | 有训练数据后再做 |
| Dynamic GNN/RL | 很高 | 较低 | 暂不优先 |
| LLM-only multi-agent | 热门 | 低 | 不建议作为核心算法 |

结论：

> 比赛最可能赢分的路线不是“最新模型越复杂越好”，而是**尽快把隐藏评分函数建模准确，然后做精确边际优化**。

---

## 16. 推荐研发路线

### V0：2–3 天可完成的强 baseline

1. 固定 Python 扫描全部节点；
2. NetworkX 建图；
3. 计算：
   - degree；
   - PageRank；
   - k-core；
   - betweenness；
   - VoteRank；
4. 构造：
   - positive influence score；
   - danger score；
5. 规则：
   - 高危负面核心 → shield；
   - 负面跨社区桥 → cut；
   - 高影响、可游说正/中立 → communicate；
6. 算法生成候选 + LLM 决策。

### V1：Simulator-driven Greedy

核心工作：

- 自定义小图；
- 反推共识模型；
- 写本地 `evaluate(graph, node_state)`；
- 每轮真实计算所有候选动作的 `ΔScore/cost`。

这一步预计比继续堆 prompt 收益更大。

### V2：Beam Search + 在线估计 r

- 第一次游说返回 new_w 后估计响应；
- 动态更新后续沟通 ROI；
- 对 Top-K 动作用 Beam Search 做 3–8 步 look-ahead。

### V3：学习扫描策略

生成不同：

- Erdős–Rényi；
- Barabási–Albert；
- Watts–Strogatz；
- SBM/community；

然后随机 persona / w / r。

训练 policy 学习：

> 给定部分可见图，下一个 scan 谁最有价值？

### V4：GNN + RL 统一动作策略

动作空间同时包含：

- scan；
- communicate；
- cut；
- shield。

这是最“论文型”的最终方案，但工程风险最高。

---

## 17. 实验与消融设计

最终不要只看单个 custom seed。

建议至少生成 500–5000 个离线种子，覆盖：

### 图结构

- ER random；
- BA scale-free；
- WS small-world；
- SBM communities；
- hub-and-spoke；
- 多社区桥接图。

### 属性分布

- 和平节点多；
- 暴力节点多；
- 高危节点集中在 hub；
- 高危节点集中在 bridge；
- persona 与 topology 相关/不相关。

### 必做对比

1. Random；
2. Degree；
3. PageRank；
4. k-core；
5. VoteRank；
6. Composite heuristic；
7. Full-scan + Greedy；
8. Adaptive-scan + Greedy；
9. Beam Search；
10. GNN/RL（若完成）。

### 指标

- 平均最终 Score；
- 相对 BaseAvg 提升；
- Score / consumed budget；
- 剩余 budget；
- LLM calls；
- 不同 seed 的标准差；
- 最差 10% seed 表现。

比赛是多隐藏种子均值，因此：

> **均值 + 方差 + 尾部失败率**比单个最高分更重要。

---

## 18. 风险与待确认信息

目前公开任务文档和 Starter Kit 仍未完整暴露以下正式评测细节：

1. 最终共识更新方程；
2. degree 如何进入“观点保留能力与影响力”；
3. 是否不同连通分量独立收敛；
4. 正式 prompt_id 的基础数值；
5. persona 与隐藏 `r` 的生成关系；
6. 正式环境中是否仍存在自定义种子示例里的 `r` 机制；
7. LLM 调用计数在正式环境中是否只统计模型请求，还是还包括框架内部的其他调用；已确认上限为初赛 120 次、复赛 250 次；
8. 是否存在节点 w 的上下界；
9. shield 后度数权重如何重算；
10. 平局时“API 调用次数”具体只统计 LLM，还是所有环境调用。

这些信息都应该优先通过：

- 最新官方规则；
- 官方 GitHub 更新；
- 官方 Mock / remote test；
- 自定义小图黑盒实验

确认，而不是用一般社会网络论文假设代替。

---

## 19. 最终建议

如果目标是比赛得分，研发优先级建议：

### P0：立刻做

- 全量扫描 baseline；
- NetworkX 全套结构特征；
- 高危/高收益联合评分；
- 极少 LLM 调用。

### P1：最关键突破

- 利用官方 custom seed 做**结算模型黑盒系统辨识**；
- 构造本地精确/近似 simulator；
- `ΔScore / cost` 动态 Greedy。

### P2：冲榜优化

- CELF；
- Beam Search；
- 隐藏响应系数在线估计；
- 社区级 cut/shield 优化。

### P3：有余力再做

- unknown graph RL sampling；
- FINDER/GCOMB 风格 GNN + RL；
- 多图 meta-RL / domain randomization。

一句话概括：

> **核心不是“找一个最重要节点”，而是在未知图、有限预算和多种动作成本下，持续估算每个动作对最终稳态分数的真实边际贡献。**

---

# 参考文献与资料

## A. 官方资料

1. SMP2026 Starter Kit  
   https://github.com/raoneng26/SMP2026

2. Casevo: Cognitive agents and social evolution simulator  
   https://github.com/rgCASS/casevo

3. Jiang et al., *Casevo: A Cognitive Agents and Social Evolution Simulator*, arXiv 2024  
   https://arxiv.org/abs/2412.19498

## B. 关键节点与 Influence Maximization

4. Kempe, Kleinberg, Tardos. *Maximizing the Spread of Influence through a Social Network*. KDD 2003.  
   https://doi.org/10.1145/956750.956769

5. Kitsak et al. *Identification of influential spreaders in complex networks*. Nature Physics, 2010.  
   https://doi.org/10.1038/nphys1746

6. Morone, Makse. *Influence maximization in complex networks through optimal percolation*. Nature, 2015.  
   https://doi.org/10.1038/nature14604

7. Zhang et al. *Identifying a set of influential spreaders in complex networks* (VoteRank). Scientific Reports, 2016.  
   https://doi.org/10.1038/srep27823

8. Chen, Wang, Yang. *Efficient Influence Maximization in Social Networks*. KDD 2009.  
   https://doi.org/10.1145/1557019.1557047

9. Leskovec et al. *Cost-effective Outbreak Detection in Networks* (CELF). KDD 2007.  
   https://www.cs.cmu.edu/~christos/PUBLICATIONS/detect-techRept.pdf

10. Tang, Shi, Xiao. *Influence Maximization in Near-Linear Time* (IMM). SIGMOD 2015.  
    https://doi.org/10.1145/2723372.2723734

## C. 综述

11. Ait Rai et al. *Influential nodes identification in complex networks: a comprehensive literature review*. 2023.  
    https://doi.org/10.1186/s43088-023-00357-w

12. Jaouadi, Ben Romdhane. *A survey on influence maximization models*. Expert Systems with Applications, 2024.  
    https://doi.org/10.1016/j.eswa.2024.123429

13. Yanchenko, Murata, Holme. *Influence maximization on temporal networks: a review*. Applied Network Science, 2024.  
    https://doi.org/10.1007/s41109-024-00625-3

14. *Critical nodes identification in complex networks: a survey*. 2025.  
    https://www.oaepublish.com/articles/ces.2025.34

15. 张琦, 汪小帆. *复杂网络观点动力学分析与干预若干研究进展*. 复杂系统与复杂性科学, 2025.  
    https://fzkx.qdu.edu.cn/CN/abstract/abstract553.shtml

## D. 未知网络与自适应探索

16. Wilder et al. *Maximizing Influence in an Unknown Social Network*. AAAI 2018.  
    https://doi.org/10.1609/aaai.v32i1.11585

17. Kamarthi et al. *Influence maximization in unknown social networks: Learning Policies for Effective Graph Sampling*. AAMAS 2020.  
    https://arxiv.org/abs/1907.11625

18. Li et al. *CLAIM: curriculum learning policy for influence maximization in unknown social networks*. UAI 2021.  
    https://proceedings.mlr.press/v161/li21b.html

19. Chen et al. *Network Inference and Influence Maximization from Samples*. ICML 2021.  
    https://proceedings.mlr.press/v139/chen21q.html

## E. Network Dismantling / GNN / RL

20. Fan et al. *Finding key players in complex networks through deep reinforcement learning*. Nature Machine Intelligence, 2020.  
    https://doi.org/10.1038/s42256-020-0177-2

21. FINDER source code  
    https://github.com/FFrankyy/FINDER

22. Manchanda et al. *Learning Heuristics over Large Graphs via Deep Reinforcement Learning* (GCOMB). NeurIPS 2020.  
    https://arxiv.org/abs/1903.03332

23. GCOMB source code  
    https://github.com/idea-iitd/GCOMB

24. Yang et al. *A deep reinforcement learning framework for influence maximization problem on large-scale social networks* (MaDGNN). Scientific Reports, 2026.  
    https://doi.org/10.1038/s41598-026-41731-9

25. Zhu et al. *BiGDN: An End-To-End Influence Maximization Framework Based on Deep Reinforcement Learning and Graph Neural Networks*. Expert Systems with Applications, 2025.  
    https://github.com/zwl1985/BiGDN

## F. Opinion Optimization / Topology Intervention

26. *Opinion maximization in social networks via link recommendation*. Theoretical Computer Science, 2025.  
    https://doi.org/10.1016/j.tcs.2025.115090

27. *Leader selection for opinion optimization in social networks*. Theoretical Computer Science, 2026.  
    https://doi.org/10.1016/j.tcs.2026.115894

28. Peng et al. *Modeling and controlling competing opinions in social networks: a continuous density approach and topological intervention*. Social Network Analysis and Mining, 2026.  
    https://doi.org/10.1007/s13278-025-01548-2

## G. 工具与代码

29. NetworkX Documentation  
    https://networkx.org/documentation/stable/

30. NDlib – Network Diffusion Library  
    https://github.com/GiulioRossetti/ndlib

31. OPIM  
    https://github.com/tangj90/OPIM

32. MCPBenchmark  
    https://github.com/K-Coconut/MCPBenchmark

33. PIANO / DISCO  
    https://github.com/lihuixidian/PIANO

34. Parallel Influence Maximization  
    https://github.com/ucrparlay/Influence-Maximization
