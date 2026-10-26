# 数据库 Schema:{{store.name}}({{store.id}})

<!-- 模板字段的含义见 database-schema-design skill 的 references/fields.md;权威定义:schemas/artifact.schema.json -->
<!-- 本文件为手工填充模板:{{...}} 是占位符,{{#each}}/{{#if}} 表示按数组/条件展开;本 skill 无渲染引擎,由 agent 对照 artifact JSON 逐项填实。 -->

> 上游:{{upstream_source}}({{upstream_kind}}) · 迭代 {{iteration}} · Verdict {{verdict}} · 生成于 {{date}}
>
> 门禁:目标库齐 {{gates.stores_complete}} · 实体守恒 {{gates.entities_within_upstream}} · 落点齐 {{gates.upstream_mapped}} · 自查处置 {{gates.findings_disposed}} · 数据流一致 {{gates.cross_consistent}}

本 schema 止于结构与约束。写持久层代码 → `incremental-implementation` + `test-driven-development`;拆任务 → `planning-and-task-breakdown`;记 ADR(主键/选型/分区决策)→ `documentation-and-adrs`。

## 残留与未决(交下游前须过目)

> 单轮评审通过不等于零残留。下表汇总 verification 的 warnings 与 accepted 风险,交下游时一并移交。

| 级别 | 条目 | 处置 |
|---|---|---|
| {{severity}} | {{item}} | {{resolution}} |

## 库定位(承接上游)

- 存储类型:{{store.kind}}
- 承接实体(⊆ 上游声明,可跨模块):{{store.covered_entities}}

### 环境与规模假设

- 方言与版本:{{store.environment.dialect_version}}
- 字符集:{{store.environment.charset}}
- 规模:{{store.environment.scale}}
- 保留期:{{store.environment.retention}}
- 多租户:{{store.environment.multi_tenant}}

### 承接的上游声明交互

| 上游交互 | 本模块角色 | schema 承接方式 | 溯源 |
| --- | --- | --- | --- |
| {{#each store.data_flow_commitments}}| {{interaction}} | {{role}} | {{schema_handling}} | {{trace}} |
{{/each}}

## Access Patterns(索引与 denorm 的依据)

| id | 读写模式 | 频率 | 查询形状 |
| --- | --- | --- | --- |
| {{#each store.access_patterns}}| {{id}} | {{pattern}} | {{frequency}} | {{query_shape}} |
{{/each}}

## 表(Table / Collection)

先总览后明细:总览表让人一眼掌握每张表"是什么、为什么存在";细节逐表展开。

### 表总览

| 表 | 目的 | 承接实体 | 主键策略 |
| --- | --- | --- | --- |
| {{#each store.tables}}| {{id}} {{name}} | {{purpose}} | {{entity}} | {{pk}} |
{{/each}}

### 表明细

<!-- mongodb 集合:以 document_shape / _id 策略 / validator 分别替代「列定义 / 主键 / 约束」三行 -->

{{#each store.tables}}
#### {{id}} {{name}}

- 目的:{{purpose}}
- 承接实体:{{entity}}
- 列定义:{{columns}}
- 主键:{{pk}}
- 约束(FK/UNIQUE/CHECK/ON DELETE):{{constraints}}
- 既有表变化:{{existing_change}}
- WHY:{{why}}
- 溯源:{{trace}}

{{/each}}

## 索引依据

| 索引 | 表 | 定义 | 服务的 access pattern | WHY |
| --- | --- | --- | --- | --- |
| {{#each store.indexes}}| {{id}} | {{table}} | {{definition}} | {{serves}} | {{why}} |
{{/each}}

## Denormalization(有依据的冗余)

| 冗余了什么 | 服务的 access pattern | 同步策略 | WHY |
| --- | --- | --- | --- |
| {{#each store.denormalization}}| {{what}} | {{serves}} | {{sync_strategy}} | {{why}} |
{{/each}}

## 演进与迁移策略

- 策略:{{store.evolution.strategy}}
- 兼容规则(什么算破坏性变更、锁影响、回滚原则):{{store.evolution.compat_rules}}
- 大表计划:{{store.evolution.large_table_plan}}

## 关键取舍

| 决策 | 选择 | 理由 | 代价 | 替代方案 |
| --- | --- | --- | --- | --- |
| {{#each store.tradeoffs}}| {{decision}} | {{choice}} | {{rationale}} | {{cost}} | {{alternative}} |
{{/each}}

## 自查对抗结论(7 维;独立评审见 verification)

| 维度 | 发现 | 处置 |
| --- | --- | --- |
| {{#each store.self_challenge}}| {{dimension}} | {{finding}} | {{disposition}}{{#if rationale}}({{rationale}}){{/if}} |
{{/each}}

## 风险

| 风险 | 影响 | 缓解方式 | 需要验证的点 |
| --- | --- | --- | --- |
| {{#each risks}}| {{risk}} | {{impact}} | {{mitigation}} | {{to_validate}} |
{{/each}}

## 给下游 Skills 的交付物

### incremental-implementation
{{downstream_deliverables.incremental_implementation}}
### test-driven_development
{{downstream_deliverables.test_driven_development}}
### planning-and-task-breakdown
{{downstream_deliverables.planning_and_task_breakdown}}
### documentation-and-adrs
{{downstream_deliverables.documentation_and_adrs}}
### c4-architecture
{{downstream_deliverables.c4_architecture}}

## DECISION 汇总(用户拍板记录)

| 决定 | 锚点 |
| --- | --- |
| {{#each decisions}}| {{decision}} | {{id}} |
{{/each}}
