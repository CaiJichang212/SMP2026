# ADR-001：最终交付边界

## 决策

`SMP_Starter_Kit/team_submission/` 是唯一的最终提交目录。其内容由
`scripts/build_submission.py` 从 `src/starnet/submission/` 同步生成，再经
`scripts/validate_submission.py` 校验。最终 ZIP 的根目录只能出现赛方契约允许的
`config.json`、`prompt/` 和 `starnet_model.py`。

## 原因

赛方以 ZIP 根目录、固定主文件名和 `ParticipantSquadModel` 接口加载参赛代码。
研发源码、测试、日志、种子、缓存和私密配置均不属于该接口，混入会增加导入失败、
泄露密钥和人工审校风险。

## 后果

日常开发应优先修改 `src/starnet/` 与 `tests/`。若最终策略拆分为多个 Python 模块，
构建脚本必须将其稳定收敛为可独立导入的 `starnet_model.py`；在赛方未确认额外模块可
随 ZIP 导入前，不允许直接把辅助包加入提交目录。
