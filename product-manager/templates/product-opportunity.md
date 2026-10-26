# Product Opportunity: {{title}}

## 业务目标与指标

- Goal: {{goal}}
- Target Metric: {{metric}}（baseline: {{baseline}} → target: {{target}}）

## 问题与根因

{{problem}} → {{root_cause}}

## 证据（Evidence Ledger 摘要）

| Claim | Type | Evidence | Confidence |
|---|---|---|---|
{{#each evidence}}| {{claim}} | {{type}} | {{evidence}} | {{confidence}} |
{{/each}}

## 机会清单与优先级

{{#each opportunities}}
### {{name}}（{{priority}}）
- 预期影响：{{impact}}
- 依据：{{evidence_ref}}
- 置信度：{{confidence}}
{{/each}}

## 建议

{{recommendation}}
