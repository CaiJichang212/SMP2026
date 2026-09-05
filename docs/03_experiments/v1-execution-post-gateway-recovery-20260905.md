# V1 实验方案执行记录：网关恢复确认后复测（2026-09-05）

## 冻结方案

本次不在失败后调整算法、阈值、动作或样本来追逐分数，而是严格沿用 [V1.0 实验方案](v1-experiment-protocol.md) 与冻结的 [`v1-local-probes.json`](../../experiments/manifests/v1-local-probes.json)（计划哈希 `7360deb234e10498`）。这是进入 P0 前必须满足的服务可用性和机制复核检查：10 个预注册 probe 各用一个新的官方 SDK session，且所有 scan、预注册动作和 `trigger_eval()` 都只调用公开 API。

可比性判据在运行前不变：匹配扫描快照、有限最终分、0 动作失败、0 协议异常。仅全体 10/10 可比较才可启动 P0 的 20 个固定终态稳定性 session；随后才是 P1 的 135-session 响应表、P2 的 420-session 图留出结算器校准和 P3 的 54-session V1/V0 配对矩阵。异常和缺失记录不得补齐、重试后混入或用于策略结论。

## 实际运行结果

赛方确认 Gunicorn 网关已扩容加固、地址和鉴权不变后，使用新结果命名空间运行：

```bash
uv run python scripts/run_v1_local_probes.py \
  --manifest experiments/manifests/v1-local-probes.json \
  --result-dir experiments/raw/v1-local-probes-post-gateway-recovery-20260905
```

| 指标 | 结果 |
| --- | ---: |
| 新 session / 预注册 probe | 10 / 10 |
| 可比较 probe | 1 / 10 |
| 可比较结果 | `isolated_p1_x0`，最终分 10.0 |
| 协议异常 | 9 `RemoteProtocolError` |
| `/api/get_budget` HTTP 异常 | 7 |
| `/api/scan` HTTP 异常 | 2 |
| 可比较 session 的动作失败 | 0 |

SDK 的安全包装仅记录 `HTTPError`，不记录 HTTP 正文、凭据或状态码；因此该批数据可以证实协议不稳定，却不能仅凭客户端记录断言 7 个预算请求和 2 个扫描请求的服务器端具体状态码。机器可读汇总为 [`v1-local-mechanism-probes-post-gateway-recovery-20260905.json`](../../experiments/reports/v1-local-mechanism-probes-post-gateway-recovery-20260905.json)，可审阅报告为 [`v1-local-mechanism-probes-post-gateway-recovery-20260905.md`](../../experiments/reports/v1-local-mechanism-probes-post-gateway-recovery-20260905.md)，原始 JSONL 位于 Git 忽略的 `experiments/raw/` 下。

## 对比分析、结论与建议

| 独立批次 | 可比较 / 计划 | 主要异常端点 | 是否可进入下一阶段 |
| --- | ---: | --- | --- |
| 历史有效参考 | 10 / 10 | 无 | 仅可作历史局部机制参考 |
| 服务不可用时复跑 | 0 / 10 | `/api/start_session` | 否 |
| 首次“恢复后”复测 | 1 / 10 | `/api/get_budget`（9） | 否 |
| 本次网关恢复确认后复测 | 1 / 10 | `/api/get_budget`（7）、`/api/scan`（2） | 否 |

这批 session 是逐个循环执行的，而非客户端主动并发；因此 9/10 的失败不能归因于本实验向服务瞬时并发发送 10 个请求。它说明服务尽管偶尔可完成整局，仍没有满足 P0 所要求的稳定可用性。没有任何游说、屏蔽或切边效果的完整样本量，故不产生新的机制估计；更不能比较 `v1_cmg` 和 `v0_deterministic`。

结论是 **P0 前置可用性检查未通过**。保持 `DEFAULT_CALIBRATION_PROFILE` 未验证，`v1_cmg` 继续精确回退到 V0，提交默认策略和无 LLM 配置不变。不要以客户端自动重试掩盖 P0 失败；赛方应先根据 UTC `2026-09-05T12:18:41Z` 至 `12:18:47Z` 的服务日志提供上述端点的 HTTP 状态码与网关/上游原因，并确认多 worker 部署中的 session 共享存储或会话黏性。确认稳定后，再以相同 manifest 和另一个新 namespace 重跑完整 10-probe 批次。
