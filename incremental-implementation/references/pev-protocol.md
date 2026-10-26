# PEV 流程细则(incremental-implementation)

SKILL.md 的流程展开:Input Gate 全表、三选一、运行目录全树、执行协议逐阶段表、
状态机全图、Verifier 独立性、Evidence Ledger 示例。核心不变量以 SKILL.md 为准,
细则以本文件为准;实施技法(基线/TDD/范围/提交/恢复)见
[guides/implementation-flow.md](../guides/implementation-flow.md)。

## Input Gate(上游分流全表)

本 skill 消费**已批准的任务清单**,不替上游做拆解或设计决定。

| 情况 | 动作 |
|---|---|
| `.pev/<轮次>/tasks/output/task-plan.md` 存在(同轮 `tasks/iterations/` 有结构化产物) | **标准上游**。轮次跟随它;直接 INIT。结构化产物是对账源:registry 转录不得增删(validate.py R6 对账) |
| 同轮 arch/module/api/db/decompose 产物 | 自动登记 `aux_sources`(只记类型 + 路径,引用不复制)——实施遇疑查设计依据,不逐个问用户 |
| 用户直接给任务清单(无 .pev 结构) | `plan_source`=该文档。建议先走 planning-and-task-breakdown 出正式产物;用户坚持 → 记 DECISION 继续,风险写明:转录分母无结构化对账源,R6 对账跳过,分母以 registry 为准 |
| 只有架构/设计产物,没有任务清单 | 不启动:先走 `planning-and-task-breakdown` 拆任务;没有架构 → 更上游(architecture-design 一族) |
| 用户给仓库现状要审计/要恢复中断的实施 | **audit 场景**(`mode="audit"`,走 `playbooks/audit.md`) |
| 实施中发现清单本身的错(漏任务、依赖失实、files_touched 严重不符、验收不可判定) | 不猜:记入 `unresolved` → 挂起等用户三选一 |

### 三选一(缺口处置,同家族)

① 回 planning-and-task-breakdown 改清单 ② 回对应设计 skill
(api-and-interface-design / database-schema-design / module-design /
architecture-design,看缺口出在哪个依据)③ 用户直接拍板(记 DECISION)。
选 ①/② → `status="WAITING_FOR_UPSTREAM"`,逐条写入 `upstream_gaps`,挂起等上游
更新;上游已更新恢复 → PLANNING(iteration+1,只重排受影响批次,已 done 且不受
影响的记录保留)。选 ③ → 记 DECISION,按 `resume_to` 回到被阻塞的阶段。

**禁止的替代动作**:在代码里顺手替清单圆谎、默默改 registry 分母、把清单错误藏进
deviations。

## 运行目录(全树)

`.pev/` 是 PEV 家族共享根目录,按需求目标分轮次;本 skill 工作目录是轮次下的
`impl/`;轮次跟随门槛上游:任务清单产物在 `.pev/` 某轮内 → 同轮,外部路径且无可
复用轮次 → 新开 `prd-<今日日期>/`(同日同名追加 `-2`、`-3`):

```text
.pev/<轮次>/
├── pm/  rc/  decompose/  arch/  module/  api/  db/   # 更上游的家族产物,合法溯源源(引用不复制)
├── tasks/                          # 门槛上游:planning-and-task-breakdown 的产物
│   ├── state.json
│   ├── iterations/                 # 结构化产物 = validate.py 的对账源
│   └── output/task-plan.md
└── impl/                           # 本 skill 的工作目录
    ├── state.json                  # 共享状态(schemas/state.schema.json)
    ├── iterations/
    │   ├── 01-plan.json            # 每轮产物按 schema 校验
    │   ├── 01-artifact.json        # 实施记录(baseline + registry + records)
    │   └── 01-verification.json
    └── output/                     # PASS 后按 templates/ 渲染的最终交付物
```

- 上游**引用不复制**:`state.plan_source` 记清单路径,`state.aux_sources` 记设计依据
  清单。上游内容永远留在原处,按需读取。
- 「取最新一轮」的判据:按轮次目录名排序取最大——`prd-<日期>` 为键,同日 `-N` 后缀
  按整数值比较(无后缀视为 0);目录名不可比时按 `impl/state.json` 修改时间。
- 文件号零填充两位(01、02…)。REVISE 轮复用原 Plan:只有 `<N>-artifact.json` /
  `<N>-verification.json` 而没有 `<N>-plan.json` 是正常的,不是缺文件。REPLAN 轮
  `iteration+1` 用新号,旧迭代文件原样保留。`state.iteration` 与当前(最大)文件号
  保持一致:INIT 为 0,首个 plan 落盘(01-)时置 1,此后 REPLAN 随新号递增。
- 重开:用户明确要求时把 `impl/` 归档为 `impl.bak-<日期>/`(不动同轮其他子目录,
  **仓库代码不回滚**——要回滚走 git)后重建。

## 执行协议(逐阶段)

严格按序运行,适用于 Claude Code 与 Codex 双端。

