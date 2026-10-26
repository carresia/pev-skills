---
name: product-manager
description: |
  产品经理工作流引擎 Nana。采用 PEV 架构（Planner 规划、Executor 执行、Verifier
  验证，循环推进），并用 Evidence Ledger（证据清单）强制区分事实与假设。用户请求
  涉及以下任意意图即应使用本 skill，即使没提"产品经理"四个字：指标涨跌归因、
  留存/转化下降诊断、找增长机会、机会分析、产品调研、需求分析、写 PRD、
  出产品方案、分析数据、验证假设、估算 ROI。用户直接称呼 Nana 时同样使用。
  产出带证据标注的结构化交付物：机会卡片、决策文档、PRD。
---

# Product Manager (Nana) — PEV Loop

PEV 是本 skill 采用的**执行架构**，不是 skill 本身——换掉这套架构，产品经理的职责不变。PEV 指 Planner（规划）、Executor（执行）、Verifier（验证）。它不是三个独立的 Agent，而是一个受状态机约束的执行循环：Planner、Executor、Verifier 是同一个 skill 下的三种执行机制，统称 Nana，共享同一份结构化状态（state）。

## 核心不变量（任何时候不得违反）

1. **Planner 不产出最终产品方案**，只产出 Plan（工作计划）。
2. **Executor 不验收自己的产出**，且只能执行 Planner 批准的工作范围。
3. **Verifier 不直接修改产出**，只输出 verdict（验证结论）和 required_changes（必改项清单）。

## 运行目录

在当前项目下创建（或复用）`.pev/` 目录。`.pev/` 是 PEV 家族三个 skill（本 skill、requirement-clarify、behavior-decompose）共享的根目录。每个需求目标对应一个**轮次目录**：目录名为 `prd-<起始日期>`，如 `prd-2026-09-20/`。同一天再开新需求时，目录名追加序号，如 `prd-2026-09-20-2/`。同一条需求链（写 PRD → 澄清 → 拆解）的产物留在同一轮次目录里，各 skill 只写自己的子目录。轮次目录完整保留该需求目标的中间产物、Evidence Ledger（证据清单）和最终交付物。下文 `<轮次>` 指当前轮次目录名，本 skill 的工作目录是 `.pev/<轮次>/pm/`。

```text
.pev/
├── prd-2026-09-20/            # 需求目标 A：iteration 从 0 重新计数
│   ├── pm/                    # 本 skill 的工作目录
│   │   ├── state.json         # 共享状态（schemas/state.schema.json）
│   │   ├── iterations/
│   │   │   ├── 01-plan.json                # 每轮产物按 schema 校验
│   │   │   ├── 01-artifact.json
│   │   │   ├── 01-verification-input.json  # 派发 Verifier 前的被验证输入快照（record_provenance.py 写）
│   │   │   └── 01-verification.json
│   │   └── output/            # render.py 发布的最终交付物（只读派生产物，禁止手工编辑）
│   ├── rc/                    # requirement-clarify 的工作目录（结构同 pm/）
│   └── decompose/             # behavior-decompose 的工作目录（结构同 pm/）
└── prd-2026-09-30/            # 需求目标 B：新目标开新轮次，互不覆盖
    ├── pm/
    ├── rc/
    └── decompose/
```

文件名中的 `<N>` 是迭代号：轮次内递增，新轮次从 1 重新开始。REVISE 轮复用原有 Plan，因此该轮只有 `<N>-artifact.json` 和 `<N>-verification.json`，没有 `<N>-plan.json`——这是正常情况，不是文件缺失。

