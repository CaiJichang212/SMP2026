# P0–P3 实验方案与本地运行结果（2026-09-06）

## 结论

P0–P3 的代码路径和安全退化在本地通过，且通过官方 `api_client.py` 的 P0 固定终态门禁已取得 `20/20` 可比较的远端结果、四种终态均零分数波动。此前的 `RemoteProtocolError` 来自受限网络路径，而非 API 载荷或端点格式。原始 P1/P2 校准的 `555/555` 个会话中，旧 `degree` 模型的图级归一化 MAE 为 `10.24%`，未达到预注册的 `≤5%` 门禁；随后完成的 P2.2 拓扑留出验证以 `540/540` 可比会话证明 `component_degree_plus_one` 的结算器门禁通过（Spearman `1.0000`、归一化 MAE 中位数 `0.00553%`）。这只取得离线结算器资格，尚未取得结构策略资格。因此当前提交继续使用无 LLM 的 `B1` 游说基线；`B2`、`B3`、`B4` 和 `B5` 仍不可晋级，也不能以本地 mock/单元测试或微图结算器误差宣称优于 B1。

机器可读运行数据见 [`p0-p3-local-validation-20260906.json`](../../experiments/reports/p0-p3-local-validation-20260906.json)，远端主实验的预注册清单见 [`p0-p3-paired-matrix-v2.json`](../../experiments/manifests/p0-p3-paired-matrix-v2.json)。原始远端响应位于被忽略的 `experiments/raw/`，不进入提交包。

## 问题、比较与可证伪假设

实验以同一完整生成 seed、同一远端重复编号为配对单位，只比较最终 `trigger_eval()` 返回的分数；提交代码不调用该方法。每条记录须同时满足扫描快照匹配、预算正确、零动作失败、零协议异常和有限终局分数，才进入统计。失败与缺失绝不插补。

| 阶段 | 主比较 | 零假设 | 可晋级条件 |
| --- | --- | --- | --- |
| P0 | 固定终态的 5 次新会话 | 服务/结算不稳定或不可用 | 20/20 可比；每个动作序列扫描/终态哈希一致，分数相对跨度 ≤2% |
| P1 | `B1 - scan_only` | 全扫描后的保守游说没有正向增益 | 只作为已实现基线和安全锚；不以本轮 P2/P3 实验重新挑选阈值 |
| P2a | `B3 - B1` | 单一结构动作无增益 | 完成校准与结构门禁；按 24 个 seed block 的配对 bootstrap 95% CI 下界 >0，任一拓扑族的均值不为负，且无新增失败 |
| P2b | `B4 - B1` | 深度 2、宽度 4 的结构束搜索无增益 | 同 P2a；还须报告 B4 相对 B3 的配对差，不能只报两者各自对 B1 的点估计 |
| P3a | `B5 - B4` | 自适应探索无增益 | P2 通过、独立情景门禁通过，且相同的 bootstrap/最差族/零新增失败要求成立 |
| P3b | `B5-step-LLM - B5`、`B5-event-LLM - B5` | LLM 调度没有增益或不值得其调用成本 | P3a 通过；两个 LLM 变体独立检验，额外报告 LLM 调用数、P95 时间和失败数 |

这里的 P2/P3 晋级条件比“平均分更高”严格：它要求成对、跨拓扑、跨 50/100 节点规模的一致改进。若任一门禁失败，后续阶段的分数不作策略结论。

## 已冻结的远端实验设计

清单使用六个拓扑族：`ER balanced`、`BA negative hubs`、`WS peace majority`、`SBM negative bridges`、`SBM violent cluster`、`three sparse components`；每族包含 50/100 节点和两个独立生成 seed，共 24 个 seed block。它刻意覆盖 P2 的高风险反例（负中心、正向桥、跨社区负桥、多个稀疏分量）和 P3 的探索困难度，而不是只在有利的 BA 图上筛选结果。

远端执行顺序由固定随机种子 `20260906` 交错；每个 seed block 的八个变体均运行三次新会话：`scan_only`、`b1_persuasion`、`b2_influence`、`b3_single_structure`、`b4_beam_structure`、`b5_adaptive`、`b5_step_llm`、`b5_event_llm`。因此是 `20` 个 P0 会话加 `24 × 8 × 3 = 576` 个主会话，共 `596` 个会话。可按小批量续跑：

```bash
uv run python scripts/run_experiments.py \
  --manifest experiments/manifests/p0-p3-paired-matrix-v2.json \
  --resume --max-new-sessions 20
```

主指标为各对比在 24 个 seed block 上先对三次重复取均值、再以 seed block 为单位进行 10,000 次 bootstrap 的平均配对差与 95% CI；辅指标为中位差、最差拓扑族差、低于 B1 的 block 比例、预算剩余、step、LLM 调用、各动作数、P95 耗时和失败数。`scan_only` 仅提供绝对参照，不能替代 B1 的主配对对照。

`B2/B3/B4` 的记录仅在字面冻结的 `CalibrationProfile` 已验证且结构门禁通过后解释；`B5` 还要求经独立验证的 `ScenarioProfile`。当前两个 profile 均未通过，运行时应精确退回 B1 或禁用相应增强，而不能把“配置了 B3/B5”的标签当作已测试到其能力。

P2.2 已使结算器本身通过拓扑留出门禁，但没有改变上述运行时解释规则：默认
`CalibrationProfile` 仍为空，`target_influence` 和 `structure_gate_passed` 仍未冻结。
新的 P2.3 清单 [`p2-structure-policy-matrix-v3.json`](../../experiments/manifests/p2-structure-policy-matrix-v3.json)
仅在实验 runner 中注入 P2.2 报告，计划比较 24 个 50/100 节点 seed block 上的
`B3-B1`、`B4-B1` 和 `B4-B3`，截至本记录尚未运行。

