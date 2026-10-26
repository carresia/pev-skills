# Playbook: Breakdown(上游产物 → 任务清单)

## 适用

门槛上游已有架构产物(`.pev/<轮次>/arch/output/`,或用户提供的架构文档),需要把架构
(连同同轮 module/api/db/decompose 产物)拆解为有序、可验证、带依赖与并行边界的实施任务清单。

## 前置条件

`state.arch_source` 存在且可读。分流见 SKILL.md Input Gate:

- 只有 Spec/PRD、无任何技术设计 → 打回上游:有业务 PRD 先走 `requirement-clarify`,
  已有 Spec 先走 `behavior-decompose`,然后 `architecture-design`,本 skill 不启动;
- 用户直接给架构文档 → 记 DECISION 继续,风险写明(对账分母粒度不可靠);
- 同轮四类设计产物(module/api/db/decompose 的 output/)自动登记为补充上游
  (只记路径,引用不复制),不逐个问用户。

## Plan 骨架

1. `survey_context` — 通读架构与 aux_sources,勘察代码库现状;选切片策略(纵切默认 /
   分层攻坚);范围过大时收敛并记 stop_conditions。
2. `build_inventory` — 登记上游工作项(架构模块 / 模块能力 / API 契约 / 库表 / Story /
   工程支撑项),定 in_scope 与范围外理由。小项目可并入第 1 步。
3. `define_phases` — 定 PHASE 划分、顺序依据、各阶段终点检查点与是否人工 review。
4. `breakdown` — 逐 PHASE 批次:任务(四档规模、验收标准、验证方式、implements、trace)。
5. `map_dependencies` — 任务依赖图 + 环检测 + 并行组划分。仅当 Plan 未把它并入 breakdown
   批次时单独成步。
6. `draft` — 聚合完整清单 → 预览与精修循环(用户指令逐条记 DECISION)→ 交 VERIFYING。

## 最终交付

`templates/task-plan.md` 渲染到 `.pev/<轮次>/tasks/output/task-plan.md`;PASS 且用户确认后
即完成,清单交给下游 skill(incremental-implementation + test-driven-development)。

## Verifier 侧重

检查矩阵、门禁阈值与 verdict 规则以 `agents/verifier.md` 为准。
