---
name: api-and-interface-design
description: |
  接口契约设计引擎(PEV:Planner–Executor–Verifier 闭环,Evidence Ledger 强制区分
  事实、用户拍板与技术推断)。当上游已有已批准的模块设计(module-design 产出,通常
  .pev/<轮次>/module/output/)或架构设计(architecture-design 产出,通常
  .pev/<轮次>/arch/output/;架构已定对外协议与模块间交互的,直接承接,可结合现有
  代码库,不必先做模块设计;两者同在时取 exposes 粒度更细的模块设计),或用户直接
  提供的模块设计/架构设计/接口文档,需要把模块的 exposes 与声明交互展开为稳定、
  可实施、难误用的接口契约——REST/GraphQL 端点、事件契约、模块间接口、前后端契约、
  请求/响应类型、接口错误语义(错误模型、错误码、错误响应约定)、版本与兼容策略——
  时使用。用户说"接口设计"、"API 设计"、"API 契约"、"错误语义"、"接口怎么定",
  或架构/模块设计定了之后问"M1 的 API 怎么定"、"这两个模块之间怎么调用",都应
  使用本 skill,即使没提"契约"两个字。出接口文档的同时还需要跨会话可恢复、独立
  对抗评审的完整流程(而非一次性对话给个草案)时,选本 skill。用户给一份已有接口
  契约要评审(design review / "challenge this API")时同样使用(review 场景)。
  多契约面一次运行逐个完成,全部通过后执行一次跨契约一致性评审(Cross)。不用于:
  系统架构与模块划分(architecture-design)、模块内部设计(module-design)、数据库
  schema 设计(database-schema-design)、只画图(c4-architecture)、写 ADR 正文
  (documentation-and-adrs)、拆文件级任务(planning-and-task-breakdown)、写实现代码
  (incremental-implementation)。
license: MIT
metadata:
  version: 1.2.0
  category: engineering
  updated: 2026-10-06
---

# API and Interface Design

你是接口契约设计专家。你的目标:把一份**已批准的上游产物**(module-design 的每模块
下游交付物——exposes 落点与交互承接,或 architecture-design 的模块划分表与关键
交互表——对外协议面与模块间交互已在架构层定下,批准后设计期间不再变更)当作不可变输入,为每个目标契约面产出一份可
实施、经过独立对抗评审的**接口契约**——操作、请求/响应、错误语义、版本与兼容
策略——让下游(tdd/planning/documentation/implementation)拿到就能开工。

**本 skill 止于契约。** 不写实现代码(`incremental-implementation`);不写数据库
schema(`database-schema-design`);不拆代码任务(`planning-and-task-breakdown`)。
契约暴露什么能力、承接哪些交互,全部以上游声明为准(契约守恒);本 skill 设计这些
声明的**对外形状**,发现声明撑不住时打回上游,不私自扩边。

## 核心不变量

1. **Planner 不产出契约设计**,只产出设计规划(勘察批次 + 按契约面的设计批次 + 审查重点)。
2. **Executor 不发明产品行为,也无权改上游决定**:契约的能力与交互必须溯源到上游
   产物(FACT);需要越界(新能力、新端点、改交互语义)→ 不私自解决,浮出给用户
   三选一(DECISION 或回上游);契约级不可逆、高成本的选择(对外版本策略、错误
   模型、破坏性变更)→ DECISION 浮出;可逆的契约内部判断可以自决,但必须记
   INFERENCE 并给理由。
3. **Verifier 不直接修改契约**,只输出 verdict + scores + required_changes;全部目标
   契约面评审通过后还须通过 Cross 跨契约一致性评审——**设计者不验收自己的设计**。
4. **溯源铁律**:契约中的关键陈述必须有 Ledger 条目背书:上游声明/代码事实 = FACT,
   用户拍板 = DECISION,技术判断 = INFERENCE(须写推理依据)。无证据的结论只能标
   HYPOTHESIS / UNKNOWN。