## 本次本地与 P0 远端测试数据

| 检查 | 结果 | 含义 |
| --- | ---: | --- |
| P0 运行时契约 | 通过 | Python、CaseVO、Mesa、NetworkX、ChromaDB 与构造函数签名符合锁定契约 |
| 全量回归 | 103 / 103 通过 | 提交布局、公开 API 适配、预算、熔断、状态和实验分析器均无失败 |
| P1–P3 聚焦回归 | 39 / 39 通过 | B1 全扫描和渐减响应；未校准结构关闭；P2 反例/束搜索；P3 情景一致性与 VOI；未校准 B5 精确退回 B1 且不消耗 LLM；555-session 校准清单和数值异常回退 |
| P2/P3 矩阵静态展开 | 596 个会话 | 原始 P0–P3 清单可由 runner 生成；20 个 P0 + 576 个主会话 |
| P0 远端门禁 | 20 / 20 可比 | 四个固定终态各 5 次；零协议/动作失败，扫描和终态哈希一致，分数相对跨度均为 0 |
| P1 响应校准 | 135 / 135 可比 | 405 条响应完整；固定 `r=1.0` 时 persona 无额外差异，prompt 与边际递减完全可复现 |
| 原始 P2 图留出校准 | 420 / 420 可比 | 旧 `degree`：Spearman 0.9543，但归一化 MAE 10.24% 超过 5%，历史上拒绝档案 |
| P2.2 拓扑留出结算器 | 540 / 540 可比 | `component_degree_plus_one`：Spearman 1.0000，归一化 MAE 0.00553%，结算器门禁通过 |
| P2.3 结构策略矩阵 | 216 个主会话已预注册 | 24 个 seed block × 3 变体 × 3 重复；尚未执行，不能作策略收益结论 |

前四行是本地实现证据；最后三行是远端得分与校准证据。它们不能混为一类：通过 103 个测试、一个四节点 P0 门禁和微图校准，不等于已证明隐藏 seed 上的 P2/P3 策略提升。

### P0 固定终态的真实分数

| 固定终态（各 5 次） | 终局分 | 相对 scan-only Δ | 剩余预算 | 动作（含扫描） |
| --- | ---: | ---: | ---: | --- |
| `scan_only` | -15.00 | 0.00 | 58 | 4 scan |
| `shield_2` | 27.86 | +42.86 | 53 | 4 scan + 1 shield |
| `communicate_1_3_4` | 82.12 | +97.12 | 40 | 4 scan + 9 comm |
| `historical_v0_terminal` | 124.61 | +139.61 | 35 | 4 scan + 1 shield + 9 comm |

这是同一四节点 fixture 的机制与稳定性证据，不是对隐藏种子的策略排名。其直接结论是：官方代理、动作反馈和终局结算在该受控条件下可重复；屏蔽和游说在此小图均有正向终局关联。它不能替代 P1 的响应表、P2 的图留出校准，尤其不能推导“屏蔽总是优于切边/游说”。

## 分析与改进建议

1. **立即保持 B1 默认。** `DEFAULT_CALIBRATION_PROFILE` 与情景档案尚未验证；结构与自适应路径的失效关闭已经被回归测试覆盖。不要为了产生 P2/P3 分数而临时放宽门禁、填充参数或读取自定义 seed 的 `r`。
2. **执行 P2.3，而不是直接启用结构策略。** P2.2 已通过结算器门禁；下一步用实验 runner 注入该报告，按 24 个 seed block 配对比较 B3/B4 与 B1，并拒绝任何不可比 block。
3. **把 P2 的“模型正确性”和“策略收益”分开。** P2.2 只证明离线结算器在新拓扑上的误差很小；仍需 P2.3 的真实终局分、bootstrap、最差拓扑族和零新增失败门禁，不能从微图预测分直接宣称策略改进。
4. **让 P3 的探索与 LLM 成本各自承担举证责任。** 先比较无 LLM 的 `B5 - B4`；仅在该差异通过后，才检验 step/event LLM。报告增益时必须同时报告调用数与 P95 时间，避免把模型成本和探索效果混在一个结论中。
5. **使用可访问官方服务的网络路径与可恢复小批次。** 每次 `--max-new-sessions 20` 后执行结果完整性检查；不要把受限网络下的失败记录当作策略或服务端结论。分析时拒绝混合 manifest、分支或 profile hash。

## 本次执行命令

```bash
uv run python -m unittest discover -s tests -v
uv run python scripts/preflight_runtime.py
uv run python -m unittest -v \
  tests.unit.test_p1_baseline tests.unit.test_candidates \
  tests.unit.test_structural tests.unit.test_adaptive \
  tests.integration.test_controller
uv run python scripts/run_experiments.py \
  --manifest experiments/manifests/p0-p3-paired-matrix-v2.json --dry-run
```

P2.3 的实验-only dry run（不会修改默认提交档案）为：

```bash
uv run python scripts/run_experiments.py \
  --manifest experiments/manifests/p2-structure-policy-matrix-v3.json \
  --experimental-calibration-report experiments/reports/p2-topology-holdout-v2-20260906.json \
  --dry-run
```

远端 P0 尝试使用相同的公开 runner 和单会话上限，以免在可用性尚未成立时制造无效主矩阵数据。完整命令和脱敏状态保存在机器可读摘要中。
