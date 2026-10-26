# PRD: {{title}}

## 1. 背景

{{background}}（含证据引用）

## 2. 目标

- 业务目标：{{goal}}
- Primary Metric: {{primary_metric}}（baseline → target）
- Secondary Metrics: {{secondary_metrics}}
- Guardrail Metrics: {{guardrail_metrics}}

## 3. 用户与场景

{{#each user_stories}}- 作为 {{user}}，我希望 {{action}}，以便 {{value}}。
{{/each}}

## 4. 方案

{{solution}}（为什么对应根因：{{solution_rationale}}）

## 5. 功能范围

### In Scope
{{in_scope}}

### Out of Scope
{{out_of_scope}}

## 6. 验证数据需求（埋点与口径）

本节定义上线后需要收集哪些数据来验证这个需求的价值。如果某个指标的口径在现有项目中不存在，对应的数据采集工作就是开发工作，必须列入第 5 节的 In Scope。

| 指标 | 口径定义 | 验证什么 | 数据来源 |
|---|---|---|---|
{{#each validation_metrics}}| {{name}} | {{definition}} | {{purpose}} | {{source}}（现有 / 需新增） |
{{/each}}

## 7. 风险与预案

{{risks}}

## 8. 上线与验收

- 上线计划：{{launch_plan}}
- 验收标准：{{acceptance}}
