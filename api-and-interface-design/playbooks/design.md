# Playbook: design(默认场景)

上游产物已批准(module-design 或 architecture-design,均为标准上游),要逐契约面的接口契约设计。交付模板:detail → `templates/api-contract.md`,brief → `templates/api-contract-brief.md`。

## Plan 骨架

```text
1. survey_upstream     —— 条目化每个目标契约面承接的上游声明(必为第一步)
2. survey_codebase     —— 仅当存在现有 API/既有端点
3. design_contracts    —— 每批一个契约面(强关联小契约面可合并一批),被消费的先做
4. cross_check         —— 跨契约一致性自查(错误语义/命名与概念漂移/版本策略/能力重复)
5. draft               —— 聚合 + downstream_deliverables + 精修循环
```

单契约面简单轮次允许 3/4/5 各一步收口;步骤数与契约面数和复杂度成正比,不为了显得周全而增加。

## Executor 要点

- **契约守恒优先**:covered_capabilities ⊆ owner_module 的快照 exposes;交互承接只取
  声明过的交互且参与方对齐;越界需求(新能力/新端点/交互语义缺失)→ `unresolved` +
  blocked → 三选一,不私自扩边。
- **操作回指能力**:每个操作写清承接哪条上游能力;写不出能力背书的操作 = 删。
- **隐性契约显式化**:排序稳定性、时序、错误文案这类会被消费者依赖的可观察行为,
  要么明确写进契约,要么收敛掉(Hyrum 定律)。
- **错误语义统一到 code 表**:detail 模式 error_model 落到 strategy + codes + 示例;
  幂等:上游交互标了 idempotency 的逐条有交代;列表操作有分页。
- **兼容交代**:detail 模式 versioning 写清什么算破坏性变更、弃用路径(One-Version
  优先,加法优于修改)。
- **响应不泄漏实现**:内部字段/表结构/堆栈/内部错误细节不进契约。
- **下游交付物节必须填**:各下游 skill 拿到什么输入,写具体条目,不写"见上文"。

## Verifier 检查重点(本场景加压项)

- upstream_snapshot 完备性(漏抄 exposes/交互行 = 分母造假,覆盖检查失效,直接 REVISE)
- 隐性契约裸奔(排序/时序/文案无意识留给实现即兴)
- 错误模型质量:code 表具体、跨操作不混用模式
- misuse_potential:逐操作问"消费者会依赖什么没承诺的行为"
- Cross:概念漂移与能力重复暴露逐项过,不走过场
