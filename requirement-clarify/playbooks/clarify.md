# Playbook: Clarify(PRD → 工程 Spec)

## 适用

上游已有业务 PRD(`.pev/<轮次>/pm/output/prd.md` 或用户提供),需澄清为工程 Spec。

## 前置条件

`state.prd_source` 存在且可读。无 PRD → 分流:还没 PRD 用 `product-manager`,
从零澄清写 spec 用 `spec-driven-development`,本 skill 不启动。

Spec 要交给 OpenSpec 工作流时:变更目录已由 `openspec new change` 创建,
init 时加 `--deliver-to <变更目录>` 登记;PASS 收口自动把 spec.md 交付到
该目录,执行状态与决策记录仍留在 `.pev/<轮次>/rc/`。未登记的轮次照旧只
发布 `rc/output/spec.md`。

## Plan 骨架

1. `interrogate_value` — 价值性问题一批(为什么做/价值假设/不做会怎样/成功长什么样),锚 PRD §背景/§目标 与上游 Evidence Ledger。
2. `interrogate_ambiguity` — 逐章扫描落地模糊地带(业务规则/权限与状态/异常与边界/数据口径/范围),一批或多批。
   两批清单作为 `grilling` 决策树的初始节点,先追踪事实,再逐轮提问。每轮顺序固定：先提交 status="blocked" 的 Artifact，确认 state 为 WAITING_FOR_INPUT，再向用户提问；当前 frontier 必须一次性包含所有前置条件已解决的未决问题。用户答复后先提交 state-update 恢复 EXECUTING，再重算 frontier 或进入锁定确认；依赖本轮未决答案的问题不得进入当前 frontier，必须留到后续轮次。AskUserQuestion 最多 4 题只是交互载体限制，不得改变 grilling frontier 的轮次语义；frontier 超过 4 题时不得使用 AskUserQuestion 压缩或拆分问题，必须用完整文本轮次一次性列出全部编号问题、推荐答案与处理路径。每题保留推荐答案，以及“①回 PM 重新提需求 ②PM 补充需求 ③直接答复”。frontier 清空后仍必须展示锁定决策清单，并取得用户共识确认。 rc 的 blocked Artifact、`WAITING_FOR_INPUT` 和 `state-update` 负责每轮状态及 DECISION 台账;用户确认锁定决策清单后再进入完成草稿。
3. `draft` — 闭环答案聚合为 Spec 正文,按 `templates/spec.md`:产品定义引用不重写,澄清结论逐条标来源。
   - §10 实施决策(≤8 条):模块职责、接口与数据约束级;不含待改文件路径。只在澄清中确有依据时写;缺依据就留空,不得为填段虚构决策。
   - §11 测试决策(≤8 条):每条 = 用户可观察的外部行为 + 验证方式;只测外部行为,不测内部实现。
   - §12 Out of Scope(≤8 条):本变更明确不处理的事项与原因,与 §13 Boundaries(行为边界)互补。

## 最终交付

`templates/spec.md`。

## Verifier 侧重

- 覆盖完备/可落地必查:PRD §5 每条 In Scope 与 §6 每项数据需求 → Spec 工程落点,缺 → REVISE。
- §6 数据需求必须已转化为工程项:需新增的埋点/口径未列入工程范围 → REVISE。
- 溯源必查:答案无 FACT/DECISION 来源 → 记 evidence_gaps,不可作为 Spec 依据。
- §10–§12 逐条核来源:实施决策/测试决策/排除范围条目无来源或来源不成立 → 记 evidence_gaps;条数超上限 → REVISE。空段不是缺陷,虚构决策才是。
