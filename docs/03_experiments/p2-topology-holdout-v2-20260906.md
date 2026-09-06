# P2.2 结算器拓扑留出验证（2026-09-06）

## 结论

P2.2 通过了预注册的**结算器**门禁。候选 `component_degree_plus_one` 在完全未参与调参和模型选择的 gate 拓扑上得到 Spearman `1.0000`、图级归一化 MAE 中位数 `0.00553%`；`path7`、`star7`、`bow_tie` 的族均值误差分别为 `0.00877%`、`0.00289%`、`0.01032%`，均低于 `5%`。

这与 P2.1 仅在已观察到的路径/三角形/星形上发现候选不同：P2.2 的 calibration、selection、gate 使用彼此不相交的图族，因此没有把意见布局的变化误当作拓扑泛化。

但本结果**不冻结** `DEFAULT_CALIBRATION_PROFILE`，也不启用 B2–B5：当前运行时仍缺少经审阅的、由公开扫描图实时导出的 `target_influence` 档案，且 `structure_gate_passed=false`。结算器可靠不等于结构规划可靠；在独立的 B3/B4 配对策略收益门禁通过前，提交默认继续是无 LLM 的 B1。

机器可读结果在 [`p2-topology-holdout-v2-20260906.json`](../../experiments/reports/p2-topology-holdout-v2-20260906.json)，原始服务响应位于忽略目录 `experiments/raw/p2-topology-holdout-v2-20260906/`。

## 预注册设计

候选公式在每个连通分量独立计算：

$$
\widehat F(G,w)=\sum_{C\in\mathcal C(G)}
\frac{|C|}{\sum_{i\in C}(d_i+1)}
\sum_{i\in C}(d_i+1)w_i.
$$

P2.1 完成后、P2.2 数据采集前，将其加入冻结候选族，并固定如下拓扑 split：

| split | 图族 | 用途 |
| --- | --- | --- |
| calibration | `path4`、`star4`、`square` | 各候选族仅可在这里拟合参数 |
| selection | `path6`、`star6`、`triangle_tail` | 仅在已拟合候选中选择模型 |
| gate | `path7`、`star7`、`bow_tie` | 最终一次泛化验证，不参与任何选择 |

每个图族交叉三种意见布局（`positive`、`mixed`、`negative_bridge`）、四种单动作（`control`、`comm`、`cut`、`shield`）和五个 fresh session，因而共有 `9 × 3 × 4 × 5 = 540` 个 P2.2 结算会话。每个动作目标、边和 prompt 均由清单显式给定；runner 先扫描全部节点，再执行最多一个公开动作，并只在本地实验 runner 调用 `trigger_eval()`。

可比性规则：扫描快照匹配、初始预算匹配、零动作失败、零协议异常和有限终局分。缺失或失败不插补。分析时只复用已完成 P1 的 `405` 条响应行；不复用历史结算行。

## 本地执行结果

运行清单为 [`p2-topology-holdout-v2.json`](../../experiments/manifests/p2-topology-holdout-v2.json)，计划哈希为 `7fd0cb7ab5b1d652`。因交互通道的单次时限，runner 在本机持久会话中以同一 `--resume` 清单顺序续跑；这不改变随机化、session 身份或动作序列。

| 检查 | 结果 |
| --- | ---: |
| 计划结算会话 | 540 |
| 完成且可比 | 540 / 540 |
| 协议失败 | 0 |
| 动作失败 | 0 |
| P1 复用响应行 | 405 |
| topology holdout | 通过（3 组图族两两不相交） |
| gate Spearman | 1.0000 |
| gate 归一化 MAE 中位数 | 0.00553% |
| 最差 gate 图族均值 MAE | 0.01032% (`bow_tie`) |

门禁使用原 5% 上限，未作放宽。其余候选在 calibration / selection 上比较后，`component_degree_plus_one` 被固定为选择模型；gate 分数未参与该选择。

## 对比与解释

| 结算器验证 | gate Spearman | gate MAE 中位数 | 拓扑留出 | 判定 |
| --- | ---: | ---: | --- | --- |
| 旧 `degree`（P2） | 0.9543 | 10.24% | 否 | 拒绝 |
| P2.1 事后重拟合回放 | 1.0000 | 0.00182% | 否 | 仅形成假设 |
| P2.2 `component_degree_plus_one` | 1.0000 | 0.00553% | 是 | 结算器通过 |

P2.2 的微小非零误差与服务端终局分保留两位小数一致；它并不表示“官方机制已被完全证明”。结论只覆盖本清单的自定义拓扑、意见范围、一个动作深度和公开 API 语义。隐藏 50/100 节点种子的策略收益仍需单独验证。

## 后续建议

1. 将该候选作为离线结构反事实的已验证结算器，但保持 runtime profile 未冻结；首先构造不含节点 ID 常数的实时 `target_influence`，只由扫描到的连通分量、度数与意见计算。
2. 单独执行 P2.3：在新的 24 个 50/100 节点 seed block 上比较 `B3 - B1`、`B4 - B1` 以及 `B4 - B3`，每 block 三次 fresh session；保持 bootstrap 95% CI 下界大于零、任一拓扑族均值不为负、零新增失败。
3. 即使 P2.3 通过，也先保留无 LLM 的结构版本；P3 的自适应探索与 LLM 消融必须在 P2 的结构资格通过后独立运行。

## 验证命令

```bash
uv run python -m unittest -v tests.unit.test_v1_calibration tests.unit.test_v1_calibration_runner
uv run python scripts/run_v1_calibration.py \
  --manifest experiments/manifests/p2-topology-holdout-v2.json \
  --phase settlement --dry-run
uv run python scripts/analyze_p2_topology_holdout.py \
  --manifest experiments/manifests/p2-topology-holdout-v2.json \
  --p1-results experiments/raw/v1-calibration-20260906/5dca23011f908f59/calibration.jsonl \
  --p2-results experiments/raw/p2-topology-holdout-v2-20260906/7fd0cb7ab5b1d652/calibration.jsonl \
  --report experiments/reports/p2-topology-holdout-v2-20260906.json
```
