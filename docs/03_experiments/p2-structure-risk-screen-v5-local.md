# P2.3 风险门本地独立 seed block（2026-09-08）

## 目的与边界

上一轮 B3/B4 的总体均值虽为正，但在 `WS peace majority` 族为负。此次先冻结一
个新的、与旧六族不同的拓扑 block，测试公开风险门是否能在强正向网络中失效关闭
结构动作，同时保留对明显负向暴力簇的屏蔽收益。

这是本地筛选，不是隐藏榜单成绩，也没有把本地的 `r` 暴露给控制器。模拟环境内部
使用 `r` 产生 `communicate` 的公开 `new_w`；策略只读扫描结果和动作返回。结算器仍
使用已通过 P2.2 的 `component_degree_plus_one` 闭式模型。

## 预注册规则

独立 block 包含 `grid_lattice`、`cycle_chords`、`two_block_bridge`、`tree_broom`
四个新拓扑族，50/100 节点各三次重复；每个 `(family, node_count, repetition)`
同时运行 B1 和风险门 `public_greedy`，按同一 seed 配对。

风险门固定为：至少有 4 个不同节点的公开首轮响应后才考虑结构动作；结构 ROI 必须
达到当前最佳游说 ROI 的 1.25 倍；和平/非负节点占比达到 0.85 且正向质量至少是
暴力负向质量 2 倍时关闭所有结构动作；其他情形也只允许负向暴力节点屏蔽，或负向
暴力端到非暴力/非负端的桥切断。所有动作仍逐次经过预算、节点、边和 quota 校验。

门禁要求族级均值差不为负、配对 bootstrap 下界不低于 0、零动作失败，并单独报告
结构动作率。这个本地门禁不授权修改 `DEFAULT_POLICY_CONFIG`，也不授权远端提交。

## 本地结果

运行命令：

```bash
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_local_policy_matrix.py \
  --block independent --node-counts 50 100 --repetitions 3 \
  --output experiments/reports/p2-structure-risk-screen-v5-independent-local.json
```

当前已完成的独立结果分别记录在：

- `experiments/reports/p2-structure-risk-screen-v5-independent-50.json`
- `experiments/reports/p2-structure-risk-screen-v5-independent-100.json`

| 拓扑族 | 规模 | B1 均值 | 风险门均值 | Δ | 最小重复 Δ | 结构动作率 | 失败 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cycle_chords` | 50 | 551.27 | 551.27 | 0.00 | 0.00 | 0.00 | 0 |
| `grid_lattice` | 50 | 1128.21 | 1128.21 | 0.00 | 0.00 | 0.00 | 0 |
| `tree_broom` | 50 | 386.96 | 406.19 | +19.23 | 0.00 | 0.67 | 0 |
| `two_block_bridge` | 50 | 181.47 | 409.81 | +228.34 | +167.09 | 8.33 | 0 |
| `cycle_chords` | 100 | 1229.91 | 1236.08 | +6.18 | 0.00 | 0.33 | 0 |
| `grid_lattice` | 100 | 2185.89 | 2185.89 | 0.00 | 0.00 | 0.00 | 0 |
| `tree_broom` | 100 | 645.18 | 681.17 | +35.99 | +32.18 | 2.33 | 0 |
| `two_block_bridge` | 100 | 442.70 | 925.88 | +483.18 | +473.88 | 16.67 | 0 |

50 节点四个 cell 的均值为 B1 `561.98`、风险门 `623.87`；100 节点四个 cell 的
均值为 B1 `1125.92`、风险门 `1257.25`。跨全部 8 个 cell 的总体均值为 B1
`843.95`、风险门 `940.56`，平均 Δ `+96.61`；四个 100 节点 cell 中两个风险门
终局均值超过 900（`grid_lattice` `2185.89`、`two_block_bridge` `925.88`）。
所有 48 个 session 均零动作失败。将每个拓扑族在 50/100 节点上的均值作为配对单位，
做 10,000 次 bootstrap，平均 Δ 的 95% CI 为 `[1.54, 267.59]`；四个族均值均非负，
结构动作率总体大于 0，且没有动作失败。因此该风险门通过了本地预注册筛选门；这
仍不等于远端上线资格或隐藏榜单证明。

## 结论与下一步

风险门在新拓扑上成功保持正向网络的结构失效关闭，并在双块负向桥上保留显著收益；
它满足本地的族级非负、bootstrap 下界和零失败条件，可进入下一步远端独立验证，但
不能仅凭本地结果冻结结构档案。
`PUBLIC_GREEDY` 继续保持显式实验模式，提交默认仍是无 LLM B1。

若获得明确的远端实验授权，下一步应使用同一 manifest 的 fresh session 运行 B1 与
风险门候选，先核对扫描/预算/终态协议，再报告真实 bootstrap 与结构动作率；P3 的
ScenarioProfile、B5 和 LLM 消融仍保持关闭。榜单 `>900` 只能由平台提交结果证明，
不能由本地模拟器或单一自定义 seed 外推。
