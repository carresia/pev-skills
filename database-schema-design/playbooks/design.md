# Playbook: design(默认场景)

上游产物已批准(module-design 或 architecture-design,均为标准上游;或 schema_request 口述/DDL 上游),要逐库的 schema 设计。交付模板:`templates/db-schema.md`。

## Plan 骨架

```text
1. survey_upstream     —— 条目化每个目标数据库承接的上游声明(必为第一步):
                          owns_data / owned_data_handling + 涉及持久化的交互
2. survey_codebase     —— 仅当存在既有库/既有表/迁移工具(选型跟随现状 + 命名风格勘察)
3. design_stores       —— 每批一个库(强关联多库可合并一批),被引用的先做
4. cross_check         —— 跨库一致性自查(命名与概念漂移/ID 策略/冗余权威源/演进一致)
5. draft               —— 聚合 + downstream_deliverables + 精修循环
```

单库简单轮次允许 3/4/5 各一步收口;步骤数与库数和复杂度成正比,不为了显得周全而增加。

## Executor 要点

- **实体守恒优先**:covered_entities 每条 ∈ 上游快照任一模块的 owns_data(库的数量
  不预设,一库可承载多模块数据);数据流承接只取声明过的交互且实体归属模块对齐;越界需求(存
  上游外数据/挪数据所有权)→ `unresolved` + blocked → 三选一,不私自扩边。
- **表回指实体**:每张表写清承载哪条上游实体声明;写不出实体背书的表 = 删。
- **access pattern 先行**:每库先声明最高频的 3~5 个读写;每个二级索引、每处
  denorm 回指它服务的具体 access pattern;无依据的索引/denorm 不入库。
- **命名见名知意**:项目既有命名风格优先;新库新表按默认规范(小写下划线、单数、
  ≤3 词、禁保留字、idx_/uniq_ 前缀),细则见
  [db-naming-and-conventions](../references/db-naming-and-conventions.md)。
- **完整性约束进库**:FK/UNIQUE/CHECK/NOT NULL 显式,ON DELETE 逐条明确,枚举列
  有约束;小数 DECIMAL;PG 的 FK 列手动建索引。
- **主键与 ID 带 WHY**:自增/UUIDv7/ULID/Snowflake 的选择写推理依据(分布式?
  可暴露?);MySQL 自增主键 `id`、禁联合主键(分布式场景选型记 DECISION)。
- **演进交代**:evolution 写清什么算破坏性 schema 变更、迁移原则(expand-contract
  优先)、锁影响评估约定;改已有表时 UP + DOWN 成对
  (模板:assets/templates/migration-template.sql);大表(千万行级)给分区/归档
  或记 accepted_risk。
- **下游交付物节必须填**:各下游 skill 拿到什么输入,写具体条目,不写"见上文"。

## Verifier 检查重点(本场景加压项)

- upstream_snapshot 完备性(漏抄 owns_data/交互行 = 分母造假,覆盖检查失效,直接 REVISE)
- 索引与 denorm 依据:逐个问"它服务哪条查询",回指不成立即退
- 命名与规范:见名知意、保留字、索引前缀、单表索引数,对照 db-naming-and-conventions 逐条扫(项目既有风格优先)
- 迁移与演进质量:改表无 UP/DOWN、无锁影响评估 = 退回;裸 ALTER 大表直接 HIGH
- misuse_potential:逐表问"会走出哪条无索引的慢路径"
- Cross:概念漂移与冗余权威源逐项过,不走过场
