# PEV 流程细则(database-schema-design)

SKILL.md 的流程展开:Input Gate 全表、三选一、运行目录全树、执行协议逐阶段表、
Verifier 独立性、Evidence Ledger 示例。核心不变量以 SKILL.md 为准,细则以本文件为准。

## Input Gate(上游分流全表)

本 skill 消费**已批准的模块设计或架构设计**,或用户直接提供的输入,不替上游补边界。

| 情况 | 动作 |
|---|---|
| `.pev/<轮次>/module/output/` 存在(PASS 渲染产物) | **标准上游**(owned_data 粒度最细,与架构产物同在时优先;owned_data_handling 有逻辑级处理声明)。轮次跟随它,直接 INIT |
| 用户直接提供模块设计/数据模型文档 | `upstream_kind=module_doc`;建议先走 module-design 出正式产物;用户坚持 → 记 DECISION 继续,风险写明(文档粒度不一,owns_data/处理声明可能不齐,覆盖对账分母不可靠) |
| 只有 `.pev/<轮次>/arch/output/`,没有 module | **标准上游**:`upstream_kind=architecture`。数据所有权以架构决策为准,可结合现有代码库与既有 schema(survey_codebase)直接 INIT;后续若补做模块设计,数据粒度可能需回头对齐(记入 risks 即可,不阻塞、不强制 DECISION) |
| 用户口述建表需求 / 给一份现有 DDL,没有上游产物 | `upstream_kind=schema_request`。INIT 时问齐三项门槛信息(access patterns、规模量级、目标方言+版本),把用户口述的实体清单当作声明分母(逐条记 DECISION,anchor=口述/文档);风险写明:无正式上游对账,边界由本次口述决定。直接 INIT,不打回 |
| 用户给一份已有 schema/DDL 文档,要评审 | **review 场景**。该文档即被评审对象(`upstream_kind=schema_doc`);对应 module-design/architecture 若存在,作为对照事实源,不当作标准设计上游 |
| 设计中发现上游层缺口(需要存上游没声明的数据、数据所有权冲突、声明撑不住 schema) | 不猜:记入 `unresolved` → 挂起等用户三选一 |

### 三选一(缺口处置,同家族)

① 回 module-design 改模块设计 ② 回 architecture-design 改架构 ③ 用户直接拍板
(记 DECISION)。选 ①/② → `status="WAITING_FOR_UPSTREAM"`,逐条写入
`upstream_gaps`,挂起等上游更新;选 ③ → 记 DECISION,按 `resume_to` 回到被阻塞的
阶段(PLANNING / EXECUTING / VERIFYING)。

**禁止的替代动作**:私自建表存上游没声明的数据、跨模块挪数据所有权、绕开数据
所有权表共享表。

## 运行目录(全树)

`.pev/` 是 PEV 家族共享根目录,按需求目标分轮次;本 skill 工作目录是轮次下的 `db/`:

```text
.pev/<轮次>/
├── arch/                      # architecture-design 的产物,合法追踪源(引用不复制)
├── module/                    # module-design 的产物,标准追踪源(引用不复制)
├── decompose/  rc/  pm/  api/ # 更上游/同上游的家族产物,合法追踪源
└── db/                        # 本 skill 的工作目录
    ├── state.json             # 共享状态(schemas/state.schema.json)
    ├── iterations/
    │   ├── 01-plan.json       # 每轮产物按 schema 校验
    │   ├── 01-artifact.json   # 单文件承载全部目标数据库的设计
    │   └── 01-verification.json
    └── output/                # PASS 后按 templates/ 渲染的最终交付物
        └── <db-id>/           # 每库一个目录
```

- 上游**引用不复制**;`state.upstream_source` 记录上游产物路径,`state.upstream_kind`
  标记类型(module_design / architecture / module_doc / schema_request / schema_doc)。
- 轮次跟随上游:模块设计在同轮 `module/`,本 skill 就在该轮 `db/` 工作;上游是外部
  路径且 `.pev/` 无可复用轮次时,跟随其所属轮次或新开 `prd-<今日日期>/`(同日同名
  追加 `-2`、`-3`)。
- 一份 `iterations/<N>-artifact.json` 承载**全部目标数据库**;REVISE 轮只修订受影响的
  库、其余原样带入并覆盖同号文件;REPLAN 轮 `iteration+1` 用新号,旧迭代文件原样
  保留;文件号零填充两位(01、02…)。
- 目标库集合变动:新增库 = 该库设计从 EXECUTING 重做,已渲染产物不自动删除,记 DECISION。
- 重开:用户明确要求时把 `db/` 归档为 `db.bak-<日期>/`(不动同轮其他子目录)后重建。

## 执行协议(逐阶段)

严格按序运行,适用于 Claude Code 与 Codex 双端。