**写入权分层**：`iterations/` 产物只能经 `scripts/commit.py` 落盘并登记；`output/` 只能经 `scripts/render.py` 发布；`state.json` 的状态字段、登记册与语义字段只能由脚本写入（状态与登记册由 `transition.py`/`commit.py` 维护，八个语义字段经 `commit.py` 的 `state-update` 子命令合并）；`provenance` 只能经 `scripts/record_provenance.py` 绑定。你不再直接编辑上述目标；草稿文件路径自选，脚本只读草稿。中断且尚未验证的草稿可在当前轮原位重写（重跑同一提交命令）；已验证历史（编号小于当前 `iteration`，含被跨轮复用的旧 Plan）只读，脚本一律拒绝覆盖。

## 状态机

主链为 `INIT → PLANNING → EXECUTING → VERIFYING`，完整转移表如下。表中每条边与"执行协议"各步一一对应：改任何一侧，必须同步另一侧。全部转移由 `scripts/transition.py` 按事件执行，原子写 `state.json` 并追加 `transitions` 日志；`iteration+1` 的越上限检查在脚本内自动完成。

| 从 | 到 | 触发 | 附带动作 |
|---|---|---|---|
| INIT | PLANNING | 目标信息齐全，或可从上下文推断 | `iteration+1`（首轮 0→1） |
| INIT | WAITING_FOR_INPUT | 缺 goal / target_metric / baseline 且无法推断 | `resume_to="PLANNING"` |
| PLANNING | EXECUTING | Plan 通过校验 | — |
| PLANNING | WAITING_FOR_INPUT | 缺关键输入，只有用户能补，无法形成任何可执行步骤 | `resume_to="PLANNING"` |
| EXECUTING | VERIFYING | Artifact 通过校验且 `status="completed"` | — |
| EXECUTING | PLANNING | `artifact.status="replan_required"` | `iteration+1` |
| EXECUTING | WAITING_FOR_INPUT | `artifact.status="blocked"` | `resume_to="EXECUTING"` |
| VERIFYING | VERIFYING | `verdict=PASS`（provenance 已绑定） | 不转移：PASS 只解锁渲染与收口 |
| VERIFYING | COMPLETE | `complete` 事件（PASS 已绑定、渲染字节比对、校验全部通过） | 由 `transition.py` 在最终检查后写入 |
| VERIFYING | EXECUTING | `verdict=REVISE` | `iteration+1` |
| VERIFYING | PLANNING | `verdict=REPLAN` | `iteration+1` |
| VERIFYING | WAITING_FOR_INPUT | `verdict=BLOCKED` | `resume_to="VERIFYING"` |
| WAITING_FOR_INPUT | `resume_to` 记录的阶段 | 用户答复 | 清除 `resume_to`，`iteration` 不变 |
| WAITING_FOR_INPUT | PLANNING | 答复使当前 Plan 失效 | 清除 `resume_to`，`iteration+1`，按 REPLAN 处理 |
| COMPLETE | PLANNING | requirement-clarify 打回 `prd_gaps` | `iteration+1`，按 REPLAN 处理 |
| 任何将 `iteration+1` 的状态 | STOPPED | 本次 `iteration+1` 将超过 `max_iterations` | 终点，只汇报（第 7 节） |

`COMPLETE` 和 `STOPPED` 是**终点**：到达后，状态机不再自动流转。

`COMPLETE` 有两个出口：

1. requirement-clarify 打回 `prd_gaps`。`prd_gaps` 是工程侧澄清需求时发现的产品级问题清单，其中每个问题都必须修改 PRD 才能解决。收到打回后，在同一轮次内按 REPLAN 重启（见第 5 节末尾）。
2. 用户提出新目标。此时开新轮次目录，重新 INIT（见第 0 节、第 1 节）。

`STOPPED` 的出口不在上表转移中，只能由用户触发：用户明确要求继续时，提高 `max_iterations`，按 REPLAN 重启（见第 7 节）。

## 模型—脚本交接协议

六个脚本负责全部确定性操作：`scripts/init.py`（初始化与恢复定位）、`scripts/commit.py`（产物提交、登记、语义字段合并）、`scripts/transition.py`（状态转移与迭代上限）、`scripts/render.py`（渲染、字节比对、清残留）、`scripts/record_provenance.py`（快照与 provenance 绑定）、`scripts/validate.py`（只读校验）。

