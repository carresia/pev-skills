# Playbook: review(对抗评审已有 schema/DDL)

用户给一份已有 schema(建表 DDL / MongoDB 集合定义 / migration 脚本 / 数据模型文档),
要独立、对抗性的评审。交付模板:`templates/db-schema-review.md`。

## 与 design 场景的差异

- **上游是被评审的 schema 文档本身**(upstream_kind=schema_doc);对应的模块设计/
  架构设计若存在,作为对照事实源,用来查"这份 schema 是否忠实承接了上游的数据
  声明与所有权"。
- **产物是发现,不是修复后的 schema**:review_findings 是交付物;要不要按发现重做
  schema 由用户决定(可另开一轮 design,mode 变更须记 DECISION)。
- **Executor 不修 schema**,self_challenge 不适用;对抗 7 维的展开就是主工作。

## Plan 骨架

```text
1. survey_upstream    —— 通读 schema 文档,提炼它声称的表/集合、列类型、主键与 ID、
                         约束、索引、迁移脚本、承接的上游数据声明
2. survey_codebase    —— 仅当 schema 落在现有库上(对照声称与实际 DDL/迁移历史)
3. review_design      —— 对抗 7 维逐维攻击(failure_modes/consistency/concurrency/
                          boundary_erosion/misuse_potential/compatibility/simpler_alternative)
4. draft              —— 汇总发现,逐条定 severity + 锚点 + 处置建议
```

## Executor 要点

- **假设 schema 有问题,找不到问题才是不正常的**:每一维至少认真攻击一次,无发现
  也要占位记录(finding="",severity=NONE),证明扫过而非漏扫。逐项核对清单:
  [schema-design-checklist](../references/schema-design-checklist.md)。
- **每条发现必须锚定 schema 文档的具体位置**(evidence_anchor 非空,脚本强制):
  哪张表/哪列/哪个索引/哪条 migration 站不住。锚不到位置的印象分不是发现,
  是意见。
- **severity 分级克制**:BLOCKING = 照此建库/迁移必然翻车(丢数据、锁死线上表);
  HIGH = 上线后高概率出事或显著浪费(无索引的热查询、浮点存钱);MEDIUM = 特定
  条件下出事;LOW = 改进建议。拿不准时写进 finding 里说明不确定来源。
- **经典攻击面必答**:金额浮点、随机 UUID 做 InnoDB 聚簇 PK、MySQL 非 utf8mb4、
  日期存字符串、枚举裸字符串、缺 FK/约束、无依据索引、大表裸 ALTER、不可逆
  migration——这些是红线级,命中即 HIGH 起步。
- **命名与规范攻击面**:不见名知意(a1/tbl1)、保留字、大小写/连字符、索引无
  idx_/uniq_ 前缀、联合主键、TEXT/BLOB 滥用、单表索引超限、存储过程/视图/触发器
  ——对照 [db-naming-and-conventions](../references/db-naming-and-conventions.md)
  逐条扫;项目既有命名风格优先,冲突不混用。
- **access pattern 盲区**:schema 声称服务的查询里,哪条走不了索引?哪张表没有任何
  声明的读路径(建了没人查)?
- 对照上游(若存在):schema 承载了上游声明的全部 owns_data 吗?有没有表存了上游
  没人声明的数据(私自扩边)?

## Verifier 检查重点(本场景加压项)

- 7 维是否真扫过(占位记录存在且非空 finding 的 evidence_anchor 成立)
- severity 是否克制、有没有把意见标成发现
- 漏攻击面:Executor 没扫到的维度组合(如"约束 × 旁路写入"、"索引 × 迁移后
  失效"这类交叉场景)
- 对照上游时,upstream_items 声明是否完备(同 design 场景的覆盖检查,若声明了)
