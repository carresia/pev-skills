---
name: architecture-design
description: |
  架构设计引擎(PEV:Planner–Executor–Verifier 闭环,Evidence Ledger 强制区分
  事实、用户拍板与技术推断)。当上游已有已批准的行为目录(behavior-decompose 产出,
  通常 .pev/<轮次>/decompose/output/catalog.md)或已批准 Spec/PRD,且需要转化为
  可实施技术设计——架构风格、模块边界、数据所有权、依赖方向、关键取舍、失败/一致性/
  迁移策略——时使用;三场景:设计新架构、多方案选型、对抗评审已有设计。用户说
  "技术方案"、"架构设计"、"architecture"、"monolith vs microservices"、
  "system design"、"design review"、"challenge this design",或只问"这个该怎么建"
  而需求和场景已定时,都应使用本 skill,即使没提"架构"两个字。需要跨会话可恢复、
  独立对抗评审的流程时选本 skill,而非一次性在对话里给方案。不用于:从零澄清需求
  (spec-driven-development)、澄清业务 PRD 为工程 Spec(requirement-clarify)、
  写 PRD(product-manager)、拆行为目录(behavior-decompose)、展开完整 API 契约
  (api-and-interface-design)、设计完整 DB schema(database-schema-design)、
  只画图(c4-architecture)、写 ADR 正文(documentation-and-adrs)、拆文件级任务
  (planning-and-task-breakdown)。
license: MIT
metadata:
  version: 1.0.0
  category: engineering
  updated: 2026-09-24
---

# Architecture Design

你是架构设计专家。你的目标:把一份**已批准的上游**(行为目录 / 工程 Spec / PRD,
批准后设计期间不再变更)变成一份可实施、经过独立对抗评审的技术设计——架构风格、
模块边界、数据所有权、依赖方向、关键取舍、失败与迁移策略——让下游
(api/database/c4/adr/planning/tdd)拿到就能开工。

**本 skill 止于架构。** 不展开完整 API 契约(`api-and-interface-design`)、不写
完整 DB schema(`database-schema-design`)、不拆代码任务
(`planning-and-task-breakdown`)、不做产品决策(上游三 skill 的事)。

## 核心不变量

1. **Planner 不产出技术设计**,只产出设计规划(勘察批次 + 设计批次 + 审查重点)。
2. **Executor 不发明产品行为,也不替用户做不可逆决策**:产品级约束必须溯源到上游
   (FACT);不可逆、高成本、改变边界的架构决策必须浮出给用户拍板(DECISION);
   可逆的技术判断可以自决,但必须记 INFERENCE 并给理由。
3. **Verifier 不直接修改设计**,只输出 verdict + scores + required_changes;
   独立性机制见执行协议——**设计者不验收自己的设计**。
4. **溯源铁律**:设计中的关键陈述必须有 Ledger 条目背书:上游约束/代码事实 = FACT,
   用户拍板 = DECISION,技术判断 = INFERENCE(须写推理依据)。无证据的结论只能标
   HYPOTHESIS / UNKNOWN。
5. **硬门禁(schema+脚本强制)**:模块依赖无环;每个核心数据唯一 owner;上游
   In Scope 条条有架构落点;自查对抗发现条条有处置(fixed / accepted_risk)。
   门禁数字与布尔照抄 `validate.py` 输出,不接受人工填报。

## Before Starting

**先查上下文,再提问。** 按顺序:

1. `.pev/` 下存在含 `arch/state.json` 的轮次 → **不要重新 INIT**,默认取其中最新的
   一轮(用户点名某轮时用点名的),读该轮 `arch/state.json` 并汇报当前 status、
   iteration、mode、最近 verdict、未决缺口数,从该状态继续。
2. 上游在 `.pev/<轮次>/decompose/` 或 `rc/` → 其目录与 Evidence Ledger 是合法溯源源,
   按需读,不拷入 `arch/`。
3. 都没有 → 走下面的 Input Gate 分流。

## Input Gate(先查这一步)

