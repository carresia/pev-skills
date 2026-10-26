# 接口契约:{{contract.name}}({{contract.id}})

<!-- 模板字段的含义见 api-and-interface-design skill 的 references/fields.md;权威定义:schemas/artifact.schema.json -->

> 上游:{{upstream_source}}({{upstream_kind}}) · 迭代 {{iteration}} · Verdict {{verdict}} · 生成于 {{date}}
>
> 门禁:目标契约面齐 {{gates.contracts_complete}} · 契约守恒 {{gates.capabilities_within_upstream}} · 落点齐 {{gates.upstream_mapped}} · 自查处置 {{gates.findings_disposed}} · 交互一致 {{gates.cross_consistent}}

本契约止于接口。写实现代码 → `incremental-implementation` + `test-driven-development`;建库 → `database-schema-design`;拆任务 → `planning-and-task-breakdown`。

## 残留与未决(交下游前须过目)

> 单轮评审通过不等于零残留。下表汇总 verification 的 warnings 与 accepted 风险,交下游时一并移交。

| 级别 | 条目 | 处置 |
|---|---|---|
| {{severity}} | {{item}} | {{resolution}} |

## 契约定位(承接上游)

- 承接模块:{{contract.owner_module}}
- 契约类型:{{contract.kind}} · 深度:{{contract.depth}}
- 承接能力(⊆ 上游声明):{{contract.covered_capabilities}}

### 承接的上游声明交互

| 上游交互 | 本模块角色 | 契约承接方式 | 溯源 |
| --- | --- | --- | --- |
| {{#each contract.interaction_commitments}}| {{interaction}} | {{role}} | {{contract_handling}} | {{trace}} |
{{/each}}

## 操作(Operations)

先总览后明细:总览表让人一眼掌握每个操作"是什么、为什么存在";细节逐操作展开,
不挤在一张九列宽表里。

### 操作总览

| 操作 | 目的 | 承接能力 |
| --- | --- | --- |
| {{#each contract.operations}}| {{id}} {{name}} | {{purpose}} | {{capability}} |
{{/each}}

### 操作明细

{{#each contract.operations}}
#### {{id}} {{name}}

- 目的:{{purpose}}
- 承接能力:{{capability}}
- 请求/载荷:{{request}}
- 响应/载荷:{{response}}
- 错误:{{errors}}
- 幂等:{{idempotency}}
- 分页:{{pagination}}
- 溯源:{{trace}}

{{/each}}

## 错误语义

- 策略:{{contract.error_model.strategy}}
- 错误码表:{{contract.error_model.codes}}
- 示例:{{contract.error_model.example}}

## 版本与兼容

- 版本策略:{{contract.versioning.strategy}}
- 兼容规则(什么算破坏性变更、弃用路径):{{contract.versioning.compat_rules}}

## 关键取舍

| 决策 | 选择 | 理由 | 代价 | 替代方案 |
| --- | --- | --- | --- | --- |
| {{#each contract.tradeoffs}}| {{decision}} | {{choice}} | {{rationale}} | {{cost}} | {{alternative}} |
{{/each}}

## 自查对抗结论(7 维;独立评审见 verification)

| 维度 | 发现 | 处置 |
| --- | --- | --- |
| {{#each contract.self_challenge}}| {{dimension}} | {{finding}} | {{disposition}}{{#if rationale}}({{rationale}}){{/if}} |
{{/each}}

## 风险

| 风险 | 影响 | 缓解方式 | 需要验证的点 |
| --- | --- | --- | --- |
| {{#each risks}}| {{risk}} | {{impact}} | {{mitigation}} | {{to_validate}} |
{{/each}}

## 给下游 Skills 的交付物

### test-driven-development
{{downstream_deliverables.test_driven_development}}
### planning-and-task-breakdown
{{downstream_deliverables.planning_and_task_breakdown}}
### documentation-and-adrs
{{downstream_deliverables.documentation_and_adrs}}
### incremental-implementation
{{downstream_deliverables.incremental_implementation}}
### database-schema-design
{{downstream_deliverables.database_schema_design}}
### c4-architecture
{{downstream_deliverables.c4_architecture}}

## DECISION 汇总(用户拍板记录)

| 决定 | 锚点 |
| --- | --- |
| {{#each decisions}}| {{decision}} | {{id}} |
{{/each}}
