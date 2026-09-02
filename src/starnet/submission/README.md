# 提交源文件

这里保存最终交付物的规范源：`config.json`、`prompt/` 和 `starnet_model.py`。
不要直接编辑 `SMP_Starter_Kit/team_submission/`；运行
`python scripts/build_submission.py` 将本目录同步到该受控交付目录。

当前阶段保留了官方基线的行为，以便先建立可重复的构建与校验闭环。新策略应先在
`src/starnet/` 和 `tests/` 中验证；当赛方确认可用的模块加载方式或单文件组装方式后，
再将其收敛到本目录的 `starnet_model.py`。
