# Playbook: Requirement（PRD / 方案设计）

## 适用

"写 PRD"、"需求文档"、"出方案"。

## 前置条件

问题与根因必须已有 FACT 级证据（在 Evidence Ledger 中）。否则 Planner 必须先安排 discovery / data-analysis 类步骤，不允许直接进入方案设计。

## Plan 骨架

1. `analyze_data` — 复核问题、根因、目标指标（已验证的则快速通过）。
2. `design` — 至少包含 Option A / Option B / Do Nothing，含 Experiment / MVP 分层。
3. `estimate_roi` — 各方案的收益、成本、风险、置信度。
4. `draft` — 按模板产出 PRD：背景、目标、用户故事、功能范围、验证数据需求（每个指标写明口径与来源；口径指指标的定义与统计方式；需新增的口径属于开发范围）、成功指标、风险。

## 最终交付

`templates/prd.md`。

## Verifier 重点检查

- Solution、Metrics、Completeness 必查；缺 Primary / Secondary / Guardrail Metrics → REVISE。
- 验证数据需求必查：指标口径缺失，或需新增的数据口径未落入功能范围（In Scope）→ REVISE。
