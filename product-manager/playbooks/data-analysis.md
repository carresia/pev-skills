# Playbook: Data Analysis（数据分析 / 假设验证）

## 适用

"分析这份数据"、"验证这个假设"、"估算 ROI"。

## Plan 骨架

1. `analyze_data` — 口径对齐：明确指标定义、时间窗、分母、数据来源，写入 `state.known`。
2. `compare` — 假设检验：分组对照 / 趋势 / 相关性，输出可证伪的结论。
3. `estimate_roi` — 收益与成本测算，标注每个输入的置信度。
4. `draft` — 形成 `templates/decision.md` 决策文档。

## 最终交付

`templates/decision.md`：结论 + 证据 + 备选方案 + 决策建议。

## Verifier 重点检查

- Evidence、ROI、Metrics 必查。任何 FACT 没有 evidence，直接记 critical_issue。
- 相关不等于因果；出现逻辑跳跃必须 REPLAN。
