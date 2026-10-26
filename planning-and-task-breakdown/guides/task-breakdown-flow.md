# 任务拆解流程指南

> 本文件是**领域知识库**,按需读取。**SKILL.md 是工作流,这里是需要想清楚时才翻的地方。**
> 流程细则(Input Gate、三选一、运行目录、执行协议、状态机、Evidence Ledger)在
> [references/pev-protocol.md](../references/pev-protocol.md),两处不重复。

门槛上游统一称 `arch_source`(架构产物或用户架构文档),同轮设计产物为 `aux_sources`。

## inventory 构建(覆盖对账的分母)

inventory 登记本轮要交付的**全部工作项**,既含设计项也含工程支撑项:

| kind | 从哪提取 | 粒度 |
|---|---|---|
| `architecture_module` | arch 产物模块划分表 | 每模块一条 |
| `module_capability` | module-design 的 exposes/组件 | 每能力一条 |
| `api_contract` | api-and-interface-design 的契约清单 | 每契约/资源一组端点一条 |
| `db_object` | database-schema-design 的表/schema | 每表(或每库核心对象组)一条 |
| `story` | decompose 行为目录 | 每 Story 一条(粒度过细时可按 Feature) |
| `spec_item` | 用户直接给的 Spec(不经家族链条时) | 按需求条目 |
| `engineering_item` | 工程支撑(CI、脚手架、migration 基建、部署脚本) | 每支撑项一条,anchor=DECISION/INFERENCE 锚点 |

规则:

- **anchor 用上游自己的位置**(如 `arch/output 模块表 M2 行`、`api 契约 C3`),不自造编号体系。
- 每项 `in_scope` 默认 true;置 false 必须在 note 写理由并留痕(谁拍的、后续轮次怎么接)。
- **第一个 artifact 定一次,迭代间不变**;变更(增删项、in_scope 翻转、换 kind/anchor)
  必须在新迭代 Evidence Ledger 记 DECISION(脚本 R9 强制)——漏拆任务时改分母是作弊。
- 上游有而 inventory 没登记的,是分母造假,Verifier 逐份对照上游抓。

## ID 生成

```text
PHASE-{n}       → 阶段
TASK-{p}.{n}    → 阶段 p 下的任务
INV-{n}         → inventory 工作项
```

```text
PHASE-1: 订单基础(可下单)
  TASK-1.1: orders 表 migration(XS)
  TASK-1.2: 创建订单 API(S)
  TASK-1.3: 下单页面与提交(M)
```

---

## 切片策略

### 纵切优先(默认)

```text
PHASE-1: 用户可以完成下单(纵切:表 + API + UI 一条路径)
PHASE-2: 用户可以查询与管理订单(纵切:查询 + 列表页)
PHASE-3: 支付与通知接入
```

每个阶段交付**可运行、可演示的端到端价值路径**。好处:集成风险逐阶段暴露、每阶段结束
系统可工作、demo 可随时给。

### 分层攻坚(例外,须 Planner 声明理由)

```text
PHASE-1: 全部数据模型与 migration
PHASE-2: 全部 API 契约实现
PHASE-3: 全部前端
```

只在两种情况成立:① 契约完全未定,上层无法动(先把契约层做完锁定);② 迁移类项目
(旧系统换骨架,横切是业务现实)。**默认不要这么切**——它把集成风险推到最后集中爆发。

### 依赖图先行

无论哪种切法,先从上游读出依赖结构:

```text
数据库 schema
    ├── API 类型/模型(依赖 schema)
    │       ├── API 端点(依赖模型)
    │       │       └── 前端 API client(依赖端点)
    │       │               └── UI 组件(依赖 client)
    │       └── 校验逻辑
    └── Seed 数据 / migration
```

实施顺序沿依赖图自底向上:**被依赖最多的先做**(数据模型、契约、公共类型)。解析顺序:

```text
第一批:无依赖项(可立即开始,天然并行组候选)
第二批:依赖全部落在第一批的
...重复直到全部归位
```

检测到环 → 标出并拆/重挂,不硬排顺序(脚本也会拦)。

---

## 排序纪律

