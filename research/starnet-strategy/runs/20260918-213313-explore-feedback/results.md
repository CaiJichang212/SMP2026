# 实测结果
- 证据：官方远端沙盒，自建种子21–26，每个10节点、预算30；不是隐藏评测。
- 环境：Python3.9锁定依赖，单核、2.5GiB、600秒上限。脚本 scripts/research_compare.py。
- 平均得分：{"natural": -94.12666666666667, "fixed": -15.030000000000001, "adaptive": 53.185, "structural": 95.48833333333333}。
- adaptive六种子均高于natural；fixed在22、25降分。structural在25比adaptive低3.30，其他相同或更高。
- 各动作日志、种子保存在explore/raw；可复核统计在metadata.json。各策略LLM调用0，仅算法研究对照。
- 协议发现：evaluate后session失效，必须在结算前读取余额；首轮读取404已修复，最终24条为完整重新运行。
- 下一阶段：独立50节点种子31–33验证，再决定正式LLM候选动作范围。

- 50节点31、32完成；33的fixed实验中出现RemoteDisconnected（服务端中途关闭连接）。不重试可能已生效的communicate，丢弃该局，保留已有日志，并以全新session重跑33整组。该失败不归为得分。
- 33重启后又在只读get_budget发生连接关闭；切换HTTP Connection: close规避复用失效连接，并再次从新session完整跑33。不在原写请求上自动重试。
