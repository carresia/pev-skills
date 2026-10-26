# 接口契约(精简):{{contract.name}}({{contract.id}})

<!-- 模板字段的含义见 api-and-interface-design skill 的 references/fields.md;权威定义:schemas/artifact.schema.json -->

> 上游:{{upstream_source}}({{upstream_kind}}) · 迭代 {{iteration}} · Verdict {{verdict}} · 生成于 {{date}}
>
> 门禁:目标契约面齐 {{gates.contracts_complete}} · 契约守恒 {{gates.capabilities_within_upstream}} · 落点齐 {{gates.upstream_mapped}} · 自查处置 {{gates.findings_disposed}} · 交互一致 {{gates.cross_consistent}}

精简模式(brief):聚焦能力 → 操作清单,无完整请求/响应 schema 与逐面错误模型。
完整契约 → 提升该契约面为 detail 深度重做。全局错误语义与版本策略以 detail 契约面
(若有)为准。

## 契约定位(承接上游,简)

- 承接模块:{{contract.owner_module}}
- 契约类型:{{contract.kind}} · 深度:{{contract.depth}}
- 承接能力(⊆ 上游声明):{{contract.covered_capabilities}}

### 承接的上游声明交互

| 上游交互 | 本模块角色 | 契约承接方式 |
| --- | --- | --- |
| {{#each contract.interaction_commitments}}| {{interaction}} | {{role}} | {{contract_handling}} |
{{/each}}

## 操作清单

| 操作 | 目的 | 承接能力 |
| --- | --- | --- |
| {{#each contract.operations}}| {{id}} {{name}} | {{purpose}} | {{capability}} |
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