| 阶段 | 读什么 | 产出 | 完成条件 |
|---|---|---|---|
| 0 恢复 | `.pev/` 下最新含 `impl/state.json` 轮次的该文件(若存在) | 状态汇报 | **不重新 INIT、不覆盖已有产物**;中断恢复先走 `playbooks/audit.md` 对账;重开按上文归档规则 |
| 1 INIT | 上游清单路径 | `state.json`:`status="INIT"`、`iteration=0`、`max_iterations=5`、`plan_source`、`aux_sources`(同轮自动登记)、`vcs`(git/none)、`mode`(implement/audit,默认 implement) | 范围与优先级能从清单推断则记入 `assumptions`,不能则一次性问齐,不逐条追问;audit 模式见 `playbooks/audit.md` |
| 2 PLANNING | `agents/planner.md`、`playbooks/implement.md` | `iterations/<N>-plan.json` | 基线全绿是进入下一步的硬条件;校验通过 → `state.plans` 登记,`status="EXECUTING"` |
| 3 EXECUTING | `agents/executor.md` | `iterations/<N>-artifact.json` | 逐任务协议(先红后绿/真跑验证/原子提交/如实记录);清单缺口 → `status="blocked"` 走三选一;全批次完成 → `status="completed"` |
| 4 VERIFYING | `agents/verifier.md` | `iterations/<N>-verification.json` | 独立性机制见下;抽查重跑验证命令是本 skill 的特色动作 |
| 5 分支 | verdict | 见状态机 | PASS → 按 `templates/implementation-report.md` 渲染到 `output/implementation-report.md` 呈最终预览,同时呈交 verification 的 `warnings`、失败/延后任务与偏离声明残留,并说明**单轮评审通过不等于零残留**;用户确认后 `status="COMPLETE"` |

**校验**:每步产物落盘后,先把**文件名**登记进 `state.plans` / `state.artifacts`
(只记文件名,不存内容副本),再运行捆绑脚本——确定性检查交给脚本,不要肉眼比对:

```bash
python3 <skill 目录>/scripts/validate.py <项目>/.pev/<轮次>/impl/
```

登记必须先于校验,否则新落盘文件会被 R10 误报为未登记。`<N>-verification.json`
无需登记——R10 只对账 plan/artifact 两类登记册,verification 按文件号与同号 artifact
配对(R7)。校验失败立即修复,不得带病流转。门禁数字比对仅当 `state.status` 为
VERIFYING 或 COMPLETE 时执行(早期阶段尚无评审产物)。仅当环境无法执行 Python 时才
逐字段人工对照 `schemas/`,并在最终报告里注明"未经过脚本校验"。

**Verifier 的独立性**——有子代理能力(如 Claude Code):spawn 一个**只读**子代理,
只给它 `agents/verifier.md`、`rubrics/implementation-review.md` 与 `.pev/<轮次>/impl/`
相关文件路径(state + 当前迭代 plan/artifact),`plan_source` 与 `aux_sources` 指向的
上游产物,以及仓库路径(允许其读仓库、跑验证命令、查 git log,不得改代码);
**不转述对话中的推理过程,只传文件**。无子代理(如 Codex 单会话):切换到 Verifier
角色后**只从文件与仓库重新推导**——重读记录与仓库实况,刻意不引用 EXECUTING 阶段的
推理(文件里没有的,视为不存在)。

## 状态机全图

```text
INIT → PLANNING → EXECUTING → VERIFYING
                                  │
        PASS ────────────────► COMPLETE(渲染 output/ → 用户确认)
        REVISE ──────────────► EXECUTING(补修实施/记录,不改 Plan)
        REPLAN ──────────────► PLANNING(重规划,iteration+1)
        BLOCKED ─────────────► WAITING_FOR_INPUT(清单缺口待用户三选一)
        用户选"回上游" ────────► WAITING_FOR_UPSTREAM(记 upstream_gaps,挂起等上游更新)
        上游已更新 ───────────► PLANNING(iteration+1,只重排受影响批次)
```

`mode="audit"` 不走 PLANNING/EXECUTING:INIT 直接 `status="VERIFYING"`(见
`playbooks/audit.md`)。

## Evidence Ledger 示例

`state.evidence` 中每条 claim 必须标注类型,示例如下:

```json
{"claim": "TASK-1.2 完成且 npm test 全绿", "type": "FACT", "evidence": "01-artifact records TASK-1.2 tests#1 输出 'Tests: 12 passed';commit a1b2c3d", "confidence": "high"}
{"claim": "TASK-2.1 需额外改动 src/middleware/auth.ts", "type": "DECISION", "evidence": "用户 2026-10-07 会话拍板(偏离批准)", "confidence": "high"}
{"claim": "基线全绿,当前红测试均为本次改动引入", "type": "FACT", "evidence": "baseline checks: npm test 34 passed / build ok @ commit e4f5a6b", "confidence": "high"}
{"claim": "TASK-3.2 的验收标准与契约 C3 的错误语义冲突,疑清单失实", "type": "INFERENCE", "evidence": "api/output/D1/contracts.md C3 定义 409,清单 TASK-3.2 验收写 400", "confidence": "medium"}
```

## 深度参考索引(何时读什么)

| 文件 | 何时读 |
|------|--------|
| [guides/implementation-flow.md](../guides/implementation-flow.md) | 基线/TDD 纪律/范围与提交纪律/中断恢复想不清楚时 |
| [rubrics/implementation-review.md](../rubrics/implementation-review.md) | 交预览前自检、评审逐项核对 |
| [templates/implementation-report.md](../templates/implementation-report.md) | 渲染最终交付物时 |
| [playbooks/audit.md](../playbooks/audit.md) | 中断恢复或完工审计时 |
