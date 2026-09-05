# 文档导航

本目录记录赛题约束、架构决策、研究结论和可复现实验。提交代码必须以
`SMP_Starter_Kit/team_submission/` 的交付边界为准，文档和实验资产不得进入最终 ZIP。

- [`00_rules/`](00_rules/)：赛题、赛程和提交契约。
- [`01_architecture/`](01_architecture/)：研发架构、依赖兼容性与架构决策记录（ADR）。
- [`02_research/`](02_research/)：算法调研与策略路线。
- [`03_experiments/`](03_experiments/)：可提交的实验结论与版本说明。
  - [`V1 推荐方案`](03_experiments/v1-recommended-design.md)：本地机制探针、V0 问题分析与结算器驱动的响应感知 Greedy 设计。
  - [`V1.0 实验方案`](03_experiments/v1-experiment-protocol.md)：预注册的校准、门禁、配对主矩阵和当前 fail-closed 决策。
  - [`SDK 恢复后复测`](03_experiments/v1-execution-sdk-restored-20260905.md)：本次新 session 的执行、无效数据判定与后续建议。
  - [`网关恢复确认后复测`](03_experiments/v1-execution-post-gateway-recovery-20260905.md)：最新独立 session 的结果、跨批次比较与服务端排查建议。
- [`04_plan/`](04_plan/)：版本实施计划与验收口径。
- [`runbooks/`](runbooks/)：本地开发、远程沙盒和提交操作手册。
