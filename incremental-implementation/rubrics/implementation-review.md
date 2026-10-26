# 实施记录质量评审量规

> 门槛上游统一称 `plan_source`(任务清单),同轮设计产物为 `aux_sources`。
> 清单本身的错浮出后交用户三选一,不是静默硬停。

**使用方**:Verifier(独立评审)、Executor(交预览前的自检)
**用途**:在渲染 output/ 之前判定实施质量
**配套**:产出格式见 `agents/verifier.md` 与 `schemas/verification.schema.json`——
**本文件只定义"怎么判",不定义"输出长什么样"**(契约只在一处定义)

---

## 严重度分级

| 级别 | 含义 | 动作 |
|---|---|---|
| **BLOCKING** | 不修就无法交付 | 交付前**必须**修 |
| **HIGH** | 重大质量问题 | 交付前**必须**修 |
| **MEDIUM** | 质量隐患 | **应当**修,时间紧可讨论 |
| **LOW** | 可改进 | 可选,记入精修 |

---

## 七个评审维度

### 1. 覆盖 Coverage

| 判据 | 严重度 | 检查 |
|---|---|---|
| 非延后任务条条 done | BLOCKING | registry 每条非 deferred 项 → done 记录;门禁 100%(脚本算) |
| 不做清单外的活 | BLOCKING | 每条记录对应 registry 任务(脚本已拦悬空);做了没人要的功能 = 范围失控 |
| 延后有据 | HIGH | deferred 逐条有理由、有出处、有后续接法,不是"难做就延后" |
| 基线先于开工 | HIGH | baseline 记录完整且全绿(脚本拦 fail;你审口径对不对——测试命令真的覆盖主路径吗) |

清单:

- [ ] registry 的每条非 deferred 项有 done 记录
- [ ] 无"顺手实现"清单外的功能
- [ ] deferred 项的理由成立且有留痕
- [ ] baseline 的检查命令是该项目真正的健康判据

### 2. 范围纪律 Scope Discipline

| 判据 | 严重度 | 检查 |
|---|---|---|
| 零未声明改动 | BLOCKING | files_changed ⊆ 声明 ∪ deviations(脚本逐文件拦) |
| 偏离逐条有据 | HIGH | deviations 的 why 是必要技术牵连,不是借口;用户批准过的有 DECISION 锚点 |
| 少改如实记录 | MEDIUM | 实际比声明改得少:合理省略还是没做完?对照验收标准判 |
| 无主改动 | BLOCKING | 仓库 diff 与记录汇总对账,改了没记的文件是造假 |

清单:

- [ ] 脚本范围违规为零
- [ ] 每条 deviation 的 why 站得住
- [ ] 仓库实际 diff ⊆ 记录的 files_changed 汇总(抽查 `git diff --stat` 对账)

### 3. 证据质量 Evidence Quality

| 判据 | 严重度 | 检查 |
|---|---|---|
| done 必有通过的验证 | BLOCKING | 每条 done 任务 ≥1 条 result=pass 且 evidence 非空(脚本拦) |
| 证据像真输出 | HIGH | evidence 是命令输出的关键行/数字,不是"全绿""正常"这类断言 |
| 先红后绿 | MEDIUM | 新逻辑/修 bug 的任务有失败测试先行(记录或 commit 历史可证)——测试纪律见 test-driven-development |
| 命令可复跑 | HIGH | 抽查 2-3 条:在仓库里重跑 verification 命令,结果与记录一致 |

清单:

- [ ] 每条 done 任务的验证证据可查、可复跑
- [ ] commit 哈希在仓库中存在,信息与任务对应
- [ ] 抽查重跑未发现与记录矛盾

### 4. 验收对照 Acceptance Alignment

| 判据 | 严重度 | 检查 |
|---|---|---|
| 逐条对照不漏不换 | BLOCKING | acceptance_results 与 registry 验收集合一致(脚本拦)且全部 met=true(脚本拦 done) |
| evidence 真证明该条 | HIGH | met=true 的证据与该条验收标准语义对应,不是证明了别的事 |
| failed 说不清卡点 | MEDIUM | failed 任务的 note 写明卡在哪、下一步是什么 |

