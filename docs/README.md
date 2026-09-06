# 文档导航

本目录记录赛题约束、架构决策、研究结论和可复现实验。提交代码必须以
`SMP_Starter_Kit/team_submission/` 的交付边界为准，文档和实验资产不得进入最终 ZIP。

- [`00_rules/`](00_rules/)：赛题、赛程和提交契约。
- [`01_architecture/`](01_architecture/)：研发架构、依赖兼容性与架构决策记录（ADR）。
- [`02_research/`](02_research/)：算法调研与策略路线。
- [`03_experiments/`](03_experiments/)：可提交的实验结论与版本说明。
  - [`V1 推荐方案`](03_experiments/v1-recommended-design.md)：本地机制探针、V0 问题分析与结算器驱动的响应感知 Greedy 设计。
  - [`V1.0 实验方案`](03_experiments/v1-experiment-protocol.md)：预注册的校准、门禁、配对主矩阵和当前 fail-closed 决策。
  - [`P0–P3 实验方案与本地结果（2026-09-06）`](03_experiments/p0-p3-experiment-plan-and-local-results-20260906.md)：三重复配对矩阵、此次本地回归与远端可用性门禁结论。
  - [`V1 校准与结构门禁结果（2026-09-06）`](../experiments/reports/v1-calibration-20260906.md)：555 个预注册会话的响应/结算数据、留出误差与 fail-closed 决策。
  - [`P2.1 结算器扩展与重拟合（2026-09-06）`](03_experiments/p2-settlement-refit-v2-20260906.md)：机制辨识、事后重分析及其验证边界。
  - [`P2.2 拓扑留出验证（2026-09-06）`](03_experiments/p2-topology-holdout-v2-20260906.md)：`component_degree_plus_one` 的独立结算器门禁结果。
- [`04_plan/`](04_plan/)：版本实施计划与验收口径。
- [`runbooks/`](runbooks/)：本地开发、远程沙盒和提交操作手册。