1. **依赖满足**:前置任务排在后继之前(文档序=拓扑序,脚本强制)。
2. **阶段终点是可工作状态**:每过完一个 checkpoint,系统能跑起来,不是攒了一堆半成品。
3. **高风险前置**:最不确定的任务(新框架、没把握的集成、性能敏感路径)排前面,fail fast;
   留到最后=雷留到最后。
4. **检查点设在阶段边界**:检查内容是本阶段验收的机器化版本(测试全绿/构建通过/
   端到端流程可用);关键里程碑 `review_with_human=true`——人看过才许进下一阶段。

## 并行边界

多 agent / 多会话可用时:

| 情况 | 处置 |
|---|---|
| **可安全并行** | 独立功能切片、已实现功能的测试补齐、文档——声明同一 `parallel_group` |
| **必须串行** | 共享 schema 的 migration、公共类型/契约改动、有依赖链的任务 |
| **需要协调** | 多任务共享一份 API 契约——先有前置任务把契约定了,再并行各自实现 |

规则:**组内不得存在任何依赖路径**(直接或传递,脚本强制);共享契约必须先有前置任务
锁定它;拿不准就不并行——串行永远合法,错误并行制造冲突返工。

---

## 拆分技法与应拆信号

技法表见 [rubrics/breakdown-review.md](../rubrics/breakdown-review.md)「拆分技法」。
应拆信号(任一命中就拆):

- 一个专注会话(约 2 小时 agent 工作)做不完
- 验收标准写不进 5 条以内
- 触及两个以上独立子系统(认证与计费)
- 标题里出现"和/and/以及"——那是两条任务

---

## 边界情况处理

### 超大项目(潜在任务 > 30)

**分批 + 排序**:

1. 与用户确认最高优先的价值路径
2. 只对前两个 PHASE 做细拆
3. 其余工作项留在 inventory(in_scope=false,note 写"第二批拆解"),不硬编占位任务
4. 记入 `stop_conditions`

### 架构决策缺失或模糊

任务拆解撞到上游没定的东西(模块间协议、错误语义、数据归属):

**不在任务描述里发明架构。** 进 `unresolved` → `status="blocked"` → 三选一(选项与
流转见 [references/pev-protocol.md](../references/pev-protocol.md)):

```text
⚠️ 缺口:架构未定义「订单模块与支付模块的同步方式」
   卡住:TASK-2.2 / TASK-2.3
   推荐答案:同步调用 + 超时补偿(仅供参考,不是默认值)
   请选:① 回 architecture-design 改架构 ② 回对应设计 skill(api/db/module)③ 你直接拍板(记为 DECISION)
```

### 重复检测

评审时按以下线索找重复任务:

- 归一化标题匹配(忽略大小写、去停用词)
- files_touched 重叠 > 80%
- implements 落点相同

检出后**先 merge 再进预览**,不把两条同类任务一起交上去。

---

## 精修提示模板

```text
用户提出以下精修要求:
{refinement_request}

当前任务清单:
{current_plan}

应用该改动并给出更新后的清单。保持所有任务 ID、依赖、implements 落点一致;
split/merge 后同步受影响的依赖与落点引用,别让对账悬空。
```

每条精修指令 = 一次 DECISION,锚点形如 `02-artifact decisions#d3`,同步进 Evidence Ledger。

---

## 常见合理化借口(自己骗自己的模式)

| 借口 | 现实 |
|---|---|
| "边做边想" | 做出乱麻和返工。10 分钟规划省几小时返工 |
| "任务很明显,不用写" | 也要写。显式任务暴露隐藏依赖和被忘的边缘情况 |
| "规划是开销" | 规划就是本 skill 的任务本身。没有规划的实现只是打字 |
| "我脑子里装得下" | 上下文窗口有限。写下来的清单才能跨会话存活 |

## 危险信号(评审重点盯)

- 没写验收标准就开干的"实现某某功能"任务
- 计划里没有任何验证步骤
- 全是 L 档任务
- 阶段之间没有检查点
- 依赖顺序没被考虑(按目录字母序排任务)
- inventory 只登记了架构模块,API 契约/库表/Story 全靠"隐含"
