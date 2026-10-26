# 模块设计(精简):{{module.name}}({{module.id}})

<!-- 模板字段的含义见 module-design skill 的 references/fields.md;权威定义:schemas/artifact.schema.json -->

> 上游:{{upstream_source}}({{upstream_kind}}) · 迭代 {{iteration}} · Verdict {{verdict}} · 生成于 {{date}}
>
> 门禁:目标模块齐 {{gates.modules_complete}} · 边界守恒 {{gates.deps_within_architecture}} · 落点齐 {{gates.upstream_mapped}} · 自查处置 {{gates.findings_disposed}} · 交互一致 {{gates.cross_consistent}}

精简模式(brief):聚焦关键内部结构与核心流程,无 FMEA。完整设计 → 提升该模块为
detail 深度重做。

## 职责与边界(承接架构,简)

- 职责:{{module.responsibility}}
- 依赖(⊆ 架构声明):{{module.depends_on}}

## 关键内部结构

| 组件 | 职责 | 隐藏的决策/信息 | 溯源 |
| --- | --- | --- | --- |
| {{#each module.internal_components}}| {{id}} {{name}} | {{responsibility}} | {{hides}} | {{trace}} |
{{/each}}

### 架构暴露能力的内部实现落点

| 架构 exposes | 实现组件 | 溯源 |
| --- | --- | --- |
| {{#each module.exposes_realization}}| {{expose}} | {{component_id}} | {{trace}} |
{{/each}}

## 核心流程

| 流程 | 步骤 | 失败处理 | 溯源 |
| --- | --- | --- | --- |
| {{#each module.core_flows}}| {{name}} | {{steps}} | {{failure_handling}} | {{trace}} |
{{/each}}

## 关键 DFX 点

| X | 设计点 | 溯源 |
| --- | --- | --- |
| {{#each module.dfx}}| {{x}} | {{design}} | {{trace}} |
{{/each}}

## 残留与未决(交下游前须过目)

| 级别 | 条目 | 处置 |
|---|---|---|
| {{severity}} | {{item}} | {{resolution}} |

## DECISION 汇总(用户拍板记录)

| 决定 | 锚点 |
| --- | --- |
| {{#each decisions}}| {{decision}} | {{id}} |
{{/each}}
