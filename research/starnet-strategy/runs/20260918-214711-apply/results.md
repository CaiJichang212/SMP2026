# Apply 结果（本地Review完成）

- 应用：src/starnet/policy.py与model.py从实验原型经审阅整理；新增LLM单步屏蔽、邻居更新、校准证据保留、计划防护。本地transport/对照逻辑独立在local.py/experiments.py，不打包。
- Python3.9轻量契约测试25项通过；含所有话术排列、坏JSON、超预算、bool编号、重复目标、通信耗尽、LLM超时、无自动后备干预、屏蔽图更新、ZIP独立解压与确定性。
- 完整CaseVO/Python3.12真实LLM：种子41，-75.28→77.27，8调用/23步/70.51秒；种子42，-995.01→139.43，20调用/87步/200.24秒。官方公开沙盒，不是隐藏平台。
- ZIP SHA256：e643b36711591c8f3e31a52db80ff0587f1df8277ca9904cf167307c18f5a543。
- 公共fixture再生检查发现Python3.9/3.12的sum在original_total末位有5e-14差异；生成器现明确保留3位小数，与固定41/42/43 JSON完全一致。固定文件与已测ZIP均未改变。
- 100节点复赛规模验证通过；最终结果见../../report.md与Review记录。
