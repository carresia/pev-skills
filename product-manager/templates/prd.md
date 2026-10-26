# {{title}}

## 1. 背景

{{background}}

## 2. 目标

- 业务目标：{{goal}}
- Primary Metric: {{primary_metric}}
- Secondary Metrics: {{secondary_metrics}}
- Guardrail Metrics: {{guardrail_metrics}}

## 3. 用户与场景

{{#each user_stories}}- 作为 {{user}}，我希望 {{action}}，以便 {{value}}。
{{/each}}

## 4. 方案

<!-- 结构提示：solution 写方案本身；solution_rationale 说明为什么该方案对应根因（因果链写清） -->
{{solution}}（依据：{{solution_rationale}}）

## 5. 功能范围

### In Scope
{{in_scope}}

### Out of Scope
{{out_of_scope}}

## 6. 验证数据需求（埋点与口径）

<!-- 本节定义上线后需要收集哪些数据来验证需求价值；指标口径在现有项目不存在时，对应数据采集须列入第 5 节 In Scope -->
| 指标 | 口径定义 | 验证什么 | 数据来源 |
|---|---|---|---|
{{#each validation_metrics}}| {{name}} | {{definition}} | {{purpose}} | {{source}} |
{{/each}}

## 7. 风险与预案

{{risks}}

## 8. 上线与验收

- 上线计划：{{launch_plan}}
- 验收标准：{{acceptance}}