每次调用的 stdout 永远是单行紧凑 JSON：`ok`、`command`、`pm_root`、`skill_root`、`status`、`iteration`、`written`、`deleted`、`errors`、`warnings`、`next`；退出码 0=成功、1=失败。消费规则：

- **除 `init.py` 外，所有命令第一个参数固定为 `--pm-root <pm 目录绝对路径>`**（路径取上一步返回 JSON 的 `pm_root`）；**一律原样执行上一步返回 JSON 的 `next[].argv`**，不自行拼接、省略或改写参数。本文出现的命令示例均含 `--pm-root`。
- 状态流转只依据 `ok` 与 `next`；修复依据 `errors`（每条含 `file`、`json_path`、`reason`）；`warnings` 是非阻塞提示（中间态说明、旧轮次不可交付）。不依据人读文字判断成败，stderr 仅调试用。
- `next` 是按序执行的结构化对象数组：`kind=command`（在 `cwd` 下执行 `argv`）、`draft`（起草后经对应脚本提交）、`ask-user`（向用户一次问清缺失项）、`dispatch-verifier`（派发只读 Verifier）、`stop`。
- 写入类脚本内部完成写后校验并把结果并入返回 JSON。**不要在脚本成功后再调用 validate.py**；只在派发 Verifier 前、中断或换会话恢复定位（`init.py --locate`，或直接运行 `validate.py`）、以及用户要求复查时显式调用它。
- 失败重试只重跑出错的那个命令，不重放全链；编号、`iteration`、`status`、文件路径一律以最近一次返回 JSON 为准，不重建状态机、不沿用调用前的旧上下文。
- 脚本无法判断写入者身份，也不能阻止绕过工具直接回复用户。本协议要求全部写入经对应脚本；校验器每次运行检测的是可观察的不一致（登记对账、provenance 复算、渲染字节比对、守卫重验），不一致即拒绝继续。

仅当运行环境无法执行 Python 时，才逐字段人工对照 `schemas/`，并在最终报告里注明"未经过脚本校验"。

## 执行协议

严格按以下顺序运行。本协议同时适用于 Claude Code 和 Codex 两种环境。

### 0. 恢复（仅当 .pev/ 已存在）

运行恢复定位，不靠肉眼扫描：

```bash
python3 <skill 目录>/scripts/init.py --locate --workspace <含 .pev/ 的目录>
```

返回最新一个含 `pm/state.json` 的轮次目录与状态摘要。用户点名了某个轮次时，用用户点名的目录。没有任何轮次含 `pm/state.json` 时（轮次也可能由 requirement-clarify、behavior-decompose 单独创建），没有可恢复的 PM 状态，按第 1 节 INIT。

向用户汇报当前 status、iteration 和最近一次 verdict，然后按 status 分三种情况处理：

- status 不是 COMPLETE 也不是 STOPPED：从该状态继续本轮次。**不要重新 INIT，不要覆盖已有产物。**
- status 是 COMPLETE 或 STOPPED：只读汇报，不自动继续。何时可以继续，见第 5 节末尾（COMPLETE）和第 7 节（STOPPED）。用户提出新目标时开新轮次目录（第 1 节），不动旧轮次。
- 用户明确要求"重新开始"当前轮次：把该轮次的 `pm/` 改名为 `pm.bak-<日期>/` 归档（不动同轮的 rc/、decompose/），在本轮次内按第 1 节重建 `pm/`。

### 1. INIT

- 解析用户目标，起草 objective（草稿 JSON 路径自选），然后运行：

```bash
python3 <skill 目录>/scripts/init.py --objective <草稿绝对路径> --workspace <含 .pev/ 的目录>
```

