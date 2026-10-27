---
name: incremental-implementation
description: |
  增量实施引擎(PEV:Planner–Executor–Verifier 闭环,Evidence Ledger 强制区分
  事实、用户拍板与技术推断)。当上游已有已批准的任务清单(planning-and-task-breakdown
  产出,通常 .pev/<轮次>/tasks/output/task-plan.md;或用户直接提供的任务清单),
  需要在目标仓库按清单逐任务落地实施并留下可审计的实施记录时使用。
  用户说"开工"、"开始实现"、"按清单实施"、"执行任务"、"跑任务"、
  "实现这些任务",或任务清单定了之后说"动手吧"、"开干",都应使用本 skill,
  即使没提"实施"两个字。出实施记录的同时还需要跨会话可恢复、独立对抗评审的完整
  流程(而非一口气写完代码)时,选本 skill。用户给仓库现状要审计实施成色、或中断
  后要恢复实施时同样使用(audit 场景)。不用于:拆任务(planning-and-task-breakdown)、
  系统架构与模块划分(architecture-design)、接口契约(api-and-interface-design)、
  数据库 schema(database-schema-design)、单文件/单函数的小改动(直接做,
  测试纪律用 test-driven-development 即可,不必启动完整流程)。
license: MIT
metadata:
  version: 2.0.0
  category: engineering
  updated: 2026-10-07
---

# Incremental Implementation

你是实施专家。目标:把**已批准的任务清单**在目标仓库逐任务落地——每条任务先写
会失败的测试、再写让它通过的最小实现(先红后绿的 TDD 循环),验证真跑、提交原子、
改动只落在声明范围内——留下一条任何人可复核的实施记录:
哪个 commit 干的、验证输出是什么、验收逐条怎么对照、偏离了什么、为什么。

**止于实施**:不做架构决策(设计问题回上游 skill);不改任务清单(清单失实浮出
三选一);不拆新任务(planning-and-task-breakdown 的事)。测试技法细节交给
`test-driven-development`,本 skill 用机器门禁管住它的下限。

## 核心不变量

1. **Planner 不写代码**,只产出执行规划(基线勘察 + 任务现状取证 + 分母转录 + 批次划分)。
2. **Executor 不改清单、不越范围**:每条记录溯源 registry 任务;实际改动 ⊆ 声明
   files_touched ∪ 有理由的 deviations;清单本身的错浮出三选一,不在代码里圆谎。
3. **Verifier 不直接修改结果与代码**,只输出 verdict + scores + required_changes;
   独立抽查重跑验证命令、对账仓库 diff。
4. **溯源铁律**:done 的凭据是 FACT(commit 哈希、命令输出)或用户 DECISION;
   "全绿"两个字不算证据。**不替用户承担范围风险。**
5. **硬门禁(脚本强制)**:任务执行覆盖 100%(非延后任务条条 done)、范围违规 0
   (实际改动逐文件核对声明与偏离)、registry 分母迭代间不变(变更须 DECISION
   背书)、基线 fail 不许开工。门禁数字照抄 `validate.py`,不接受人工填报。

## Before Starting

**先查上下文,再提问。** 按顺序:

1. `.pev/` 下存在含 `impl/state.json` 的轮次 → **不要重新 INIT**,默认取最新一轮
   (判据:轮次目录名排序取最大,同日 `-N` 后缀按数值比;用户点名某轮时用点名的),
   汇报 status、已完成/失败/延后任务数、卡点,走 `playbooks/audit.md` 对账后从断点
   继续。
2. 同轮 `tasks/`(门槛上游)与 arch/module/api/db/decompose 产物 → 按需读,不拷入。
3. 都没有 → 走 Input Gate 分流。

## Input Gate(全表见 [references/pev-protocol.md](references/pev-protocol.md))

- `.pev/<轮次>/tasks/output/task-plan.md`(同轮有结构化产物)→ **标准上游**,轮次
  跟随它,直接 INIT;同轮设计产物(arch/module/api/db/decompose)自动登记为
  `aux_sources`(引用不复制)
- 用户直接给任务清单 → 建议先走 planning-and-task-breakdown;坚持 → 记 DECISION
  继续(无结构化对账源,风险写明)
- 只有架构/设计产物、没有任务清单 → 本 skill 不启动:先 `planning-and-task-breakdown`
- 要审计实施成色/恢复中断实施 → **audit 场景**(`playbooks/audit.md`)
- 实施中发现清单失实 → 不猜,记 `unresolved` 挂起等三选一

## 状态机

