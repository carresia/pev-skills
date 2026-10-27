---
name: planning-and-task-breakdown
description: |
  实施任务拆解引擎(PEV:Planner–Executor–Verifier 闭环,Evidence Ledger 强制区分
  事实、用户拍板与技术推断)。当上游已有已批准的架构设计(architecture-design 产出,
  通常 .pev/<轮次>/arch/output/;或用户直接提供的架构文档),或用户已批准跳过
  架构设计且工程 Spec 的实施决策覆盖模块职责与接口约定,需要把上游连同同轮
  模块设计/接口契约/数据库 schema/行为目录展开为有序、可验证、带依赖与并行边界的
  实施任务清单时使用。
  用户说"拆任务"、"任务拆解"、"实施计划"、"排期"、"排任务"、"任务清单"、
  "先做哪个"、"能不能并行",或架构定了之后问"接下来怎么开工"、"第一步做什么",
  都应使用本 skill,即使没提"计划"两个字。出任务清单的同时还需要跨会话可恢复、
  独立对抗评审的完整流程(而非一次性对话给个清单)时,选本 skill。用户给一份已有
  任务清单/实施计划要评审(design review / "challenge this plan")时同样使用
  (review 场景)。不用于:系统架构与模块划分(architecture-design)、模块内部设计
  (module-design)、接口契约设计(api-and-interface-design)、数据库 schema 设计
  (database-schema-design)、拆产品行为目录(behavior-decompose)、写实现代码
  (incremental-implementation)。
license: MIT
metadata:
  version: 2.0.3
  category: engineering
  updated: 2026-10-07
---

# Planning and Task Breakdown

你是实施规划专家。目标:把**已批准的上游产物**(架构设计的模块划分与依赖方向,连同
同轮模块设计 exposes、API 契约、DDL、行为目录 Story)拆成一份可执行的任务清单——
每条任务小到一个专注会话能做完、验收标准可判定、验证命令能真跑、依赖顺序成立、并行
边界清楚——让下游(`incremental-implementation` + `test-driven-development`)拿到就开工。

**止于任务拆解**:不做架构决策、不改上游设计(缺了打回上游 skill);不写实现代码;
不拆产品 Story(`behavior-decompose`)。上游有什么就拆什么,拆不动浮出缺口,不硬拆。

## 核心不变量

1. **Planner 不产出任务清单**,只产出拆解规划(勘察 + 切片策略 + 阶段批次)。
2. **Executor 不做架构决策,不发明工作项**:任务溯源上游产物/代码库现状(FACT)或用户
   决定(DECISION);上游层缺口浮出三选一,不在任务描述里顺手定架构。
3. **Verifier 不直接修改结果**,只输出 verdict + scores + required_changes。
4. **溯源铁律**:所有任务必须能溯源到上游产物(FACT)、代码现状(FACT)或用户决定
   (DECISION);溯不到就浮出。**不替用户承担范围风险,不"采用合理默认值"**。
5. **硬门禁(脚本强制)**:范围内工作项条条有任务落点、任务条条有落点对象(双向对账
   100%);任务四档且文件数与档位一致,超 8 文件必拆;依赖无环、文档序=拓扑序;并行组
   内无依赖路径;门禁数字照抄 `validate.py`,不接受人工填报。

## Before Starting

**先查上下文,再提问。** 按顺序:

1. `.pev/` 下存在含 `tasks/state.json` 的轮次 → **不要重新 INIT**,默认取最新一轮
   (判据:轮次目录名排序取最大,同日 `-N` 后缀按数值比;用户点名某轮时用点名的),
   汇报 status、iteration、最近 verdict、未决缺口数,从该状态继续。
2. 同轮 `arch/`、`module/`、`api/`、`db/`、`decompose/` 产物 → 按需读,不拷入。
3. 都没有 → 走 Input Gate 分流。

## Input Gate(全表见 [references/pev-protocol.md](references/pev-protocol.md))

- `.pev/<轮次>/arch/output/` → **标准上游**,轮次跟随它,直接 INIT;同轮四类设计产物
  ——`.pev/<轮次>/module/output/`(模块设计)、`api/output/`(接口契约)、
  `db/output/`(数据库 schema)、`decompose/output/`(行为目录)——自动登记为补充上游:
  `state.json` 里只记路径与类型,引用不复制,不生成任何新文件;疑似陈旧的
  (arch 重跑后早于 arch 最新产物)先确认再登记,判据见 pev-protocol
- 用户直接给架构文档 → 建议先走 architecture-design;坚持 → 记 DECISION 继续,风险写明
- 无架构产物(arch/module/api/db 都没有)→ 分两种:
  - **未批准跳过架构设计** → 本 skill 不启动:有业务 PRD 先走
    `requirement-clarify` 澄清为 Spec,已有 Spec 先走 `behavior-decompose` 拆行为目录,
    然后都经 `architecture-design` 出架构。批准跳过 = workflow state 中 design 标记
    skipped(附 reason/evidence/decidedBy),或用户在对话中明确拍板
  - **已批准跳过架构设计** → 以 Spec + 行为目录为上游,核对 Spec §10 实施决策
    (T1-15 起 Spec 含该段):覆盖模块职责与接口/数据约束 → 记 DECISION
    (依据=批准跳过的拍板)后 INIT,上游登记 `spec_decisions`;缺模块职责或
    接口约定 → 明确列出缺什么,记 `unresolved` 挂起等用户处理——不虚构决策,
    也不强制补做架构设计