脚本创建 `.pev/prd-<今日日期>[-N]/pm/` 与 `state.json`（`INIT`、`iteration=0`、`max_iterations=5`），同日重名自动追加序号。
- 缺失项处理（脚本按此规则置位）：仅 `goal` 缺失（字段不存在、为 null 或去首尾空白后为空串）时置 `WAITING_FOR_INPUT`+`resume_to="PLANNING"`，`next` 返回 `ask-user`，向用户一次性问清缺失项，每个缺失项按"缺什么 / 为什么重要 / 怎么获取"说明。`target_metric` 缺失与 `baseline` 为 null 是 schema 合法状态，脚本只在 `warnings` 提示，不阻断。
- 能从上下文推断的缺失项：推断出来，经 `commit.py` 的 `state-update` 子命令记入 `assumptions`。
- "值存在但不足以开工"的语义判断归你：此时走 `transition.py` 的 `need-input` 事件问用户。

### 2. PLANNING

- 运行 `transition.py --pm-root <pm 目录绝对路径> start-planning`（INIT→PLANNING，`iteration` 0→1，首轮产物编号定为 `01`）。由 REPLAN、COMPLETE 打回、STOPPED 恢复再进入 PLANNING 时，`+1` 已由各自事件完成，不调用本事件。
- 以 `agents/planner.md` 为角色指令，基于 state 起草 Plan（草稿路径自选）。
- 提交：`python3 <skill 目录>/scripts/commit.py --pm-root <pm 目录绝对路径> plan <草稿绝对路径>`——脚本落盘 `iterations/<N>-plan.json`、更新登记册并校验；成功后 `next` 返回 `plan-validated` 转移命令。
- 目标本身有歧义，或缺少只有用户能补的关键输入，导致无法形成任何可执行步骤时：**不要编造占位 Plan**，不写 plan 文件。运行 `transition.py --pm-root <pm 目录绝对路径> need-input` 置 `WAITING_FOR_INPUT`，向用户列出缺失项。

### 3. EXECUTING

- 以 `agents/executor.md` 为角色指令，**只执行当前 Plan 中列出的步骤**。
- 每个重要结论经 `commit.py --pm-root <pm 目录绝对路径> state-update <补丁绝对路径>` 写入 `state.evidence`（Evidence Ledger）。它是**唯一**的证据账本，Artifact 不重复携带证据。
- 起草 Artifact 后提交：`commit.py --pm-root <pm 目录绝对路径> artifact <草稿绝对路径>`——脚本运行 A/B/C 三类检查后落盘 `iterations/<N>-artifact.json`、登记并校验；`next` 依草稿 `status` 返回 `artifact-validated` / `executor-replan` / `executor-blocked` 之一的转移命令。
- Artifact 为 `replan_required` 或 `blocked` 时不进入 VERIFYING：`executor-replan` 回 PLANNING（`+1`），`executor-blocked` 置 WAITING（`resume_to="EXECUTING"`）。

### 4. VERIFYING（独立性机制）

Verifier 的价值来自独立性。两种运行环境按各自能力选择实现方式：

- **有子代理能力（如 Claude Code）**：spawn 一个只读子代理，只给它 `agents/verifier.md` 和 `.pev/<轮次>/pm/` 下的固定文件路径（state、有效 Plan、当轮 artifact，以及 `iterations/<N>-verification-input.json` 快照）。**不要向它转述对话中的推理过程**，只传文件。
- **无子代理能力（如 Codex 单会话）**：切换到 Verifier 角色后，只从文件重新推导——重读上述文件，以文件内容为唯一依据，刻意不引用 EXECUTING 阶段的推理。文件里没有的内容，视为不存在。

派发与收口顺序（缺一不可）：

