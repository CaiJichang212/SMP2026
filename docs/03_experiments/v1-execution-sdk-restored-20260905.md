# V1 实验方案执行记录：SDK 恢复后复测（2026-09-05）

## 方案与预注册边界

本次严格执行 [V1 实验方案](v1-experiment-protocol.md) 的可用性前置检查，使用冻结的 [`v1-local-probes.json`](../../experiments/manifests/v1-local-probes.json) 清单（计划哈希 `7360deb234e10498`）创建 10 个**全新**官方调试 session。它是 P0 的恢复确认和 P1/P2 前的机制复核，不是隐藏 seed 上的策略排名。

探针包含：孤立和平节点上的 `prompt=1` 重复游说、`prompt=2` 单次游说，以及两节点负面桥上的对照、游说、切边、屏蔽和“屏蔽后游说”。每个 session 只通过官方公开 API 扫描、执行预注册动作，并由本地 runner 在终止后调用 `trigger_eval()`；提交策略没有运行或变更。

可比性规则事先冻结：必须有匹配的扫描快照、有限最终分、0 动作失败和 0 协议异常。缺失或异常记录不插补，不能同历史批次合并。

完整 V1 的后续门禁保持不变：P0 固定终态 20 session 的稳定性检查；P1 为 135 session 的 persona × prompt × 初值响应表；P2 为 420 session 的图留出结算器校准；只有前三层通过，才执行 P3 的 6 seed × 3 重复 × 3 变体（54 session）配对矩阵。

## 本次执行与结果

执行命令：

```bash
uv run python scripts/run_v1_local_probes.py \
  --manifest experiments/manifests/v1-local-probes.json \
  --result-dir experiments/raw/v1-local-probes-sdk-restored-20260905
```

| 指标 | 结果 |
| --- | ---: |
| 预注册 / 已运行 probe | 10 / 10 |
| 可比较 probe | 1 / 10 |
| 协议异常 | 9 `RemoteProtocolError` |
| 动作失败（唯一可比较 session） | 0 |
| 可比较终局分 | `isolated_p2_x1` = 25.0 |

9 个失败 session 都已成功通过 `/api/start_session` 建立会话，但紧接着的公开 `/api/get_budget` 返回 HTTP 异常；它们没有扫描快照或最终分。该诊断不包含响应正文或凭据。分析器因此给出 `insufficient_noncomparable_data`，且没有生成任何机制指标。

原始 JSONL 位于 Git 忽略目录 `experiments/raw/v1-local-probes-sdk-restored-20260905/7360deb234e10498/`；受版本控制的机器可读汇总和报告分别为 [`v1-local-mechanism-probes-sdk-restored-20260905.json`](../../experiments/reports/v1-local-mechanism-probes-sdk-restored-20260905.json) 与 [`v1-local-mechanism-probes-sdk-restored-20260905.md`](../../experiments/reports/v1-local-mechanism-probes-sdk-restored-20260905.md)。

## 对比、结论与建议

历史参考批次有 10/10 可比较 probe，而此前一次服务不可用时为 0/10。本次的 1/10 说明本机到服务的路径并非完全断开，但 90% 的协议失败表明服务尚未达到该方案要求的稳定可用性；不能把单个 25.0 分数或历史机制数据用于填补这 9 条记录。

因此 P0 未通过，P1、P2 和 P3 均未启动；不能重新估计游说衰减、不能校准结算器、不能比较 `v1_cmg` 和 `v0_deterministic`，更不能晋级或修改提交默认策略。`DEFAULT_CALIBRATION_PROFILE` 应继续保持未验证，`v1_cmg` 保持精确 V0 的 fail-closed 回退，V0 无 LLM 路径仍是唯一有正式矩阵支持的默认选择。

下一步应先向赛方确认“`start_session` 成功而 `get_budget` 返回 HTTP 错误”的服务端会话一致性/负载问题。不要通过重试掩盖或忽略异常来提高通过率。赛方确认稳定后，应使用相同 manifest 和新的 result namespace 再跑完整 10-probe 批次；只有 10/10 可比后，才按方案依次运行 P0 的 20 session、P1、P2 和 P3，并分别报告各层门禁结果。
