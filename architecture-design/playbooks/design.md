# Playbook: design(默认场景)

上游已批准,要一份可实施的技术设计。交付模板:`templates/architecture.md`。

## Plan 骨架

```text
1. survey_upstream    —— 提炼架构输入(必为第一步)
2. survey_codebase    —— 仅当存在现有代码库/既有系统
3. choose_style       —— 架构风格 + 为什么拒绝更简单/更复杂
4. define_modules     —— 边界 + 模块 + 依赖方向(大系统分多批,每批一组模块域)
5. map_interactions   —— 关键交互 + 数据所有权(可与 4 合并,小系统)
6. state_tradeoffs    —— 关键取舍 + 运行演进约束
7. draft              —— 聚合 + downstream_deliverables + self_challenge 自查
```

小系统允许 4/5/6 合并为一个 `define_modules` step;步骤数与复杂度成正比,
不为了显得周全而增加。

## Executor 要点

- **风格默认从简**:模块化单体/清晰分层是默认答案;微服务、事件驱动只在有真实的
  独立部署/团队边界/故障隔离/扩展隔离/合规隔离需求时引入,且需求必须可溯源到上游
  (记 FACT),否则记 DECISION 浮出。
- **依赖方向显式**:每个模块的 depends_on 必须写全;核心域不依赖外围(不依赖
  框架/交付机制的方向倒挂是 Verifier 的必抓项)。
- **数据所有权**:每个核心数据一个 owner 模块,owner 必须在写方列表里;非 owner
  写同一数据 = 一致性 bug 的出生地,要么改设计,要么进 risks 并给理由。
- **交互只到架构级**:同步调用/异步消息/数据流 + 一致性要求 + 失败处理 + 幂等
  需要;不写 API 签名,那是 `api-and-interface-design` 的活。
- **下游交付物节必须填**:六个下游 skill 各自拿到什么输入,写具体条目,不写
  "见上文"。

## Verifier 检查重点(本场景加压项)

- upstream_items 声明完备性(漏声明 = 覆盖检查失去分母,直接 REVISE)
- 每个复杂度机制的"真实问题"溯源
- simpler_alternative 维度:有没有明显更简单的方案被无声跳过
- 数据所有权的写方列表:非 owner 写方逐条质询
