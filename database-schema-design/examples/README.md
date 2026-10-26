# 金样示例(随包自检)

本目录是一个**完整通过 `scripts/validate.py` 校验**的单库设计示例(PostgreSQL,
单模块 M1),首次上手时先抄这里的形状,再改造成自己的项目。

结构对应关系:

```text
design-single-pg/                  # 即 .pev/<轮次>/db/ 工作目录
├── state.json                     # 共享状态(已 COMPLETE)
├── iterations/
│   ├── 01-plan.json               # Planner 产出
│   ├── 01-artifact.json           # Executor 产出(全部目标库)
│   └── 01-verification.json       # Verifier 产出(PASS + 红线全过)
└── output/D1/orders-schema.md     # 渲染后的最终交付物
```

要点:

- `01-artifact.json` 是核心,读它即可掌握全部必填块:`input_summary.upstream_snapshot`(上游快照)→ `upstream_items`(覆盖对账分母)→ `stores[]`(逐库设计)→ `upstream_mapping`(分子对账)。
- 实体名(`covered_entities` / `tables[].entity` / `upstream_items[].item`)必须**逐字符一致**,漂移一个空格都过不了校验。
- evidence 三条演示了 FACT / DECISION / INFERENCE 三档;DECISION 的 `evidence` 用 `01-artifact decisions#d2` 回指 `decisions` 锚点。
- 本示例 `upstream_source` 是占位路径,未随包附带真实上游产物;真实项目里应指向实际的 module/arch 产物。示例的 evidence 因此不带 `source{path}`,避免新鲜度回读失败。

验证方式:

```bash
python3 scripts/validate.py examples/design-single-pg
# 期望:exit 0,输出「全部产物通过 schema 与语义规则校验」
```

`tests/run_tests.py` 里有一条用例(T45)持续保证本示例不腐坏。
