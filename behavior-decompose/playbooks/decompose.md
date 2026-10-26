# Playbook: Decompose(Spec/PRD → 行为目录)

## 适用

上游已有工程 Spec(`.pev/<轮次>/rc/output/spec.md`,优先)或用户直接提供已批准 PRD,
需拆解为行为目录(Epic → Feature → Story → 验收标准 → 11 类场景两级表态)。

## 前置条件

`state.spec_source` 存在且可读。分流:

- 有 PRD 但没澄清过 → 建议先走 `requirement-clarify`(用户明确要求直拆 PRD 才兜底直收);
- 什么上游都没有 → `spec-driven-development` 从零澄清;
- 要写/改 PRD → `product-manager`。本 skill 不启动。

## Plan 骨架

1. `analyze_requirement` — 解析目标、范围边界、拆解深度;选策略(top-down 默认 /
   bottom-up);范围过大时收敛(如 top 3 epics)并记 stop_conditions。
2. `decompose` — 逐 Epic 批次:EPIC(scope + success criteria)→ FEATURE → STORY
   (业务语言、≤8 故事点、验收标准达下限、INVEST 六项检查、trace 溯源)。
3. `enumerate_scenarios` — 定全局 `category_defaults` + 逐 Story 枚举场景(11 类清单、
   两级表态与 `covers` 声明规则见 guides/decomposition-flow.md「场景覆盖算法」)。
   仅当 Plan 未把它并入 decompose 批次时单独成步。
4. `map_dependencies` — 产品级依赖图(blocked-by / related-to)+ 环检测。
5. `draft` — 聚合完整目录 → 预览与精修循环(用户指令逐条记 DECISION)→ 交 VERIFYING。

## 最终交付

`templates/catalog.md` 渲染到 `.pev/<轮次>/decompose/output/catalog.md`;PASS 且用户确认后即完成,
目录交给下游 skill。

## Verifier 侧重

检查矩阵、门禁阈值与 verdict 规则以 `agents/verifier.md` 为准。
