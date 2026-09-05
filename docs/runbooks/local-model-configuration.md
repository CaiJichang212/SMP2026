# 本地 OpenAI API 兼容模型配置

在仓库根目录的 `.env` 设置下列变量（不要提交真实 API Key）：

```dotenv
SMP_LLM_API_KEY=您的网关密钥
SMP_LLM_BASE_URL=http://43.133.177.230:3819/v1
SMP_LLM_MODEL=gpt-5.6-luna
```

运行器使用 OpenAI Chat Completions 兼容协议：`POST /v1/chat/completions`、
`Authorization: Bearer ...`、`model`、`messages` 与 JSON Object 输出约束。地址可以省略
`/v1`，运行时会自动补齐；不要在地址末尾再加 `/chat/completions`。

验证本地配置并运行远程沙盒：

```bash
uv run python scripts/run_baseline_openai.py
```

提交代码不会读取 `.env`，也不会包含 API Key；正式评测使用赛方注入的 LLM 实例。
