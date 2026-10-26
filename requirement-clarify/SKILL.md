---
name: requirement-clarify
description: |
  开发侧需求澄清引擎(PEV:Planner–Executor–Verifier 闭环,Evidence Ledger
  强制区分事实、推断与人类决定)。当上游已有业务 PRD(product-manager/Nana
  产出,或用户直接提供 PRD 文档)且需要澄清为工程规格 Spec 时使用:拿着 PRD
  向 PM(用户)提问,先质疑需求价值,再追问落地模糊地带,追踪 PRD 与代码自答,
  追踪不到才问人,产出带溯源标注的工程 Spec 交给 behavior-decompose。无 PRD 从零澄清
  需求 → 用 spec-driven-development;写 PRD/需求分析/找机会 → 用
  product-manager;枚举用户场景 → decompose;选架构 → architecture-design。
---

# Requirement Clarify — PEV Loop

本 skill 的职责是把业务 PRD 澄清为工程 Spec。PEV(Planner–Executor–Verifier)
只是承载职责的**执行架构**——架构可换,职责不变。Planner、Executor、Verifier
是三种执行机制,共享一个结构化 state,对应现实中**开发拿着 PM 的 PRD 对焦**:
先质疑需求价值,再追问落地模糊地带,能从 PRD 和代码里追到答案就自答,追踪
不到才抛给 PM(用户)定夺。

## 核心不变量(任何时候不得违反)

1. **Planner 不产出工程 Spec**,只产出问题规划(价值先行,模糊随后)。
2. **Executor 不自答产品问题**,且只能执行 Planner 批准的澄清范围;追踪优先,问人是兜底。
3. **Verifier 不直接修改结果**,只输出 verdict + required_changes。
4. **溯源铁律**:Spec 中所有产品级陈述必须能溯源到 PRD(FACT)或 human 澄清决定(DECISION);追踪不到就问人,不发明答案;不做架构决策(那是 architecture-design 的事)。

## Proactive Triggers

读 PRD 时命中以下情况,**不等人问,当场预警**——它们会让澄清白做,或让 Spec 交付即落空:

- **PRD §5 承诺的能力在代码库无对应实现或依赖** → 先暴露成本与工期风险,别留到开发期才发现。
- **PRD §6 数据需求用现有埋点/口径采集不到** → 直接点明"按现口径无法验收",推动补埋点进工程范围。
- **PRD 自相矛盾**(如 §2 目标人群与 §5 范围指向不同用户群)→ 矛盾不澄清 Spec 必错,退回 PM 重写。
- **PRD 缺 §5 范围或 §6 数据需求章节** → Verifier 的覆盖检查将失去锚点,先要求补齐再澄清。
- **未决问题全部集中在同一章节** → 说明该章节本身没写清,建议整章重写,而非逐条追问。

## 运行目录

`.pev/` 是 PEV 家族三个 skill(product-manager、本 skill、behavior-decompose)
共享的根目录,按需求目标分轮次目录 `prd-<日期>/`(命名与创建规则见
product-manager)。本 skill 的工作目录是轮次目录下的 `rc/`:

```text
.pev/<轮次>/
├── pm/                        # product-manager 的产物(Evidence Ledger、PRD),合法追踪源
├── rc/                        # 本 skill 的工作目录
│   ├── state.json             # 共享状态(schemas/state.schema.json),含 prd_source
│   ├── iterations/
│   │   ├── 01-plan.json       # 每轮产物按 schema 校验
│   │   ├── 01-artifact.json
│   │   └── 01-verification.json
│   └── output/                # PASS 后按 templates/ 渲染的最终交付物
└── decompose/                 # behavior-decompose 的工作目录(结构同 rc/)
```

上游 PRD **引用不复制**。`state.prd_source` 记录其路径(通常
`.pev/<轮次>/pm/output/prd.md`),追踪与打回都以它为准。轮次跟随 PRD:PRD
在 `.pev/` 某轮的 pm/ 下,本 skill 就在该轮的 rc/ 工作。同轮 `pm/` 下的
中间产物(Evidence Ledger、迭代记录)是合法追踪源,按需读取,不拷入 `rc/`。

文件名中的 `<N>` 是迭代号,等于写入时的 `state.iteration + 1`(初始 iteration=0,首轮即 01)。REVISE 轮复用原 Plan,因此只有
`<N>-artifact.json` / `<N>-verification.json` 而没有 `<N>-plan.json`,这是正常的,不是缺文件。

## 状态机

