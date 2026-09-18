# 方法来源与适用边界（2026-09-18在线获取）

| 来源 | 可借鉴的方法 | 本赛题限制 / 实现决定 |
|---|---|---|
| DeGroot (1974), [Reaching a Consensus](https://doi.org/10.1080/01621459.1974.10480137) | 线性意见更新、拓扑与长期影响权重 | 官方没有公开转移矩阵；仅用观测度数作为排序启发，不能宣称精确稳态预测 |
| Kempe, Kleinberg, Tardos (2003), [Maximizing the Spread of Influence through a Social Network](https://www.cs.cornell.edu/home/kleinber/kdd03-inf.pdf) | 在预算下按边际收益挑选节点 | 本赛题是连续正负意见+可删图，不是IC/LT扩散；不套用1-1/e保证 |
| Golovin & Krause, [Adaptive Submodularity](https://arxiv.org/abs/1003.3967) | 观测反馈后重规划，比较单位成本的预期边际收益 | 未证明官方目标满足自适应子模性；采用流程思想，不声称近似界 |
| Yao et al., [ReAct](https://arxiv.org/abs/2210.03629) | 推理、动作、环境反馈循环 | LLM从公开合法候选中选择；每个批次有明确上限，负反馈即取消旧计划 |
| [rgCASS/casevo](https://github.com/rgCASS/casevo) | ModelBase、AgentBase、Prompt与记忆工厂 | 本机新版需Python>=3.11；线上是旧agent_mesa，需分别验证 |
| [raoneng26/SMP2026](https://github.com/raoneng26/SMP2026) | 环境API、提交目录与入口示例 | README仍有旧限制，优先遵守本项目赛题/补充信息的120/250限制 |

检索方式：由赛题关键词“共识、影响力最大化、部分可观测决策、LLM动作反馈”定向检索论文与官方仓库。
来源原文保存在spec/raw，访问均HTTP 200。Crossref核验DeGroot题名；arXiv核验摘要；Cornell原始论文PDF下载成功。
一个候选arXiv编号1511.00863核验后发现是量子计算论文，已排除，不作为证据。
没有复制论文或其他项目策略源码，也没有安装第三方策略包。历史项目的分数不纳入当前对比。
