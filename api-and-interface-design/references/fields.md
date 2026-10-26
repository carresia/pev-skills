# Artifact 字段速查(api-and-interface-design)

Executor 产出的 `iterations/<N>-artifact.json` 字段的人话解释,供人工审核
executor / verifier / templates 时对照。权威定义在
[schemas/artifact.schema.json](../schemas/artifact.schema.json),两者冲突以 schema 为准。

共同逻辑:契约里暴露的一切能力 ⊆ 上游声明(**契约守恒**),上游声明的能力条条有
契约落点(**覆盖对账**)。**上游快照** = `input_summary.upstream_snapshot`,把上游
产物的模块声明(exposes/owns_data)与交互声明(mode/一致性/失败处理/幂等)抄成
结构化 JSON,是所有 ⊆ 检查的机器基准。

## 顶层字段(artifact 内)

| 字段 | 是什么 |
|---|---|
| `upstream_snapshot.modules[]` | 上游对每个模块的声明:id、名称、`exposes`(对外暴露什么能力)、`owns_data`(拥有哪些数据) |
| `upstream_snapshot.interactions[]` | 上游声明的交互:id(如 I3)、场景、发起方、接收方,及 `mode`(sync/async/data-flow)、`consistency`、`failure_handling`、`idempotency`(后四项自上游交互声明抄——arch 关键交互表或 module 下游交付物;缺则省略) |
| `upstream_items` | 覆盖对账的分母:目标模块的每条能力条目(如 M1-E2)与每条目标交互(如 I3),从上游产物逐条抄下 |
| `upstream_mapping` | 覆盖对账的分子:每条上游条目落在哪个契约面(与 upstream_items 双向对账,validate.py 强制) |
| `codebase_fit` | 勘察现有 API 的结论:当前模式、可复用约定、勿破坏边界、技术债、已知瓶颈 |
| `risks` | 明确接受的风险:风险、影响、缓解方式、待验证点 |
| `downstream_deliverables` | 给下游 skills(tdd/planning/documentation/implementation)的输入清单 |

## 契约面级字段(contracts[] 内)

| 字段 | 是什么 |
|---|---|
| `kind` | 契约面类型:rest / graphql / event / internal / frontend_backend |
| `depth` | detail(完整契约)/ brief(能力→操作清单级,无完整请求/响应 schema) |
| `owner_module` | 该契约面承接哪个模块的能力(必须 ∈ 上游快照模块) |
| `covered_capabilities` | 本契约面承接的上游能力(必须 ⊆ 快照 exposes) |
| `operations` | 契约操作:REST 为 method+path,事件为事件名+载荷;detail 模式 request/response 非空,brief 模式必须为空 |
| `error_model` | 错误语义:策略、错误码表、示例(detail 必填非空;brief 必须省略整个字段,渲染文档注明全局错误语义以 detail 契约面为准) |
| `versioning` | 版本与兼容策略:策略、兼容规则(detail 必填非空) |
| `tradeoffs` | 契约关键取舍:决策、选择、理由、`cost`(放弃了什么)、替代方案 |
| `self_challenge` | 提交前 7 维自查(failure_modes / consistency / concurrency / boundary_erosion / misuse_potential / compatibility / simpler_alternative)的发现与处置 |