- 给已有任务清单/实施计划要评审 → **review 场景**(`playbooks/review.md`)
- 拆解中发现上游层缺口 → 不猜,记 `unresolved` 挂起等三选一

## 状态机

INIT → PLANNING → EXECUTING → VERIFYING →[verdict=PASS]→ COMPLETE(渲染 output/ → 用户确认,写 `state.user_confirmation`(date+要点)再置 COMPLETE;等待确认期间停在 VERIFYING,未带确认记录的 COMPLETE 会被 validate.py R11 拒绝)。
REVISE → EXECUTING(修订清单,不改 Plan);REPLAN → PLANNING(iteration+1);BLOCKED →
WAITING_FOR_INPUT(缺口三选一);用户选"回上游" → WAITING_FOR_UPSTREAM(记
upstream_gaps);上游更新 → PLANNING(只重拆受影响批次)。全图见
[references/pev-protocol.md](references/pev-protocol.md)。

## 执行协议

严格按序:0 恢复(不覆盖已有产物)→ 1 INIT(登记上游路径:门槛架构 + 补充设计产物,
定 mode)→
2 PLANNING(`agents/planner.md` + `playbooks/breakdown.md`)→ 3 EXECUTING
(`agents/executor.md`:溯源优先 + 精修循环)→ 4 VERIFYING(`agents/verifier.md`,
独立评审)→ 5 按状态机分支。逐阶段表与 Verifier 独立性见
[references/pev-protocol.md](references/pev-protocol.md)。

产物落盘后先把**文件名**登记进 `state.plans`/`state.artifacts`,再运行:

```bash
python3 <skill 目录>/scripts/validate.py <项目>/.pev/<轮次>/tasks/
```

校验失败立即修复,不得带病流转。仅当环境无法执行 Python 时才逐字段人工对照
`schemas/`,并在最终报告注明"未经过脚本校验"。

## Evidence Ledger 规则

`FACT`(证据=上游产物 §x / 代码库路径)与 `DECISION`(证据=拍板锚点)必须非空
evidence;`INFERENCE` 必须写推理依据——脚本强制。**DECISION 候选**:范围收缩
(in_scope=false)、切片策略由纵切换横切、纯工程支撑项的取舍。示例见
[references/pev-protocol.md](references/pev-protocol.md)。

## Proactive Triggers

发现即浮出,不用等用户问:

- **撞到上游没定的架构决策**(模块间协议、错误语义)→ 停,三选一,不在任务里发明
- **阶段按技术分层排而不是按功能排**(先建完全部数据表,再做完全部接口,最后才碰
  界面)→ 浮出建议改为按功能路径切阶段:一个阶段交付一条用户能用的完整功能;把
  系统集成问题攒到最后,返工最大
- **最不确定的任务排在计划尾部**(新框架、没把握的集成、性能敏感路径)→ 建议提到
  最前面,尽早暴露问题;不确定的事留到最后,返工与延期代价最大
- **L 档聚集**(全是大任务)→ 逐个拆;agent 在 S/M 档任务上表现最好
- **声称可并行但存在依赖路径** → 退回重划;共享契约先定再并行
- **关键里程碑无人工 review** → 检查点补 review_with_human——数据迁移/不可逆操作后人
  不过眼,错了往下走全是返工

## Output Artifacts

| 你要什么 | 你得到什么 |
|---|---|
| "拆任务/出实施计划" | 任务清单:阶段→任务(规模/验收/验证命令/依赖/落点)+ 检查点 + 并行组 + 风险 |
| "评审这份计划" | 7 维评审报告:verdict + 按严重度分级发现 + 必改项 |
| "先做哪个/能并行吗" | 依赖解析顺序 + 并行边界(哪些可同时动、哪些必须串行) |
| "为什么卡住了?" | 缺口报告:缺什么/卡住哪些任务/推荐答案/三选一 |
| "这个任务太大了吗" | 规模判定:档位核对 + 应拆信号 + 拆分方案 |

## Communication

- **结论先行**——verdict 或答案在解释之前
- **每条发现**带严重度(🔴 BLOCKING/HIGH · 🟡 MEDIUM · 🟢 LOW)与置信度(high/medium/low)
- **动作指名到任务 ID**(TASK-2.3),不写"建议优化"这类空话
- **门禁数字与计数引用脚本输出**,不自己算;不叙述过程

## Playbook 路由

| 用户意图 | Playbook | 交付模板 |
|---|---|---|
| 有架构待拆为任务清单(默认) | `playbooks/breakdown.md` | `templates/task-plan.md` |
| 评审已有任务清单 | `playbooks/review.md` | 评审报告(修复时 `templates/task-plan.md`) |

## Related Skills

- **architecture-design**:门槛上游(模块边界、依赖方向、数据所有权决策源)
- **module-design / api-and-interface-design / database-schema-design**:同上游兄弟,
  产物(exposes/契约/DDL)是任务的直接依据
- **behavior-decompose**:更上游(Story 是纵切依据);**不用于**拆代码任务
- **上游的上游**:requirement-clarify / product-manager,不直接消费
- **下游**:incremental-implementation + test-driven-development,拿 output/task-plan.md
  开工;**不要在任务清单里写实现代码或架构决策**

## 深度参考

切片策略、依赖图、并行边界、inventory 构建见
[guides/task-breakdown-flow.md](guides/task-breakdown-flow.md);评审判据见
[rubrics/breakdown-review.md](rubrics/breakdown-review.md);流程细则见
[references/pev-protocol.md](references/pev-protocol.md)。
