# SMP2026 协作约定

## 环境与源码

- 使用 Python 3.11+ 与 `uv`：初始化用 `uv sync`，所有命令用 `uv run ...`；不要使用 `pip`、手动激活环境或提交 `.venv/`。
- 新增依赖使用 `uv add <包>`（开发依赖：`uv add --group dev <包>`），并提交 `pyproject.toml` 和 `uv.lock`。
- `casevo` 是赛方指定的运行时与导入名；不得为解决本地导入问题而伪造、替换或打包它。
- 日常源码在 `src/starnet/`，测试在 `tests/`。`Blackboard` 仅保存赛段契约和环境公开事实；预测、LLM 输出与隐藏字段不得写入其中。

## 策略安全边界

- 仅调用公开环境 API。每个动作发送前校验预算、节点、边、沟通次数和 `prompt_id`；返回结果才可更新本地状态。
- Python 先生成并校验候选；LLM 只能排序这些候选，须受调用配额限制，并对超时、异常和非法输出确定性回退。
- 当前提交默认是无 LLM 的 B1 游说策略。CMG、结构规划和自适应探索仅限通过校准/场景门禁后的实验变体，门禁失败必须失效关闭。
- 提交代码不得访问环境私有成员、调用 `end_turn()` 或 `trigger_eval()`；结算只由本地 runner/官方评测器执行。

## 提交与验证

- `src/starnet/submission/` 是 `config.json`、`prompt/` 和入口的规范源；策略模块位于 `src/starnet/`，由构建脚本内联。
- 不要直接编辑 `SMP_Starter_Kit/team_submission/`；它是受控生成目录。
- 每次改动至少运行：

  ```bash
  uv run python -m unittest discover -s tests -v
  uv run python scripts/build_submission.py
  uv run python scripts/validate_submission.py
  ```

- 提交前运行 `uv run python scripts/package_submission.py --name <name>.zip`。ZIP 根目录只能包含 `config.json`、`prompt/` 与 `starnet_model.py`。
- 不提交 API Key、`.env`、日志、缓存、`experiments/raw/`、`runs/` 或其他本地资产。实验参数写入 `experiments/manifests/`，审阅结论写入 `experiments/reports/`。
