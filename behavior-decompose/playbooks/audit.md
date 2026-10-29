# Playbook: Audit(审计已有拆解)

## 适用

用户已有行为目录(Epic → Feature → Story),要求评审质量——只评审打分,不重拆。

## 前置条件

- 待审计的树:用户提供文件或直接粘贴;
- `spec_source`:能定位上游(Spec/PRD)则定位,用于覆盖与溯源比对;定位不到也可审,
  但溯源维度记 evidence_gaps 并在报告中注明"无上游可比"。

## 流程(不走完整 PEV 环)

1. INIT:确定轮次目录(上游可定位在 `.pev/` 某轮→同轮;否则新开 `prd-<今日日期>/`),
   创建 `.pev/<轮次>/decompose/state.json`,`status="VERIFYING"`、`iteration=1`
   (直接进入评审,Plan/EXECUTING 不发生),`spec_source` 记上游或 "unavailable"。
2. 把既有树解析为 `iterations/01-artifact.json`(文件名登记进 `state.artifacts`,R9 对账):`status="completed"`、`artifact` 块
   填树,并**补 `category_defaults`**——按既有目录的适用面归纳全局适用/豁免,全局豁免
   写项目级依据(这本身就是审计判断的一部分);能溯源的条目补 `trace` + Evidence
   Ledger(FACT),溯不到的留空——这正是 Verifier 要抓的。
3. 审查走单一入口:跑 `scripts/review.py`(生成冻结输入与机器检查),按
   `agents/verifier.md` 完成 5 项检查矩阵 + 7 维评分 + 覆盖率门禁,写
   `reviews/<id>/candidate.json`,再跑同一命令提交校验(`01-verification.json`
   由脚本写为投影)。
4. 呈现审计报告(verdict + findings by severity)。

## 分支

- 用户只要报告 → 渲染报告即结束,`status="COMPLETE"`。
- 用户要求修复 → 按正常状态机流转:REVISE 项回 EXECUTING **只修 fail 项**
  (不重拆 pass 项);缺口未决 → 三选一;漏整个 Epic → REPLAN。

## 最终交付

审计报告(inline 呈现),修复场景下最终交付 `templates/catalog.md`。
