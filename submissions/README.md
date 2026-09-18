# 提交包

`starnet-20260918.zip`由`uv run python scripts/build_submission.py`生成（运行uv时设置项目规定的UV_CACHE_DIR）。
源码在`src/starnet/`，不要手工修改ZIP中的代码。

ZIP白名单：

- `config.json`
- `prompt/commander.txt`
- `prompt/reflect.txt`
- `starnet_model.py`

线上使用官方注入的LLM和凭证；没有本地客户端、环境变量、测试种子、原始日志或依赖。
仅已做本地/官方公开沙盒验证；尚无天池隐藏种子成绩。最终哈希和运行指标见`research/starnet-strategy/report.md`。
