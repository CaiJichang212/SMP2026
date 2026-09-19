# SMP 2026 星网智能体

实现：公开观测建图 → 同节点话术校准 → 估计结构边际与剩余预算机会成本 → LLM选择游说/屏蔽/切边 → 逐步校验执行。
单个指挥Agent继承CaseVO/agent_mesa的AgentBase，主类继承ModelBase。只使用五个公开环境API。

原提交包：`submissions/starnet-20260918.zip`，用户反馈官方531.1233分，保留不覆盖。
V2候选包：`submissions/starnet-20260918-v2.zip`。包内仅`config.json`、`prompt/`、`starnet_model.py`。
V2官方≥950目标尚未验证；研究状态和实际验证结果见[续研报告](research/starnet-strategy/report-v2.md)。
研究对照、真实LLM实验与官方隐藏平台结果分别记录；**本地验证不代表官方完赛或排名**。

## 目录

| 路径 | 内容 |
|---|---|
| `src/starnet/` | 可复用策略、框架编排、角色配置、提示词 |
| `scripts/` | 资源限制、公开沙盒对照、真实LLM运行、确定性打包 |
| `tests/` | Python3.9策略/预算/故障/授权契约测试 |
| `data/public_seeds/` | 自建公开验证种子，不传给参赛模型 |
| `research/starnet-strategy/` | research-lab各阶段、论文来源、比较与决策 |
| `SMP_Starter_Kit/` | 原始参考SDK，保持原样；不要直接运行local_test.py |
| `submissions/` | 生成ZIP，Git忽略 |

## 轻量开发与打包

```bash
UV_CACHE_DIR=/tmp/smp20260918-uv-cache uv sync --locked
UV_CACHE_DIR=/tmp/smp20260918-uv-cache uv run python -m unittest discover -s tests -v
UV_CACHE_DIR=/tmp/smp20260918-uv-cache uv run python scripts/build_submission.py
```

按`uv.lock`使用Python3.9。打包会检查Python3.9语法、源码拼接、公开API、ZIP白名单及本地密钥排除，输出SHA256。
单元测试中的框架double只验证协议，不代替真实CaseVO运行。

## 官方沙盒自建种子对照

```bash
bash scripts/run_limited.sh uv run python scripts/research_compare.py \
  --seeds 21,22,23,24,25,26 --nodes 10 --budget 30 \
  --output /tmp/starnet-comparison/comparison.jsonl
```

`natural/fixed/adaptive/structural`均为无LLM的研究对照，不能当作提交方案。
脚本不重试可能已生效的写操作；传输失败需新建session重跑整局。结算会销毁session，因此先记余额再evaluate。

## 真实LLM和完整CaseVO验证

根目录已忽略的`.env`需包含`.env.example`列出的3项。不要提交凭证。
本机现有完整CaseVO环境在另一个项目中，当前只读使用它；没有修改外部CaseVO。

```bash
ANONYMIZED_TELEMETRY=False bash scripts/run_limited.sh \
  uv run --no-project --python /home/ubuntu/SMP2026casevo/SMP2026/.venv/bin/python \
  python scripts/run_submission.py \
  --zip submissions/starnet-20260918-v2.zip \
  --seed data/public_seeds/42-n50.json \
  --output /tmp/starnet-real-llm/result.json
```

此命令会调用真实LLM、消耗本地API额度。运行时为Python3.12；线上旧`agent_mesa`和官方`glm-4-plus`仍需平台验证。
模型使用注入LLM，不替换其凭证或服务；本地HTTP客户端仅在研究runner中。
`run_limited.sh`限制单核、2.5GiB地址空间、10分钟，实验串行。环境HTTP为5s连接/20s读取，LLM为5s/45s；模型LLM截止55s后停止。

## 规则与研究记录

- [赛题](docs/task/赛题任务.md)、[补充规则](docs/task/补充信息.md)、[FAQ](docs/task/SMP2026常见问题解答.md)
- [当前状态](research/starnet-strategy/state.md)、[决策](research/starnet-strategy/decision.md)、[论文与开源来源](research/starnet-strategy/sources.md)

120/250步与LLM调用分别计数。坏JSON最多重问一次；LLM失败时不自动切换为硬编码干预；屏蔽/切边后立即重规划。
完整原始日志留在各run的`raw/`（Git忽略），摘要及指标在受跟踪的研究文件中。平台提交需用户账号，隐藏种子结果不得用自建种子分数代替。

## V2配对矩阵

固定自建种子在`data/optimization_matrix/`，包含六类拓扑、六种话术排列、
不同响应系数与初始分布。`optimization_matrix.py`的纯算法对照不是参赛智能体。

```bash
bash scripts/run_limited.sh uv run python scripts/optimization_matrix.py \
  --remote --seeds 126,127,134,135,142,143 \
  --policies natural,incumbent,completion --output /tmp/starnet-v2-matrix/results.jsonl
UV_CACHE_DIR=/tmp/smp20260918-uv-cache uv run python scripts/compare_submission_pair.py \
  --baseline submissions/starnet-20260918.zip --candidate submissions/starnet-20260918-v2.zip \
  --seed-dir data/optimization_matrix --seeds 120,124,134 --output /tmp/starnet-v2-pairs
```

配对脚本内部逐局调用资源限制器，不并行实验。断连或超时的动作局单列，
不用失败成绩参与均值；只读预算查询最多重试一次，修改状态的API不重试。
