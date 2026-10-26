# Playbook: design(唯一场景)

上游架构已批准,要逐模块的内部技术设计。交付模板:detail → `templates/module-detail.md`,
brief → `templates/module-brief.md`。

## Plan 骨架

```text
1. survey_architecture  —— 条目化每个目标模块的架构声明(必为第一步)
2. survey_codebase      —— 仅当存在现有代码库/既有系统
3. design_modules       —— 每批一个模块(强关联小模块可合并一批),被依赖的先做
4. cross_check          —— 跨模块一致性自查(交互对齐/机制重复/概念漂移)
5. draft                —— 聚合 + downstream_deliverables + 精修循环
```

单模块简单轮次允许 3/4/5 各一步收口;步骤数与模块数和复杂度成正比,不为了显得周全而增加。

## Executor 要点

- **边界守恒优先**:depends_on / owns_data / exposes 全部以架构快照为准;越界需求
  (新依赖/更宽暴露/别人的数据)→ `unresolved` + blocked → 三选一,不私自扩边。
- **高内聚信息隐藏**:组件单一职责;`hides` 写组件隐藏的真实设计决策(写不出 =
  边界是画的);组件扇出 5+ 个外部交互先质疑切分。
- **exposes 条条有落点**:架构暴露的每项能力都指到实现组件;指不到 = 缺口,浮出。
- **DFX 落设计点**:哪个组件、什么机制、什么参数;detail 五项 DFX 全覆盖 + FMEA
  覆盖全部核心组件;brief 只写关键 DFX 点。
- **内部复杂度点名真实问题**:模块里的每个队列/缓存/状态机/后台任务都要回答
  "解决什么可溯源的问题";答不出 = 删。
- **下游交付物节必须填**:六个下游 skill 各自拿到什么输入,写具体条目,不写
  "见上文"。

## Verifier 检查重点(本场景加压项)

- architecture_snapshot 完备性(漏抄 exposes/交互行 = 覆盖检查失去分母,直接 REVISE)
- 每个组件 `hides` 的真实性(复述职责 ≠ 隐藏决策)
- FMEA 质量:失效模式是真失效(依赖挂/消息重/并发冲突)还是走形式
- hidden_coupling:内部设计有没有绕开架构声明的隐式依赖(共享存储/时序耦合/读别
  人的表)
- Cross:机制重复与概念漂移逐项过,不走过场
