# 🛸 SMP 2026 星网挑战赛

本仓库同时保存官方 Starter Kit、可测试的策略研发源码、实验资产和最终提交构建流程。

## 仓库导航

```text
SMP2026/
├── SMP_Starter_Kit/       # 官方 SDK、沙盒客户端和生成的交付目录
├── src/starnet/           # 可测试的策略、状态、运行时和提交素材源码
├── tests/                 # 单元、契约与集成测试
├── fixtures/              # 小型固定种子、轨迹和脱敏响应
├── experiments/           # 实验清单、报告和被忽略的原始结果
├── scripts/               # 构建、校验、打包与实验入口
├── docs/                  # 赛题约束、ADR、调研、计划和操作手册
├── runs/                  # 本地运行轨迹（忽略，不提交）
└── artifacts/             # 构建出的 ZIP 等产物（忽略，不提交）
```

### 源码、构建产物与提交物

策略研发源码与最终提交物之间的关系如下：

```text
src/starnet/model|policy|runtime/     策略事实、图分析、候选生成和运行控制器
src/starnet/submission/               提交入口壳、config.json 和 prompt/ 的规范源
                 |
                 | uv run python scripts/build_submission.py
                 v
SMP_Starter_Kit/team_submission/      赛方兼容的生成交付目录
                 |
                 | uv run python scripts/package_submission.py --name <name>.zip
                 v
artifacts/submission/<name>.zip       最终上传文件
```

`src/starnet/` 是日常维护的唯一策略源：

- `model/blackboard.py`：环境事实的唯一来源。
- `policy/`：动作合法性、图分析和候选动作生成。
- `runtime/`：环境适配、控制器状态机与运行轨迹。
- `submission/`：提交配置、提示词和 `ParticipantSquadModel` 的开发态入口。

用户反馈已提交的 P8 `conservative` 官方得分仍为 **761.9467**。
其原本地确认增益仅 `+0.84%`，不能换算为官方成绩或证明接近 >900。
本轮复放发现候选覆盖很窄，并通过 108 次公开沙盒调用确认旧模拟器漏掉了
游说后的 `[-100,100]` 截断。修正包为
`artifacts/submission/starnet-p9-bounded-response-20260913.zip`：
独立 84 对确认相对原 P8 为 24 胜/60 平/0 负，平均增益 +10.4140；
真实 LLM 公开沙盒成对提高 17.09。新包尚无官方分数，不能据此认定 >900。
资格与实际 ZIP 已验证，详见[交付报告](experiments/reports/p9-bounded-release-20260913.md)。
详见 [同分归因与本轮实验](experiments/reports/p9-official-feedback-attribution-20260913.md)
及[倾向边界机制](docs/01_architecture/adr/005-communication-opinion-bounds.md)。

`SMP_Starter_Kit/team_submission/` 不是第二份需要维护的策略源码。构建脚本会复制
`config.json` 与 `prompt/`，并将 `src/starnet` 的策略模块内联为单文件
`starnet_model.py`。因此不要直接修改该目录；本地 OpenAI 兼容模型运行器、校验和打包都
使用它。

`SMP_Starter_Kit/` 的其余内容是官方提供的 SDK 与本地调试辅助文件：`api_client.py`
负责远程沙盒通信，`local_test.py` 是官方测试入口，`custom_seeds/` 保存其测试种子。

每次策略改动后执行：

```bash
uv run python -m unittest discover -s tests -v
uv run python scripts/build_submission.py
uv run python scripts/validate_submission.py
```

提交前再执行：

```bash
uv run python scripts/package_submission.py --name <name>.zip
```

最终 ZIP 的根目录只能包含 `config.json`、`prompt/` 和 `starnet_model.py`。本地密钥、日志、
缓存、实验种子和测试工具不得进入提交包。框架源码位于同级独立仓库 `../casevo`，不要将
赛题策略提交到该仓库。

---

# 官方 Starter Kit 说明

欢迎参加 **SMP 2026 社交媒体预测挑战赛（拯救地球之星网文明降临）**！
本 SDK 工具包旨在帮助您在本地环境调试、验证基于 CaseVO 框架编写的智能体系统。

---

## 📂 目录结构说明

以下目录区分官方本地测试工具与由构建流程生成的交付目录：

```text
SMP_Starter_Kit/
├── 📄 local_test.py          # 【测试入口】官方本地运行测试脚本
├── 📄 api_client.py          # 【系统工具】连接官方测试沙盒的 HTTP 代理
├── 📄 zhipu.py               # 【系统工具】智谱大模型 API 接口封装
├── 📁 custom_seeds/          # 【系统工具】存放本地测试的网络图 JSON
│
└── 📁 team_submission/       # 🎯【构建产物】赛方加载和最终打包的交付目录
    ├── config.json           # 参赛者的智能体角色配置文件
    ├── 📁 prompt/            # 各智能体的大语言模型提示词模板
    └── starnet_model.py      # CaseVO 主控逻辑代码（类名必须为 ParticipantSquadModel）
```

