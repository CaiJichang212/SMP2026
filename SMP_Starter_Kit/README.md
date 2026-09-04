# 🛸 SMP 2026 星网挑战赛 - 开发者本地调试 SDK

欢迎参加 **SMP 2026 社交媒体预测挑战赛（拯救地球之星网文明降临）**！
本 SDK 工具包旨在帮助您在本地环境调试、验证基于 CaseVO 框架编写的智能体系统。

---

## 📂 目录结构说明

请仔细阅读以下目录结构，明确哪些是**本地测试工具**，哪些是**您的提交代码**：

```text
SMP_Starter_Kit/
├── 📄 local_test_run.py      # 【测试入口】本地运行测试的主脚本
├── 📄 api_client.py          # 【系统工具】连接官方测试沙盒的 HTTP 代理
├── 📄 zhipu.py               # 【系统工具】智谱大模型 API 接口封装
├── 📁 custom_seeds/          # 【系统工具】存放本地测试的网络图 JSON
│
└── 📁 team_submission/       # 🎯【核心工作区】您需要修改并最终打包提交的代码文件夹！
    ├── config.json           # 参赛者的智能体角色配置文件
    ├── 📁 prompt/            # 各智能体的大语言模型提示词模板
    └── starnet_model.py      # CaseVO 主控逻辑代码（类名必须为 ParticipantSquadModel）
```

## 🚀 快速开始 (Quick Start)

### 1. 环境准备
确保您的电脑上已安装 Python 3.11+。在仓库根目录初始化受控开发环境：

```bash
uv sync
```

### 2. 配置您的 API Key
本地调试时，大模型推理消耗的是您自己的算力。请打开 `local_test.py`，找到以下行并填入您自己的智谱 API Key：

```python
YOUR_KEY = "您的智谱API_KEY"
```

### 3. 运行本地测试
在终端中执行以下命令：

```bash
cd SMP_Starter_Kit
uv run python local_test.py
```
终端将演示基础 API 的调用方法，随后您的 CaseVO 智能体会自动接管并开始干预网络，最终由官方沙盒服务器返回最终得分！

## 📡 沙盒环境 (Environment API) 指南

您的智能体需要通过调用 `self.env` 提供的 API 来感知世界并实施打击。

- `self.env.get_remaining_budget()`：获取当前剩余精神力预算。
- `self.env.scan_node(node_id)`：扫描节点，消耗 `0.5` 预算。返回节点详细信息（含 `comm_left` 剩余沟通次数）。
- `self.env.communicate(node_id, prompt_id)`：话术游说，消耗 `2.0` 预算。
- `self.env.cut_link(u, v)`：切断链路，消耗 `3.0` 预算。
- `self.env.shield_node(node_id)`：全域屏蔽，消耗 `5.0` 预算。

## ⚠️ 极度警告：硬性限制规则

为了考验算法效率，官方评测机对代码进行了严格限制：

- **通信带宽限流（API Limits）**：在单次图网络评测中，代码对大模型（LLM）的调用次数硬上限为 **50 次**（初赛标准）。如果您设计了过度冗长的“内部开会”逻辑导致超限，系统将强制熔断并判负！请结合图论算法精简 LLM 的调用。
- **禁止白盒篡改**：您的 `ParticipantSquadModel` 必须通过 `self.env` 交互，严禁尝试篡改沙盒底层内存，否则按作弊处理。

## 📤 如何打包提交？ (极其重要)

当您完成调试准备提交时，请务必严格按照官方推文的标准打包：

- **清理隐私**：绝对不要把您的 API Key 写死在 `team_submission` 的任何代码里！
- **正确打包 ZIP**：进入 `team_submission/` 文件夹内部，将里面的 `config.json`、`prompt/` 文件夹、`starnet_model.py` 这三个项目全部选中，右键打包为 `.zip` 压缩包（命名为您队伍的名称，例如 `Tsinghua_AI.zip`）。
- **结构自查**：请双击打开您刚生成的 ZIP 包，里面必须直接是 `config.json` 等文件，**绝对不能**多套一层名为 `team_submission` 的外壳文件夹！
- **平台上传**：在规定时间段内，将该 ZIP 文件提交至官方指定通道。

---

🎉 **祝各位指挥官好运，期待您拯救星网文明！**
```
