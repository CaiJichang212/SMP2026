# Public-greedy 结构实验候选（2026-09-08）

## 策略边界

`PUBLIC_GREEDY` 是显式实验模式，不会被默认 `config.json` 选中。它不使用 LLM，
每次扫描完成后枚举公开图上的合法 `communicate`、`cut`、`shield`，使用已经通过
拓扑留出的 `component_degree_plus_one` 结算公式计算一步终局增益，只保留严格正增益，
执行一个动作后重新扫描决策。默认 B1 的 fail-closed 行为不变。

该候选仍不是结构策略正式门禁通过的证明；它用于获得新的端到端实验分数，不能替代
独立的结构收益验证。

## 本地 smoke matrix

使用六个生成的 50 节点拓扑各一次、同一自定义公开 API 语义和本地结算器：

| 拓扑 | B1 | public-greedy | 差值 |
| --- | ---: | ---: | ---: |
| `er_balanced` | 757.308 | 772.889 | +15.581 |
| `ba_negative_hubs` | 356.758 | 524.663 | +167.905 |
| `ws_peace_majority` | 907.925 | 907.925 | 0.000 |
| `sbm_negative_bridges` | 545.521 | 560.588 | +15.068 |
| `sbm_violent_cluster` | 181.449 | 288.979 | +107.531 |
| `three_sparse_components` | 170.833 | 177.929 | +7.096 |

该矩阵是本地模型筛选证据，不是隐藏排行榜成绩；正式结果仍以平台提交分为准。

在官方沙盒公开 API 的四节点自定义 seed 上，B1 得分为 `87.38`，
`PUBLIC_GREEDY` 得分为 `124.61`；两次均零动作失败。该结果只用于协议和方向性
核验，不能外推到隐藏 seed。

## 交付

- 安全默认：`starnet-b1-v4-default-20260908.zip`
- 实验候选：`starnet-public-greedy-experimental-20260908.zip`

两个 ZIP 均只包含规定的 `config.json`、`prompt/` 和 `starnet_model.py`。
