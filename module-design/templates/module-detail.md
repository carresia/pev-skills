# 模块设计:{{module.name}}({{module.id}})

<!-- 模板字段的含义见 module-design skill 的 references/fields.md;权威定义:schemas/artifact.schema.json -->

> 上游:{{upstream_source}}({{upstream_kind}}) · 迭代 {{iteration}} · Verdict {{verdict}} · 生成于 {{date}}
>
> 门禁:目标模块齐 {{gates.modules_complete}} · 边界守恒 {{gates.deps_within_architecture}} · 落点齐 {{gates.upstream_mapped}} · 自查处置 {{gates.findings_disposed}} · 交互一致 {{gates.cross_consistent}}

本设计止于模块。完整接口契约 → `api-and-interface-design`;建库 → `database-schema-design`(数据库设计是系统级决定);拆任务 → `planning-and-task-breakdown`。

## 残留与未决(交下游前须过目)

> 单轮评审通过不等于零残留。下表汇总 verification 的 warnings 与 accepted 风险,交下游时一并移交。

| 级别 | 条目 | 处置 |
|---|---|---|
| {{severity}} | {{item}} | {{resolution}} |

## 职责与边界(承接架构)

- 职责(承接架构声明):{{module.responsibility}}
- 不负责:{{module.not_responsible}}
- 依赖(⊆ 架构声明):{{module.depends_on}}

### 对架构关键交互的承接

| 架构交互 | 本模块角色 | 内部承接方式 | 溯源 |
| --- | --- | --- | --- |
| {{#each module.interaction_commitments}}| {{interaction}} | {{role}} | {{internal_handling}} | {{trace}} |
{{/each}}

### 自有数据的内部处理(逻辑级,无表结构)

| 数据(架构所有权) | 内部处理方式 | 溯源 |
| --- | --- | --- |
| {{#each module.owned_data_handling}}| {{data}} | {{handling}} | {{trace}} |
{{/each}}

## 内部设计

### 内部组件

| 组件 | 职责 | 隐藏的决策/信息 | 溯源 |
| --- | --- | --- | --- |
| {{#each module.internal_components}}| {{id}} {{name}} | {{responsibility}} | {{hides}} | {{trace}} |
{{/each}}

### 核心流程

| 流程 | 步骤 | 失败处理 | 溯源 |
| --- | --- | --- | --- |
| {{#each module.core_flows}}| {{name}} | {{steps}} | {{failure_handling}} | {{trace}} |
{{/each}}

### 架构暴露能力的内部实现落点

| 架构 exposes | 实现组件 | 说明 | 溯源 |
| --- | --- | --- | --- |
| {{#each module.exposes_realization}}| {{expose}} | {{component_id}} | {{note}} | {{trace}} |
{{/each}}

## DFX 特性设计(Design for X,面向质量属性的设计)

| X | 设计点(组件/机制/参数) | 溯源 |
| --- | --- | --- |
| {{#each module.dfx}}| {{x}} | {{design}} | {{trace}} |
{{/each}}

覆盖:可靠性 reliability · 可测试性 testability · 可维护性 maintainability · 可观测性 observability · 安全性 security

### FMEA(失效模式与影响分析)

| 组件 | 失效模式 | 影响 | 检测 | 缓解 |
| --- | --- | --- | --- | --- |
| {{#each module.fmea}}| {{component_id}} | {{failure_mode}} | {{effect}} | {{detection}} | {{mitigation}} |
{{/each}}

## 关键取舍

| 决策 | 选择 | 理由 | 代价 | 替代方案 |
| --- | --- | --- | --- | --- |
| {{#each module.tradeoffs}}| {{decision}} | {{choice}} | {{rationale}} | {{cost}} | {{alternative}} |
{{/each}}

## 自查对抗结论(7 维;独立评审见 verification)

| 维度 | 发现 | 处置 |
| --- | --- | --- |
| {{#each module.self_challenge}}| {{dimension}} | {{finding}} | {{disposition}}{{#if rationale}}({{rationale}}){{/if}} |
{{/each}}

## 风险

| 风险 | 影响 | 缓解方式 | 需要验证的点 |
| --- | --- | --- | --- |
| {{#each risks}}| {{risk}} | {{impact}} | {{mitigation}} | {{to_validate}} |
{{/each}}

## 给下游 Skills 的交付物

### api-and-interface-design
{{downstream_deliverables.api_and_interface_design}}
### database-schema-design
{{downstream_deliverables.database_schema_design}}
### c4-architecture
{{downstream_deliverables.c4_architecture}}
### documentation-and-adrs
{{downstream_deliverables.documentation_and_adrs}}
### planning-and-task-breakdown
{{downstream_deliverables.planning_and_task_breakdown}}
### test-driven-development
{{downstream_deliverables.test_driven_development}}

## DECISION 汇总(用户拍板记录)

| 决定 | 锚点 |
| --- | --- |
| {{#each decisions}}| {{decision}} | {{id}} |
{{/each}}
