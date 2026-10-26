# Artifact 字段速查(database-schema-design)

Executor 产出的 `iterations/<N>-artifact.json` 字段的人话解释,供人工审核
executor / verifier / templates 时对照。权威定义在
[schemas/artifact.schema.json](../schemas/artifact.schema.json),两者冲突以 schema 为准。

共同逻辑:schema 里承载的一切实体 ⊆ 上游声明(**实体守恒**),上游声明的数据条条有
schema 落点(**覆盖对账**)。**上游快照** = `input_summary.upstream_snapshot`,把上游
产物的模块声明(owns_data/exposes)与交互声明(mode/一致性/失败处理/幂等)抄成
结构化 JSON,是所有 ⊆ 检查的机器基准。

## 顶层字段(artifact 内)

| 字段 | 是什么 |
|---|---|
| `upstream_snapshot.modules[]` | 上游对每个模块的声明:id、名称、`owns_data`(拥有哪些数据)、`exposes`(对外暴露什么能力,可选) |
| `upstream_snapshot.interactions[]` | 上游声明的交互:id(如 I3)、场景、发起方、接收方,及 `mode`(sync/async/data-flow)、`consistency`、`failure_handling`、`idempotency`(后四项自上游交互声明抄——arch 关键交互表或 module 下游交付物;缺则省略) |
| `upstream_items` | 覆盖对账的分母:目标模块的每条数据条目(如 M1-D2)与每条涉及持久化的交互(如 I3),从上游产物逐条抄下(schema_request 时来自用户口述,记 DECISION) |
| `upstream_mapping` | 覆盖对账的分子:每条上游条目落在哪个库(与 upstream_items 双向对账,validate.py 强制) |
| `codebase_fit` | 勘察现有库的结论:当前模式、可复用约定、勿破坏边界、技术债、已知瓶颈 |
| `risks` | 明确接受的风险:风险、影响、缓解方式、待验证点 |
| `downstream_deliverables` | 给下游 skills(implementation/tdd/planning/documentation)的输入清单 |

## 库级字段(stores[] 内;一库或多库)

| 字段 | 是什么 |
|---|---|
| `kind` | 存储类型:postgresql / mysql / mongodb |
| `covered_entities` | 本库承接的上游数据实体(可跨模块);每条必须 ∈ 上游快照任一模块的 owns_data |
| `environment` | 存储环境与规模假设:dialect_version(如 PostgreSQL 16)、charset、scale(行数量级/增长/读写比)、retention、multi_tenant。方言与规模非空是门槛 |
| `access_patterns` | 本库的读写模式(最高频 3~5 个):pattern、frequency、query_shape——索引与 denorm 的依据分母 |
| `tables` | 表/集合设计(mongodb 时为 collection):name、entity(回指 covered_entities)、purpose、existing_change(既有表:延续/新增/变更/废弃+迁移影响)、why。关系型:columns(列级定义)+ pk(主键策略+WHY)+ constraints,三者非空;mongodb:document_shape(文档字段结构+embed/reference 决策)+ validator($jsonSchema+validationLevel),两者非空 |
| `indexes` | 二级索引:definition + `serves`(回指 access_pattern id)——无依据索引不许入库 |
| `denormalization` | 有依据的冗余:what + `serves`(回指 access_pattern id)+ sync_strategy |
| `data_flow_commitments` | 承接的上游声明交互:interaction(∈ 快照交互)、role、schema_handling(如 outbox 表/消费去重唯一键);本库承接实体的归属模块必须是该交互的参与方 |
| `evolution` | 演进与迁移策略:strategy(如 expand-contract)、compat_rules(什么算破坏性变更、锁影响、回滚原则)、large_table_plan(大表分区/归档)。必填非空 |
| `tradeoffs` | 库级关键取舍:决策、选择、理由、`cost`(放弃了什么)、替代方案 |
| `self_challenge` | 提交前 7 维自查(failure_modes / consistency / concurrency / boundary_erosion / misuse_potential / compatibility / simpler_alternative)的发现与处置 |
