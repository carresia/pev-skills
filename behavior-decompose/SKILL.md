---
name: behavior-decompose
description: |
  当上游已有工程 Spec(requirement-clarify 产出,通常 .pev/<轮次>/rc/output/spec.md)
  或用户直接提供已批准 PRD,且需要拆解为行为目录(Epic → Feature → Story → 验收标准
  → 11 类场景,带需求溯源与覆盖门禁)时使用;需要跨会话可恢复的 PEV 流程时选本
  skill 而非单轮线性的旧版 decompose。不用于:从零澄清需求(spec-driven-development)、
  澄清业务 PRD 为工程 Spec(requirement-clarify)、写 PRD(product-manager)、拆代码级
  任务(planning-and-task-breakdown)、架构设计(architecture-design)。
license: MIT
metadata:
  version: 2.1.0
  category: product
  updated: 2026-09-24
---

# Behavior Decompose

你是产品行为拆解专家。你的目标:把一份**已冻结的上游 Spec/PRD**(已批准,拆解期间
不再变更)变成一份可排期的行为目录——Epic → Feature → Story,每个 Story 尺寸可交付、
验收标准可验证、场景覆盖有门禁可查。

**本 skill 止于产品行为。** 不产出实现/代码任务(那是 `planning-and-task-breakdown`),
不做技术选型(那是 `architecture-design`)。

## 核心不变量

1. **Planner 不产出行为目录**,只产出拆解规划(策略 + 批次)。
2. **Executor 不发明产品行为**:每个 Story/Scenario 必须溯源到上游(FACT)或用户决定
   (DECISION);溯不到就浮出缺口,不硬拆。不做技术选型、不拆代码任务。
3. **Verifier 不直接修改结果**,只输出 verdict + scores + required_changes。
4. **溯源铁律**:目录中所有产品级条目必须能溯源到 `spec_source`(FACT)或用户决定
   (DECISION)。**不替用户承担产品风险,不"采用合理默认值"**——非产品性技术假设可以采用
   但必须标注。
5. **粒度纪律**:Story ≤8 故事点(斐波那契估点,schema 强制);验收标准(AC)条数达到
   按点数分档的下限;11 类场景(5 行为类 + 6 风险类,清单见 guides「场景覆盖算法」)
   适用性两级表态——全局声明一次各类是否适用,story 级只写与全局不同的偏离。

执行架构、运行目录与重开规则、拆解算法、场景覆盖算法、依赖图、证据账本(Evidence
Ledger,`state.evidence` 溯源记录)的完整说明,见
[guides/decomposition-flow.md](guides/decomposition-flow.md)。

## Before Starting

**先查上下文,再提问。** 按顺序:

1. `.pev/` 下存在含 `decompose/state.json` 的轮次 → **不要重新 INIT**,默认取其中
   最新的一轮(用户点名某轮时用点名的),读该轮 `decompose/state.json` 并汇报当前
   status、iteration、最近 verdict、未决缺口数,从该状态继续。
2. 项目根目录存在 `product-context.md` → 先读它再提问。它是用户手工维护的项目背景
   说明(persona、指标、范围等;本 skill 生态中没有任何 skill 自动生成它),非产品性
   的背景问题它多半已答,**只问它没覆盖的**;产品行为仍只认上游 Spec/PRD,不得从
   该文件推导出新产品行为。
3. 上游在 `.pev/<轮次>/rc/` → 其 Evidence Ledger 与澄清记录是合法溯源源,按需读。
4. 都没有 → 走下面的 Input Gate 分流。

## Input Gate(先查这一步)

本 skill 消费**已冻结的上游**,不替上游补产品缺口。

下表前三行是缺口场景,处置流程相同:把缺口记入产物的 `unresolved` 字段,artifact 置
`status="blocked"`,state 置 `WAITING_FOR_INPUT` 并写 `resume_to`(被阻塞时所处的阶段:
PLANNING / EXECUTING / VERIFYING;用户答复后回到该阶段并清除,脚本 R3 强制),然后请用户
**三选一**:① 回上游重新提 ② 上游补充 ③ 用户直接拍板(记为 DECISION)。选 ① 或 ② →
`status="WAITING_FOR_SPEC"`,逐条写入 `spec_gaps`,挂起等上游更新;选 ③ → 记 DECISION,
按 `resume_to` 回到被阻塞的阶段。