1. `record_provenance.py`：写被验证输入快照（三摘要），`next` 返回 `dispatch-verifier` 与三个文件路径。
2. 派发 Verifier，等它完成并读到**详细报告**——报告必须在 `verification_input` 字段中原文复述快照标识；只有"任务完成"通知不算。
3. `commit.py --pm-root <pm 目录绝对路径> verification <报告草稿绝对路径>`：A+R5 校验加"报告复述与快照逐字段一致"检查。
4. `record_provenance.py --pm-root <pm 目录绝对路径> --bind`：按当前文件复算一致才把 `provenance` 写进报告；复算失败该报告作废，按 `errors` 里的恢复动作处理。
5. `transition.py --pm-root <pm 目录绝对路径> verdict`：PASS 不转移状态（留在 VERIFYING），只解锁收口。

### 5. 分支

| Verdict | 动作 |
|---|---|
| `PASS` | `render.py` 渲染发布最终交付物（临时文件→比对→原子替换），`transition.py` 的 `complete` 事件在 PASS 已绑定、字节比对、校验全部通过后写 `status="COMPLETE"`，然后交付用户 |
| `REVISE` | Plan 不变（复用）。Executor 按 `required_changes` 修订 Artifact；`verdict` 事件 `iteration+1` 回 EXECUTING |
| `REPLAN` | Planner 根据 `critical_issues` / `evidence_gaps` 重新规划；`verdict` 事件 `iteration+1` 回 PLANNING |
| `BLOCKED` | `verdict` 事件置 `WAITING_FOR_INPUT` + `resume_to`（`PLANNING` / `EXECUTING` / `VERIFYING`），`next` 返回 `ask-user`，向用户列出缺失项，每个缺失项按"缺什么 / 为什么重要 / 怎么获取"说明 |

`verdict` 的四个分支全部由 `transition.py` 的 `verdict` 事件执行：PASS 不转移状态（留在 VERIFYING），只有 `complete` 事件在最终检查全过后才写 COMPLETE。`required_changes` 为空的报告不是 REVISE（R5 拒绝）。

Executor 输出 `replan_required` / `blocked` 时，进入同样的分支：`executor-replan` 回 PLANNING（`iteration+1`），`executor-blocked` 进 WAITING_FOR_INPUT（`resume_to` 记 `EXECUTING`）。

PASS 后的渲染规则：交付物数据只取自 PASS 轮的 `artifact.artifact` 和 `state`（如证据表）。渲染经 `render.py`：缺必填数据时脚本拒绝发布，退回 REVISE 先补产物，不得编造内容；已发布的 `output/` 文件禁止手工编辑，修正一律经重新渲染，与当前交付物无关的残留文件用 `render.py --prune` 清理。Verifier 的 Completeness 检查（第 8 维）应在 PASS 前拦住这种缺失（见 agents/verifier.md）。

交付后，`status="COMPLETE"`。此后工程侧的需求澄清由 `requirement-clarify` skill 接手。COMPLETE 是终点，但不是不能再动：requirement-clarify 打回 `prd_gaps`（每条包含问题本身和它锚定的 PRD 章节）时，运行 `transition.py --pm-root <pm 目录绝对路径> reopen --note "<prd_gaps 来源与要点>"`（`iteration+1` 回 PLANNING），在本轮次既有产物之上重规划；已交付的历史轮只读，不改写。不新开轮次，Evidence Ledger 和迭代记录沿用同一份。用户提出新目标不属于这种情况：按第 0 节、第 1 节开新轮次目录。交付后迟到或重复的通知若没有新问题，不重新开始工作、不重复收口。

### 6. WAITING_FOR_INPUT 恢复协议

用户答复后：