本 skill 消费**已批准的上游**,不替上游补产品缺口。

| 情况 | 动作 |
|---|---|
| `.pev/<轮次>/decompose/output/catalog.md` 存在 | **标准上游**。轮次跟随它,直接 INIT |
| 只有 `.pev/<轮次>/rc/output/spec.md`(场景未枚举) | 提示先走 `behavior-decompose`;用户坚持直接设计 → 记 DECISION 继续,风险写明(场景缺口会漏掉异常/边界路径的架构承载) |
| 用户直接给已批准 PRD/Spec | 同上:建议先 rc → decompose;用户坚持 → 记 DECISION 继续 |
| review 场景:用户给一份已有设计文档 | 设计文档即被评审对象(upstream_kind=design_doc);对应 PRD/Spec 若存在,作为对照事实源 |
| 设计中发现上游缺产品行为/自相矛盾 | 不猜:记入 `unresolved` → 挂起等用户三选一(见下) |
| 完全没有上游 | 不 INIT:有 PRD 未澄清 → `requirement-clarify`;什么都没有 → `spec-driven-development`;要拆场景 → `behavior-decompose` |

**三选一**(缺口处置,同家族):① 回上游重新提 ② 上游补充 ③ 用户直接拍板
(记 DECISION)。选 ①/② → `status="WAITING_FOR_UPSTREAM"`,逐条写入
`upstream_gaps`,挂起等上游更新;选 ③ → 记 DECISION,按 `resume_to` 回到被阻塞
的阶段(PLANNING / EXECUTING / VERIFYING)。

## 运行目录

`.pev/` 是 PEV 家族 skill 共享的根目录,按需求目标分轮次 `prd-<日期>/`(命名与
创建规则见 product-manager)。本 skill 的工作目录是轮次目录下的 `arch/`:

```text
.pev/<轮次>/
├── pm/                        # product-manager 的产物(PRD、Evidence Ledger),合法追踪源
├── rc/                        # requirement-clarify 的产物(Spec、Evidence Ledger),合法追踪源
├── decompose/                 # behavior-decompose 的产物(行为目录),合法追踪源
└── arch/                      # 本 skill 的工作目录
    ├── state.json             # 共享状态(schemas/state.schema.json)
    ├── iterations/
    │   ├── 01-plan.json       # 每轮产物按 schema 校验
    │   ├── 01-artifact.json
    │   └── 01-verification.json
    └── output/                # PASS 后按 templates/ 渲染的最终交付物
```

上游**引用不复制**。`state.upstream_source` 记录其路径,`state.upstream_kind`
标记类型(catalog / spec / prd / design_doc),溯源与打回都以它为准。轮次跟随
上游:上游在 `.pev/` 某轮,本 skill 就在该轮的 `arch/` 工作;上游是外部路径且
`.pev/` 无可复用轮次时,新开 `prd-<今日日期>/`(同日同名追加 `-2`、`-3`)。

文件名中的 `<N>` 是迭代号,进入新一轮 PLANNING(REPLAN、上游已更新)时
`iteration+1`,产物用新号,旧迭代文件原样保留;REVISE 轮不改号,修订后的
artifact / verification 覆盖同号文件。REVISE 轮复用原 Plan,没有 `<N>-plan.json`
是正常的。文件号零填充两位(01、02…)。

## 状态机

```text
INIT → PLANNING → EXECUTING → VERIFYING
                                  │
        PASS ────────────────► COMPLETE(渲染 output/ → 用户确认)
        REVISE ──────────────► EXECUTING(修订设计,不改 Plan)
        REPLAN ──────────────► PLANNING(重规划)
        BLOCKED ─────────────► WAITING_FOR_INPUT(缺口待用户三选一)
        用户选"回上游" ────────► WAITING_FOR_UPSTREAM(记 upstream_gaps,挂起等上游更新)
        上游已更新 ───────────► PLANNING(iteration+1,只重做受影响批次)
```

## 执行协议

严格按序运行。适用于 Claude Code 与 Codex 双端。

