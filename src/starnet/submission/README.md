# 提交源文件

这里保存最终交付物的规范源：`config.json`、`prompt/` 和 `starnet_model.py`。
不要直接编辑 `SMP_Starter_Kit/team_submission/`；运行
`uv run python scripts/build_submission.py` 将本目录同步到该受控交付目录。

当前初赛候选启用经过本地平均分门验证的 P8 `conservative`。它从公开事实生成
结构与游说候选，以五个响应情景比较完整后续策略，并保留 LLM 对新动作与基线动作
的最终选择。入口仍使用官方注入的 `host_env` 与 `llm`。

`experimental_p8_mode` 必须匹配 `policy/p8_qualification.py` 中的已审阅模式；
资格缺失、不匹配或初始资源不符合 50 节点/100 预算时，使用原 `public_greedy`。
预测和 LLM 输出不写入事实 Blackboard。

资格来自预登记的 701--705 新数据平均分与图族占比压力测试。旧 601--605 的
“每族均值非负”确认仍记为失败；新资格不表示每个种子都会提高，也不代表官方
隐藏种子已超过 900。完整证据见 `experiments/reports/p8-mean-objective-result-20260913.json`。
