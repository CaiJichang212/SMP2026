# SMP 2026 星网赛题

本仓库用于星网赛题研究、实验与提交。规则以 [`docs/task/赛题任务.md`](docs/task/赛题任务.md)、
[`docs/task/补充信息.md`](docs/task/补充信息.md) 和常见问题解答为准；
`SMP_Starter_Kit/` 是原始参考 SDK，不代表已验证通过的提交方案。

## 目录

| 路径 | 用途 |
| --- | --- |
| `docs/task/` | 用户提供的赛题、补充规则和常见问题解答 |
| `SMP_Starter_Kit/` | 原始示例、测试客户端、示例种子和基线提交 |
| `src/starnet/` | 后续可测试的算法/编排源代码 |
| `data/` | 小型公开测试数据；`generated/`、`private/` 不跟踪 |
| `research/starnet-strategy/` | research-lab 状态、阶段记录和证据 |
| `tests/`、`scripts/` | 测试与受限实验工具 |
| `submissions/` | 生成的 ZIP 包（不跟踪） |

提交 ZIP 的根目录只能包含 `config.json`、`prompt/` 和
`starnet_model.py`，不能将整个 `SMP_Starter_Kit/` 或工作目录打包。
示例包位于 `SMP_Starter_Kit/team_submission/`；目前尚无经验证的最终提交包。

## 开发环境

要求 uv 和本机 Python 3.9。项目只锁定轻量图分析/HTTP 依赖，不预装
CaseVO/Chroma，也不预设线上旧版 `agent_mesa` 与本地 `casevo` 等价。

```bash
UV_CACHE_DIR=/tmp/smp20260918-uv-cache uv sync --locked
UV_CACHE_DIR=/tmp/smp20260918-uv-cache uv run python -c 'import networkx, requests; print("ok")'
```

根目录 `.env` 是本地测试凭证，已忽略；`.env.example` 仅展示变量名。
已有本地 LLM 配置可以用于后续受控测试，线上只用主办方注入的 LLM，
任何密钥都不得进入代码、日志或 ZIP。不要直接运行原始
`SMP_Starter_Kit/local_test.py`：其中仍有占位 Key、旧的 50 步限制，
而且远端请求没有超时。后续建立适配器并验证 API 后再运行实际测评。

## 主机限制和进度

主机为 2 vCPU、约 4 GB 内存。耗资源命令使用
`bash scripts/run_limited.sh uv run <命令>` 串行运行；脚本限制单核、
线程数、10 分钟实际运行时间和 2.5 GiB 虚拟地址空间。先跑小种子，
记录峰值内存、耗时、步数、LLM 调用数与剩余预算，确认稳定后再扩展。
如地址空间限制导致框架无法启动，先记录并分析原因，不直接去掉限制。

当前只完成任务准备，不宣称策略得分或线上兼容性。
研究进度和下一阶段见 [`research/starnet-strategy/state.md`](research/starnet-strategy/state.md)。
若实验需要用户协助且本地方案已穷尽，给 `li_y_c@qq.com` 发送
问题、证据和明确所需操作；不在邮件中包含凭证。
