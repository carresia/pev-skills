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

## 命令面(唯一执行协议)

命令只在模型必须拿主意的地方存在;下一步已确定的步骤由命令自动做完
(渲染、绑定、状态推进、收口都是脚本内部行为,**模型不得手做**)。
每条命令的 stdout 是单行 JSON;**一律原样执行上一命令返回的 `next[].argv`
(或按 `next[].kind` 行动)**,不要自行发明下一步。

| 何时用 | 命令 |
|---|---|
| 开始/续接一轮澄清 | `python3 <skill>/scripts/init.py --workspace <含 .pev/ 的目录> --prd-source <PRD 路径> --objective <goal 草稿路径>`;变更已创建且 Spec 要交给 OpenSpec 工作流时,加 `--deliver-to <变更目录,相对 workspace>` 登记 PASS 后把 spec.md 交付到该目录 |
| 不知道从哪轮续接 | `python3 <skill>/scripts/init.py --locate --workspace <目录>`(只读汇报) |
| 用户要求推倒重来 | 同上 init 加 `--restart`(自动归档 rc.bak-<日期>) |
| Plan 草稿写完 | `python3 <skill>/scripts/commit.py --rc-root <rc 目录> plan <草稿路径>` |
| Artifact 草稿写完(草稿 `status` 字段即岔路:completed/replan_required/blocked) | `python3 <skill>/scripts/commit.py --rc-root <rc 目录> artifact <草稿路径>` |
| 验证报告写完(报告 `verdict` 字段即岔路:PASS/REVISE/REPLAN/BLOCKED) | `python3 <skill>/scripts/commit.py --rc-root <rc 目录> verification <草稿路径>`;**verdict=PASS 时同一命令自动完成绑定、渲染与收口** |
| 用户答复了 blocked 的问题(补丁字段即岔路:invalidate_plan/back_to_prd/prd_refreshed) | `python3 <skill>/scripts/commit.py --rc-root <rc 目录> state-update <补丁路径>` |
| 用户要求修订已收口的轮 | `python3 <skill>/scripts/reopen.py --rc-root <rc 目录> --note <修订要点>` |
| 任何时候想确认现状/定位续跑点 | `python3 <skill>/scripts/validate.py --rc-root <rc 目录>`(只读) |

**写入边界**:state.json、登记册、验证输入快照、provenance、`output/spec.md`
与登记的交付副本(`<deliver_to>/spec.md`)一律由脚本写;模型只写三类草稿
文件(plan/artifact/verification JSON,按 `schemas/` 校验)与 state-update
补丁。手改脚本管辖的文件会被逐字节/摘要校验当场发现并拒绝。

## 草稿要点

- **Plan**(`agents/planner.md` 为角色指令,先执行「Proactive Triggers」预警):
  严格两层——①`interrogate_value` 价值性提问;②`interrogate_ambiguity` 逐章
  扫描落地模糊地带(业务规则/权限与状态/异常与边界/数据口径/范围)。价值先行
  由脚本强制(R5)。
- **Artifact**(`agents/executor.md`):只执行当前 Plan 批次;**追踪优先**——
  ①PRD(prd_source)②同轮 `.pev/<轮次>/pm/` 中间产物 ③codebase;追到的答案写
  `artifact.answers`(question/answer/source)并给 `evidence` 带上 FACT 条目
  (脚本会自动同步进 state 的 Evidence Ledger,不要手改 state);追不到 →
  `status="blocked"`+`replan_reason`,不要编答案。
- **Verification**(`agents/verifier.md`):独立审查。有子代理能力就 spawn 只读
  子代理,只给文件路径,不转述对话推理;无子代理就只从文件重推。报告必须
  **逐字段复述** `iterations/<N>-verification-input.json` 到
  `verification_input` 字段(提交时脚本核对,不一致即拒收)。
- **等待恢复补丁**(state-update):用户答复 → `evidence`(DECISION 条目)+
  `answers`;答复推翻 Plan → 加 `invalidate_plan:true`;选"回 PM" →
  `back_to_prd:true`+`prd_gaps`;PRD 已更新 → `prd_refreshed:true`。

## 运行目录

```text
.pev/<轮次>/
├── pm/                        # product-manager 的产物(PRD),合法追踪源,引用不复制
├── rc/                        # 本 skill 的工作目录
│   ├── state.json             # 共享状态(schemas/state.schema.json;脚本管辖)
│   ├── iterations/
│   │   ├── 01-plan.json       # <N> = 写入时 iteration+1;REVISE 轮无新 plan 属正常
│   │   ├── 01-artifact.json
│   │   ├── 01-verification-input.json  # 脚本冻结的验证输入快照
│   │   ├── 01-verification.json        # PASS 后含脚本写入的 provenance
│   │   └── ...
│   └── output/
│       └── spec.md            # 唯一交付物;只由 PASS 收口链确定性渲染产生
└── decompose/                 # behavior-decompose 的工作目录(结构同 rc/)
```

`state.prd_source` 记录上游 PRD 路径(通常 `.pev/<轮次>/pm/output/prd.md`,
或用户直接提供的文档),追踪与打回都以它为准。找不到 PRD 不开工:还没 PRD →
`product-manager`;从零澄清写 spec → `spec-driven-development`。

## 恢复纪律(任意位置断电)

一切写入原子且幂等:**中断后重跑中断的那条命令即收敛**,不重复递增 iteration,
不产生半程账本。接手时只做三件事:跑 `init.py --locate` 找到轮次 → 读
`validate.py` 输出的 status/iteration/errors → 按"命令面"表从中断处继续。
**不要重新 INIT,不要覆盖或手改已有产物。**状态机规则(什么状态允许什么命令、
迭代上限、渲染一致性)全部由脚本与测试强制,模型无需背诵,按命令面的
"何时用"列选择即可。

## Evidence Ledger 规则

`state.evidence` 中每条 claim 必须标注类型(由脚本按 R1 强制):

```json
{"claim": "PRD §2 目标为提升新用户激活率", "type": "FACT", "evidence": "PRD §2", "confidence": "high"}
{"claim": "现有项目无 activation 埋点", "type": "FACT", "evidence": "src/analytics/events.ts grep 无命中", "confidence": "high"}
{"claim": "激活窗口期定为注册后 24 小时", "type": "DECISION", "evidence": "01-artifact answers#q3", "confidence": "high"}
```

- `FACT`(证据=PRD §x / `.pev/<轮次>/pm/` 产物 / 代码文件)与 `DECISION`(证据=澄清记录锚点)都必须有非空 `evidence`;没有证据的结论只能标 `INFERENCE` / `HYPOTHESIS` / `UNKNOWN`。
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
