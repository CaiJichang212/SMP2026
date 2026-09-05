# V1 实验结论：SDK 恢复后复测（2026-09-05）

冻结的 10-probe 本地机制清单已通过官方调试服务用新 session 实际执行，但仅 1/10 可比较。其余 9 个 session 均在 `/api/start_session` 成功后，于公开 `/api/get_budget` 收到 HTTP 异常并被记录为 `RemoteProtocolError`。分析状态为 `insufficient_noncomparable_data`；没有用历史分数或唯一成功样本补齐。

| 批次 | 可比较 / 计划 | 可作 V1 机制结论 |
| --- | ---: | --- |
| 历史有效参考 | 10 / 10 | 可以，限于局部小图 |
| 此前服务不可用复跑 | 0 / 10 | 不可以 |
| SDK 恢复后本次复测 | 1 / 10 | 不可以 |

结论：服务尚不满足 V1 P0 的“完整执行、0 协议异常”门禁。不得启动 P1 响应校准、P2 结算器校准或 P3 的 V1/V0 配对主矩阵；不得冻结 CMG 档案或切换提交默认策略。保持 V0 的无 LLM 默认与 V1 fail-closed 回退。

建议先由赛方确认已创建 session 在 `/api/get_budget` 的服务端可用性，再以相同 manifest 创建一批全新 session 重跑。完整设计、实际命令、可比性规则和后续阶段见 [`v1-execution-sdk-restored-20260905.md`](../../docs/03_experiments/v1-execution-sdk-restored-20260905.md)。本批分析详见 [`v1-local-mechanism-probes-sdk-restored-20260905.md`](v1-local-mechanism-probes-sdk-restored-20260905.md)。
