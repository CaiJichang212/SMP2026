# 实验清单

每次可比较实验应在这里保存参数：代码 commit、CaseVO commit、随机种子集、预算、
LLM 开关、候选策略和指标。原始日志写入 `experiments/raw/`，该目录不进入 Git；经复核的
统计结论写入 `experiments/reports/` 与 `docs/03_experiments/`。

`p0-p3-paired-matrix-v2.json` 是 P0–P3 的预注册远端矩阵：它以当前提交的
`b1_persuasion` 为基线，对 P2 结构规划与 P3 自适应/LLM 消融分别设置进入门禁和配对比较。

`v1-calibration.json` 的 135 个响应会话和 420 个历史结算会话由
`uv run python scripts/run_v1_calibration.py --resume --max-new-sessions N` 采集；
`scripts/calibrate_v1.py` 会拒绝不完整、不可比、重复不足或数值不达门槛的档案。

`p2-settlement-refit-mechanism-v2.json` 是 P2.1 的 29 会话机制辨识清单，针对
路径、三角形和星形的结算误差。它只生成候选结算器，不能冻结 runtime profile；
P2.2 已按拓扑两两不相交的 calibration / selection / gate split 完成验证。

`p2-topology-holdout-v2.json` 是 P2.2 的 540 会话结算器验证清单：九个图族按
calibration / selection / gate 严格分开，每族交叉三种意见布局、四种单动作和五个
fresh session。`analyze_p2_topology_holdout.py` 仅复用 P1 的响应表，绝不混入 V1 的
历史结算行；该清单已 540/540 可比并通过结算器门禁，但不启用默认 runtime profile。

`p2-structure-policy-matrix-v3.json` 是 P2.3 的策略收益矩阵。它以通过 P2.2 的
实验档案（仅由 runner 注入）比较 B3/B4 与 B1，覆盖六个拓扑族、50/100 节点、两个
seed 和三次 fresh session，当前仅完成预注册，尚未产生策略收益结论。它不修改提交
的默认档案。

`p2-structure-policy-matrix-v4-lowmem.json` 是 v3 内存修复后的独立 cohort：同一
清单和配对门槛，但每次只由一个新子进程执行一个 session，避免 4G 环境中的 Python
allocator 和反事实图状态累积。v3 的旧记录不得混入 v4；统计由
`scripts/analyze_p2_policy_matrix.py` 生成。

P3 的正式收益实验在 scenario profile 通过前不应运行。当前已保存的
`p3-gate-closed-negative-control-20260906.json` 只验证未校准 B5 的失效关闭行为，
不是自适应或 LLM 的收益证据。
