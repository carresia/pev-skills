# 金样:implement-single-phase

最小可过校验的完整工程:上游任务清单 2 条任务(线性依赖),impl 侧单批次执行完毕,
含 1 条有 DECISION 背书的偏离。演示:

- 上游对账:`tasks/iterations/01-artifact.json`(对账源)↔ `impl` 的 `task_registry`
- 实施记录:baseline / registry / task_records(done 任务的 commit + 测试证据 + 验收逐条对照)
- 范围纪律:TASK-1.2 改了声明外的 `src/middleware/auth.ts`,走 deviations(path + why + DECISION 锚点)

校验:

```bash
python3 ../../scripts/validate.py impl/
# 预期:OK;task_execution_pct=100.0 通过;scope_violations=0 通过
```
