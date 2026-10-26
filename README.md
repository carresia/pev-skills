# pev-skills

个人 PEV（Planner–Executor–Verifier，规划–执行–验证闭环）工作流技能集，覆盖从产品需求到增量实施的完整链路。每个 skill 是一个独立目录，含 `SKILL.md` 及配套的 agents / playbooks / schemas / templates 等资源。

## Skill 清单

| Skill | 用途 |
|---|---|
| `product-manager` | 产品经理工作流引擎（Nana）：需求分析、机会分析、写 PRD |
| `requirement-clarify` | 把业务 PRD 澄清为带溯源标注的工程 Spec |
| `behavior-decompose` | 把 Spec/PRD 拆解为行为目录（Epic → Feature → Story → 验收标准） |
| `architecture-design` | 把行为目录转化为架构设计（模块边界、依赖、关键取舍） |
| `module-design` | 把架构模块逐个展开为模块级技术设计（内部组件、DFX、FMEA） |
| `api-and-interface-design` | 把模块 exposes 展开为接口契约（API、事件、模块间接口） |
| `database-schema-design` | 把声明的数据实体展开为数据库 schema（DDL、索引、迁移） |
| `planning-and-task-breakdown` | 把架构及配套设计展开为有序、可验证的实施任务清单 |
| `incremental-implementation` | 按任务清单逐任务落地实施，留下可审计的实施记录 |

## 流水线关系

```
product-manager → requirement-clarify → behavior-decompose → architecture-design
    → module-design / api-and-interface-design / database-schema-design
    → planning-and-task-breakdown → incremental-implementation
```

各 skill 可独立使用，也可按上述顺序串成完整链路；上游产出通常落在 `.pev/<轮次>/…/output/`。

## 安装

把需要的 skill 目录软链或拷贝到 `~/.claude/skills/` 下即可，例如：

```bash
ln -s "$PWD/architecture-design" ~/.claude/skills/architecture-design
```
