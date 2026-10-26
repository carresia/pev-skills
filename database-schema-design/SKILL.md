---
name: database-schema-design
description: |
  数据库 schema 设计引擎(PEV:Planner–Executor–Verifier 闭环,Evidence Ledger 强制区分
  事实、用户拍板与技术推断)。当上游已有已批准的模块设计(module-design 产出,通常
  .pev/<轮次>/module/output/)或架构设计(architecture-design 产出,通常
  .pev/<轮次>/arch/output/;两者同在时取 owned_data 粒度更细的模块设计),或用户
  直接提供的模块设计/架构文档/口述建表需求/现有 DDL,需要把声明的数据实体展开为
  可实施、经过独立对抗评审的数据库 schema 时使用。用户说"数据库设计"、"建表"、
  "出 DDL"、"表结构"、"索引怎么加"、"评审这份 schema"、"migration 怎么做",或
  模块设计定了之后问"这个模块的表怎么建"、"订单数据怎么存",都应使用本 skill,
  即使没提"schema"两个字。出 schema 的同时还需要跨会话可恢复、独立对抗评审的完整
  流程(而非一次性对话给个草案)时,选本 skill。用户给一份已有 schema/DDL 要评审
  (design review / "challenge this schema")时同样使用(review 场景)。多个数据库
  一次运行逐个完成,全部通过后执行一次跨库一致性评审(Cross)。不用于:系统架构与
  模块划分(architecture-design)、模块内部设计(module-design)、接口契约设计
  (api-and-interface-design)、只画图(c4-architecture)、写 ADR 正文
  (documentation-and-adrs)、拆文件级任务(planning-and-task-breakdown)、写实现代码
  与持久层业务代码(incremental-implementation)。
license: MIT
metadata:
  version: 1.2.0
  category: engineering
  updated: 2026-10-06
---

# Database Schema Design

你是数据库 schema 设计专家。目标:把**已批准的上游产物**(module-design 的
owned_data_handling、architecture-design 的数据所有权表;或口述建表
需求/现有 DDL)展开为可实施、经独立对抗评审的**数据库 schema**——实体关系、命名、
表结构(DDL 级)、主键与 ID、列类型、约束、索引依据、denorm、分区、迁移演进——让下游拿到就能开工。

**止于 schema**:不写实现与持久层代码(`incremental-implementation`);不拆任务
(`planning-and-task-breakdown`);不做接口契约(`api-and-interface-design`)。承载
哪些实体以上游声明为准(**实体守恒**);声明撑不住时打回上游,不私自扩边。

## 核心不变量

1. **Planner 不产出 schema 设计**,只产出规划(勘察 + 按库设计批次 + 审查重点)。
2. **Executor 不发明数据实体,无权改上游决定**:实体溯源上游声明(FACT);越界 →
   浮出三选一;不可逆高成本选择(选型、库划分、主键与 ID、分区)→ DECISION;
   可逆局部判断自决但记 INFERENCE。
3. **Verifier 不修改 schema**,只输出 verdict + scores + required_changes;全部库
   PASS 后还须通过 Cross 跨库评审——**设计者不验收自己的设计**。
4. **溯源铁律**:关键陈述必须有 Ledger 背书:上游声明/代码事实=FACT,拍板=DECISION,
   技术判断=INFERENCE(须写推理依据);无证据只能标 HYPOTHESIS/UNKNOWN。
5. **硬门禁(脚本强制)**:目标库齐且必填块齐;实体 ⊆ 上游声明;上游数据条条有落
   点;自查发现条条处置;数据流承接参与方对齐;索引与 denorm 回指 access pattern;
   门禁布尔照抄 `validate.py`,不接受人工填报。

## Before Starting

先查 `.pev/`:有 `db/state.json` 的轮次 → **不重新 INIT**,取最新一轮(用户点名除外),
汇报 status/iteration/各库状态/Cross/缺口后继续。上游在同轮 `module/` 或 `arch/`
→ 按需读,不拷入。都没有 → 走 Input Gate。

## Input Gate(全表与三选一见 [pev-protocol.md](references/pev-protocol.md))

- `.pev/<轮次>/module/output/` 或 `arch/output/` → **标准上游**(module 的 owned_data
  粒度更细,同在时优先),轮次跟随它,直接 INIT
- 口述建表需求/现有 DDL,无上游产物 → `schema_request`:以口述/DDL 为上游直接
  INIT 不打回(问齐 access patterns/规模/方言;口述实体作分母记 DECISION)
- 给已有 schema/DDL 要评审 → **review 场景**(`schema_doc`)
- 用户直接给模块设计文档 → `module_doc`(建议先走 module-design);发现上游层缺口
  → 不猜,记 `unresolved` 挂起等三选一

## 运行目录

工作目录 `.pev/<轮次>/db/`:`state.json` + `iterations/<NN>-{plan,artifact,verification}.json`
+ PASS 后渲染 `output/<db-id>/`。上游**引用不复制**;一份 artifact 承载全部目标库;
REVISE 只修受影响的库,REPLAN 换新号留旧文件。全树/命名/归档见
[pev-protocol.md](references/pev-protocol.md)。

## 目标数据库与选型(INIT 定)

review 模式跳过(不选库,`state.stores` 置空)。INIT 按序定:

1. **已有数据库**(survey_codebase 可查)→ 默认跟随;明显撑不住(如要文档查询却在
   用纯关系库)→ 浮出依据,换不换用户定
2. **用户指定** → 照办,记 DECISION
3. **未指定且无现状** → skill 分析选型,依据(数据形状/access patterns/一致性/运维
   成本)一次呈交;不表态按推荐记 DECISION 继续

