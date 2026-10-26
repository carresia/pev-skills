# Playbook: Discovery（问题发现 / 机会挖掘）

## 适用

"指标为什么降"、"找增长机会"、"诊断问题"、"这个功能值不值得做"。

## Plan 骨架

1. `analyze_data` — 建立指标树，确认 baseline 与趋势（目标指标必须有数据来源）。
2. `segment_users` — 拆分人群 / 渠道 / 环节，定位问题集中处。
3. `user_research` / `compare` — 验证流失、转化的原因，区分 FACT 与 HYPOTHESIS。
4. `design` — 形成机会清单与优先级。每条机会必须关联 Evidence Ledger 条目的 `id`（如 E1）。

## 最终交付

`templates/product-opportunity.md`：机会卡片 + 优先级 + 证据。

## Verifier 重点检查

- Goal 和 Evidence 必查。Root Cause 检查适用于诊断类场景；非诊断场景（竞品、roadmap 等）改为检查"每条结论是否都有对应依据"。
- 机会若建立在 HYPOTHESIS 上，confidence 不得超过 medium，且验证实验必须写进机会卡片的后续步骤（artifact 内），不得放进 required_changes——PASS 不携带必改项。