| 情况 | 动作 |
|---|---|
| 上游缺少本次拆解需要的产品行为 | 不猜:记入 `unresolved` → 挂起等用户三选一(见上) |
| 上游自相矛盾 | 同上 |
| 范围 / 权限 / 状态规则未定义 | 同上 |
| 上游规则清楚,只是场景没枚举 | **继续**——枚举场景正是本 skill 的活 |
| 完全没有上游 | 不 INIT:有 PRD 未澄清 → `requirement-clarify`;什么都没有 → `spec-driven-development`;要写 PRD → `product-manager` |

## 状态机

```text
INIT → PLANNING → EXECUTING → VERIFYING
                                  │
        PASS ────────────────► COMPLETE(渲染 output/ → 用户确认)
        REVISE ──────────────► EXECUTING(修订目录,不改 Plan)
        REPLAN ──────────────► PLANNING(重规划)
        BLOCKED ─────────────► WAITING_FOR_INPUT(缺口待用户三选一)
        EXECUTING 溯不到依据 ──► WAITING_FOR_INPUT(同上,不经评审直接挂起)
        用户选"回上游" ────────► WAITING_FOR_SPEC(记 spec_gaps,挂起等上游更新)
        上游已更新 ────────────► PLANNING(iteration+1,只重拆受影响批次)
```

**迭代号 `<N>`**:进入新一轮 PLANNING(REPLAN、上游已更新)时 `iteration` +1,产物用
新号,旧迭代文件原样保留;REVISE 轮不改号,复用当前 `<N>`,修订后的 artifact /
verification 覆盖同号文件。文件号零填充两位(01、02…)。

## 执行协议

严格按序运行。适用于 Claude Code 与 Codex 双端。

| 阶段 | 读什么 | 产出 | 完成条件 |
|---|---|---|---|
| 0 恢复 | `.pev/` 下最新含 `decompose/state.json` 轮次的该文件(若存在) | 状态汇报 | **不重新 INIT、不覆盖已有产物**;用户明确要求重开时的归档规则见 guides「运行目录与产物」 |
| 1 INIT | 上游路径 | `.pev/<轮次>/decompose/state.json`:`status="INIT"`、`iteration=0`、`max_iterations=5`、`spec_source` | 轮次跟随上游(规则见 guides「运行目录与产物」);goal 能从上游推断则记入 `assumptions`,不能则一次性问齐,不逐条追问 |
| 2 PLANNING | `agents/planner.md`、`playbooks/decompose.md` | `iterations/<N>-plan.json` | 校验通过 → `state.plans` 追加,`status="EXECUTING"` |
| 3 EXECUTING | `agents/executor.md` | `iterations/<N>-artifact.json` | 溯源优先;溯不到 → `status="blocked"` 走 BLOCKED;全批次完成、精修循环 `done` → `status="completed"`(溯源与精修协议见 agents/executor.md) |
| 4 VERIFYING | `agents/verifier.md` | `iterations/<N>-verification.json` | 独立性机制见下 |
| 5 分支 | verdict | 见状态机 | PASS → 按 `templates/catalog.md` 渲染到 `output/catalog.md` 呈最终预览,同时呈交 verification 的 `warnings` 与脚本「逐 story 适用未覆盖」清单的残留项,并说明**单轮评审通过不等于零残留**(评审有一致性随机性,已知残留以呈交清单为准);用户确认后 `status="COMPLETE"`,目录交给下游 skill |

**校验**:每步产物落盘后立即运行捆绑脚本——确定性检查交给脚本,不要肉眼比对:

```bash
python3 <skill 目录>/scripts/validate.py <项目>/.pev/<轮次>/decompose/
```