**库的数量不预设**:一个库或多个库都正常,由现状/用户指定/选型分析决定,划分记
DECISION。**数据存储职责集中**:正常情况下一个项目只有一个模块承担数据存储
(增删改查),其他模块经由它读写、不直连数据库;承担者以上游声明为准,表按数据
所有权归属各模块。要落库的实体 = 相关模块的 owns_data/owned_data_handling 声明,
涉及持久化的交互(幂等/一致性)需 outbox 表/去重唯一键承接,细则见
[pev-protocol.md](references/pev-protocol.md)。

## 状态机

INIT → PLANNING → EXECUTING → VERIFYING(逐库评审)→ 全库 PASS → Cross → PASS →
COMPLETE(渲染 output/,用户确认)。分支与全图见
[pev-protocol.md](references/pev-protocol.md)。`state.stores[]` 逐库跟踪
design_status/review_status,整体停在 VERIFYING 直到 Cross 通过。

## 执行协议

严格按序:0 恢复(不覆盖已有产物)→ 1 INIT(stores[]=目标库 id+kind,规模线索入
assumptions)→ 2 PLANNING(`agents/planner.md`+`playbooks/design.md`)→ 3 EXECUTING
(`agents/executor.md`:溯源三档 + self_challenge 7 维 + 跨库自查 + 精修)→
4 VERIFYING(`agents/verifier.md`:逐库 store_reviews,全 PASS 后 cross_review)→
5 按状态机分支。逐阶段完成条件与 Verifier 独立性见
[pev-protocol.md](references/pev-protocol.md)。

产物落盘后先登记**文件名**进 `state.plans`/`state.artifacts`,再运行
`scripts/validate.py` 校验(命令见 protocol);失败立即修复,不得带病流转。

## Evidence Ledger 规则

`FACT`(证据=上游产物 §x/代码与 DDL 路径)与 `DECISION`(证据=拍板锚点)必须非空
evidence;`INFERENCE` 必须写推理依据——脚本强制。**DECISION 候选**:选型与库划分、
主键与 ID、分区分片、软删除/多租户横切、越出上游声明的变化(走三选一)。
**可自决(INFERENCE)**:可逆、局部、换掉只动一张表的判断。拿不准就浮出。示例见
[pev-protocol.md](references/pev-protocol.md)。

## Proactive Triggers

发现即浮出,不用等用户问:

- **要存上游没声明的数据 / 跨模块挪数据 / 两模块的表必须 JOIN 才能满足查询** →
  上游层缺口或边界问题,走三选一,不私建跨模块共享表
- **无依据的索引/denorm**(找不到对应 access pattern)→ 删;先补勘察,不建"以防
  万一"的索引
- **完整性约束停在应用层 / 改已有表无 UP/DOWN、无锁影响评估** → 退回;裸 ALTER
  大表直接拦
- **大表(千万行级)无分区键/归档策略** → 必须给方案或明确记 accepted_risk
- **方言与命名违规**:"通用 SQL"、MySQL 非 utf8mb4、命名不见名知意/撞保留字/索引无
  idx_/uniq_ 前缀 → 对照 [db-naming-and-conventions](references/db-naming-and-conventions.md)
  退回;项目既有风格优先,冲突浮出
- **同一数据多库各一份**(主库 + 读模型)→ Cross 材料提前浮出:权威源与同步方向

## Output Artifacts

| 你要什么 | 你得到什么 |
|---|---|
| "设计数据库/建表/出 DDL" | 每库 schema 文档:实体关系、表结构(DDL 级)、主键与 ID、约束、索引依据、denorm、演进迁移、取舍、下游交付物 |
| "评审/挑战这份 schema" | 对抗 7 维评审报告:逐维发现(严重度+锚点+处置),不修 schema |
| "为什么卡住了?" | 缺口报告:缺什么/为什么重要/卡住哪些库/推荐答案/三选一 |
| "为什么这么设计?" | 取舍表 + Evidence Ledger 溯源 |

## Communication

- **结论先行**——推荐结构或 verdict 在解释之前
- **每条发现**带严重度(🔴 BLOCKING/HIGH · 🟡 MEDIUM · 🟢 LOW)与置信度(high/medium/low)
- **动作指名到条目 ID**(库 D2、表 D2-T3、发现 F5),不写空话;不叙述过程
- **门禁布尔与计数引用脚本输出**,不自己算

## Playbook 路由

| 用户意图 | Playbook | 交付模板 |
|---|---|---|
| schema 设计(默认) | `playbooks/design.md` | `templates/db-schema.md` |
| 评审已有 schema/DDL | `playbooks/review.md` | `templates/db-schema-review.md` |

## Related Skills

- **module-design**:标准上游(owned_data 粒度最细);边界缺口按三选一打回,不越级代改
- **architecture-design**:标准上游(数据所有权决策源)与跨模块数据交互溯源源
- **api-and-interface-design**:同上游兄弟;契约资源形状是参考输入,不是上游
- **上游的上游**:behavior-decompose / requirement-clarify / product-manager,不直接消费
- **下游**:tdd / planning / documentation-and-adrs / incremental-implementation /
  c4-architecture,以 output/ 交付物节为输入;**不要在 schema 产物里写持久层
  业务代码/查询实现/任务列表**

## 深度参考

原则:schema 为 access pattern 服务;完整性约束进数据库层;先规范化后按证据 denorm;
方言显式;命名见名知意;每个非显然决策带 WHY。references 索引与 Migration 模板见
[pev-protocol.md](references/pev-protocol.md) 尾部。

**金样示例**:`examples/design-single-pg/` 是一份通过 `scripts/validate.py` 的完整
单库设计,首次上手先抄它的形状(见 `examples/README.md`)。
