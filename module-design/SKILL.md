---
name: module-design
description: |
  模块设计引擎(PEV:Planner–Executor–Verifier 闭环,Evidence Ledger 强制区分
  事实、用户拍板与技术推断)。当上游已有已批准的架构设计(architecture-design 产出,
  通常 .pev/<轮次>/arch/output/;或用户直接提供的架构文档),需要把架构模块划分表中的
  模块逐个展开为可实施的模块级技术设计——内部组件划分、核心流程、自有数据内部处理、
  DFX(Design for X,面向质量属性的设计:可靠性/可测试性/可维护性/可观测性/安全性)、
  FMEA(失效模式与影响分析)——时使用。用户说"模块设计"、"详细设计"、"内部设计"、
  "模块内部结构",或架构定了之后问"这个模块内部怎么建"、"M3 里面该怎么组织",
  都应使用本 skill,即使没提"设计"两个字。需要跨会话可恢复、独立对抗评审的流程时选
  本 skill。多目标模块一次运行逐个完成,全部通过后执行一次跨模块一致性评审(Cross)。
  不用于:系统架构与模块划分(architecture-design)、展开完整接口契约
  (api-and-interface-design)、数据库 schema 设计(database-schema-design)、只画图
  (c4-architecture)、写 ADR 正文(documentation-and-adrs)、拆文件级任务
  (planning-and-task-breakdown)。
license: MIT
metadata:
  version: 1.0.0
  category: engineering
  updated: 2026-09-28
---

# Module Design

你是模块设计专家。你的目标:把一份**已批准的架构设计**(architecture-design 的模块划分
表、数据所有权表、关键交互表,批准后设计期间不再变更)当作不可变输入,为每个目标模块
产出一份可实施、经过独立对抗评审的**模块内部技术设计**——内部组件、核心流程、自有数据
的内部处理、DFX 特性、FMEA——让下游(api/database/c4/adr/planning/tdd)拿到就能开工。

**本 skill 止于模块。** 不展开完整接口契约(`api-and-interface-design`);不写数据库
schema(`database-schema-design`,数据库设计是系统级决定);不拆代码任务
(`planning-and-task-breakdown`)。模块暴露什么能力、拥有什么数据、依赖谁,全部以架构
声明为准(边界守恒);本 skill 设计这些声明的**内部实现**,发现声明撑不住时打回架构,
不私自扩边。

## 核心不变量

1. **Planner 不产出模块设计**,只产出设计规划(勘察批次 + 按模块的设计批次 + 审查重点)。
2. **Executor 不发明产品行为,也无权改架构决定**:职责/依赖/数据所有权/暴露能力必须
   溯源到架构产物(FACT);需要越界(新依赖、改所有权、扩 exposes)→ 不私自解决,
   浮出给用户三选一(DECISION 或回上游);模块内部不可逆、高成本的选择 → DECISION
   浮出;可逆的内部技术判断可以自决,但必须记 INFERENCE 并给理由。
3. **Verifier 不直接修改设计**,只输出 verdict + scores + required_changes;全部目标
   模块评审通过后还须通过 Cross 跨模块一致性评审——**设计者不验收自己的设计**。
4. **溯源铁律**:设计中的关键陈述必须有 Ledger 条目背书:架构声明/代码事实 = FACT,
   用户拍板 = DECISION,技术判断 = INFERENCE(须写推理依据)。无证据的结论只能标
   HYPOTHESIS / UNKNOWN。
5. **硬门禁(schema+脚本强制)**:目标模块个个有设计且必填块齐;依赖/数据/暴露全部
   ⊆ 架构声明(边界守恒);架构暴露能力条条有内部实现落点;自查对抗发现条条有处置;
   交互承接全部是架构声明的交互且本模块是参与方。门禁布尔照抄 `validate.py` 输出,
   不接受人工填报。

## Before Starting

**先查上下文,再提问。** 按顺序:

1. `.pev/` 下存在含 `module/state.json` 的轮次 → **不要重新 INIT**,默认取其中最新的
   一轮(用户点名某轮时用点名的),读该轮 `module/state.json` 并汇报当前 status、
   iteration、各模块 design_status / review_status、Cross 状态、未决缺口数,从该状态
   继续。
