# P3 公开首次响应校准筛选（2026-09-12）

## 假设与方法

首轮游说成功后的 `new_w - old_w` 是公开事实。实验比较三种只使用该事实的游说预算滚动分配：

- `fixed`：未试节点恒用 12.75 的总体首轮先验；已试节点只用自身公开首轮响应，并按 `1, 1/2, 1/4` 衰减。
- `pooled`：未试节点用所有公开首轮响应的收缩均值。
- `persona_shrunk`：未试节点用同 persona 的收缩均值；无该 persona 记录时回退固定先验。

每次动作后重新计算所有合法 `comm` 槽的公开组件影响系数与 ROI。实验扫描全部节点，只调用 `scan_node`、`communicate`、`get_remaining_budget` 和 `evaluate`；本地 seed 的 `r` 仅由环境在 `communicate` 内部使用，策略模块没有接收或读取该字段。

筛选规则预注册为：一个校准变体必须在两个数据块的每个拓扑族平均配对差都严格为正，且零动作失败，才允许进入提交候选。

## 25 次重复的配对结果（50 节点）

| 数据块 | 变体 | 相对 fixed 平均分差 | 最低单 seed 分差 | 族均值全部为正 | 失败数 |
| --- | --- | ---: | ---: | --- | ---: |
| 独立拓扑（4 族，100 对） | pooled | -0.105 | -17.304 | 否 | 0 |
| 独立拓扑（4 族，100 对） | persona_shrunk | -0.649 | -44.152 | 否 | 0 |
| 既有拓扑（6 族，150 对） | pooled | -0.318 | -24.630 | 否 | 0 |
| 既有拓扑（6 族，150 对） | persona_shrunk | -1.382 | -42.366 | 否 | 0 |

原始可复现结果：[独立块 JSON](p3-response-ablation-independent-r25-20260912.json) 与 [既有块 JSON](p3-response-ablation-existing-r25-20260912.json)。运行命令为：

```bash
uv run python scripts/run_response_ablation.py --block independent --node-count 50 --repetitions 25 --output experiments/reports/p3-response-ablation-independent-r25-20260912.json
uv run python scripts/run_response_ablation.py --block existing --node-count 50 --repetitions 25 --output experiments/reports/p3-response-ablation-existing-r25-20260912.json
```

## 结论

不晋级。公开首轮响应对同一节点后续槽位有价值，当前 `fixed` 方法已经利用该信息；把它迁移到别的未试节点没有在独立或既有块上产生稳定收益。尤其 persona 收缩在局部拓扑上出现较大负尾部，不能作为冲击 >900 的可靠改动。

后续应把实验容量投向可改变候选集合或终局目标的公开机制，而不是继续调整游说响应先验。