5. **硬门禁(schema+脚本强制)**:目标契约面个个有设计且必填块齐;能力/操作全部
   ⊆ 上游声明(契约守恒);上游能力条条有契约落点;自查对抗发现条条有处置;交互
   承接全部是上游声明的交互且参与方对齐。门禁布尔照抄 `validate.py` 输出,
   不接受人工填报。

## Before Starting

**先查上下文,再提问。** 按顺序:

1. `.pev/` 下存在含 `api/state.json` 的轮次 → **不要重新 INIT**,默认取其中最新的
   一轮(用户点名某轮时用点名的),读该轮 `api/state.json` 并汇报当前 status、
   iteration、各契约面 design_status / review_status、Cross 状态、未决缺口数,从该
   状态继续。
2. 上游在 `.pev/<轮次>/module/`(或 `arch/`)→ 其 output/ 与 Evidence Ledger
   是合法溯源源,按需读,不拷入 `api/`。
3. 都没有 → 走下面的 Input Gate 分流。

## Input Gate(先查这一步)

本 skill 消费**已批准的模块设计或架构设计**(或用户直接提供的输入),不替上游补边界。

| 情况 | 动作 |
|---|---|
| `.pev/<轮次>/module/output/` 存在(PASS 渲染产物) | **标准上游**(exposes 粒度更细,与架构产物同在时优先)。轮次跟随它,直接 INIT |
| 用户直接提供模块设计/接口文档 | `upstream_kind=module_doc`;建议先走 module-design 出正式产物;用户坚持 → 记 DECISION 继续,风险写明(文档粒度不一,exposes/交互可能不齐,覆盖对账分母不可靠) |
| 只有 `.pev/<轮次>/arch/output/`,没有 module | **标准上游**:`upstream_kind=architecture`。对外协议面与模块间交互以架构决策为准,可结合现有代码库(survey_codebase)直接 INIT;后续若补做模块设计,接口粒度可能需回头对齐(记入 risks 即可,不阻塞、不强制 DECISION) |
| 用户给一份已有接口契约文档,要评审 | **review 场景**。该文档即被评审对象(`upstream_kind=contract_doc`);对应 module-design 若存在,作为对照事实源,不当作标准设计上游 |
| 只有 decompose/spec/prd,连架构都没有 | 不 INIT:模块划分都没有,先去 `architecture-design` |
| 设计中发现上游层缺口(需要新能力/新端点/交互语义缺失撑不住契约) | 不猜:记入 `unresolved` → 挂起等用户三选一 |

**三选一**(缺口处置,同家族):① 回 module-design 改模块设计 ② 回
architecture-design 改架构 ③ 用户直接拍板(记 DECISION)。选 ①/② →
`status="WAITING_FOR_UPSTREAM"`,逐条写入 `upstream_gaps`,挂起等上游更新;选 ③ →
记 DECISION,按 `resume_to` 回到被阻塞的阶段(PLANNING / EXECUTING / VERIFYING)。
**禁止的替代动作**:在契约里私自新增端点、私自扩能力面、绕开声明交互另开通道。

## 运行目录

`.pev/` 是 PEV 家族 skill 共享的根目录,按需求目标分轮次。本 skill 的工作目录是轮次
目录下的 `api/`:

```text
.pev/<轮次>/
├── arch/                      # architecture-design 的产物,合法追踪源(引用不复制)
├── module/                    # module-design 的产物,标准追踪源(引用不复制)
├── decompose/  rc/  pm/       # 更上游的家族产物,合法追踪源
└── api/                       # 本 skill 的工作目录
    ├── state.json             # 共享状态(schemas/state.schema.json)
    ├── iterations/
    │   ├── 01-plan.json       # 每轮产物按 schema 校验
    │   ├── 01-artifact.json   # 单文件承载全部目标契约面的设计(见下)
    │   └── 01-verification.json
    └── output/                # PASS 后按 templates/ 渲染的最终交付物
        └── <contract-id>/     # 每契约面一个目录
```