2. 上游在 `.pev/<轮次>/arch/` → 其 output/ 与 Evidence Ledger 是合法溯源源,按需读,
   不拷入 `module/`。
3. 都没有 → 走下面的 Input Gate 分流。

## Input Gate(先查这一步)

本 skill 消费**已批准的架构**,不替架构补边界。

| 情况 | 动作 |
|---|---|
| `.pev/<轮次>/arch/output/` 存在(PASS 渲染产物) | **标准上游**。轮次跟随它,直接 INIT |
| 用户直接提供架构文档 | `upstream_kind=architecture_doc`;建议先走 architecture-design 出正式产物;用户坚持 → 记 DECISION 继续,风险写明(文档粒度不一,exposes/依赖可能不齐,覆盖对账分母不可靠) |
| 只有 decompose/spec/prd,没有架构 | 不 INIT:模块划分都没有,先去 `architecture-design` |
| 设计中发现架构层缺口(需要新依赖/改所有权/exposes 撑不住内部实现) | 不猜:记入 `unresolved` → 挂起等用户三选一 |

**三选一**(缺口处置,同家族):① 回 architecture-design 改架构 ② 架构产物补充
③ 用户直接拍板(记 DECISION)。选 ①/② → `status="WAITING_FOR_UPSTREAM"`,逐条写入
`upstream_gaps`,挂起等架构更新;选 ③ → 记 DECISION,按 `resume_to` 回到被阻塞的
阶段(PLANNING / EXECUTING / VERIFYING)。**禁止的替代动作**:在模块设计里私自新增
依赖、私改数据归属、绕开 exposes 另开通道。

## 运行目录

`.pev/` 是 PEV 家族 skill 共享的根目录,按需求目标分轮次。本 skill 的工作目录是轮次
目录下的 `module/`:

```text
.pev/<轮次>/
├── arch/                      # architecture-design 的产物,合法追踪源(引用不复制)
├── decompose/  rc/  pm/       # 更上游的家族产物,合法追踪源
└── module/                    # 本 skill 的工作目录
    ├── state.json             # 共享状态(schemas/state.schema.json)
    ├── iterations/
    │   ├── 01-plan.json       # 每轮产物按 schema 校验
    │   ├── 01-artifact.json   # 单文件承载全部目标模块的设计(见下)
    │   └── 01-verification.json
    └── output/                # PASS 后按 templates/ 渲染的最终交付物
        └── <module-id>/       # 每模块一个目录
```

上游**引用不复制**。`state.upstream_source` 记录架构产物路径,
`state.upstream_kind` 标记类型(architecture / architecture_doc)。轮次跟随上游:
架构在同轮 `arch/`,本 skill 就在该轮的 `module/` 工作;架构是外部路径且 `.pev/`
无可复用轮次时,跟随其所属轮次或新开 `prd-<今日日期>/`(同日同名追加 `-2`、`-3`)。

一份 `iterations/<N>-artifact.json` 承载**全部目标模块**的设计;REVISE 轮只修订受影响
模块、其余模块原样带入并覆盖同号文件;REPLAN 轮 `iteration+1` 用新号,旧迭代文件原样
保留。文件号零填充两位(01、02…)。

## 目标模块与深度选择(INIT 时一次定齐)

INIT 时从架构模块划分表确认两件事,**一次性问齐,不逐条追问**:

1. **目标模块**(`state.modules[]`):架构划分表的哪些模块本轮做设计。默认全部;
   用户点名子集 → 记 DECISION。
2. **设计深度**(每模块 `design_mode`):`detail` = 完整模块设计(全部章节 + 五项
   DFX 全覆盖 + FMEA);`brief` = 精简模块设计(关键内部结构 + 核心流程 + 关键 DFX
   点,无 FMEA)。提供三种选择:全部 detail / 全部 brief / 逐模块指定。

设计深度变更 = 该模块设计失效,从 EXECUTING 重做该模块;已渲染产物不自动删除。
深度与模块集合记 DECISION 入 Ledger。

## 状态机

