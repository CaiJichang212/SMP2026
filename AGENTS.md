# SMP2026 协作约定

## 开发环境

- 使用 Python 3.11+ 和 `uv` 管理环境与依赖；不要使用 `pip`、手动激活虚拟环境或提交 `.venv/`。
- 初始化或更新环境：`uv sync`；运行命令统一使用 `uv run <命令>`。
- 新增运行依赖使用 `uv add <包>`，仅开发依赖使用 `uv add --group dev <包>`；提交 `pyproject.toml` 与 `uv.lock` 的对应变更。
- `agent_mesa` 以赛方官方运行时为准。未获确认前，不要为绕过本地导入错误而伪造、打包或替换它。

## 代码与测试

- 日常策略代码放在 `src/starnet/`，测试放在 `tests/`；`Blackboard` 是环境事实的唯一来源。
- 只能调用公开环境 API；所有动作在发送前做预算、节点、边、次数和 `prompt_id` 校验。LLM 只能排序 Python 生成的合法候选，并必须有确定性回退。
- 每次改动至少运行：

  ```bash
  uv run python -m unittest discover -s tests -v
  uv run python scripts/build_submission.py
  uv run python scripts/validate_submission.py
  ```

## 提交边界

- 只编辑 `src/starnet/submission/` 作为提交源；不要直接修改生成的 `SMP_Starter_Kit/team_submission/`。
- 提交前运行 `uv run python scripts/package_submission.py --name <name>.zip`。ZIP 根目录只能包含 `config.json`、`prompt/` 与 `starnet_model.py`。
- 不提交 API Key、`.env`、日志、缓存、实验原始结果或其他本地资产；不要使用环境私有方法或 `end_turn()`。
