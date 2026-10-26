# Playbook: review(对抗评审已有设计)

用户给一份已有技术设计,要独立、对抗性的评审。交付模板:`templates/review-report.md`。

## 与 design 场景的差异

- **上游是被评审的设计文档本身**(upstream_kind=design_doc);对应的 PRD/Spec/行为
  目录若存在,作为对照事实源,用来查"设计是否忠实承载上游"。
- **产物是发现,不是修复后的设计**:review_findings 是交付物;要不要按发现重做
  设计,由用户决定(可以另开一轮 design,mode 变更须记 DECISION)。
- **Executor 不修设计**,self_challenge 不适用;对抗 7 维的展开就是主工作。

## Plan 骨架

```text
1. survey_upstream    —— 通读设计文档,提炼它声称的边界/所有权/取舍/规模假设
2. survey_codebase    —— 仅当设计落在现有代码库上(对照声称与实际)
3. review_design      —— 对抗 7 维逐维攻击(failure_modes/consistency/concurrency/
                          boundary_erosion/migration_rollback/scale_cliff/simpler_alternative)
4. draft              —— 汇总发现,逐条定 severity + 锚点 + 处置建议
```

## Executor 要点

- **假设设计有问题**,找不到问题才是不正常的:每一维至少认真攻击一次,无发现
  也要占位记录(finding="",severity=NONE),证明扫过而非漏扫。
- **每条发现必须锚定设计文档的具体位置**(evidence_anchor 非空,脚本强制):
  哪一节/哪张表/哪个假设站不住。锚不到的印象分不是发现,是意见。
- **severity 分级克制**:BLOCKING = 照此设计开发必然返工/翻车;HIGH = 上线后
  高概率出事或显著浪费;MEDIUM = 特定条件下出事;LOW = 改进建议。拿不准降不升级
  时,写进 finding 里说明不确定来源。
- **更简方案维(simpler_alternative)是必答题**:被评审设计引入的每个复杂度机制,
  是否都有可溯源的真实问题背书?有没有实质上更简单的替代?评审报告漏答
  这题 = 不完整。
- 对照上游(若存在):设计承载了全部 In Scope 吗?有没有设计里的能力上游没人要?

## Verifier 检查重点(本场景加压项)

- 7 维是否真扫过(占位记录存在且 finding 非空条目的锚点成立)
- severity 是否克制、有没有把意见标成发现
- 漏攻击面:Executor 没扫到的维度组合(如"消息重复 × 迁移中"这类交叉场景)
- 对照上游时,upstream_items 声明是否完备(同 design 场景的覆盖检查)