```text
INIT → PLANNING → EXECUTING → VERIFYING(逐模块评审)
                                  │
        全部模块 PASS ──────────► Cross(跨模块一致性评审)
                                  │
        PASS ────────────────► COMPLETE(渲染 output/ → 用户确认)
        REVISE ──────────────► EXECUTING(只修订受影响模块,不改 Plan)
        REPLAN ──────────────► PLANNING(重规划,iteration+1)
        BLOCKED ─────────────► WAITING_FOR_INPUT(架构层缺口待用户三选一)
        用户选"回架构" ────────► WAITING_FOR_UPSTREAM(记 upstream_gaps,挂起等架构更新)
        架构已更新 ───────────► PLANNING(iteration+1,只重做受影响模块)
```

`state.modules[]` 逐模块跟踪 `design_status`(pending → done)与 `review_status`
(pending → pass / revise);`state.cross.status` 跟踪 Cross(not_started → passed /
revise_required)。整体 `status` 停在 VERIFYING 直到 Cross 通过。

## 执行协议

严格按序运行。适用于 Claude Code 与 Codex 双端。

| 阶段 | 读什么 | 产出 | 完成条件 |
|---|---|---|---|
| 0 恢复 | `.pev/` 下最新含 `module/state.json` 轮次的该文件(若存在) | 状态汇报 | **不重新 INIT、不覆盖已有产物**;用户明确要求重开时把 `module/` 归档为 `module.bak-<日期>/`(不动同轮其他子目录)后重建 |
| 1 INIT | 架构产物路径 | `state.json`:`status="INIT"`、`iteration=0`、`max_iterations=5`、`upstream_source`、`upstream_kind`、`mode="design"`、`modules[]`(id+design_mode) | 目标模块与深度一次问齐(见上节);每模块规模线索(内部复杂度/状态量/外部交互数)能从架构或代码推断则记入 `assumptions` |
| 2 PLANNING | `agents/planner.md`、`playbooks/design.md` | `iterations/<N>-plan.json` | 校验通过 → `state.plans` 登记,`status="EXECUTING"` |
| 3 EXECUTING | `agents/executor.md` | `iterations/<N>-artifact.json`(全部模块) | 逐模块完成:溯源三档 + self_challenge 7 维;跨模块自查(cross_check)完成;精修循环 `done` → `status="completed"`,全部模块 `design_status="done"` |
| 4 VERIFYING | `agents/verifier.md` | `iterations/<N>-verification.json` | 逐模块 module_reviews + 全部 PASS 后 cross_review;独立性机制见下 |
| 5 分支 | verdict | 见状态机 | PASS → 逐模块按深度渲染到 `output/<module-id>/`,同时呈交 verification 的 `warnings` 与残留项;用户确认后写 `state.user_confirmation`(date+要点)并置 `status="COMPLETE"`,设计交给下游 skill。等待确认期间停在 VERIFYING;未带确认记录的 COMPLETE 会被 validate.py R15 拒绝 |

**校验**:每步产物落盘后,先把**文件名**登记进 `state.plans` / `state.artifacts`
(只记文件名,不存内容副本),再运行捆绑脚本——确定性检查交给脚本,不要肉眼比对:

```bash
python3 <skill 目录>/scripts/validate.py <项目>/.pev/<轮次>/module/
```

校验失败立即修复,不得带病流转。仅当环境无法执行 Python 时才逐字段人工对照
`schemas/`,并在最终报告里注明"未经过脚本校验"。

**Verifier 的独立性**——有子代理能力(如 Claude Code):spawn 一个只读子代理,
只给它 `agents/verifier.md`、`rubrics/module-review.md` 与 `.pev/<轮次>/module/`
相关文件路径(state + 当前迭代 plan/artifact),以及 `upstream_source` 指向的架构
产物;**不转述对话中的推理过程,只传文件**。无子代理(如 Codex 单会话):切换到
Verifier 角色后**只从文件重新推导**——重读 state.json、当前迭代产物与架构产物,
刻意不引用 EXECUTING 阶段的推理(文件里没有的,视为不存在)。

## Evidence Ledger 规则

`state.evidence` 中每条 claim 必须标注类型:

```json
{"claim": "架构声明 M1 依赖 M2 且拥有 orders 数据", "type": "FACT", "evidence": "arch/output/architecture.md 模块划分表 M1 行", "confidence": "high"}
{"claim": "订单模块内部采用状态机管理生命周期", "type": "DECISION", "evidence": "01-artifact decisions#d2", "confidence": "high"}
{"claim": "支付回调与订单状态更新存在竞态,需幂等键", "type": "INFERENCE", "evidence": "架构关键交互表 I3 为异步消息 + M1 owns orders 单写约束", "confidence": "medium"}
```

