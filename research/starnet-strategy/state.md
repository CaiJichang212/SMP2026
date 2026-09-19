# 研究状态
- Status: v2-local-review-pass-official-950-pending (2026-09-19)
- Research item: 从用户反馈官方531.1233继续优化；目标官方≥950。
- Theme/domain: 部分可观测网络干预，LLM核心决策。
- Current best strategy: V2归一化图代理、结构边际及剩余游说预算比较，由LLM批准动作。
- Completed runs: Prepare、Specify、Baseline、Explore、Compare、Decide、Apply、Review（本地）。
- Evidence summary: V2真实LLM50节点配对666.0733→798.0300，+19.8111%，2胜1平；40项测试、100节点及真实断边验证通过。详见report-v2.md。
- Open questions: V2在官方旧agent_mesa/指定GLM/隐藏种子上的新分数；尚不能证明≥950。
- Next phase: 官方平台Review；新分数未达950或报错则重新Explore，使用未见种子验证。
- Handoff: V2及完整验证报告已就绪；原包531.1233为用户反馈，原包保留。新版交接见下文。
- Documentation review (2026-09-18): 根据提交ZIP及已有实验记录新增 `docs/方案/starnet-20260918-方案说明.md`；记录于 `runs/20260918-231219-documentation/`。未更改模型/ZIP，未追加远端试验；平台验收仍待完成。

## Reopened 2026-09-18: target 950
- Status: specified; next Baseline / Explore.
- User-reported official incumbent score: 531.1233; reported top1: 948.58.
- New spec: runs/20260918-231900-spec-950/plan.md.
- Preserve previous decisions and ZIP; calibrate topology marginal estimates and
  expand paired custom-seed matrix before selecting a replacement.
- Baseline completed: 38 public-sandbox unit-response observations support a
  component-normalized degree+1 proxy on six small graph families. Explore active:
  topology marginal gains and communication-budget completion; no final changes.
- Explore completed: six official paired seeds, candidate168.9583 vs heuristic
  control122.4167,6/6wins; low-degree calibration rejected. ProxyMAE0.5106.
  Next Compare: frozen held-out matrix; final model and original ZIP unchanged.
- Compare completed: official holdout666.445 vs636.765,4wins/1tie/1loss,
  proxyMAE0.3322. Reopened Explore for communication-response uncertainty;
  new holdout144-161 reserved. No claimed official950 result.
- Decision ready: apply nominal topology completion, keep uncertainty stress as
  LLM advice rather than hard filtering. Required next: realLLM old/new paired
  review120/124/134,100-node and negative-prompt boundary, package validation.
- Applied: V2 ZIP38f37e00...,39 Python3.9 tests pass. RealLLM review active:
  first successful pair120 old-37.19 -> V2+243.98 (delta+281.17), authorized
  actions/budget checked. First aborted ReadTimeout attempt excluded, preserved.
- RealLLM paired review complete:50nodes120/124/134, old666.0733 -> V2 798.0300,
  +19.8111%,2wins/1tie,132LLM calls total.100node actualZIP:461.36 vs natural
  -1211.67,153steps/65calls,539.98s.40tests pass. Final cut smoke/handoff pending.
- Final local Review passed: actual cut(1,2)85.71→100,5LLM calls; byte-identical
  rebuild and secret checks pass.8successful realLLM episodes,1failed attempt
  excluded and preserved. Official950 remains unverified; submission handoff next.
- Handoff completed (2026-09-19): Gmail returned SENT for the authorized email to
  li_y_c@qq.com. This confirms provider acceptance, not recipient reading or
  platform submission. Await V2 official score/logs; official950 goal remains open.
