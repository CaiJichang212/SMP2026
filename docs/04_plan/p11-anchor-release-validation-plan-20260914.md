# P11 anchor 发布验证方案

日期：2026-09-14。状态：**未执行，候选已拒绝，归档供后续发布链设计参考**。
不得据此启用策略或打开 1401--1403 确认集。

## 0. 归档结论

本方案的前置条件最终未满足。anchor full-development 在第 187/252 case
`p9:ws_resampled:901:centered_independent:wide:24.0_7.0_-12.0` 触发预注册
worst-pair 提前否决：anchor minus original P11 为 `-47.081441`，低于 `-10`
底线。结果为 `complete=false`、`aborted=true`、`development_gate_passed=false`。

失败并非入口或依赖问题。该 case 中 anchor 节点的 selected-prompt 首轮等效响应为
`8.867232`，低影响 ID 探测节点对应值为 `25.505976`。单一高图影响节点并不保证响应
幅度具有总体代表性；低 anchor 先验使候选过早枯竭，anchor 只执行 80 个动作，而原 P11
执行 87 个动作并高出 `47.08`。因此不接入 canonical、不运行 anchor 360 确认，也不
放宽门槛。

原始低节点 P11 已独立通过 252 开发门禁，其冻结 `07ac5f9` 策略与 360 新确认不受
anchor 附加候选失败影响，应沿原 P11 协议继续。以下内容仅记录：如果未来另一个 anchor
类候选先通过完整开发门禁，如何避免混淆 research 与 release 证据。

## 1. 决策边界

本方案只在 `p11-anchor-full-development-20260914` 完整通过预注册门禁后执行。
36-case anchor 初筛和当前 252-case overlay 都是 research 执行：runner 创建
`ParticipantSquadModel` 后替换 controller。它们能证明算法候选的收益，但不能证明未来
canonical entry 已接线，也不能用旧 source hash 回填为 canonical 证据。

选择最稳妥的最小复算路径：

1. 一次性把 anchor 接入 canonical，但资格常量继续为 `None`，普通构建仍执行 P9。
2. 在这一个冻结 canonical snapshot 上重新 fresh 执行 252 个 anchor candidate。
3. 同 case 的 P9、known-best-ID 和 fixed1-magnitude 参考臂从已经严格审计的原始
   252 raw 精确复制并再次重放审计，不重新执行。
4. canonical 252 通过后才生成并运行 360 个 fresh confirmation anchor candidate；
   参考臂只在现有 cache helper 能证明状态等价时复用。
5. 统计、入口、Python 3.9 和最终 ZIP 四类证据分别封存，不能互相替代。

不采用“旧 overlay 252 + 新 canonical 360 直接 seal”的省算力方案。它要求放宽
development/confirmation source snapshot 一致性，无法证明 entry 接线和被确认的策略体
属于同一版本。

## 2. Canonical 失效关闭接入

使用新模式名 `prompt_learning_anchor`，避免旧的 `prompt_learning` 报告或资格元数据
误启用 anchor。一次 canonical integration commit 应同时完成：

- 将 `p11_response_anchor_experiment.py` 放入 `INLINE_MODULES`，顺序位于基础 P11
  runtime 后、submission entry 前；
- `ParticipantSquadModel` 仅在资格函数返回 `prompt_learning_anchor` 时构造
  `AnchoredPromptLearningController`；原 `prompt_learning` 分支保持原控制器；
- anchor controller 显式报告 `p11_experiment_mode="prompt_learning_anchor"`；
- qualification 接受两个已知模式的精确匹配，但三个常量保持 `None`；
- config 请求 anchor 模式仍不能越过空资格；
- baseline runner、build source coverage 和 disabled-compatibility manifest 覆盖新增模块；
- 未知、缺失、拼写错误或只有 config flag 的模式全部回退到 P9。

接入后冻结 commit 和完整 source snapshot，再执行：完整单测、build、validate、Python
3.9 AST/import，以及 disabled P9 的逐动作兼容检查。后续统计运行期间不得修改 snapshot
内任何文件。

## 3. Canonical 252 开发审计

新增独立协议、runner 和 analyzer，命名中包含 `p11-anchor-release`；不得修改原
`p11-full-policy-validation-20260914` 的协议、raw 或 audit。

每个开发 case 的新执行只有 anchor candidate。参考证据按以下映射复用：

| 新审计臂 | 来源 | 处理 |
| --- | --- | --- |
| anchor | 冻结 canonical anchor source | fresh 执行并保存完整公开动作 |
| P9 no-probe | 原 252 raw 同 case | 字节级复制，记录源 raw SHA、case ID、action SHA |
| known-best-ID | 原 252 raw 同 case | 同上 |
| fixed1 magnitude | 原 252 raw 同 case | 同上 |
| original P11 | 原 252 raw 同 case | 仅作 anchor 增量诊断，不参与发布主臂替代 |

