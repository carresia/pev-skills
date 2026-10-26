# 对抗评审报告:{{goal}}

> 被评审 schema:{{upstream_source}} · 迭代 {{iteration}} · Verdict {{verdict}} · 生成于 {{date}}
>
> 门禁:7 维全齐且诚实 {{gates.findings_disposed}}

<!-- 本文件为手工填充模板:{{...}} 是占位符,{{#each}}/{{#if}} 表示按数组/条件展开;本 skill 无渲染引擎,由 agent 对照 review_findings 逐项填实。 -->

本报告止于发现与处置建议。是否按发现重做 schema 由用户决定(另走 design 场景,mode 变更记 DECISION)。

## 结论

- 总体判断:{{overall_verdict}}
- BLOCKING:{{blocking_count}} 条 · HIGH:{{high_count}} 条 · MEDIUM:{{medium_count}} 条 · LOW:{{low_count}} 条
- 最严重的三个问题:{{top3}}

## 评审覆盖声明(对抗 7 维,全部扫过)

| 维度 | 发现 | 严重度 |
| --- | --- | --- |
| {{#each review_findings}}| {{dimension}} | {{finding}} | {{severity}} |
{{/each}}

## 发现明细

{{#each review_findings}}
{{#if finding}}
### {{id}} [{{severity}}] {{dimension}}

- **发现**:{{finding}}
- **锚点**:{{evidence_anchor}}
- **处置建议**:{{recommendation}}
{{/if}}
{{/each}}

## 对照上游(若提供了模块设计/架构设计)

{{upstream_cross_check}}

## DECISION 汇总(评审中用户拍板的口径)

| 决定 | 锚点 |
| --- | --- |
| {{#each decisions}}| {{decision}} | {{id}} |
{{/each}}
