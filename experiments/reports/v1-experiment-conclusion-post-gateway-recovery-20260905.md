# V1 实验结论：网关恢复确认后复测（2026-09-05）

赛方确认网关扩容后，冻结的 10-probe manifest 已用 10 个全新官方 SDK session 再次执行。结果为 1/10 可比较；7 个 session 在 `/api/get_budget`、2 个在 `/api/scan` 出现 `RemoteProtocolError(... HTTPError)`。唯一完整的 `isolated_p1_x0` 终局分为 10.0，不能单独形成任何机制或策略结论。

相对历史有效批次的 10/10、此前 0/10 和首次恢复后 1/10，本次仍只有 1/10。这证明服务在该运行窗口仍不满足 V1 的 0 协议异常可用性门禁，而不是地址、鉴权、动作预算或 V1 参数的改变。

结论：不启动 P0、P1、P2、P3；不冻结 CMG 校准档案；不改变提交默认 V0 无 LLM 路径。建议赛方核查 UTC `12:18:41Z`–`12:18:47Z` 的网关和上游日志，并特别验证扩容后 session 存储在 worker 间共享或负载均衡保持会话黏性。稳定后，以新 session 和相同 manifest 重跑，不用重试掩盖异常。

完整方案、结果、对比与可复现命令见 [`v1-execution-post-gateway-recovery-20260905.md`](../../docs/03_experiments/v1-execution-post-gateway-recovery-20260905.md)。
