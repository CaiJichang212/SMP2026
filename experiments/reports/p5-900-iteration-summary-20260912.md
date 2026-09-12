# P5 实验迭代与真实 LLM 官方沙盒结果

## 结论

本轮已完成多 Agent 分工、配对实验、候选优化筛查、真实 LLM 官方沙盒测试和提交包构建，**尚未达到或证明平台成绩 >900**。用户提供的历史最高成绩是 `765.8400`；该值及目标 900 按平台展示的原始成绩口径记录，不套用赛题文档中的 100 分相对评分公式。

同一 50 节点公开种子上，comm→shield guard 的官方终分由 `421.18` 提升至 `453.55`，增益 `32.37`（约 `7.69%`）。但跨种子筛查存在负增益图族，未通过晋级门禁，规范源中的 `experimental_public_comm_shield_guard` 已关闭。预算尾部前瞻的前三轮探索均未改善终分，也不接入提交策略。

## 设计与证据层级

1. 对照为逐动作 LLM 选择合法候选的 `public_greedy`。最高分历史 ZIP 的 `llm_schedule=off` 且包含三个角色，不按新答疑直接复投。
2. 本地比较以 `(family, node_count, repetition)` 配对，50 与 100 节点分别汇总；检查终分、图族均值、失败数和预算。已经参与调参的图族不能重新称为未见拓扑。
3. guard 冻结后的新重复种子验证见 [确认性实验清单](../manifests/p5-public-guard-confirmatory-20260912.json)。晋级要求 guard-off 与生产对照一致、零动作失败、每族均值非负及图族 bootstrap 95% 区间下界严格大于零。
4. 真实实验使用独立官方沙盒会话，扫描核对请求种子、公开反馈驱动策略、runner 单独调用 `trigger_eval()`。真实模型为本地配置的 `gpt-5.6-luna`，不能替代官方评测使用的 `glm-4-plus` 验证。
5. 平台隐藏种子成绩才可确认 >900。公开种子上的绝对终分、合成图终分或单种子百分比增益均不可换算成隐藏种子成绩。

## 真实实验结果

完整本地结果见 [guard 复验报告](p5-public-guard-replicated-validation-20260912.md) 和 [预算前瞻报告](p4-public-tail-structure-lookahead-20260912.md)。guard 本轮共 121 对、363 次完整策略会话，全部零动作失败且 guard-off 复现生产对照；冻结的新重复种子中仍出现单种子 `-107.2779`，各分层均未通过门禁。修正后的 `[5,25)` 预算前瞻在 10 对既有/独立种子上全部持平，零失败，不接入运行时。

| 种子 / 实验臂 | 官方终分 | 本地终分 | LLM 接受 / 调用 | 动作成功 / 尝试 | 剩余预算 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 官方四节点样例，guard 开 | 124.61 | 124.607143 | 14 / 14 | 14 / 14 | 35 |
| BA 负 hub，50 节点，r4，guard 关 | 421.18 | 421.280774 | 77 / 77 | 77 / 77 | 0 |
| BA 负 hub，50 节点，r4，guard 开 | 453.55 | 453.626625 | 77 / 77 | 77 / 77 | 0 |

三次运行均满足初始预算和完整扫描快照匹配，LLM 回退为零。50 节点两臂各执行 78 次模型 step，其中 77 次有动作：扫描 50、游说 20、屏蔽 7、切边 0，低于 120 次限额。

两臂真实动作逐条在本地重放后，每次游说返回的 `new_w` 最大误差均为 `0.0`。本地闭式终分与官方终分仍有 `0.100774`、`0.076625` 的残差，说明结算层存在数值差异；不能把本地模拟器当成逐位精确的官方结算器。

本次只有一个 50 节点种子的真实配对，且没有同臂多次 LLM 重复，不能估计模型随机性或隐藏拓扑泛化。guard 选择这个 BA 种子用于机制验证，也不能据此作无偏整体效果估计。

本地忽略目录中的完整轨迹：

- `runs/p5-real-llm-smoke/20260912T093733Z_my_test_network_00d22e1aa964.jsonl`
- `runs/p5-real-llm-50-control/20260912T094255Z_ba_negative_hubs-50-r4_45bb89d79cd1.jsonl`
- `runs/p5-real-llm-50/20260912T093906Z_ba_negative_hubs-50-r4_714e161e1f8f.jsonl`

50 节点种子由 `seed_payload("ba_negative_hubs", 50, 4)` 生成，文件 SHA-256 为 `d349566972f4e2e8852b182596ff8880ce9ea9bbbdac4fa51606f9286e645fdb`。对照运行记录了 `runner.configuration`；两次较早的 guard 运行发生在元数据功能加入前，没有事后伪造该事件。

复跑两臂时使用同一生成种子，在下列命令中分别选择 `off`、`on`；无需修改提交源：

```bash
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_baseline_openai.py --seed experiments/raw/p5-seeds/ba_negative_hubs-50-r4.json --experimental-policy-mode public_greedy --public-comm-shield-guard off --timeout 20 --no-console-log --log-dir runs/p5-real-llm-50-control
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_baseline_openai.py --seed experiments/raw/p5-seeds/ba_negative_hubs-50-r4.json --experimental-policy-mode public_greedy --public-comm-shield-guard on --timeout 20 --no-console-log --log-dir runs/p5-real-llm-50
```

## 修复与交付

- `communicate` 返回 `None` 时按失败处理；失败 cut/shield 扣费、失败 scan/communicate 不扣费的行为由测试覆盖，事实只依据公开返回更新。
- 真实运行器保留提交策略完整配置，修复相对日志路径，避免日志进入生成提交目录；新增有效配置、种子及代码哈希记录。
- 新规则和成绩口径已补入赛题文档。失败的 guard 实验显式关闭，其他既有未提交工作保留。
- 最终验证：`uv run python -m unittest discover -s tests -v` 共 136 项通过，`build_submission.py`、`validate_submission.py`、`package_submission.py` 全部通过，`git diff --check` 无错误。
- 审计包：`artifacts/submission/starnet-public-greedy-llm-audited-20260912.zip`，SHA-256 `16c9737974b6567af074d5154b687eb06e72de50f0a1f6c72a717b776e4ab797`。包中的模型代码哈希与真实对照臂记录一致。ZIP 根目录仅包含 `config.json`、`prompt/`、`starnet_model.py`；只有一个 CommanderAgent，`llm_schedule=step`，guard 关闭。

这是合规和可复现性修复后的对照包，不是声称已提升到 900 的新冠军策略；本轮未上传平台或获得新的隐藏种子分数。

## 下一轮方向

优先研究能改变最终预算分配的联合结构方案，并在预测状态中计算，不能把预测写入 Blackboard。先冻结算法和预算限制，用全新拓扑与响应分布验证，再扩大真实 LLM 官方配对。响应先验微调和只改变尾部动作顺序的方案已经缺少增益证据，不应继续靠重复查看相同留出集选择参数。

只有候选通过跨图族门禁后，才值得使用官方模型做多次重复并进入平台提交。当前缺少通过门禁的新候选与新平台反馈，因此目标保持未达成。
