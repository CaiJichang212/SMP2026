# 实验清单

每次可比较实验应在这里保存参数：代码 commit、CaseVO commit、随机种子集、预算、
LLM 开关、候选策略和指标。原始日志写入 `experiments/raw/`，该目录不进入 Git；经复核的
统计结论写入 `experiments/reports/` 与 `docs/03_experiments/`。

`p0-p3-paired-matrix-v2.json` 是 P0–P3 的预注册远端矩阵：它以当前提交的
`b1_persuasion` 为基线，对 P2 结构规划与 P3 自适应/LLM 消融分别设置进入门禁和配对比较。

`v1-calibration.json` 的 135 个响应会话和 420 个图留出会话由
`uv run python scripts/run_v1_calibration.py --resume --max-new-sessions N` 采集；
`scripts/calibrate_v1.py` 会拒绝不完整、不可比、重复不足或数值不达门槛的档案。
