# PEV 流程细则(planning-and-task-breakdown)

SKILL.md 的流程展开:Input Gate 全表、三选一、运行目录全树、执行协议逐阶段表、
状态机全图、Verifier 独立性、Evidence Ledger 示例。核心不变量以 SKILL.md 为准,
细则以本文件为准;领域算法(切片/依赖/并行/inventory)见
[guides/task-breakdown-flow.md](../guides/task-breakdown-flow.md)。

## Input Gate(上游分流全表)

本 skill 消费**已批准的技术设计**,不替上游做架构决定。

| 情况 | 动作 |
|---|---|
| `.pev/<轮次>/arch/output/` 存在 | **标准上游**。轮次跟随它;同轮 `module/output/`、`api/output/`、`db/output/`、`decompose/output/` 四类设计产物自动登记为补充上游 `aux_sources`(state 里只记类型 + 路径,引用不复制,不生成任何新文件);直接 INIT |
| 同轮设计产物疑似陈旧 | 该条 aux **不自动登记**:判据=该 aux 目录最新产物的修改时间早于 `arch/` 最新产物(arch 重跑/REPLAN 过即命中)。浮出问用户「此产物对应最新架构吗」,确认有效才登记;失效 → 回对应设计 skill(module/api/db)重做 |
| 用户直接给架构文档(±Spec/设计文档) | `arch_source`=该文档。建议先走 architecture-design 出正式产物;用户坚持 → 记 DECISION 继续,风险写明:对账分母粒度不可靠,覆盖门禁的保障减弱 |
| 只有 module/api/db 产物,无 arch | 缺门槛上游 → 建议回 architecture-design(模块边界、依赖方向、数据所有权是任务排序的依据);用户坚持直接拆 → DECISION 记风险后继续 |
| 只有 Spec/PRD,无任何技术设计 | 不启动:有业务 PRD → `requirement-clarify` 澄清为工程 Spec;已有 Spec → `behavior-decompose` 拆行为目录;然后都经 `architecture-design` 出架构 |
| 用户给一份已有任务清单/实施计划要评审 | **review 场景**(`mode="review"`,走 `playbooks/review.md`) |
| 拆解中发现上游层缺口(架构未定模块间协议、契约缺错误语义、DDL 撑不住约束) | 不猜:记入 `unresolved` → 挂起等用户三选一 |

### 三选一(缺口处置,同家族)

① 回 architecture-design 改架构 ② 回对应设计 skill(module-design /
api-and-interface-design / database-schema-design,看缺口出在哪个产物)③ 用户直接拍板
(记 DECISION)。选 ①/② → `status="WAITING_FOR_UPSTREAM"`,逐条写入 `upstream_gaps`,
挂起等上游更新;上游已更新恢复 → PLANNING(iteration+1,只重拆受影响批次)。选 ③ →
记 DECISION,按 `resume_to` 回到被阻塞的阶段(PLANNING / EXECUTING / VERIFYING)。

**禁止的替代动作**:在任务描述里顺手发明架构、替上游定模块间协议、把缺口藏进
"实现细节任务"。

## 运行目录(全树)

`.pev/` 是 PEV 家族共享根目录,按需求目标分轮次;本 skill 工作目录是轮次下的 `tasks/`;
轮次跟随门槛上游:架构产物在 `.pev/` 某轮内→同轮,外部路径且无可复用轮次→新开
`prd-<今日日期>/`(同日同名追加 `-2`、`-3`):

```text
.pev/<轮次>/
├── pm/  rc/  decompose/          # 更上游的家族产物,合法溯源源(引用不复制)
├── arch/                          # 门槛上游:architecture-design 的产物
├── module/  api/  db/             # 同上游兄弟:自动登记为补充上游(引用不复制)
└── tasks/                         # 本 skill 的工作目录
    ├── state.json                 # 共享状态(schemas/state.schema.json)
    ├── iterations/
    │   ├── 01-plan.json           # 每轮产物按 schema 校验
    │   ├── 01-artifact.json
    │   └── 01-verification.json
    └── output/                    # PASS 后按 templates/ 渲染的最终交付物
```

- 上游**引用不复制**:`state.arch_source` 记门槛上游路径(架构产物),`state.aux_sources`
  是补充上游清单,每条只记类型 + 路径(kind:module_design / api_contract / db_schema /
  behavior_catalog / spec)。上游内容永远留在原处,按需读取。
- 「取最新一轮」的判据:按轮次目录名排序取最大——`prd-<日期>` 为键,同日 `-N` 后缀
  按整数值比较(无后缀视为 0);目录名不可比时按 `tasks/state.json` 修改时间。
- 文件号零填充两位(01、02…)。REVISE 轮复用原 Plan:只有 `<N>-artifact.json` /
  `<N>-verification.json` 而没有 `<N>-plan.json` 是正常的,不是缺文件。REPLAN 轮
  `iteration+1` 用新号,旧迭代文件原样保留。`state.iteration` 与当前(最大)文件号
  保持一致:INIT 为 0,首个 plan 落盘(01-)时置 1,此后 REPLAN 随新号递增。
- 重开:用户明确要求时把 `tasks/` 归档为 `tasks.bak-<日期>/`(不动同轮其他子目录)后重建。

## 执行协议(逐阶段)

严格按序运行,适用于 Claude Code 与 Codex 双端。