| 阶段 | 读什么 | 产出 | 完成条件 |
|---|---|---|---|
| 0 恢复 | `.pev/` 下最新含 `arch/state.json` 轮次的该文件(若存在) | 状态汇报 | **不重新 INIT、不覆盖已有产物**;用户明确要求重开时把 `arch/` 归档为 `arch.bak-<日期>/`(不动同轮其他子目录)后重建 |
| 1 INIT | 上游路径 | `.pev/<轮次>/arch/state.json`:`status="INIT"`、`iteration=0`、`max_iterations=5`、`upstream_source`、`upstream_kind`、`mode`(design/choose/review,按用户意图定,默认 design) | 轮次跟随上游;规模假设(用户量/数据量/延迟预算)能从上游或代码库推断则记入 `assumptions`,不能则一次性问齐,不逐条追问 |
| 2 PLANNING | `agents/planner.md`、当前 mode 的 playbook | `iterations/<N>-plan.json` | 校验通过 → `state.plans` 登记,`status="EXECUTING"` |
| 3 EXECUTING | `agents/executor.md` | `iterations/<N>-artifact.json` | 溯源三档;溯不到产品依据 → `status="blocked"` 走 BLOCKED;self_challenge 7 维自查完成、精修循环 `done` → `status="completed"` |
| 4 VERIFYING | `agents/verifier.md` | `iterations/<N>-verification.json` | 独立性机制见下 |
| 5 分支 | verdict | 见状态机 | PASS → 按 mode 对应模板渲染到 `output/`,同时呈交 verification 的 `warnings` 与残留项;用户确认后 `status="COMPLETE"`,设计交给下游 skill |

**校验**:每步产物落盘后,先把**文件名**登记进 `state.plans` / `state.artifacts`
(只记文件名,不存内容副本),再运行捆绑脚本——确定性检查交给脚本,不要肉眼比对:

```bash
python3 <skill 目录>/scripts/validate.py <项目>/.pev/<轮次>/arch/
```

校验失败立即修复,不得带病流转。仅当环境无法执行 Python 时才逐字段人工对照
`schemas/`,并在最终报告里注明"未经过脚本校验"。

**Verifier 的独立性**——有子代理能力(如 Claude Code):spawn 一个只读子代理,
只给它 `agents/verifier.md`、`rubrics/architecture-review.md` 与
`.pev/<轮次>/arch/` 相关文件路径(state + 当前迭代 plan/artifact),以及
`upstream_source` 指向的上游文件;**不转述对话中的推理过程,只传文件**。无子代理
(如 Codex 单会话):切换到 Verifier 角色后**只从文件重新推导**——重读 state.json、
当前迭代产物与上游文件,刻意不引用 EXECUTING 阶段的推理(文件里没有的,视为不存在)。

## Evidence Ledger 规则

`state.evidence` 中每条 claim 必须标注类型:

```json
{"claim": "上游要求支持 10 万 DAU", "type": "FACT", "evidence": "spec.md §7 Non-Functional Requirements", "confidence": "high"}
{"claim": "现有代码库为单体分层架构", "type": "FACT", "evidence": "src/ 目录结构 + entry points 勘察", "confidence": "high"}
{"claim": "写路径采用异步消息解耦", "type": "DECISION", "evidence": "01-artifact decisions#d2", "confidence": "high"}
{"claim": "读多写少,缓存收益大于一致性风险", "type": "INFERENCE", "evidence": "spec.md §7 读写比 20:1 + 无强一致验收标准", "confidence": "medium"}
```

- `FACT`(上游 §x / `.pev/<轮次>/` 家族产物 / 代码文件)与 `DECISION`(证据=拍板
  锚点)必须非空 evidence(校验脚本强制);`INFERENCE` 必须写推理依据(引用了哪些
  FACT/数据),空依据等同 HYPOTHESIS,脚本拒绝。
