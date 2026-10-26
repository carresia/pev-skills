# 选型决策:{{goal}}

> 上游:{{upstream_source}}({{upstream_kind}}) · 迭代 {{iteration}} · Verdict {{verdict}} · 生成于 {{date}}
>
> 门禁:候选结构 {{gates.dependency_acyclic}} · 上游映射 {{gates.upstream_mapped}} · 代价与推荐 {{gates.findings_disposed}}

本决策止于选型与推荐。选定后的完整设计另走 design 场景(同轮次或新迭代,mode 变更记 DECISION)。

## 残留与未决(交下游前须过目)

| 级别 | 条目 | 处置 |
|---|---|---|
| {{severity}} | {{item}} | {{resolution}} |

## 结论

- 推荐:**{{recommendation.option_id}}**
- 核心理由:{{recommendation.rationale}}
- 失效条件(出现即应重新选型):{{recommendation.conditions}}

## 选型硬约束(来自上游,评估维度来源)

{{input_summary}}

## 候选方案

{{#each options}}
### {{id}}: {{name}}

- 概要:{{summary}}
- 对上游的契合:{{fit}}
- **真实代价**:{{cost}}
- 复杂度:{{complexity}} · 风险:{{risks}}
{{/each}}

## 评估矩阵

| 维度(锚定上游) | 权重 |{{#each options}} {{id}} {{/each}}| 理由 |
| --- | --- |{{#each options}} --- {{/each}}| --- |
{{#each evaluation}}| {{criterion}} | {{weight}} |{{scores_cells}}| {{rationale}} |
{{/each}}

## 落选理由

{{#each recommendation.rejected_because}}
- {{@key}}: {{this}}
{{/each}}

## 上游映射(推荐方案下的承载)

| 上游条目 | 落点 | 溯源 |
| --- | --- | --- |
{{#each upstream_mapping}}| {{upstream_item}} | {{module_id}} | {{trace}} |
{{/each}}

## DECISION 汇总(用户拍板记录)

| 决定 | 锚点 |
| --- | --- |
{{#each decisions}}| {{decision}} | {{id}} |
{{/each}}