| 阶段 | 读什么 | 产出 | 完成条件 |
|---|---|---|---|
| 0 恢复 | `.pev/` 下最新含 `tasks/state.json` 轮次的该文件(若存在) | 状态汇报 | **不重新 INIT、不覆盖已有产物**;重开按上文归档规则 |
| 1 INIT | 上游产物路径 | `state.json`:`status="INIT"`、`iteration=0`、`max_iterations=5`、`arch_source`(门槛上游路径)、`aux_sources`(补充上游清单,同轮自动登记)、`mode`(design/review,按用户意图定,默认 design) | 范围与优先级能从上游推断则记入 `assumptions`,不能则一次性问齐,不逐条追问;review 模式见 `playbooks/review.md` |
| 2 PLANNING | `agents/planner.md`、`playbooks/breakdown.md` | `iterations/<N>-plan.json` | 校验通过 → `state.plans` 登记,`status="EXECUTING"` |
| 3 EXECUTING | `agents/executor.md` | `iterations/<N>-artifact.json` | 溯源优先;上游层缺口 → `status="blocked"` 走三选一;全批次完成、精修循环 `done` → `status="completed"`(溯源与精修协议见 agents/executor.md) |
| 4 VERIFYING | `agents/verifier.md` | `iterations/<N>-verification.json` | 独立性机制见下 |
| 5 分支 | verdict | 见状态机 | PASS → 按 `templates/task-plan.md` 渲染到 `output/task-plan.md` 呈最终预览,同时呈交 verification 的 `warnings` 与脚本「未覆盖工作项」清单的残留项,并说明**单轮评审通过不等于零残留**;用户确认后 `status="COMPLETE"`,清单交给下游 skill |

**校验**:每步产物落盘后,先把**文件名**登记进 `state.plans` / `state.artifacts`
(只记文件名,不存内容副本),再运行捆绑脚本——确定性检查交给脚本,不要肉眼比对:

```bash
python3 <skill 目录>/scripts/validate.py <项目>/.pev/<轮次>/tasks/
```

登记必须先于校验,否则新落盘文件会被 R10 误报为未登记。`<N>-verification.json`
无需登记——R10 只对账 plan/artifact 两类登记册,verification 按文件号与同号 artifact
配对(R7)。校验失败立即修复,不得带病流转。
门禁数字比对仅当 `state.status` 为 VERIFYING 或 COMPLETE 时执行(早期阶段尚无评审产物)。
仅当环境无法执行 Python 时才逐字段人工对照 `schemas/`,并在最终报告里注明"未经过脚本校验"。

**Verifier 的独立性**——有子代理能力(如 Claude Code):spawn 一个只读子代理,只给它
`agents/verifier.md`、`rubrics/breakdown-review.md` 与 `.pev/<轮次>/tasks/` 相关文件路径
(state + 当前迭代 plan/artifact),以及 `arch_source` 与 `aux_sources` 指向的上游产物;
**不转述对话中的推理过程,只传文件**。无子代理(如 Codex 单会话):切换到 Verifier 角色
后**只从文件重新推导**——重读 state.json、当前迭代产物与上游产物,刻意不引用 EXECUTING
阶段的推理(文件里没有的,视为不存在)。

## 状态机全图

```text
INIT → PLANNING → EXECUTING → VERIFYING
                                  │
        PASS ────────────────► COMPLETE(渲染 output/ → 用户确认)
        REVISE ──────────────► EXECUTING(修订清单,不改 Plan)
        REPLAN ──────────────► PLANNING(重规划,iteration+1)
        BLOCKED ─────────────► WAITING_FOR_INPUT(上游层缺口待用户三选一)
        用户选"回上游" ────────► WAITING_FOR_UPSTREAM(记 upstream_gaps,挂起等上游更新)
        上游已更新 ───────────► PLANNING(iteration+1,只重拆受影响批次)
```

`mode="review"` 不走 PLANNING/EXECUTING:INIT 直接 `status="VERIFYING"`(见
`playbooks/review.md`)。

## Evidence Ledger 示例

`state.evidence` 中每条 claim 必须标注类型,示例如下:

```json
{"claim": "TASK-1.2 创建订单 API 依据契约 C3 POST /orders", "type": "FACT", "evidence": "api/output/D1/contracts.md C3", "confidence": "high"}
{"claim": "TASK-3.1 由用户 merge 指令合并而来", "type": "DECISION", "evidence": "02-artifact decisions#d3", "confidence": "high"}
{"claim": "auth 中间件已有实现可复用,无需新任务", "type": "FACT", "evidence": "src/middleware/auth.ts 已存在且覆盖契约 C2 的鉴权要求", "confidence": "high"}
{"claim": "migration 脚手架任务有必要:现有仓库无任何 migration 基建", "type": "INFERENCE", "evidence": "代码库无 migrations/ 目录、package.json 无迁移依赖", "confidence": "medium"}
```

## 深度参考索引(何时读什么)

| 文件 | 何时读 |
|------|--------|
| [guides/task-breakdown-flow.md](../guides/task-breakdown-flow.md) | 切片/依赖/并行/inventory 构建/边界情况想不清楚时 |
| [rubrics/breakdown-review.md](../rubrics/breakdown-review.md) | 交预览前自检、评审逐项核对 |
| [templates/task-plan.md](../templates/task-plan.md) | 渲染最终交付物时 |
