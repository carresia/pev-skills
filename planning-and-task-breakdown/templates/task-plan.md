# 实施任务清单 — {{goal}}

> 门槛上游:{{arch_source}} · 补充源:{{aux_sources}} · 迭代 {{iteration}} · Verdict {{verdict}} · 生成于 {{date}}
>
> 覆盖门禁:范围内工作项落点 {{upstream_coverage_pct}}%(须 100%)

本清单止于任务拆解。架构/设计决策 → 上游 skill;写代码 → `incremental-implementation` +
`test-driven-development`。

<!-- 渲染说明(渲染后删除本注释):{{}} 为占位符,#each 按数组逐条展开;数组为空时
对应小节整节省略。取值来源:goal/arch_source/aux_sources/iteration ← state.json;
verdict ← 最新迭代 verification.verdict;upstream_coverage_pct 与 uncovered ←
validate.py 输出,照抄不自算;warnings/evidence_gaps ← 最新 verification;
tasks ← 各 phase 任务平铺;parallel_groups ← 按 parallel_group 聚合;
decisions ← Evidence Ledger 中 type=DECISION 条目。 -->

## 残留与未决(交下游前须过目)

> 单轮评审通过不等于零残留。下表汇总三处来源,交下游时一并移交。

| 来源 | 条目 |
|---|---|
{{#each warnings}}
| verification.warning | {{this}} |
{{/each}}
{{#each evidence_gaps}}
| evidence_gap | {{this}} |
{{/each}}
{{#each uncovered}}
| 未覆盖工作项(脚本清单) | {{this}} |
{{/each}}

## 工作项登记(inventory)

| ID | 类型 | 工作项 | 溯源 | 范围内 |
|---|---|---|---|---|
{{#each inventory}}
| {{id}} | {{kind}} | {{title}} | {{anchor}} | {{#if in_scope}}是{{else}}否——{{note}}{{/if}} |
{{/each}}

## 依赖总览(全阶段任务平铺)

| 任务 | 前置 |
|---|---|
{{#each tasks}}
| {{id}} {{title}} | {{dependencies}} |
{{/each}}

## 并行组(按 parallel_group 聚合)

| 组 | 任务 |
|---|---|
{{#each parallel_groups}}
| {{group}} | {{tasks}} |
{{/each}}

{{#each phases}}

## {{id}}: {{title}}

**Objective**:{{objective}}

| 任务 | 规模 | 文件数 | 落点 | 溯源 |
|---|---|---|---|---|
{{#each tasks}}
| {{id}} {{title}} | {{size}} | {{files_touched.length}} | {{implements}} | {{trace}} |
{{/each}}

{{#each tasks}}

### {{id}}: {{title}}

**Description**:{{description}}

**Files**
{{#each files_touched}}
- {{this}}
{{/each}}

**Acceptance Criteria**
{{#each acceptance_criteria}}
- [ ] {{this}}
{{/each}}

**Verification**
| 方式 | 类型 | 判定 |
|---|---|---|
{{#each verification}}
| {{how}} | {{kind}} | {{expectation}} |
{{/each}}

**Dependencies**:{{dependencies}} · **并行组**:{{parallel_group}}
{{/each}}

**Checkpoint**
{{#each checkpoint.checks}}
- [ ] {{this}}
{{/each}}
{{#if checkpoint.review_with_human}}
- [ ] **人工 review:过检后须人确认才进下一阶段**
{{/if}}
{{/each}}

## 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
{{#each risks}}
| {{risk}} | {{impact}} | {{mitigation}} |
{{/each}}

## 开放问题

{{#each open_questions}}
- {{this}}
{{/each}}

## DECISION 汇总(用户拍板记录)

| 决定 | 锚点 |
|---|---|
{{#each decisions}}
| {{claim}} | {{evidence}} |
{{/each}}
