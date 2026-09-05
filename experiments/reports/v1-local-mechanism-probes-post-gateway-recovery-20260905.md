# V1 本地机制探针结果

数据：`experiments/raw/v1-local-probes-post-gateway-recovery-20260905/7360deb234e10498/results.jsonl`；计划哈希：`7360deb234e10498`。

| 指标 | 值 |
| --- | ---: |
| 预注册 probe | 10 |
| 已观测 probe | 10 |
| 可比较 probe | 1 |

## 结果无效（不作机制结论）

协议异常：

- `RemoteProtocolError`：9

安全诊断（不含响应正文或凭据）：

- `remote sandbox protocol error at /api/get_budget: request failed (HTTPError)`：7
- `remote sandbox protocol error at /api/scan: request failed (HTTPError)`：2

本批记录没有满足预注册可比性条件的完整数据。不得用空值、异常响应或历史分数补齐；应在官方调试服务恢复后，以相同 manifest 创建新 session 复跑。
