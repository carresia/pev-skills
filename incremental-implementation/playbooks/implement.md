# Playbook: Implement(任务清单 → 实施)

## 适用

门槛上游已有任务清单(`.pev/<轮次>/tasks/output/task-plan.md`,同轮 `tasks/iterations/`
有结构化产物;或用户提供的任务清单),需要按清单逐任务落地实施并留下可审计的实施记录。

## 前置条件

`state.plan_source` 存在且可读。分流见 SKILL.md Input Gate:

- 只有架构/设计产物、没有任务清单 → 打回上游:先走 `planning-and-task-breakdown`;
- 用户直接给任务清单(无 .pev 结构)→ 记 DECISION 继续(转录分母无结构化对账源,
  风险写明),Executor 逐条转录为 task_registry;
- 同轮 arch/module/api/db/decompose 产物自动登记为 `aux_sources`(实现遇疑查设计依据,
  引用不复制),不逐个问用户。

## Plan 骨架

1. `survey_context` — 勘察仓库现状与**基线**(分支/commit/测试与构建是否全绿);
   基线 fail → 浮出,不进入下一步。基线通过后按 `guides/pre-implementation-explore.md`
   只读取证当前批次任务,报告存 `impl/explore/`,FACT 并入 Evidence Ledger;影响任务的
   conflict/unresolved 必须阻塞该任务。定高风险任务的前置顺序。
2. `build_task_registry` — 从上游结构化产物(或用户清单)逐条转录任务分母
   (id/标题/声明文件/验收标准/依赖/trace)。小工程可并入第 1 步。
3. `define_batches` — 按依赖与 PHASE 边界定执行批次、每批恢复点(批次末系统可工作)
   与停止条件;范围过大时收敛并记 stop_conditions。

## 执行与记录

逐任务协议(先红后绿/真跑验证/原子提交/如实记录)见 `agents/executor.md`;测试纪律
与实施技法见 [guides/implementation-flow.md](../guides/implementation-flow.md)。
每批产物落盘 → 登记 → 校验:

```bash
python3 <skill 目录>/scripts/validate.py <项目>/.pev/<轮次>/impl/
```

## 最终交付

`templates/implementation-report.md` 渲染到 `.pev/<轮次>/impl/output/implementation-report.md`;
PASS 且用户确认后 `status="COMPLETE"`,实施记录与仓库改动一并交付。

## Verifier 侧重

检查矩阵、门禁阈值与 verdict 规则以 `agents/verifier.md` 为准;抽查重跑验证命令是
本 skill Verifier 的特色动作——证据真实性比记录完整性更根本。
