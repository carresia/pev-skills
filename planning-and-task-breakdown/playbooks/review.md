# Playbook: Review(评审已有任务清单)

## 适用

用户已有任务清单/实施计划(文件或直接粘贴),要求评审质量——只评审打分,不重拆。

## 前置条件

- 待评审的清单:用户提供文件或直接粘贴;
- `arch_source`:能定位架构产物则定位,用于覆盖与溯源比对;定位不到也可审,但溯源维度
  记 evidence_gaps 并在报告中注明"无上游可比"。

## 流程(不走完整 PEV 环)

1. INIT:确定轮次目录(上游可定位在 `.pev/` 某轮→同轮;否则新开 `prd-<今日日期>/`),
   创建 `.pev/<轮次>/tasks/state.json`,`status="VERIFYING"`、`mode="review"`、`iteration=1`
   (直接进入评审,PLANNING/EXECUTING 不发生),`arch_source` 记上游或 "unavailable"。
2. 把既有清单解析为 `iterations/01-artifact.json`(文件名登记进 `state.artifacts`,R10 对账):
   `status="completed"`、按既有清单归纳 `inventory`(能溯源的工作项补 anchor,溯不到的
   留空——这正是 Verifier 要抓的)、`phases`/`checkpoint` 照既有结构填,不补值不美化。
3. 以 `agents/verifier.md` 跑 5 项检查矩阵 + 7 维评分 + 覆盖门禁,产出
   `01-verification.json`,运行校验脚本。
4. 呈现评审报告(verdict + findings by severity)。

## 分支

- 用户只要报告 → 渲染报告即结束,`status="COMPLETE"`。
- 用户要求修复 → 按正常状态机流转:REVISE 项回 EXECUTING **只修 fail 项**(不重拆
  pass 项);缺口未决 → 三选一;漏整个上游产物 → REPLAN。

## 最终交付

评审报告(inline 呈现),修复场景下最终交付 `templates/task-plan.md`。