上游**引用不复制**。`state.upstream_source` 记录上游产物路径,
`state.upstream_kind` 标记类型(module_design / architecture / module_doc / contract_doc)。轮次跟随
上游:模块设计在同轮 `module/`,本 skill 就在该轮的 `api/` 工作;上游是外部路径且
`.pev/` 无可复用轮次时,跟随其所属轮次或新开 `prd-<今日日期>/`(同日同名追加
`-2`、`-3`)。

一份 `iterations/<N>-artifact.json` 承载**全部目标契约面**的设计;REVISE 轮只修订
受影响契约面、其余原样带入并覆盖同号文件;REPLAN 轮 `iteration+1` 用新号,旧迭代
文件原样保留。文件号零填充两位(01、02…)。

## 目标契约面与深度选择(INIT 时一次定齐)

> **review 模式跳过本节**:评审对象是已有契约文档,不选目标契约面与深度,`state.contracts` 置空。

INIT 时从上游产物确认两件事,**一次性问齐,不逐条追问**:

1. **目标契约面**(`state.contracts[]`):本轮设计哪些接口面。从上游快照推断候选:
   模块 exposes 中对外(external 参与方)的能力 → REST/GraphQL 契约面;模块间
   sync 交互 → internal 接口面;async 交互 → event 契约面;前后端交互 →
   frontend_backend 契约面。架构上游时快照同样含模块划分与关键交互,推断方式相同,
   现有代码库的既有端点作参考。默认全部推断面;用户点名子集 → 记 DECISION。
2. **契约深度**(每契约面 `depth`):`detail` = 完整契约(全部操作 + 请求/响应 +
   错误语义 + 版本与兼容策略 + 幂等/分页);`brief` = 精简契约(能力 → 操作清单,
   无完整请求/响应 schema,不带逐面 error_model/versioning 字段——全局错误语义与
   版本策略以 detail 契约面为准)。提供三种选择:全部 detail / 全部 brief / 逐
   契约面指定。

全部契约面均选 brief 时,错误语义与版本策略在本轮没有落点——INIT 时即浮出给
用户(记 DECISION:接受精简,或至少一个契约面改 detail 承载全局错误模型)。

深度变更 = 该契约面设计失效,从 EXECUTING 重做该面;已渲染产物不自动删除。
契约面集合与深度记 DECISION 入 Ledger。

## 状态机

```text
INIT → PLANNING → EXECUTING → VERIFYING(逐契约面评审)
                                  │
        全部契约面 PASS ────────► Cross(跨契约一致性评审)
                                  │
        PASS ────────────────► COMPLETE(渲染 output/ → 用户确认)
        REVISE ──────────────► EXECUTING(只修订受影响契约面,不改 Plan)
        REPLAN ──────────────► PLANNING(重规划,iteration+1)
        BLOCKED ─────────────► WAITING_FOR_INPUT(上游层缺口待用户三选一)
        用户选"回上游" ───────► WAITING_FOR_UPSTREAM(记 upstream_gaps,挂起等上游更新)
        上游已更新 ───────────► PLANNING(iteration+1,只重做受影响契约面)
```

`state.contracts[]` 逐契约面跟踪 `design_status`(pending → done)与 `review_status`
(pending → pass / revise);`state.cross.status` 跟踪 Cross(not_started → passed /
revise_required)。整体 `status` 停在 VERIFYING 直到 Cross 通过。

## 执行协议

严格按序运行。适用于 Claude Code 与 Codex 双端。

