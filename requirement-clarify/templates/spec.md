# Spec: {{title}}

> 上游 PRD: `{{prd_source}}` — 本 Spec 引用其产品定义,不重写;与 PRD 冲突时以 PRD 为准,先回 PRD 再改这里。

## 1. Problem & Objective(引用)

- 问题与证据: 见 `{{prd_source}}` §1 — {{background_summary}}
- 目标与用户价值: 见 `{{prd_source}}` §2 — {{objective_summary}}

## 2. Scope(引用 + 工程补充)

- 见 `{{prd_source}}` §5 — {{scope_summary}}
- 工程侧补充(澄清新增): {{eng_scope_addenda}}

## 3. User-Visible Behavior(引用 + 细化)

{{prd_ref_user_stories}}

细化(逐条标来源): {{behavior_detail}}

## 4. Business Rules(澄清主场)

{{#each rules}}- {{rule}}(来源: {{source}})
{{/each}}
## 5. Permissions & State Rules

{{#each permissions}}- {{rule}}(来源: {{source}})
{{/each}}
## 6. Exception Behavior

{{#each exceptions}}- {{case}} → {{handling}}(来源: {{source}})
{{/each}}
## 7. Non-Functional Requirements

{{#each nfrs}}- {{requirement}}(来源: {{source}})
{{/each}}
## 8. 数据需求工程化(承接 PRD §6)

引用 `{{prd_source}}` §6 数据清单,**不设目标数字**;本节验收口径 = 每项数据需求是否已转化为具体工程实现。

| 指标 | 口径(PRD§6 引用) | 现状 | 工程项 |
|---|---|---|---|
{{#each data_metrics}}| {{name}} | {{definition}} | {{status}}(证据: {{code_evidence}}) | {{work_item}}(前端/后端/数据侧,锚 §2 工程侧补充) |
{{/each}}

## 9. Acceptance Criteria

{{#each acceptance}}- {{criteria}}
{{/each}}
- 埋点交付验收: {{tracking_acceptance}}(§8 表中"需新增"各项全部落地)

## 10. Boundaries

- Always: {{always}}
- Ask first: {{ask_first}}
- Never: {{never}}

## 11. Open Questions(随 Spec 移交下游,开发前必须闭环)

{{#each open_questions}}- [ ] {{question}}(owner: {{owner}})
{{/each}}
