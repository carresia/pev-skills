# Decision: {{title}}

## 结论

{{conclusion}}（confidence: {{confidence}}）

## 证据

| Claim | Type | Evidence |
|---|---|---|
{{#each evidence}}| {{claim}} | {{type}} | {{evidence}} |
{{/each}}

## 备选方案

{{#each solutions}}
### {{name}}
- 收益：{{benefit}}（confidence: {{benefit_confidence}}）
- 成本：{{cost}}
- 风险：{{risks}}
{{/each}}

## ROI 测算

{{roi}}

## 决策建议

{{recommendation}}