```text
INIT → PLANNING → EXECUTING → VERIFYING
                                  │
        PASS ────────────────► COMPLETE
        REVISE ──────────────► EXECUTING(重执行,不改 Plan)
        REPLAN ──────────────► PLANNING(重规划)
        BLOCKED ─────────────► WAITING_FOR_INPUT(向用户呈未决问题,见恢复协议)
                                  │
        用户直接答复 ─────────► 回到 resume_to 记录的阶段
        用户选"回 PM" ────────► WAITING_FOR_PRD(记 prd_gaps,挂起等 PRD 更新)
                                  │
        PRD 已更新 ────────────► PLANNING(iteration+1,只重规划受影响问题)
```

## 校验

每步产物写入文件后,先把**文件名**登记进 `state.plans` / `state.artifacts`(按产物类型,不存内容副本),再运行捆绑校验脚本——脚本双向对账登记册与 `iterations/` 目录(R10),确定性检查交给脚本,不要靠肉眼比对:

```bash
python3 <skill 目录>/scripts/validate.py <项目>/.pev/<轮次>/rc/
```

校验失败立即修复,不得带病流转。仅当环境无法执行 Python 时才逐字段人工对照
`schemas/`,并在最终报告里注明"未经过脚本校验"。

## 执行协议

严格按以下顺序运行。适用于 Claude Code 与 Codex 双端。

### 0. 恢复(仅当 .pev/ 已存在)

先确定轮次目录:默认取 `.pev/` 下最新一个含 `rc/state.json` 的轮次,用户点名
则用点名的目录。没有任何轮次含 `rc/state.json`(轮次也可能由
product-manager、behavior-decompose 单独创建)时,没有可恢复的澄清状态,按第 1 节 INIT。

确定轮次后读取该轮 `rc/state.json`,向用户汇报 status、iteration、最近一次
verdict、未决问题数,从该状态继续。**不要重新 INIT,不要覆盖已有产物。**仅当
用户明确要求"重新开始"时,把 `rc/` 归档为 `rc.bak-<日期>/`(不动同轮的
pm/、decompose/),在本轮次内重建。

### 1. INIT

- 定位上游 PRD:优先 `.pev/` 下最新一个含 `pm/output/prd.md` 的轮次,用户直接给路径亦可。
- **找不到 PRD → 不 INIT,分流引导**:还没 PRD → `product-manager`;从零澄清写 spec → `spec-driven-development`。
- 确定轮次目录:PRD 在 `.pev/` 某轮的 pm/ 下 → 轮次取该轮;PRD 是外部路径 → 新开 `prd-<今日日期>/` 轮次(同日已有同名目录时,追加 `-2`、`-3`)。
- 创建 `.pev/<轮次>/rc/state.json`:`status="INIT"`、`iteration=0`、`max_iterations=5`、`prd_source=<PRD 路径>`。
- 澄清目标(goal)能从 PRD §2 推断则推断并记入 `assumptions`;不能则向用户一次性问齐,不要逐条追问。

### 2. PLANNING

- 以 `agents/planner.md` 为角色指令(通读 PRD 时先执行「Proactive Triggers」预警),产出**问题规划**,严格两层:
  ①`interrogate_value` 价值性提问(为什么做/价值假设/不做会怎样/成功长什么样);
  ②`interrogate_ambiguity` 逐章扫描落地模糊地带(业务规则/权限与状态/异常与边界/数据口径/范围)。
- 写入 `.pev/<轮次>/rc/iterations/<N>-plan.json`,运行校验脚本。
- 通过后:`status="EXECUTING"`。

### 3. EXECUTING

- 以 `agents/executor.md` 为角色指令,**只执行当前 Plan 的问题批次**。
- **追踪优先**:每个问题依次查 ①PRD(prd_source)②同轮 `.pev/<轮次>/pm/` 的中间产物(若存在)③codebase;追到的答案写入 `artifact.answers`(question/answer/source)并同步 `state.evidence`(FACT,evidence=PRD §x / 产物路径 / 代码文件)。
- 追踪不到的问题进未决清单,**不要编答案**:artifact `status="blocked"`(replan_reason 写明缺什么/为什么重要),跳到第 5 步 BLOCKED 分支。
- 全部问题闭环后,`draft` 聚合出 Spec 正文写入 `<N>-artifact.json` 的 `artifact` 块,运行校验脚本。
- 通过后:`status="VERIFYING"`。
- Artifact `status="replan_required"` 时跳到第 5 步分支处理。

### 4. VERIFYING(独立性机制)

Verifier 的价值来自独立,双端按各自能力选择实现:

- **有子代理能力(如 Claude Code)**:spawn 一个只读子代理,只给它
  `agents/verifier.md` 和 `.pev/<轮次>/rc/` 相关文件路径(state + 当前迭代的
  plan/artifact),以及 `prd_source` 指向的 PRD 文件。**不要转述对话中的推理过程**,只传文件。