清单:

- [ ] 每条验收标准的 evidence 读完就能确认满足
- [ ] 没有偷换标准措辞(脚本对集合,这里对语义)
- [ ] failed/deferred 的原因与下一步清晰

### 5. 提交纪律 Commit Discipline

| 判据 | 严重度 | 检查 |
|---|---|---|
| 一任务一提交 | HIGH | done 任务有 commit(脚本拦空);commit 不混两件独立的事 |
| 信息可读 | MEDIUM | commit 信息说清做了什么、为什么,不是 "fix"、"update" |
| 不可逆操作单独成提交 | HIGH | 迁移/删数据/改公共配置单独 commit,可单独回滚 |

### 6. 可恢复性 Recoverability

| 判据 | 严重度 | 检查 |
|---|---|---|
| 批次末系统可工作 | BLOCKING | 每批结束构建/测试绿——中断后能从批次边界恢复,而不是从头再来 |
| 每任务可独立回滚 | HIGH | 回滚任一任务的 commit 不破坏其他任务(公共改动有前置任务先定) |
| 恢复点密集 | MEDIUM | 记录落在任务粒度;一条记录管多件事 = 恢复粒度粗 |

### 7. 可溯源 Traceability

| 判据 | 严重度 | 检查 |
|---|---|---|
| registry 忠实转录上游 | BLOCKING | 上游 tasks/ 在时脚本对账;你审 files_touched/acceptance_criteria 转录语义一致(外部清单场景尤其) |
| Ledger 与记录一致 | BLOCKING | type=FACT/DECISION 的条目都有非空 evidence(脚本拦);测试输出/commit 是标准 FACT 证据 |
| 记录 ↔ 清单 ↔ 设计链路通 | HIGH | 有疑义的实现能顺着 trace 查到任务与设计依据(aux_sources) |

---

## 评分

每个维度 1-5 分:

| 分 | 含义 |
|---|---|
| 5 | 优秀——无需改进 |
| 4 | 良好——有小改进空间 |
| 3 | 合格——达到最低门槛,仍有改进空间 |
| 2 | 低于门槛——需要显著改进 |
| 1 | 差——需要推倒重做 |

## 通过判定

**PASS** = 七维全部 ≥3 分,且无 BLOCKING 项,且 `task_execution_pct` = 100%、
`scope_violations` = 0(数字达标由脚本 R8 强制)。

**不 PASS** 时按问题的**归属**分流(与 `agents/verifier.md` 的 verdict 定义一致):

- 问题出在**实施/记录** → `REVISE`,回 Executor
- 问题出在**执行规划** → `REPLAN`,回 Planner
- **缺口未决**或无法验证(仓库状态不可审计)→ `BLOCKED`,进 `WAITING_FOR_INPUT`

迭代上限由 `state.max_iterations` 决定(**不硬编码次数**)。超出即停止,并明确报告:
当前最佳实施状态、未解决的 critical_issues、覆盖率与范围违规数字、仍未闭环的缺口。
**不得宣称完成。**

---

## 常见质量模式

### 好的模式

- 每条 done 记录:commit 哈希 + 真实输出摘要 + 逐条验收对照,拿来就能复核
- 偏离声明少而准,每条 why 都是真牵连
- 抽查重跑验证命令,输出与记录一致
- 仓库 diff 与记录汇总严丝合缝,没有无主文件
- 批次边界上系统可运行、可演示

### 有问题的模式

- evidence 全是"通过""全绿"四个字(脚本拦空 evidence,但断言式证据要靠人审)
- files_changed 照抄声明清单而非实际改动(抽查 diff 就穿帮)
- 一个 commit 捆三条任务,回滚只能三件事一起回
- deviations 写"实现需要"(为什么需要?牵连什么?)——站不住的借口
- failed 任务的 note 写"有问题"三个字
- 测试是实施后补的,没有先红后绿的痕迹(代码全写完才写测试,测的是实现不是行为)
- 基线检查只跑了 `ls`,主干测试红着就开工
