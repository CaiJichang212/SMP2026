# 决策（2026-09-18）

## Selected approach
公开图完整扫描、同节点话术反馈校准、度数/人设/边际递减辅助生成候选，单个CaseVO指挥Agent由真实LLM批准有限批次动作。游说为主；允许LLM在w<-20且度数>=3的已知节点上选择屏蔽，每次仅一个，执行后重建邻居并重规划。暂不启用切边。

## Why it won / Evidence summary
见runs/20260918-214506-comparison-matrix：9个自建种子的36个完整远端实验。反馈策略解决话术编号变化；结构增强平均收益最高且9种子均高于自然分，但2种子相对纯反馈退化。因此将其呈现为有风险的候选、明确要求LLM比较通信机会成本，不能声称已有精确共识模型。

## Rejected approaches
- 固定prompt1：在负话术排列上损害得分。
- 纯算法作为提交：不合规；只作实验对照。
- 无条件自动屏蔽、精确共识公式、切边：缺少稳健逐动作收益证明，不自动执行，也不套用论文保证。
- 原始SDK直接提交：包含未授权环境方法、过时50限制与缺失预算/失败检查，保留原件作参考。

## Requirements
仅5个公开API；每步一动作；120/250调用和步数分别限制；全部动作有LLM计划授权；校准与屏蔽单步反馈，扫描最多8、游说最多4；计划执行前再验预算、节点、通信次数。LLM坏JSON最多重问一次，超时停机；环境变更请求不重试；异常只记录类型，不打印凭证。保留注入LLM，不硬编码替代服务。

## Application scope
src/starnet/{policy,model}.py、config.json与prompt模板；scripts研究/真实运行/打包工具；tests；公开data/public_seeds；submissions ZIP；README与研究报告。参考SDK和外部casevo不修改。

## Required validation
Python3.9策略及安全契约测试、真实CaseVO运行、真实LLM+官方自建小图/50节点验证，必要时100节点；ZIP独立解压运行、AST合法API审查、密钥排除、打包哈希。若真实策略低于自然均分，返回Explore而不宣称完成。

## Risks
训练种子较少；隐藏人设/话术可能全负或有不同参数；未知话术探测存在损失；LLM可能不选算法对照最佳动作。新增LLM组合的成绩必须单列。官方glm-4-plus及旧agent_mesa尚未在评测机验证。

## Exceptions
本地已有完整CaseVO环境为Python3.12，项目轻量依赖按uv.lock用Python3.9；两层证据分开。旧agent_mesa在PyPI未找到、官方隐藏种子与提交身份不可用，相关平台门槛明确延后，最终包只宣称本地验证，不冒充正式完赛。

应用时邻接整理：可复用的本地HTTP/LLM客户端和公开实验逻辑移到src/starnet/local.py、experiments.py，scripts只保留命令行入口；它们不进入ZIP。
