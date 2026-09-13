# ADR-004：评测环境 Python 3.9 兼容基线

## 状态

已接受，依据 2026-09-13 平台实际报错修订。

## 背景

仓库研发环境使用 Python 3.11+，本地 CaseVO 版本也要求较新的 Python。赛方
[`SMP2026常见问题解答.docx`](../../00_rules/SMP2026常见问题解答.docx) 没有写明
Python 小版本，但列出了线上预装包，其中包括：

- `networkx==3.1`
- `mesa==2.3.2`
- `typing_extensions==4.5.0`
- `requests==2.29.0`
- `numpy==1.24.3`

平台导入 `starnet-p8-mean-20260913.zip` 时返回：

```text
cannot import name 'TypeAlias' from 'typing' (/usr/local/lib/python3.9/typing.py)
```

该 traceback 是线上解释器为 Python 3.9 的直接证据。首个 P8 包在本地 Python
3.12 中通过语法、导入、测试和打包检查，但内联模块从 `typing` 导入了 Python 3.9
不提供的 `TypeAlias`，所以在线上初始化策略之前失败。

## 决策

1. 仓库开发和测试继续使用 Python 3.11+ 与 `uv`，不降低项目依赖基线。
2. 最终 `starnet_model.py` 同时以 **CPython 3.9** 和 FAQ 中的
   **NetworkX 3.1** 为交付兼容基线。
3. 只用于类型标注的新版 `typing` 名称优先改写为无需运行时导入的形式。例如普通
   类型别名使用赋值，不导入 `TypeAlias`。确实需要 backport 时才从赛方已安装的
   `typing_extensions` 导入，并验证其固定版本提供该名称。
4. `scripts/validate_submission.py` 必须以 Python 3.9 grammar 解析生成文件，并拒绝
   已知的 Python 3.10+ `typing` 导入。
5. 提交前至少用 Python 3.9 直接导入最终 ZIP；测试必须针对 **ZIP 内文件**，不能只
   验证 `src/` 或构建前模块。
6. Python 3.9 导入测试可能生成 `__pycache__`。最终顺序必须是：完成动态测试，重新
   构建清理生成目录，再校验和打包。任何校验失败都不得继续上传。

## 实施结果

`TypeAlias` 已改成普通别名，策略计算和候选排序不变。修复后的 ZIP 在 CPython
3.9.25 与 `networkx==3.1` 下从 ZIP 根目录成功导入 `ParticipantSquadModel`；生成
文件引用的全部 NetworkX 名称均存在于 3.1。完整证据见
[`p8-python39-compatibility-20260913.md`](../../../experiments/reports/p8-python39-compatibility-20260913.md)。

修复包：`artifacts/submission/starnet-p8-mean-20260913.zip`，SHA-256：
`067d232f5360e67114d1bf0f1937a574f71b743cd2049cf6d20372a45eb06c50`。

## 后果

- “本地测试通过”不再等价于“线上可导入”；发布验收同时覆盖研发环境和交付环境。
- 新增内联模块、标准库导入或 NetworkX API 时，必须复查 Python 3.9 与 FAQ 固定版本。
- 若赛方更新 Python 或依赖清单，应依据新公告和一次真实导入结果更新本 ADR，不能仅
  根据本地环境推断。
