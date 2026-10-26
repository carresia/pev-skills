# 金样示例:design-single-module

一份通过 `scripts/validate.py` 的完整单轮 design 工程:架构(arch)+ 契约(api)+
schema(db)上游,拆出 2 个 PHASE、6 条任务、1 个并行组、范围内工作项覆盖 100%。

首次上手先抄它的形状:

- `state.json` — arch_source(门槛上游)+ aux_sources(同轮自动收纳)+ 登记册
- `iterations/01-plan.json` — Planner 规划(勘察 → 登记工作项 → 定阶段 → 拆任务 → 依赖)
- `iterations/01-artifact.json` — inventory(分母)+ phases(任务/检查点)+ Evidence Ledger
- `iterations/01-verification.json` — Verifier 独立评审,PASS

自检命令:

```bash
python3 ../../scripts/validate.py .
```