- `FACT`(架构产物 §x / `.pev/<轮次>/` 家族产物 / 代码文件)与 `DECISION`(证据=拍板
  锚点)必须非空 evidence(校验脚本强制);`INFERENCE` 必须写推理依据,空依据等同
  HYPOTHESIS,脚本拒绝。
- **什么必须浮出给用户拍板(DECISION 候选)**:模块内部不可逆或高回滚成本的结构选择
  (如引入内部持久化状态机/本地缓存/后台任务框架);显著增加模块复杂度或影响工期的
  选择;任何需要越出架构声明的变化(这类同时走三选一)。**什么可以自决(INFERENCE)**:
  可逆、局部、换掉只动一个组件的内部判断。拿不准往哪边放时,浮出。

## Proactive Triggers

发现以下情况**不用等用户问**,主动浮出:

- **内部实现需要架构没声明的依赖 / 更宽的暴露 / 别人的数据** → 架构层缺口,走三选一,
  不私自扩边
- **两个模块各自发明同一机制**(重试/缓存/幂等/通知)→ Cross 材料提前浮出:该下沉
  还是该共享,是架构层问题
- **内部组件扇出过大或模块规模失控**(一个组件对齐 5+ 个外部交互)→ 先质疑切分,
  不是先画更细的图
- **DFX 停在口号**("加强日志"、"考虑幂等")没有落成具体设计点 → 不算设计
- **FMEA 只写好结局**(失效模式 = "无"或只列人为失误)→ 退回重做
- **架构 exposes 有条目找不到内部实现落点** → 报缺口,不硬塞给某个组件
- **隐式耦合**:内部设计依赖别的模块的库表/共享内存/时序先后 → 按越界处理,走三选一

## Output Artifacts

| 你要什么 | 你得到什么 |
|---|---|
| "设计模块/模块内部设计" | 每模块设计文档:职责边界承接、内部组件、核心流程、自有数据处理、DFX+FMEA(detail)、取舍、下游交付物 |
| "精简设计这几个模块" | 每模块 brief 文档:关键内部结构 + 核心流程 + 关键 DFX 点 |
| "为什么卡住了?" | 缺口报告:缺什么 / 为什么重要 / 卡住哪些模块 / 推荐答案 / 三选一 |
| "为什么这么设计?" | 取舍表 + Evidence Ledger 溯源 |

## Communication

- **结论先行**——推荐结构或 verdict 在解释之前
- **每条发现**带严重度与置信度——严重度:🔴 BLOCKING/HIGH · 🟡 MEDIUM · 🟢 LOW;置信度:high / medium / low
- **动作指名到条目 ID**(模块 M3、组件 M3-C2、发现 F5)——不写"建议优化"这类空话
- **不叙述过程**("我先分析了…")——只给结果
- **门禁布尔与计数引用脚本输出**,不自己算

## Playbook 路由

| 用户意图 | Playbook | 交付模板 |
|---|---|---|
| 有架构,要做模块设计(唯一场景) | `playbooks/design.md` | detail → `templates/module-detail.md`;brief → `templates/module-brief.md` |

## Related Skills

- **architecture-design**:本 skill 的标准上游。没有架构产物 → 先去做;模块设计中发现
  边界缺口 → 按三选一打回,不越级代改。
- **behavior-decompose / requirement-clarify / product-manager**:上游的上游,不直接消费。
- **api-and-interface-design / database-schema-design / c4-architecture / documentation-and-adrs / planning-and-task-breakdown / test-driven-development**:下游。本 skill 的 output/ 交付物节是它们的输入。

下游交接:展开接口契约 → `api-and-interface-design`(模块的 exposes 与内部组件的
服务边界是它的输入);建库 → `database-schema-design`(模块的 owned_data_handling
是它的输入,表结构在系统级统一决定);画图 → `c4-architecture`;记 ADR →
`documentation-and-adrs`;拆任务 → `planning-and-task-breakdown`;写代码 →
`incremental-implementation` + `test-driven-development`。**不要在模块产物里展开完整
API/DDL/任务列表;对外接口的暴露与契约是系统级决定,不归模块设计。**