| 阶段 | 读什么 | 产出 | 完成条件 |
|---|---|---|---|
| 0 恢复 | `.pev/` 下最新含 `db/state.json` 轮次的该文件(若存在) | 状态汇报 | **不重新 INIT、不覆盖已有产物**;重开按上文归档规则 |
| 1 INIT | 上游产物路径 | `state.json`:`status="INIT"`、`iteration=0`、`max_iterations=5`、`upstream_source`、`upstream_kind`、`mode`(design/review,按用户意图定,默认 design)、`stores[]`(目标数据库 id+kind;review 置空) | 目标数据库与选型一次问齐(SKILL.md 选型规则;review 跳过);每库规模线索(行数量级/增长/读写比/现有表数)能从上游或代码推断则记入 `assumptions` |
| 2 PLANNING | `agents/planner.md`、`playbooks/design.md` | `iterations/<N>-plan.json` | 校验通过 → `state.plans` 登记,`status="EXECUTING"` |
| 3 EXECUTING | `agents/executor.md` | `iterations/<N>-artifact.json`(全部库) | 逐库完成:溯源三档 + self_challenge 7 维;跨库自查(cross_check)完成;精修循环 `done` → `status="completed"`,全部库 `design_status="done"` |
| 4 VERIFYING | `agents/verifier.md` | `iterations/<N>-verification.json` | 逐库 store_reviews + 全部 PASS 后 cross_review;独立性机制见下 |
| 5 分支 | verdict | 按状态机 | PASS → 逐库渲染到 `output/<db-id>/`,同时呈交 verification 的 `warnings` 与残留项;用户确认后 `status="COMPLETE"`,schema 交给下游 skill |

**校验**:每步产物落盘后,先把**文件名**登记进 `state.plans` / `state.artifacts`
(只记文件名,不存内容副本),再运行捆绑脚本——确定性检查交给脚本,不要肉眼比对:

```bash
python3 <skill 目录>/scripts/validate.py <项目>/.pev/<轮次>/db/
```

校验失败立即修复,不得带病流转。门禁布尔与 verification 的逐位比对仅当 state.status
为 VERIFYING 或 COMPLETE 时执行(早期阶段尚无评审产物,不做比对)。仅当环境无法执行
Python 时才逐字段人工对照 `schemas/`,并在最终报告里注明"未经过脚本校验"。

**Verifier 的独立性**——有子代理能力(如 Claude Code):spawn 一个只读子代理,只给它
`agents/verifier.md`、`rubrics/db-review.md` 与 `.pev/<轮次>/db/` 相关文件路径
(state + 当前迭代 plan/artifact),以及 `upstream_source` 指向的上游产物;**不转述
对话中的推理过程,只传文件**。无子代理(如 Codex 单会话):切换到 Verifier 角色后
**只从文件重新推导**——重读 state.json、当前迭代产物与上游产物,刻意不引用
EXECUTING 阶段的推理(文件里没有的,视为不存在)。

## 状态机全图

```text
INIT → PLANNING → EXECUTING → VERIFYING(逐库评审)
                                  │
        全部库 PASS ─────────────► Cross(跨库一致性评审)
                                  │
        PASS ────────────────► COMPLETE(渲染 output/ → 用户确认)
        REVISE ──────────────► EXECUTING(只修订受影响的库,不改 Plan)
        REPLAN ──────────────► PLANNING(重规划,iteration+1)
        BLOCKED ─────────────► WAITING_FOR_INPUT(上游层缺口待用户三选一)
        ├─ 用户选"回上游" ────► WAITING_FOR_UPSTREAM(记 upstream_gaps,挂起等上游更新)
        └─ 用户直接拍板(记 DECISION) ──► 按 resume_to 回到 PLANNING/EXECUTING/VERIFYING
        上游已更新 ───────────► PLANNING(iteration+1,只重做受影响的库)
```

## Evidence Ledger 示例

`state.evidence` 中每条 claim 必须标注类型,示例如下:

```json
{"claim": "上游声明 M1 拥有 orders 数据且逻辑级处理为本地表存储", "type": "FACT", "evidence": "module/output/M1/module-detail.md owned_data_handling 节 + arch 数据所有权表 M1 行", "confidence": "high"}
{"claim": "订单主库选 PostgreSQL 16,主键 BIGINT 自增(单库写入,无分片计划)", "type": "DECISION", "evidence": "01-artifact decisions#d2", "confidence": "high"}
{"claim": "订单号需要全局唯一且有可读前缀,故另设 order_no 生成列而非用 PK 兜底", "type": "INFERENCE", "evidence": "上游声明 I3 为 async-message 且幂等 required,消费者以 order_no 去重,PK 自增不含业务语义", "confidence": "medium"}
```

## 深度参考索引(何时读什么)

要落库的实体 = 目标模块声明的 owns_data / owned_data_handling;涉及持久化的声明交互
(幂等/一致性)需要 outbox 表/去重唯一键等承接。数据存储职责正常集中在一个模块,
其他模块经由它读写、不直连数据库;库的数量不预设。

| 文件 | 何时读 |
|------|--------|
| [schema-design-checklist.md](schema-design-checklist.md) | 每次交付前自查、review 逐项核对 |
| [db-naming-and-conventions.md](db-naming-and-conventions.md) | 定名、建表、加索引时(命名规范 + 设计硬规则) |
| [pev-protocol.md](pev-protocol.md) | 走流程时(Input Gate/目录/逐阶段表/Ledger 示例) |
| [data-types.md](data-types.md) | 定列类型时 |
| [keys-and-indexes.md](keys-and-indexes.md) | 定 PK、加索引时 |
| [relationships-and-constraints.md](relationships-and-constraints.md) | 建关系时 |
| [normalization-and-modeling.md](normalization-and-modeling.md) | 建模时 |
| [migrations.md](migrations.md) | 改已有表时 |
| [partitioning-and-scale.md](partitioning-and-scale.md) | 大表(>千万行)时 |
| [nosql-mongodb.md](nosql-mongodb.md) | MongoDB 时 |
| [fields.md](fields.md) | 写/审 artifact 时(字段人话速查) |

Migration 模板:[assets/templates/migration-template.sql](../assets/templates/migration-template.sql)
