# 历史提交 ZIP 本地分数与官方分数对比

后续更新：用户已授权并完成四个 LLM 包的 24 次真实模型会话，共 1,018 次模型调用。真实终分与本文回退参照相同，完整十包最终对比见 [真实模型复测报告](archive-real-llm-analysis-20260912.md)。本文保留离线阶段的测试模式与星号说明，不能将其原始数据改称真实调用数据。

## 范围与有效性

- 数据源：`archive-score-comparison-offline-20260912.json` 和 `archive-score-comparison-fallback-20260912.json`。
- 对 6 个原始配置中实际关闭 LLM 的 ZIP，各运行 6 个固定 50 节点、预算 100 的种子，共 36 个会话。
- 36/36 会话状态为 `completed`，均为 `offline_only=true`；LLM 调用、LLM 传输错误和动作失败均为 0。
- 对另外 4 个原生会请求 LLM 的 ZIP，使用 `--offline-only --allow-offline-fallback` 各运行相同 6 个种子，共 24 个会话。24/24 会话完成、动作失败为 0，但这是强制 LLM 失败后的确定性回退测试，没有调用网络或真实 LLM。
- 每个 ZIP 在每个种子上只有 1 次运行。由于这些策略和本地环境在该模式下是确定性的，这足以复现所列种子，但不足以代表官方隐藏种子分布。
- 标记为 `*` 的 4 个结果只代表回退路径，不能解释为这些 ZIP 使用真实 LLM 时的本地分数。

## 汇总结果

| ZIP | 测试模式 | 本地六种子均值 | 本地最小值 | 本地最大值 | 官方分数 |
|---|---|---:|---:|---:|---:|
| `starnet-public-greedy-v9-optimized-20260908.zip` | 原配置 LLM-off | 547.9557 | 177.9300 | 907.9252 | 761.9467 |
| `starnet-public-greedy-llm-candidate-20260912.zip`* | 强制 LLM 失败回退 | 547.9557 | 177.9300 | 907.9252 | 761.9467 |
| `starnet-public-greedy-llm-audited-20260912.zip`* | 强制 LLM 失败回退 | 547.9557 | 177.9300 | 907.9252 | 未评测 |
| `starnet-public-greedy-experimental-20260908.zip` | 原配置 LLM-off | 538.8291 | 177.9300 | 907.9252 | 765.8400 |
| `starnet-public-greedy-risk-aware-20260908.zip` | 原配置 LLM-off | 526.8516 | 170.8330 | 907.9252 | 731.4633 |
| `starnet-b1-risk-aware-source-20260908.zip` | 原配置 LLM-off | 486.6322 | 170.8330 | 907.9252 | 550.9400 |
| `starnet-b1-v4-default-20260908.zip` | 原配置 LLM-off | 486.6322 | 170.8330 | 907.9252 | 550.9400 |
| `v1-cmg.zip` | 原配置 LLM-off | 486.3704 | 105.7958 | 930.4258 | 655.3267 |
| `v1-experiment-tools.zip`* | 强制 LLM 失败回退 | 486.3704 | 105.7958 | 930.4258 | 655.3267 |
| `v0-baseline-0904-1.zip`* | 强制 LLM 失败回退 | 486.3704 | 105.7958 | 930.4258 | 655.3267 |

强制回退批次中，`candidate` 和 `audited` 各记录 491 次强制 LLM 失败，`v1-experiment-tools` 和 `v0-baseline` 各记录 18 次；实际 LLM 调用和传输错误均为 0。这里的失败计数是测试注入量，不是运行故障。

只对 6 个原配置无需 LLM 的 ZIP 计算相关性：本地与官方分数的 Pearson 相关系数为 **0.9141**，平均排名的 Spearman 相关系数为 **0.7647**。排除双方共同的 B1 并列后，14 个可比较策略对中 11 对方向一致、3 对不一致，Kendall tau-b 为 **0.5714**。强制回退结果不参与相关性计算，因为其执行条件与对应官方 LLM 提交不同。

因此，本地矩阵对策略档位有一定辨别力：三个 `public_greedy` 包在本地和官方都高于两个 B1 包；但它不适合用几分的本地差距断言官方名次。主要不一致为：

1. 本地 `v9` 比 `experimental` 高 9.1266，官方则 `experimental` 比 `v9` 高 3.8933。
2. 本地 `v1-cmg` 比两个 B1 低 0.2618，官方则高 104.3867。

第二项尤其说明六种子等权平均没有覆盖官方隐藏场景权重。`v1-cmg` 在 `ba_negative_hubs` 和 `ws_peace_majority` 上位居第一，但在另外四类场景表现偏低。

## 同源码异配置对

`starnet-public-greedy-risk-aware-20260908.zip` 与 `starnet-b1-risk-aware-source-20260908.zip` 的 `starnet_model.py` 完全相同，只有配置触发的策略不同。

| 种子族 | public_greedy - B1 |
|---|---:|
| `er_balanced` | +26.6769 |
| `ba_negative_hubs` | +146.2807 |
| `ws_peace_majority` | 0.0000 |
| `sbm_negative_bridges` | -0.7663 |
| `sbm_violent_cluster` | +69.1255 |
| `three_sparse_components` | 0.0000 |
| **六种子均值** | **+40.2195** |

该配置在 3 个种子上胜、2 个持平、1 个小幅负向。官方差值为 **+180.5233**，方向一致，幅度明显大于本地矩阵。

`starnet-public-greedy-experimental-20260908.zip` 与 `starnet-b1-v4-default-20260908.zip` 也具有完全相同的 `starnet_model.py`。

| 种子族 | public_greedy - B1 |
|---|---:|
| `er_balanced` | +15.5814 |
| `ba_negative_hubs` | +167.9052 |
| `ws_peace_majority` | 0.0000 |
| `sbm_negative_bridges` | +15.0675 |
| `sbm_violent_cluster` | +107.5307 |
| `three_sparse_components` | +7.0970 |
| **六种子均值** | **+52.1970** |

该配置在 5 个种子上胜、1 个持平。官方差值为 **+214.9000**，同样方向一致、幅度大于本地矩阵。

两个不同代码版本的 B1 包在所有六个种子上分数和动作序列哈希完全一致。这说明这些场景下，两版代码实际走了同一条 B1 行为路径，也为历史 ZIP runner 的忠实性提供了交叉校验。

## 结论与使用边界

本地结果支持 `public_greedy` 相对 B1 的提升是真实策略效果，而非归档代码差异造成。`v9` 在本地六类场景的平均值最高，但官方结果仍以 `experimental` 为已提交最高分，因此不应依据当前本地均值改写官方最优结论。

单个本地种子超过 900 只表示该场景的绝对分高，不能视为达成排行榜平均分大于 900。后续优化应扩大独立种子数量，并按官方结果重新校准场景分布；真实 LLM 四包应在获准后单列测试，不能与本离线表混合或声称已经得到真实 LLM 本地分数。
