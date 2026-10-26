# Playbook: Audit(审计实施状态 / 中断恢复)

## 适用

两种情况:

1. **中断恢复**:上一会话实施到一半,用户说"继续实施"、"我们做到哪了"——先审计
   已有实施记录与仓库实况,再从断点继续;
2. **完工审计**:用户给一份已有实施(仓库现状 ± 实施记录)要验证成色——只审计
   出报告,不补实施。

## 前置条件

- 待审计对象:`.pev/` 下含 `impl/state.json` 的轮次(恢复场景),或用户指定的仓库
  状态 + 清单(完工审计);
- `plan_source`(state.json 的门槛上游字段,INIT 时填写):待审计的实施所依据的
  任务清单——标准位置是同轮 `tasks/output/task-plan.md`;外部场景为用户提供的清单
  文档。能定位则定位,用于覆盖与验收比对;定位不到也可审,但覆盖维度记
  evidence_gaps 并在报告中注明"无清单可比"。

## 流程

1. INIT:确定轮次目录(已有 impl/ → 同轮续用;外部场景新开 `prd-<今日日期>/`),
   `mode="audit"`、`status="VERIFYING"`、`iteration=1`(审计不走 PLANNING/EXECUTING)。
2. 把仓库实况整理为 `iterations/01-artifact.json`:从 git 历史(基线 commit → HEAD)
   提取逐任务记录——能对上清单任务的归位;对不上的改动如实记为无主改动
   (files_changed 挂到所在 commit 说明,acceptance_results 标未对照)。**不美化、
   不替记录补值**——实况什么样记什么样,差距正是审计要暴露的。
3. 以 `agents/verifier.md` 跑 5 项检查矩阵 + 7 维评分 + 双门禁,产出
   `01-verification.json`,运行校验脚本。
4. 呈现审计报告(verdict + findings by severity + 无主改动清单)。

## 分支

- **恢复场景**:报告后按正常状态机继续——已 done 且抽查无误的任务保留记录,断点
  任务起继续 EXECUTING(新迭代号);发现历史记录与实况不符 → 以实况为准,差异记
  evidence_gaps,必要时 REPLAN。
- **纯审计**:报告即终点,`status="COMPLETE"`,不补实施(用户另行决定)。

## 最终交付

审计报告(inline 呈现);恢复场景最终交付 `templates/implementation-report.md`。
