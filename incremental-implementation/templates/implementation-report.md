# 实施报告 — {{goal}}

> 门槛上游:{{plan_source}} · 补充源:{{aux_sources}} · 迭代 {{iteration}} · Verdict {{verdict}} · 生成于 {{date}}
>
> 门禁:任务执行覆盖 {{task_execution_pct}}%(须 100%)· 范围违规 {{scope_violations}} 项(须 0)

本报告止于实施。拆任务 → `planning-and-task-breakdown`;架构/契约/DDL 变更 → 对应
设计 skill;测试技法 → `test-driven-development`。

<!-- 渲染说明(渲染后删除本注释):{{}} 为占位符,#each 按数组逐条展开;数组为空时
对应小节整节省略。取值来源:goal/plan_source/aux_sources/iteration ← state.json;
verdict ← 最新迭代 verification.verdict;task_execution_pct 与 scope_violations ←
validate.py 输出,照抄不自算;warnings/evidence_gaps ← 最新 verification;
records ← artifact.task_records;deviations ← 各 record 的 deviations 平铺;
decisions ← Evidence Ledger 中 type=DECISION 条目。 -->

## 残留与未决(交付前须过目)

> 单轮评审通过不等于零残留。下表汇总三处来源,交付时一并移交。

| 来源 | 条目 |
|---|---|
{{#each warnings}}
| verification.warning | {{this}} |
{{/each}}
{{#each evidence_gaps}}
| evidence_gap | {{this}} |
{{/each}}
{{#each unfinished}}
| 未完成/失败/延后任务 | {{this}} |
{{/each}}

## 基线

分支 `{{baseline.branch}}` · 起点 commit `{{baseline.commit}}`

| 检查 | 结果 |
|---|---|
{{#each baseline.checks}}
| {{what}} | {{result}} |
{{/each}}

## 任务执行总览

| 任务 | 状态 | 提交 | 实改文件 | 偏离 | 验证 |
|---|---|---|---|---|---|
{{#each records}}
| {{id}} {{title}} | {{status}} | {{commits.length}} | {{files_changed.length}} | {{deviations.length}} | {{pass_count}}/{{tests.length}} |
{{/each}}

{{#each records}}

### {{id}}: {{title}}

**状态**:{{status}}{{#if note}} — {{note}}{{/if}}

**Commits**:{{commits}}

**实际改动文件**
{{#each files_changed}}
- {{this}}
{{/each}}

{{#if deviations}}
**偏离声明**
| 文件 | 理由 |
|---|---|
{{#each deviations}}
| {{path}} | {{why}} |
{{/each}}
{{/if}}

**验证记录**
| 命令 | 类型 | 结果 | 证据 |
|---|---|---|---|
{{#each tests}}
| {{how}} | {{kind}} | {{result}} | {{evidence}} |
{{/each}}

**验收对照**
| 验收标准 | 满足 | 证据 |
|---|---|---|
{{#each acceptance_results}}
| {{criterion}} | {{met}} | {{evidence}} |
{{/each}}
{{/each}}

## 延后任务

| 任务 | 理由 | 后续 |
|---|---|---|
{{#each deferred_tasks}}
| {{id}} {{title}} | {{note}} | {{next}} |
{{/each}}

## DECISION 汇总(用户拍板记录)

| 决定 | 锚点 |
|---|---|
{{#each decisions}}
| {{claim}} | {{evidence}} |
{{/each}}