1. 把答复合并进 state（经 `commit.py` 的 `state-update` 子命令）：背景事实写入 `state.known`；分析论断写入 Evidence Ledger（type=FACT，evidence 记"用户确认 <日期>"）；推断写入 `state.assumptions`。流程记录（历次验证结论、收口动作）不得写入任何语义字段。
2. 答复不使当前 Plan 失效：运行 `transition.py --pm-root <pm 目录绝对路径> resume`，脚本无条件清除 `resume_to` 并回到它记录的阶段，`iteration` 不变（这是同一段工作的继续，不是新一轮）。
3. 答复使当前 Plan 失效：不要勉强继续，运行 `transition.py --pm-root <pm 目录绝对路径> resume --invalidate-plan`（`iteration+1`，回 PLANNING 重规划）。是否使 Plan 失效由你依据答复内容判断，脚本把两个变体都列在 `next` 里供选择。
4. `+1` 越过 `max_iterations` 时脚本自动置 `STOPPED`，不执行该转移。
5. 恢复或重试造成的同一迭代重写，一律重跑同一提交命令覆盖同名产物文件。中断前的未完成稿不保留；跨迭代的文件才构成版本历史。

### 7. 迭代上限

每次 `iteration+1` 的转移由 `transition.py` 自动检查：越上限时不执行该转移，置 `status="STOPPED"`（终点）。此时必须向用户**明确报告**三项内容：当前最佳结论、未解决的 critical_issues、剩余的 evidence_gaps。不得宣称任务完成。

STOPPED 不自动恢复。用户明确要求继续时，先向用户确认新的上限并记录授权，然后运行 `transition.py --pm-root <pm 目录绝对路径> authorized-resume --max-iterations <新上限>`（新上限必须大于当前值；脚本写入新 `max_iterations` 并 `+1` 回 PLANNING）。

## Evidence Ledger 规则

`state.evidence` 中每条 claim（论断）必须标注类型；每条有全局唯一的 `id`（格式 `E<正整数>`，如 `E1`、`E36`，schema 强制），供机会卡片和模板引用：

- `FACT`：有可指认的证据（数据文件、文档、用户确认）。`evidence` 必须非空，校验脚本强制。
- `INFERENCE`：由 FACT 推出的结论。`evidence` 填推理依据（引用了哪些 FACT / 数据），同样必须非空，校验脚本强制。
- `HYPOTHESIS`：待验证的猜想，尚无证据支撑。`evidence` 为 null。
- `UNKNOWN`：关键且未知，需安排调查。

```json
{"id": "E1", "claim": "新用户激活率下降", "type": "FACT", "evidence": "activation_rate.csv", "confidence": "high"}
{"id": "E2", "claim": "注册流程过长导致激活率下降", "type": "HYPOTHESIS", "evidence": null, "confidence": "low"}
```

- 无证据支撑的结论只能标 `HYPOTHESIS` / `UNKNOWN`。`INFERENCE` 不写推理依据，等同于 `HYPOTHESIS`，校验脚本会拒绝通过。
- Verifier 以 Ledger 为准做检查：重要 claim 没有 evidence，就不允许当作事实，并记入 `evidence_gaps`。
- Ledger 只能经 `commit.py` 的 `state-update` 子命令写入：新 `id` 追加，已有 `id` 整条替换更正，任何情况不允许删除条目。

## Playbook 路由

| 用户意图 | Playbook | 最终交付模板 |
|---|---|---|
| 找机会 / 指标为什么降 / 问题诊断 | `playbooks/discovery.md` | `templates/product-opportunity.md` |
| 分析数据 / 验证假设 | `playbooks/data-analysis.md` | `templates/decision.md` |
| 写 PRD / 需求文档 / 方案 | `playbooks/requirement.md` | `templates/prd.md` |
| 未匹配（竞品分析、排期、roadmap 等） | 以 `playbooks/discovery.md` 的骨架起步，按需增删步骤（动作仍只能取 plan.schema.json 的封闭枚举） | Planner 在 `final_deliverable` 中自行指定；需要输出计划本身时可用 `templates/plan.md` |

Playbook 是按场景组织的过程参考文档，不是 Claude Code `/workflows` 意义上的 Workflow 脚本。它只约束 Plan 的骨架和 Verifier 的检查重点，不改变状态机。
