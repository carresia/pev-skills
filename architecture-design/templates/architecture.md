# 架构决策:{{goal}}

> 上游:{{upstream_source}}({{upstream_kind}}) · 迭代 {{iteration}} · Verdict {{verdict}} · 生成于 {{date}}
>
> 门禁:依赖无环 {{gates.dependency_acyclic}} · owner 唯一 {{gates.unique_owners}} · 上游映射 {{gates.upstream_mapped}} · 自查处置 {{gates.findings_disposed}}

本设计止于架构。完整接口 → `api-and-interface-design`;建库 → `database-schema-design`;拆任务 → `planning-and-task-breakdown`。

## 残留与未决(交下游前须过目)

> 单轮评审通过不等于零残留。下表汇总 verification 的 warnings 与 accepted 风险,交下游时一并移交。

| 级别 | 条目 | 处置 |
|---|---|---|
| {{severity}} | {{item}} | {{resolution}} |

## 结论

- 推荐架构:{{style.choice}}
- 核心理由:{{style.rationale}}
- 不推荐的方向:更简 {{style.rejected_simpler}} · 更复杂 {{style.rejected_complexer}}
- 最大架构风险:{{top_risk}}

## 架构输入摘要

- 目标 / 范围 / 关键约束 / 非功能要求 / 规模假设:
{{input_summary}}
- 上游条目(U1…Un,覆盖分母,见「上游映射」表)

## 现有架构适配(仅现有库)

- 当前模式 / 应复用的约定 / 需避免破坏的边界 / 已知技术债 / 已知扩展瓶颈:
{{codebase_fit}}

## 系统边界

- 系统内 / 系统外 / 外部依赖 / 信任边界 / 部署边界:
{{boundaries}}

## C4 映射

- Context / Container / 是否需要 Component / 是否需要 Deployment:
{{c4_mapping}}

## 模块划分

| 模块 | 职责 | 拥有的数据 | 暴露能力 | 依赖 | 不负责 | 溯源 |
| --- | --- | --- | --- | --- | --- | --- |
{{#each modules}}| {{id}} {{name}} | {{responsibility}} | {{owns_data}} | {{exposes}} | {{depends_on}} | {{not_responsible}} | {{trace}} |
{{/each}}

## 关键交互

| 场景 | 发起方 | 接收方 | 交互方式 | 一致性要求 | 失败处理 |
| --- | --- | --- | --- | --- | --- |
{{#each interactions}}| {{scenario}} | {{from}} | {{to}} | {{mode}} | {{consistency}} | {{failure_handling}} |
{{/each}}

## 数据所有权

| 数据 | Owner 模块 | 读方 | 写方 | 一致性要求 |
| --- | --- | --- | --- | --- |
{{#each data_ownership}}| {{data}} | {{owner}} | {{readers}} | {{writers}} | {{consistency}} |
{{/each}}

## 上游映射(覆盖对账)

| 上游条目 | 架构落点 | 溯源 |
| --- | --- | --- |
{{#each upstream_mapping}}| {{upstream_item}} | {{module_id}} | {{trace}} |
{{/each}}

## 关键取舍

| 决策 | 选择 | 理由 | 代价 | 替代方案 |
| --- | --- | --- | --- | --- |
{{#each tradeoffs}}| {{decision}} | {{choice}} | {{rationale}} | {{cost}} | {{alternative}} |
{{/each}}

## 自查对抗结论(7 维;独立评审见 verification)

| 维度 | 发现 | 处置 |
| --- | --- | --- |
{{#each self_challenge}}| {{dimension}} | {{finding}} | {{disposition}}{{#if rationale}}({{rationale}}){{/if}} |
{{/each}}

## 风险

| 风险 | 影响 | 缓解方式 | 需要验证的点 |
| --- | --- | --- | --- |
{{#each risks}}| {{risk}} | {{impact}} | {{mitigation}} | {{to_validate}} |
{{/each}}

## 运行与演进约束

- 部署 / 监控告警 / 备份恢复 / 回滚 / 容量增长:
{{ops_constraints}}

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
{{#each decisions}}| {{decision}} | {{id}} |
{{/each}}