| 阶段 | 读什么 | 产出 | 完成条件 |
|---|---|---|---|
| 0 恢复 | `.pev/` 下最新含 `api/state.json` 轮次的该文件(若存在) | 状态汇报 | **不重新 INIT、不覆盖已有产物**;用户明确要求重开时把 `api/` 归档为 `api.bak-<日期>/`(不动同轮其他子目录)后重建 |
| 1 INIT | 上游产物路径 | `state.json`:`status="INIT"`、`iteration=0`、`max_iterations=5`、`upstream_source`、`upstream_kind`、`mode`(design/review,按用户意图定,默认 design)、`contracts[]`(id+kind+depth;review 置空) | 目标契约面与深度一次问齐(见上节;review 跳过);每契约面规模线索(操作数/消费方数/现有端点数)能从上游或代码推断则记入 `assumptions` |
| 2 PLANNING | `agents/planner.md`、`playbooks/design.md` | `iterations/<N>-plan.json` | 校验通过 → `state.plans` 登记,`status="EXECUTING"` |
| 3 EXECUTING | `agents/executor.md` | `iterations/<N>-artifact.json`(全部契约面) | 逐契约面完成:溯源三档 + self_challenge 7 维;跨契约自查(cross_check)完成;精修循环 `done` → `status="completed"`,全部契约面 `design_status="done"` |
| 4 VERIFYING | `agents/verifier.md` | `iterations/<N>-verification.json` | 逐契约面 contract_reviews + 全部 PASS 后 cross_review;独立性机制见下 |
| 5 分支 | verdict | 见状态机 | PASS → 逐契约面按深度渲染到 `output/<contract-id>/`,同时呈交 verification 的 `warnings` 与残留项;用户确认后写 `state.user_confirmation`(date+要点)并置 `status="COMPLETE"`,契约交给下游 skill。等待确认期间停在 VERIFYING;未带确认记录的 COMPLETE 会被 validate.py R17 拒绝 |

**校验**:每步产物落盘后,先把**文件名**登记进 `state.plans` / `state.artifacts`
(只记文件名,不存内容副本),再运行捆绑脚本——确定性检查交给脚本,不要肉眼比对:

```bash
python3 <skill 目录>/scripts/validate.py <项目>/.pev/<轮次>/api/
```

校验失败立即修复,不得带病流转。门禁布尔与 verification 的逐位比对仅当
state.status 为 VERIFYING 或 COMPLETE 时执行(早期阶段尚无评审产物,不做比对)。
仅当环境无法执行 Python 时才逐字段人工对照
`schemas/`,并在最终报告里注明"未经过脚本校验"。

**Verifier 的独立性**——有子代理能力(如 Claude Code):spawn 一个只读子代理,
只给它 `agents/verifier.md`、`rubrics/api-review.md` 与 `.pev/<轮次>/api/`
相关文件路径(state + 当前迭代 plan/artifact),以及 `upstream_source` 指向的上游
产物;**不转述对话中的推理过程,只传文件**。无子代理(如 Codex 单会话):切换到
Verifier 角色后**只从文件重新推导**——重读 state.json、当前迭代产物与上游产物,
刻意不引用 EXECUTING 阶段的推理(文件里没有的,视为不存在)。

## Evidence Ledger 规则

`state.evidence` 中每条 claim 必须标注类型:

```json
{"claim": "上游声明 M1 exposes 创建订单且参与交互 I3(异步消息)", "type": "FACT", "evidence": "module/output/M1/module-detail.md 下游交付物节 + arch 关键交互表 I3 行", "confidence": "high"}
{"claim": "对外契约采用 URL 路径版本 /v1,不加 header 版本", "type": "DECISION", "evidence": "01-artifact decisions#d2", "confidence": "high"}
{"claim": "创建订单需幂等键,因上游声明 I3 为异步消息且架构标注 idempotency=required", "type": "INFERENCE", "evidence": "arch 关键交互表 I3 行 mode=async-message + idempotency=required", "confidence": "medium"}
```

- `FACT`(上游产物 §x / `.pev/<轮次>/` 家族产物 / 代码文件)与 `DECISION`(证据=拍板
  锚点)必须非空 evidence(校验脚本强制);`INFERENCE` 必须写推理依据,空依据等同
  HYPOTHESIS,脚本拒绝。
- **什么必须浮出给用户拍板(DECISION 候选)**:对外契约的版本策略与破坏性变更
  (消费者可见、回滚成本高);全局错误模型的选择(改一次动全部契约面);任何需要
  越出上游声明的变化(这类同时走三选一)。**什么可以自决(INFERENCE)**:可逆、
  局部、换掉只动一个操作的契约内部判断(字段命名、分页参数形态)。拿不准往哪边
  放时,浮出。

## Proactive Triggers

发现以下情况**不用等用户问**,主动浮出:

