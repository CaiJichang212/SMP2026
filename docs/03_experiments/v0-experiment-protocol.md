# V0 远程实验运行说明

运行前使用 `.env` 配置 `SMP_LLM_API_KEY`（仅 `v0_llm3` 需要）；可选 `SMP_SERVER_URL`、`SMP_LLM_BASE_URL`、`SMP_LLM_MODEL`。这些值不会进入清单、JSONL、CSV 或报告。

```bash
uv run python scripts/run_experiments.py --dry-run
uv run python scripts/run_experiments.py --resume
uv run python scripts/analyze_experiments.py
```

首次正式运行会先构建提交目录并跑完整测试。每个 session 使用新远程 session，扫描快照不匹配或预算不为预期时均会标为不可比。执行环境若有外部时间切片，可用 `--resume --skip-preflight --max-new-sessions N` 续跑；`spec_hash` 不变的已完成结果不会重跑。

门禁固定执行 20 个四节点 session。若每个终态的扫描/终态哈希一致且相对波动不超过 2%，主矩阵是 `6 × 8 × 1`；否则自动选择三种高激活 seed 并变为 `3 × 8 × 2`。两条路径均为 48 个主 session、68 个正式 session。

原始结果放在忽略的 `experiments/raw/v0-matrix/<manifest-hash>/`：门禁、稳定矩阵和不稳定矩阵分别位于 `gate/`、`stable/`、`unstable/`。因此不同清单或门禁分支绝不会共享 `results.jsonl`/`results.csv`。统计脚本会拒绝混合的 plan/branch，也会排除协议异常或动作失败的 session，再按 seed 与 `scan_only` 配对进行 10,000 次 bootstrap。