- **无子代理(如 Codex 单会话)**:切换到 Verifier 角色后,**只从文件重新推导**
  ——重读 state.json、当前迭代产物与 PRD,以文件内容为唯一依据,刻意不引用
  EXECUTING 阶段的推理(文件里没有的,视为不存在)。

无论哪种方式:产出写入 `.pev/<轮次>/rc/iterations/<N>-verification.json`,运行校验脚本。

### 5. 分支

| Verdict | 动作 |
|---|---|
| `PASS` | 按 `templates/spec.md` 渲染最终交付物到 `.pev/<轮次>/rc/output/spec.md`,`status="COMPLETE"` |
| `REVISE` | Plan 不变,Executor 按 `required_changes` 修订 Artifact;`iteration+1`,回 EXECUTING |
| `REPLAN` | Planner 吸收 `critical_issues`/`evidence_gaps` 重规划;`iteration+1`,回 PLANNING |
| `BLOCKED` | `status="WAITING_FOR_INPUT"`,`resume_to="EXECUTING"`,向用户逐问列出:问题 / 为什么重要 / 推荐答案 / **三选一**(①回 PM 重新提需求 ②PM 补充需求 ③直接答复) |

Executor 输出 `replan_required` / `blocked` 时同样进入对应分支(回 PLANNING 或
WAITING_FOR_INPUT),`resume_to` 记 `EXECUTING`。

### 6. WAITING_FOR_INPUT 恢复协议

用户答复后:

1. 答复合并进 state:直接答复的 → `DECISION` 入 Evidence Ledger(evidence=澄清记录锚点,如 `01-artifact answers#q3`),并记入当前轮 artifact 的 `decisions`;
2. `iteration` 不变——这是同一段工作的继续,不是新一轮;
3. `status = resume_to`,清除 `resume_to`,从中断处继续;
4. 答复中选了"回 PM"(①或②)→ 不硬续:把对应问题逐条写入 `prd_gaps`(question + prd_anchor),`status="WAITING_FOR_PRD"`;
5. 若答复使当前 Plan 失效,按 REPLAN 处理(`iteration+1`,回 PLANNING)。

### 7. WAITING_FOR_PRD 恢复协议

用户告知 PRD 已更新(通常经 product-manager 的 REPLAN 完成):

1. 重读 `prd_source` 与同轮 `.pev/<轮次>/pm/` 的新产物,diff 出变化;
2. 清空 `prd_gaps`;已闭环的 answers / Ledger 条目保留,不重问;
3. PRD 更新推翻既有 DECISION 的,对应问题重开;
4. 回 PLANNING(`iteration+1`),只重规划受影响的问题批次。

### 8. 迭代上限

`iteration > max_iterations` 时立即停止,**明确报告**:当前最佳 Spec 状态、未解决的
critical_issues、仍未闭环的问题。不得宣称完成。

## Evidence Ledger 规则

`state.evidence` 中每条 claim 必须标注类型:

```json
{"claim": "PRD §2 目标为提升新用户激活率", "type": "FACT", "evidence": "PRD §2", "confidence": "high"}
{"claim": "现有项目无 activation 埋点", "type": "FACT", "evidence": "src/analytics/events.ts grep 无命中", "confidence": "high"}
{"claim": "激活窗口期定为注册后 24 小时", "type": "DECISION", "evidence": "01-artifact answers#q3", "confidence": "high"}
```

- `FACT`(证据=PRD §x / `.pev/<轮次>/pm/` 产物 / 代码文件)与 `DECISION`(证据=澄清记录锚点)都必须有非空 `evidence`(校验脚本强制);没有证据的结论只能标 `INFERENCE` / `HYPOTHESIS` / `UNKNOWN`。
- Verifier 以 Ledger 为准自动检查:答案无来源 → 不允许作为 Spec 依据,记入 `evidence_gaps`。

## Playbook 路由

| 用户意图 | Playbook | 最终交付模板 |
|---|---|---|
| 有 PRD 待澄清为工程 Spec(本 skill 唯一场景) | `playbooks/clarify.md` | `templates/spec.md` |

## 下游 Handoff(不是本 skill 的工作)

| 下一步需求 | Skill |
|---|---|
| 枚举正常/异常/边界场景 | `behavior-decompose`(PEV 链内,直接读 rc/output/spec.md);`decompose`(独立流程) |
| 选架构、定模块边界 | `architecture-design` |
| 拆成文件级任务 | `planning-and-task-breakdown` |
| 写代码 | `incremental-implementation` + `test-driven-development` |

**不要在澄清产出里做技术选型或任务拆分。**
