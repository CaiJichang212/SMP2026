# P2.3 结构策略配对实验最终结果（2026-09-07）

## 实验完成情况

P2.3 使用 [`p2-structure-policy-matrix-v4-lowmem.json`](../../experiments/manifests/p2-structure-policy-matrix-v4-lowmem.json)，在 4G 服务器上以独立子进程和低并发 worker 续跑。计划包含 24 个 seed block、3 次重复和 B1/B3/B4 三个变体，共 216 个远端 session。

| 指标 | 结果 |
| --- | ---: |
| 计划主 session | 216 |
| 完成且可比 | 216/216 |
| 协议/动作失败 | 0 |
| P0 gate | 20/20，四种终态分数跨度均为 0 |
| B3 实际执行结构动作 | 60/72 |
| B4 实际执行结构动作 | 60/72 |
| bootstrap 重采样 | 10,000 次，按 24 个 seed block |

机器可读原始数据位于被忽略的 `experiments/raw/p2-structure-policy-matrix-v4-lowmem-20260906/`；聚合数据由原子 session 文件重建。统计结果见 [`p2-structure-policy-matrix-v4-lowmem-20260906.json`](../../experiments/reports/p2-structure-policy-matrix-v4-lowmem-20260906.json)。

## 配对结果

| 对比 | 均值 Δ | 中位 Δ | 95% bootstrap CI | 最差拓扑族均值 | 门禁 |
| --- | ---: | ---: | --- | ---: | --- |
| B3 - B1 | 101.731 | 34.500 | [43.440, 165.115] | -9.255（WS peace majority） | 不通过 |
| B4 - B1 | 101.052 | 30.665 | [44.274, 162.663] | -9.255（WS peace majority） | 不通过 |
| B4 - B3 | -0.679 | 0.000 | [-6.864, 5.138] | -13.345（SBM violent cluster） | 不通过 |

## 结论

1. **不能晋级 B3/B4 为默认策略。** 虽然总体均值相对 B1 为正，两个结构策略在 WS peace majority 拓扑族均值为负，违反“任何拓扑族不得为负”的预注册门槛。
2. **B4 没有显示出相对 B3 的稳定收益。** B4-B3 的置信区间跨过 0，且点估计略为负；束搜索复杂度没有得到收益证据。
3. **部分 B3/B4 session 没有实际结构动作。** 这 12 个 block 的策略退化为完整游说路径，进一步说明结构候选在正向和平网络上不应强制执行。它们保留在完整 cohort 中，但策略门禁要求实际结构动作，因此不能被当作结构能力的成功证据。
4. **默认仍保持无 LLM B1。** `CalibrationProfile` 和 `structure_gate_passed` 不冻结，B2/B3/B4 运行时继续失效关闭；P3 正式收益矩阵不因 P2 的总体均值为正而启动。

## 改进建议

- 对 WS peace majority 先做结构动作风险分析：切桥可能损失正向传播，屏蔽节点可能破坏正向连通性；应提高保守风险门槛，而不是用总体均值掩盖族级负收益。
- 将结构候选的“实际执行率”作为独立上线门槛；若候选经常退化为 B1，应报告为结构策略未触发，而不是按 B3/B4 能力解释。
- 暂不继续增加 B4 搜索深度或宽度。B4-B3 没有收益证据，增加搜索只会扩大计算和内存成本。
- 重新设计结构影响特征和族级风险模型后，使用新的、拓扑不相交的 seed block 重复 P2.3；不能在本 cohort 上事后调阈值再重算。
- P3 应继续保持正式收益实验关闭；只保留已经通过的 B5 fail-closed 负对照，待 P2 通过和独立 scenario profile 验证后再做 B5/LLM 消融。