analyzer 必须先验证原 raw SHA 和已发布 strict-audit SHA，再逐臂重放预算、合法性、
公开返回、终局分数与 action hash。复制的参考记录必须与源 row 完全相等；不得重新标成
`fresh_execution`。anchor 还需验证：prompt ID、probe nodes 和 probe budget 与原 P11
一致；anchor 至多一次；总校准预算不超过 14；成功、失败、跳过和裁剪状态自洽；每个
host step 最多一个动作。

发布开发 estimand 是 anchor minus P9，不是 anchor minus original P11。应用原 P11
完整策略的 topology-block bootstrap、探索成本、known-ID gap、编号对称和资源门禁，
并额外要求已预注册的 anchor-minus-original-P11 full screen 通过。输出
`selected_variant="prompt_learning_anchor"` 和 canonical source snapshot。

这样只需 252 次新 candidate 执行，不重复 756 次已经审计且同 case 完全相同的参考臂。

## 4. 360 新确认

只有 canonical 252 audit 通过后，才允许 generator 打开预留的 1401--1403 case。
确认协议沿用已冻结的 360 设计：288 core、48 edge、24 degree stress，不增删观察后不利
的 strata 或门禁。

所有 360 个 anchor candidate 必须 fresh 执行。P9、fixed1 magnitude 和 known-ID
参考可以使用 `p11_reference_cache.py` 已证明的等价变换：

- P9/fixed1 只在完整 seed state 和实际 prompt-1 强度相同的 sibling 间复用；
- known-ID 只在最佳强度相同且 helper 可重放产生目标 action log 时重标；
- tie、zero、all-negative、clip 和 degree stress 不因结果不利而跳过；
- cache row 保存 source case、reuse kind、源/目标 seed hash 和可再生 action hash；
- anchor candidate 永不缓存。

confirmation analyzer 使用 canonical 252 完全相同的 source snapshot，执行原 360 门禁，
并增加 anchor 资源/状态审计。任何 snapshot 差异、anchor 错误、非法动作、非有限值、
case 缺失或 cache 不可重放都使确认失败。

## 5. 独立资格与 release chain

保留现有低 P11 release chain 的默认语义。anchor 使用独立协议和 artifact 名称；公共
helper 可以参数化，但默认参数必须继续验证旧的
`PromptLearningRuntimeController/prompt_learning`。

anchor seal 至少绑定：

- anchor release protocol SHA；
- canonical 252 development audit 与 360 confirmation audit；
- 两者完全相同且覆盖全部 INLINE/config/prompt 的 source snapshot；
- `selected_variant="prompt_learning_anchor"`；
- controller 类型 `AnchoredPromptLearningController`；
- `p11_experiment_mode="prompt_learning_anchor"`；
- probe、anchor、selected-prompt dispatch、action/planning/runtime 均为有效状态；
- clean real-LLM entry、Python 3.9 + NetworkX 3.1 entry 和 modern entry；
- 三个 entry 的 model SHA、seed SHA、动作 SHA 和分数按协议一致。

入口证据必须由 canonical anchor 的临时未发布 assembly 生成，并标记
`unreleased_candidate_assembly=true`。旧低 P11 entry 即使动作碰巧相同也不能复用，
因为 controller 类型、模式、model SHA 和 anchor diagnostics 不同。

seal 通过后只修改 qualification 的三个文字常量为 anchor 模式、anchor activation
report 路径和 SHA。anchor 使用独立 source manifest，例如
`p11-anchor-release-sources-20260914.json`；不得覆盖低 P11 manifest。最终 verifier 将
激活后的 assembly 把 qualification 元数据还原为冻结值，必须精确得到已测试的未发布
model SHA，从而证明除资格元数据外没有策略变化。

## 6. 最终 ZIP 验证顺序

1. metadata-only activation commit；
2. 写入并验证 anchor 独立 source manifest；
3. 完整单测、build、validate；
4. Python 3.9 + NetworkX 3.1 直接导入最终 assembly；
5. package 生成根目录仅含 `config.json`、`prompt/`、`starnet_model.py` 的 ZIP；
6. 对 ZIP 内实际 `starnet_model.py` 运行 final-entry case，要求
   `unreleased_candidate_assembly=false`、`final_zip_execution=true` 和 archive SHA；
7. verifier 检查唯一成员、文件字节、source manifest、activation report、entry 证据、
   metadata-only reconstruction，最后才写 `release_gate_passed=true`。

官方分数只能在提交该最终 ZIP 后填写，不能由本地开发/确认均值推算为大于 900。

## 7. 停止条件

以下任一条件成立即保持当前低 P11 或 P9，不生成 anchor 发布 ZIP：

- 当前 overlay 252 anchor screen 未完整通过；
- canonical 252 的 anchor-minus-P9 任一原门禁失败；
- 360 confirmation 任一 core/full/stress/edge/resource 门禁失败；
- research 与 canonical source 被错误声称为相同；
- entry 不能证明 anchor 实际使用，或 Python 3.9 与 modern 动作不一致；
- final ZIP 不能还原到已确认策略体，或出现 `TypeAlias` 等 Python 3.9 不兼容导入。