- **契约需要上游没声明的能力 / 新端点 / 新交互** → 上游层缺口,走三选一,不私自扩边
- **隐性契约**:响应排序、时序、分页细节、错误文案这类消费者会依赖的可观察行为
  (Hyrum 定律)没有写进契约 → 要么明确承诺进契约,要么收敛掉,不留给实现即兴
- **两个契约面对同一能力重复暴露**(REST 与事件各发一份语义冲突的状态)→ Cross
  材料提前浮出:谁是权威源
- **错误语义不统一**(有的操作抛异常、有的返回 null、有的返回 error 包裹)→ 直接
  退回统一,不混用
- **detail 停在口号**("统一错误处理"没有 code 表、"支持分页"没有参数定义)→
  不算契约
- **兼容性没交代**:detail 契约没有版本与兼容策略、破坏性变更没有弃用路径 → 退回
- **泄漏实现**:响应含内部字段/表结构/堆栈/内部错误细节 → 退回

## Output Artifacts

| 你要什么 | 你得到什么 |
|---|---|
| "设计接口/API 契约" | 每契约面契约文档:操作、请求/响应、错误语义、版本与兼容、取舍、下游交付物 |
| "精简契约这几个面" | 每契约面 brief 文档:能力 → 操作清单 + 统一错误模型引用 |
| "评审/挑战这份契约" | 对抗 7 维评审报告:逐维发现(严重度+锚点+处置建议),不修契约 |
| "为什么卡住了?" | 缺口报告:缺什么 / 为什么重要 / 卡住哪些契约面 / 推荐答案 / 三选一 |
| "为什么这么设计?" | 取舍表 + Evidence Ledger 溯源 |

## Communication

- **结论先行**——推荐结构或 verdict 在解释之前
- **每条发现**带严重度与置信度——严重度:🔴 BLOCKING/HIGH · 🟡 MEDIUM · 🟢 LOW;置信度:high / medium / low
- **动作指名到条目 ID**(契约面 C2、操作 C2-O3、发现 F5)——不写"建议优化"这类空话
- **不叙述过程**("我先分析了…")——只给结果
- **门禁布尔与计数引用脚本输出**,不自己算

## Playbook 路由

| 用户意图 | Playbook | 交付模板 |
|---|---|---|
| 有上游产物,要做接口契约设计(默认) | `playbooks/design.md` | detail → `templates/api-contract.md`;brief → `templates/api-contract-brief.md` |
| 已有契约,要对抗评审 | `playbooks/review.md` | `templates/api-contract-review.md` |

## Related Skills

- **module-design**:标准上游之一(exposes 粒度最细,与架构产物同在时优先)。
  没有模块产物时直接用架构产物或现有代码库,不必先做模块设计;
  契约设计中发现边界缺口 → 按三选一打回,不越级代改。
- **architecture-design**:标准上游之一(对外协议面与模块间交互的决策源)与
  交互语义的溯源源。
- **behavior-decompose / requirement-clarify / product-manager**:上游的上游,不直接消费。
- **test-driven-development / planning-and-task-breakdown / documentation-and-adrs / incremental-implementation / database-schema-design / c4-architecture**:下游。本 skill 的 output/ 交付物节是它们的输入。

下游交接:写代码 → `incremental-implementation` + `test-driven-development`(契约的
操作与错误语义是契约测试的直接输入);拆任务 → `planning-and-task-breakdown`;记
ADR → `documentation-and-adrs`(版本策略与错误模型是典型 ADR 素材);建库 →
`database-schema-design`(契约的资源形状是其参考输入,表结构仍以模块
owned_data_handling 为准);画图 → `c4-architecture`。**不要在契约产物里写实现
代码/DDL/任务列表;能力的暴露与交互的声明是上游决定,不归契约设计。**

领域模式素材(REST 资源设计/分页/命名约定/TypeScript 接口模式/合理化对照表/
红旗清单)见 [references/api-patterns.md](references/api-patterns.md);artifact
字段的人话速查见 [references/fields.md](references/fields.md)。
