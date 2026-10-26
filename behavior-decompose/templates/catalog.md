# 行为目录 — {{goal}}

> 上游:{{spec_source}} · 迭代 {{iteration}} · Verdict {{verdict}} · 生成于 {{date}}
>
> 覆盖门禁:场景类别 {{scenario_category_pct}}%(≥90%) · P0/P1 风险类 {{critical_risk_pct}}%(须 100%)
>
> 全局场景表态:适用 {{category_defaults.applicable}} · 全局豁免 {{category_defaults.inapplicable}}

本目录止于产品行为。技术选型 → `architecture-design`;代码级任务 → `planning-and-task-breakdown`。

## 残留与未决(交下游前须过目)

> 单轮评审通过不等于零残留。下表汇总 verification 的 warnings 与脚本「逐 story 适用未覆盖」清单,交下游时一并移交。

| 级别 | 条目 | 处置 |
|---|---|---|
| {{severity}} | {{item}} | {{resolution}} |

## 依赖总览

| 项 | 依赖 | 类型 | 说明 |
|---|---|---|---|
| {{from}} | {{to}} | {{blocked-by/related-to}} | {{note}} |

{{#each epics}}

## {{id}}: {{title}}

**Scope**:{{scope}}
**Success Criteria**:{{success_criteria}}

{{#each features}}

### {{id}}: {{title}}

| Story | 点数 | 优先级 | 溯源 |
|---|---|---|---|
{{#each stories}}
| {{id}} {{title}} | {{points}} | {{priority}} | {{trace}} |
{{/each}}

{{#each stories}}

#### {{id}}: {{title}}

**Acceptance Criteria**
{{#each acceptance_criteria}}
- {{this}}
{{/each}}

**Scenarios**
| 类别 | Given | When | Then | 溯源 |
|---|---|---|---|---|
{{#each scenarios}}
| {{class}} | {{given}} | {{when}} | {{then}} | {{trace}} |
{{/each}}
{{/each}}
{{/each}}
{{/each}}

## DECISION 汇总(用户拍板记录)

| 决定 | 锚点 |
|---|---|
| {{decision}} | {{evidence}} |