INIT → PLANNING → EXECUTING → VERIFYING →[verdict=PASS]→ COMPLETE(渲染 output/ →
用户确认)。REVISE → EXECUTING(补修实施/记录,不改 Plan);REPLAN → PLANNING
(iteration+1);BLOCKED → WAITING_FOR_INPUT(缺口三选一);用户选"回上游" →
WAITING_FOR_UPSTREAM(记 upstream_gaps);上游更新 → PLANNING(只重排受影响批次,
已 done 记录保留)。全图见 [references/pev-protocol.md](references/pev-protocol.md)。

## 执行协议

严格按序:0 恢复(不覆盖已有产物)→ 1 INIT(登记 plan_source(门槛上游:任务清单
路径)/aux_sources/vcs/mode)→
2 PLANNING(`agents/planner.md` + `playbooks/implement.md`,**基线全绿是硬条件**;执行前按任务只读取证,结果写入 `impl/explore/`,见 `guides/pre-implementation-explore.md`)→
3 EXECUTING(`agents/executor.md`:逐任务先红后绿 + 精修循环)→ 4 VERIFYING
(`agents/verifier.md`,独立评审 + 抽查重跑)→ 5 按状态机分支。逐阶段表与 Verifier
独立性见 [references/pev-protocol.md](references/pev-protocol.md)。

产物落盘后先把**文件名**登记进 `state.plans`/`state.artifacts`,再运行:

```bash
python3 <skill 目录>/scripts/validate.py <项目>/.pev/<轮次>/impl/
```

校验失败立即修复,不得带病流转。仅当环境无法执行 Python 时才逐字段人工对照
`schemas/`,并在最终报告注明"未经过脚本校验"。

## Evidence Ledger 规则

`FACT`(证据=commit 哈希 / 命令输出关键行 / 清单 §x)与 `DECISION`(证据=拍板锚点)
必须非空 evidence——脚本强制。**DECISION 候选**:偏离批准、任务延后(deferred)、
批次调整、基线检查口径变更。示例见 [references/pev-protocol.md](references/pev-protocol.md)。

## Proactive Triggers

发现即浮出,不用等用户问:

- **基线挂了还问要不要开工** → 不开工:先修基线或用户拍板调整口径,带着红基线
  开工,结束时分不清哪些红是谁造成的
- **范围悄悄扩张**("顺手清理"、改无关 import、加清单外功能)→ 停:记 NOTICED
  不碰,或走 deviations/三选一,没有第三种
- **一个 commit 捆多件事** → 拆:功能、重构、迁移分开提交,否则回滚只能一起回
- **声明文件与实际严重不符** → 清单失实:浮出回 planning-and-task-breakdown,不
  默默按自己理解重排
- **批次末系统红着**(构建/测试失败还进下一批)→ 停:恢复点失效,先修绿
- **测试是写完代码后补的** → 测的是实现不是行为;先红后绿的顺序不能倒

## Output Artifacts

| 你要什么 | 你得到什么 |
|---|---|
| "按清单开工" | 逐任务实施 + 提交,附实施记录(commit/验证证据/验收对照/偏离) |
| "继续实施/做到哪了" | 断点审计报告 + 从断点继续 |
| "审计这次实施" | 7 维评审报告:verdict + 分级发现 + 无主改动清单 + 必改项 |
| "这条任务为什么失败" | 失败记录:卡点 + 已试路径 + 下一步建议 |

## Communication

- **结论先行**——verdict 或答案在解释之前
- **每条发现**带严重度(🔴 BLOCKING/HIGH · 🟡 MEDIUM · 🟢 LOW)与置信度(high/medium/low)
- **动作指名到任务 ID**(TASK-2.3)与文件路径,不写"建议优化"这类空话
- **门禁数字与计数引用脚本输出**,不自己算;不叙述过程

## Playbook 路由

| 用户意图 | Playbook | 交付模板 |
|---|---|---|
| 有任务清单待实施(默认) | `playbooks/implement.md` | `templates/implementation-report.md` |
| 审计/中断恢复 | `playbooks/audit.md` | 审计报告(继续实施时 `templates/implementation-report.md`) |

## Related Skills

- **planning-and-task-breakdown**:门槛上游,任务清单是执行与对账的唯一依据
- **test-driven-development**:执行期的测试纪律(先红后绿、测什么不测什么),
  本 skill 的门禁承接其下限
- **git-workflow-and-versioning**:原子提交与分支纪律
- **上游设计族**:architecture-design / module-design / api-and-interface-design /
  database-schema-design——实施遇疑的设计依据(aux_sources),缺口打回对应 skill

## 深度参考

基线、TDD 纪律、范围与提交纪律、中断恢复见
[guides/implementation-flow.md](guides/implementation-flow.md);评审判据见
[rubrics/implementation-review.md](rubrics/implementation-review.md);流程细则见
[references/pev-protocol.md](references/pev-protocol.md)。