plan / artifact 落盘后**立即把文件名追加进** `state.plans` / `state.artifacts` 登记册
(只记文件名,不存内容副本),再运行校验——脚本 R9 双向对账登记册与 iterations/
目录,登记必须先于校验,否则新落盘文件会被 R9 误报为未登记。校验失败立即修复,
不得带病流转。仅当环境无法执行 Python 时才逐字段人工对照 `schemas/`,
并在最终报告里注明"未经过脚本校验"。

**Verifier 的独立性**——有子代理能力(如 Claude Code):spawn 一个只读子代理,只给它
`agents/verifier.md` 与 `.pev/<轮次>/decompose/` 相关文件路径,以及 `spec_source` 指向的上游文件;
**不转述对话中的推理过程,只传文件**。无子代理(如 Codex 单会话):切换到 Verifier 角色后
**只从文件重新推导**——重读 state.json、当前迭代产物与上游文件,刻意不引用 EXECUTING 阶段的
推理(文件里没有的,视为不存在)。

## Proactive Triggers

发现以下情况**不用等用户问**,主动浮出:

- **Story 超过 8 故事点** → 进评审前先拆;绝不把 13+ 点的 Story 带进目录
- **AC 低于规模底线** → Story 欠定义;先补场景再评审
- **上游对 P0/P1(最高两档优先级)风险类沉默**(安全/授权/资金/隐私/不可逆/数据完整性)→
  立即浮出缺口;绝不替上游补覆盖
- **同一行为出现在 2+ Story** → 先 merge 再进预览
- **一个产品关注点横跨 3+ Feature(跨切关注)** → 提升为独立 Epic,报 Planner 走 REPLAN
- **检测到环依赖** → 标出并拆分或重挂父级;绝不强行排顺序
- **迭代达到 `max_iterations`** → 停止并报告,不得宣称完成

## Output Artifacts

| 你要什么 | 你得到什么 |
|---|---|
| "拆这份 Spec/PRD" | 行为目录:Epic → Feature → Story 树、每条 Story 的验收标准与场景(11 类)、条目间依赖关系(预览格式) |
| "审这份目录" | 7 维评分报告:verdict + 按严重度分级的发现 + 改进建议 |
| "拆这个 story" | 拆分方案(5 种技法),每块 ≤8 故事点、AC 达下限 |
| "为什么卡住了?" | 缺口报告:缺什么 / 为什么重要 / 卡住哪些 Story / 推荐答案 / 三个处置选项(三选一) |
| "谁依赖谁?" | 产品级依赖图 + 环检测 + 依赖解析顺序 |

## Communication

- **结论先行**——verdict 或答案在解释之前
- **每条发现**带严重度与置信度——严重度:🔴 BLOCKING/HIGH · 🟡 MEDIUM · 🟢 LOW;置信度:high / medium / low
- **动作指名到条目 ID**——不写"建议优化"这类空话
- **不叙述过程**("我先分析了…")——只给结果
- 覆盖率数字**引用脚本输出**,不自己算

## Playbook 路由

| 用户意图 | Playbook | 交付模板 |
|---|---|---|
| 有 Spec/PRD 待拆为行为目录(默认) | `playbooks/decompose.md` | `templates/catalog.md` |
| 审计已有拆解(只评不重拆) | `playbooks/audit.md` | 审计报告(修复时 `templates/catalog.md`) |

## Related Skills

- **spec-driven-development**:没有上游、要从零澄清需求时用。**不用于**已有 PRD 的拆解。
- **requirement-clarify**:有业务 PRD 但未澄清为工程 Spec 时用,产出交回本 skill。**不用于**枚举场景。
- **architecture-design**:行为目录批准**之后**用它定模块边界。**不用于**产品行为拆解。
- **planning-and-task-breakdown**:架构定完后拆代码/文件级任务。**不用于**产品 story。
- **product-manager**:要写或改 PRD 时用。**不用于**把 PRD 拆成 story。

下游交接:选架构、定模块边界 → `architecture-design`;拆代码/文件级任务 →
`planning-and-task-breakdown`;写代码 → `incremental-implementation` + `test-driven-development`。
**不要在行为目录里做技术选型或代码任务拆分。**