## 🚀 快速开始 (Quick Start)

### 1. 环境准备
确保已安装 Python 3.11+ 和 `uv`，然后在仓库根目录初始化依赖：

```bash
uv sync
```

仓库研发环境使用 Python 3.11+；赛方 FAQ 列出的线上依赖环境实际运行 Python 3.9。
构建后的单文件提交因此还会按 Python 3.9 语法和 `typing` 可用名称单独校验，不能把
研发环境的标准库能力直接带入提交包。

### 2. 配置您的 API Key
本地调试时，大模型推理消耗的是自己的算力。将密钥保存在根目录 `.env`，不要写入
`team_submission/` 或最终 ZIP：

```bash
SMP_LLM_API_KEY=...
SMP_LLM_BASE_URL=http://43.133.177.230:3819/v1
SMP_LLM_MODEL=gpt-5.6-luna
```

### 3. 运行本地测试
使用当前提交策略和 OpenAI Chat Completions 兼容模型运行远程沙盒：

```bash
uv run python scripts/run_baseline_openai.py
```
该脚本会先构建 `team_submission/`，再加载生成的 `ParticipantSquadModel` 运行，并将本地
诊断轨迹写入 `runs/v0-baseline/`（保留历史目录名；完成摘要中的 `p8_mode` 表明实际启用模式）。

运行器使用标准的 `POST /v1/chat/completions`、Bearer API Key 和
`response_format: {"type":"json_object"}`；`SMP_LLM_BASE_URL` 可以带或不带 `/v1`，
会被规范化为正确的端点。默认配置对应本仓库测试的 `gpt-5.6-luna` 网关。模型请求超时、
HTTP 错误或格式错误不会重试，以确保一次控制器 LLM 计数只对应一次远程请求，并立即走确定性回退。

## 📡 沙盒环境 (Environment API) 指南

2026-09-12 赛方答疑：每个智能体须继承 `casevo.AgentBase`，最终动作由 LLM 从 Python 校验的候选中决定；不要求调用 `prompt/` 中的所有文件。失败的切边和屏蔽仍扣费，失败的扫描和游说不扣费。完整约束见 `docs/00_rules/task-spec.md`。

您的智能体需要通过调用 `self.env` 提供的 API 来感知世界并实施打击。

- `self.env.get_remaining_budget()`：获取当前剩余精神力预算。
- `self.env.scan_node(node_id)`：扫描节点，消耗 `0.5` 预算。返回节点详细信息（含 `comm_left` 剩余沟通次数）。
- `self.env.communicate(node_id, prompt_id)`：话术游说，消耗 `2.0` 预算。
- `self.env.cut_link(u, v)`：切断链路，消耗 `3.0` 预算。
- `self.env.shield_node(node_id)`：全域屏蔽，消耗 `5.0` 预算。

## ⚠️ 极度警告：硬性限制规则

为了考验算法效率，官方评测机对代码进行了严格限制：

- **LLM 调用上限（正式评测）**：单个图网络种子中，初赛最多调用 LLM **120 次**，复赛最多 **250 次**。调用计数必须覆盖异常和超时路径，并保留确定性回退。
- **本地回合保护（仅调试）**：早期 SDK 中写死的 50 次不是正式评测规则。`local_test.py` 读取 `custom_seeds/my_test_network.json` 的 `global_setting.max_api_calls` 作为本地回合保护值；可随自定义种子的规模调整，它不覆盖正式评测的 LLM 上限。
- **禁止白盒篡改**：您的 `ParticipantSquadModel` 必须通过 `self.env` 交互，严禁尝试篡改沙盒底层内存，否则按作弊处理。

## 📤 如何打包提交？ (极其重要)

当您完成调试准备提交时，请务必严格按照官方推文的标准打包：

- **清理隐私**：绝对不要把您的 API Key 写死在 `team_submission` 的任何代码里！
- **正确打包 ZIP**：先运行 `uv run python scripts/build_submission.py` 和 `uv run python scripts/validate_submission.py`，再运行 `uv run python scripts/package_submission.py --name <name>.zip`。该脚本会从 `team_submission/` 创建 ZIP，避免误带外层目录。
- **评测环境兼容**：线上 traceback 已确认 Python 3.9，FAQ 固定 `networkx==3.1`。
  新增内联模块后要用该组合导入最终 ZIP。动态测试完成后重新构建、校验、打包，避免
  把测试生成的 `__pycache__` 带入 ZIP。详见 [ADR-004](docs/01_architecture/adr/004-evaluator-python39-compatibility.md)。
- **结构自查**：请双击打开您刚生成的 ZIP 包，里面必须直接是 `config.json` 等文件，**绝对不能**多套一层名为 `team_submission` 的外壳文件夹！
- **平台上传**：在规定时间段内，将该 ZIP 文件提交至官方指定通道。

---

🎉 **祝各位指挥官好运，期待您拯救星网文明！**