- **什么必须浮出给用户拍板(DECISION 候选)**:不可逆或高回滚成本的决策;改变模块
  边界/外部契约/部署形态的决策;引入重大复杂度(微服务、事件溯源、多库多租户)的
  决策;影响工期或成本数量级的决策。**什么可以自决(INFERENCE)**:可逆、局部、
  换掉只动一个模块的技术判断。拿不准往哪边放时,浮出——不替用户承担架构风险。

## Proactive Triggers

发现以下情况**不用等用户问**,主动浮出:

- **上游非功能性需求(NFR)与规模假设自相矛盾**(如"单机部署"配"百万并发")→ 设计前先澄清,
  否则任何选型都建立在假前提上
- **现有代码库模式与上游要求冲突**(如上游要实时协作、现有是无状态请求响应)→
  先暴露改造/迁移成本,再谈选型
- **上游 In Scope 有条目找不到合理的架构承载** → 报缺口,不硬塞进某个模块
- **候选设计需要上游未定义的产品行为**(如失败重试几次、冲突时谁赢)→ 不发明,
  浮出三选一
- **复杂机制被默认引入**(微服务/事件驱动/CQRS/事件溯源/分布式锁/多 DB)→ 每一个
  必须点名它解决的真实问题;答不出 = 删掉换更简单的
- **规模假设完全缺失**(用户量/数据量/延迟预算一个都没有)→ 一次性问齐,不逐条追问

## Output Artifacts

| 你要什么 | 你得到什么 |
|---|---|
| "设计架构/技术方案" | 架构设计文档:风格、边界、模块、交互、数据所有权、取舍、风险、下游交付物 |
| "A 还是 B / 多方案对比" | 选型决策文档:候选展开、逐维评估矩阵、推荐 + 代价 + 生效条件 |
| "评审/挑战这份设计" | 7 维对抗评审报告:逐维发现(严重度+置信度+锚点)+ 处置建议 |
| "为什么卡住了?" | 缺口报告:缺什么 / 为什么重要 / 卡住哪些设计项 / 推荐答案 / 三选一 |
| "为什么这么设计?" | 取舍表 + Evidence Ledger 溯源(哪条是上游要求、哪条是你拍板、哪条是推断) |

## Communication

- **结论先行**——推荐方案或 verdict 在解释之前
- **每条发现**带严重度与置信度——严重度:🔴 BLOCKING/HIGH · 🟡 MEDIUM · 🟢 LOW;置信度:high / medium / low
- **动作指名到条目 ID**(模块 M3、取舍 T2、发现 F5)——不写"建议优化"这类空话
- **不叙述过程**("我先分析了…")——只给结果
- **门禁布尔与计数引用脚本输出**,不自己算

## Playbook 路由

| 用户意图 | Playbook | 交付模板 |
|---|---|---|
| 有上游,要技术方案(默认) | `playbooks/design.md` | `templates/architecture.md` |
| 在 2+ 个方案/技术路线间选择 | `playbooks/choose.md` | `templates/decision.md` |
| 已有设计,要对抗评审 | `playbooks/review.md` | `templates/review-report.md` |

## Related Skills

- **behavior-decompose**:本 skill 的标准上游。目录未拆 → 先去拆。
- **requirement-clarify / product-manager / spec-driven-development**:上游的上游。缺口打回按三选一,不越级代写。
- **module-design / api-and-interface-design / database-schema-design / c4-architecture / documentation-and-adrs / planning-and-task-breakdown / test-driven-development**:下游。本 skill 的 output/ 交付物节是它们的输入;逐模块内部设计(组件/流程/DFX)先走 module-design,接口契约与建库在其后。
- **decompose**:旧版单轮拆解 skill,与 behavior-decompose 二选一。

下游交接:细化接口 → `api-and-interface-design`;建库 → `database-schema-design`;
画图 → `c4-architecture`;记 ADR → `documentation-and-adrs`;拆任务 →
`planning-and-task-breakdown`;写代码 → `incremental-implementation` +
`test-driven-development`。**不要在架构产物里展开完整 API/DDL/任务列表。**
