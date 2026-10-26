# Playbook: review(对抗评审已有接口契约)

用户给一份已有接口契约(OpenAPI/REST/GraphQL/事件/模块间接口文档),要独立、对抗性的
评审。交付模板:`templates/api-contract-review.md`。

## 与 design 场景的差异

- **上游是被评审的契约文档本身**(upstream_kind=contract_doc);对应的模块设计
  (module-design)若存在,作为对照事实源,用来查"这份契约是否忠实承接了上游的
  exposes 与声明交互"。
- **产物是发现,不是修复后的契约**:review_findings 是交付物;要不要按发现重做契约
  由用户决定(可另开一轮 design,mode 变更须记 DECISION)。
- **Executor 不修契约**,self_challenge 不适用;对抗 7 维的展开就是主工作。

## Plan 骨架

```text
1. survey_upstream    —— 通读契约文档,提炼它声称的操作、请求/响应、错误语义、
                         版本与兼容策略、承接的上游能力/交互
2. survey_codebase    —— 仅当契约落在现有代码库上(对照声称与实际)
3. review_design      —— 对抗 7 维逐维攻击(failure_modes/consistency/concurrency/
                          boundary_erosion/misuse_potential/compatibility/simpler_alternative)
4. draft              —— 汇总发现,逐条定 severity + 锚点 + 处置建议
```

## Executor 要点

- **假设契约有问题,找不到问题才是不正常的**:每一维至少认真攻击一次,无发现也要
  占位记录(finding="",severity=NONE),证明扫过而非漏扫。
- **每条发现必须锚定契约文档的具体位置**(evidence_anchor 非空,脚本强制):
  哪个端点/哪个操作/哪个错误码/哪条兼容规则站不住。锚不到位置的印象分不是发现,
  是意见。
- **severity 分级克制**:BLOCKING = 照此契约开发/对接必然返工翻车;HIGH = 上线后
  高概率出事或显著浪费;MEDIUM = 特定条件下出事;LOW = 改进建议。拿不准时写进
  finding 里说明不确定来源。
- **隐性契约裸奔是接口评审的必答题**:排序稳定性、时序、错误文案、字段顺序这些
  消费者会依赖的可观察行为(Hyrum 定律),契约是否明确承诺或明确不承诺?漏答 = 不完整。
- **错误语义与兼容是重点攻击面**:错误模型是否落到 code 表、跨操作是否混用模式;
  detail 契约是否有版本与兼容策略、破坏性变更有无弃用路径、列表有无分页、幂等
  有无交代。
- 对照上游(若存在):契约承载了上游的全部 exposes 与声明交互吗?有没有契约里的
  能力上游没人要(私自扩边)?

## Verifier 检查重点(本场景加压项)

- 7 维是否真扫过(占位记录存在且非空 finding 的 evidence_anchor 成立)
- severity 是否克制、有没有把意见标成发现
- 漏攻击面:Executor 没扫到的维度组合(如"错误语义 × 分页边界"这类交叉场景)
- 对照上游时,upstream_items 声明是否完备(同 design 场景的覆盖检查,若声明了)
