# Artifact 字段速查(module-design)

Executor 产出的 `iterations/<N>-artifact.json` 字段的人话解释,供人工审核
executor / verifier / templates 时对照。权威定义在
[schemas/artifact.schema.json](../schemas/artifact.schema.json),两者冲突以 schema 为准。

共同逻辑:设计里的一切对外承诺 ⊆ 架构声明(**边界守恒**),架构声明条条有内部
落点(**覆盖对账**)。**架构快照** = `input_summary.architecture_snapshot`,把架构的
模块声明(职责/依赖/暴露/数据)与关键交互抄成结构化 JSON,是所有 ⊆ 检查的机器基准。

## 顶层字段(artifact 内)

| 字段 | 是什么 |
|---|---|
| `architecture_snapshot.modules[]` | 架构对每个模块的声明:id、职责、`depends_on`(依赖谁)、`exposes`(对外暴露什么能力)、`owns_data`(拥有哪些数据) |
| `architecture_snapshot.interactions[]` | 架构声明的关键交互:id(如 I3)、场景、发起方、接收方 |
| `upstream_items` | 覆盖对账的分母:每个目标模块的职责条目(如 M1-R)与每条暴露能力(如 M1-E2),从架构产物逐条抄下 |
| `upstream_mapping` | 覆盖对账的分子:每条上游条目落在哪个模块(与 upstream_items 双向对账,validate.py 强制) |
| `codebase_fit` | 勘察现有代码库的结论:当前模式、可复用约定、勿破坏边界、技术债、已知瓶颈 |
| `risks` | 明确接受的风险:风险、影响、缓解方式、待验证点 |
| `downstream_deliverables` | 给下游 skills(api/database/c4/adr/planning/tdd)的输入清单 |

## 模块级字段(modules[] 内)

| 字段 | 是什么 |
|---|---|
| `depends_on` | 本模块依赖哪些模块(必须 ⊆ 架构快照声明;要新依赖 = 架构层缺口,走三选一) |
| `internal_components` | 模块内部切成哪几个组件;`hides` = 该组件隐藏的设计决策,是这条边界存在的理由(复述职责不算) |
| `core_flows` | 核心流程:名字、步骤、失败处理 |
| `exposes_realization` | 架构给的每条对外能力由哪个内部组件实现(落点) |
| `owned_data_handling` | 架构分配给本模块的自有数据在内部怎么处理(逻辑级,不含表结构;表结构归 database-schema-design) |
| `interaction_commitments` | 本模块承接哪些架构声明的交互、以什么角色(发起方/接收方)、内部怎么承接 |
| `dfx` | 面向质量属性的设计点:可靠性/可测试性/可维护性/可观测性/安全性;必须落到具体组件与机制,口号不算 |
| `fmea` | 失效模式与影响分析:哪个组件会怎么坏、影响、怎么发现、怎么兜底(仅 detail 模式) |
| `tradeoffs` | 模块内关键取舍:决策、选择、理由、`cost`(放弃了什么)、替代方案 |
| `self_challenge` | 提交前 7 维自查(failure_modes / consistency / concurrency / boundary_erosion / hidden_coupling / testability / simpler_alternative)的发现与处置 |
