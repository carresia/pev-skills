"""planning-and-task-breakdown 反博弈回归测试(仅依赖 Python 标准库)。

每个用例构造一个临时 .pev 工程,断言 validate.py 的退出码与错误定位:
超 8 文件、档位与文件数不符、验收标准爆表、悬空引用(工作项/任务)、依赖环、
自依赖、文档序违反拓扑、并行组内有依赖路径(直接/传递)、范围内工作项漏拆
还判 PASS、门禁数字人工填报不符、改分母漏拆任务无 DECISION 背书、换溯源锚点
无背书、登记册不符、空 evidence、缺 replan_reason、状态门缺字段/多字段,都必须被拦下;
干净产物(design/review/带范围外项/REVISE 中间态)必须全绿通过;
非 UTF-8 文件必须优雅报错而非崩溃。
"""

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
VALIDATE = SKILL / "scripts" / "validate.py"

SCORE_DIMS = ["coverage", "granularity", "ordering", "verifiability",
              "parallelization", "checkpoints", "traceability"]


def task(tid, size, n_files, ac=("接口按契约返回", "错误码符合约定"), implements=("INV-2",),
         deps=(), group=None, verification_kinds=(("test", "npm test -- --grep orders"),)):
    doc = {
        "id": tid,
        "title": f"{tid} 实现",
        "description": "做什么、不做什么",
        "size": size,
        "files_touched": [f"src/{tid.replace('.', '_')}_f{i}.ts" for i in range(n_files)],
        "acceptance_criteria": list(ac),
        "verification": [{"how": cmd, "kind": kind} for kind, cmd in verification_kinds],
        "implements": list(implements),
        "dependencies": list(deps),
        "trace": "arch/output 模块表 M1 行",
    }
    if group is not None:
        doc["parallel_group"] = group
    return doc


def checkpoint():
    return {"checks": ["npm test 全绿", "npm run build 通过"], "review_with_human": False}


def inventory():
    return [
        {"id": "INV-1", "kind": "architecture_module", "title": "M1 订单模块",
         "anchor": "arch/output 模块表 M1 行", "in_scope": True},
        {"id": "INV-2", "kind": "api_contract", "title": "C3 订单契约",
         "anchor": "api/output/D1/contracts.md C3", "in_scope": True},
        {"id": "INV-3", "kind": "db_object", "title": "orders 表",
         "anchor": "db/output/D1/orders-schema.md orders", "in_scope": True},
        {"id": "INV-4", "kind": "engineering_item", "title": "migration 脚手架",
         "anchor": "01-artifact decisions#d1", "in_scope": True},
    ]


def phases():
    return [
        {"id": "PHASE-1", "title": "订单基础(可下单)", "objective": "用户可完成下单",
         "tasks": [
             task("TASK-1.1", "XS", 1, implements=("INV-3", "INV-4")),
             task("TASK-1.2", "S", 2, deps=("TASK-1.1",), group="g1"),
             task("TASK-1.3", "S", 2, deps=("TASK-1.1",), group="g1",
                  implements=("INV-2",), verification_kinds=(("build", "npm run build"),)),
             task("TASK-1.4", "M", 3, deps=("TASK-1.2",), implements=("INV-1",),
                  verification_kinds=(("test", "npm test"), ("manual", "浏览器下单走通"))),
         ],
         "checkpoint": checkpoint()},
        {"id": "PHASE-2", "title": "订单查询", "objective": "用户可查订单",
         "tasks": [
             task("TASK-2.1", "S", 2, deps=("TASK-1.1",)),
             task("TASK-2.2", "M", 3, deps=("TASK-2.1", "TASK-1.4"), implements=("INV-1",)),
         ],
         "checkpoint": checkpoint()},
    ]


def evidence():
    return [
        {"claim": "TASK-1.2 依据契约 C3", "type": "FACT",
         "evidence": "api/output/D1/contracts.md C3", "confidence": "high"},
        {"claim": "migration 脚手架登记为工程支撑项", "type": "DECISION",
         "evidence": "01-artifact decisions#d1", "confidence": "high"},
    ]


def artifact():
    return {
        "status": "completed",
        "evidence": evidence(),
        "artifact": {"inventory": inventory(), "phases": phases()},
    }


def plan():
    return {
        "goal": "g", "understanding": "u", "known": [], "unknown": [], "assumptions": [],
        "plan": [{"id": "step_1", "objective": "o", "action": "survey_context",
                  "inputs": [], "expected_output": "e", "success_criteria": "s"}],
        "final_deliverable": "f", "stop_conditions": [],
    }


def state(status="VERIFYING", mode="design"):
    return {
        "objective": {"goal": "test"},
        "arch_source": "arch/output/architecture.md",
        "aux_sources": [
            {"kind": "api_contract", "path": "api/output/D1/contracts.md"},
            {"kind": "db_schema", "path": "db/output/D1/orders-schema.md"},
        ],
        "mode": mode,
        "status": status,
        "iteration": 1,
        "max_iterations": 5,
        "plans": ["01-plan.json"],
        "artifacts": ["01-artifact.json"],
        "evidence": [],
    }


def verification(verdict="PASS", pct=100.0):
    return {
        "verdict": verdict,
        "scores": {d: 4 for d in SCORE_DIMS},
        "coverage": {"upstream_coverage_pct": pct, "notes": ""},
        "strengths": [],
        "critical_issues": [],
        "warnings": [],
        "required_changes": [],
        "evidence_gaps": [],
        "confidence": "high",
    }


def run_case(files, expect_ok, expect_sub=None):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / ".pev" / "prd-2026-10-07" / "tasks"
        (root / "iterations").mkdir(parents=True)
        for name, doc in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(doc, bytes):
                path.write_bytes(doc)
            else:
                path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(VALIDATE), str(root)],
                              capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        if expect_ok:
            if proc.returncode != 0:
                return f"期望通过但失败(exit={proc.returncode}):\n{out}"
        else:
            if proc.returncode == 0:
                return f"期望失败但通过:\n{out}"
            if expect_sub and expect_sub not in out:
                return f"错误未命中预期定位({expect_sub!r}):\n{out}"
        return None


def full_files(st=None, art=None, ver=None, extra=None):
    files = {
        "state.json": st if st is not None else state(),
        "iterations/01-plan.json": plan(),
        "iterations/01-artifact.json": art if art is not None else artifact(),
        "iterations/01-verification.json": ver if ver is not None else verification(),
    }
    if extra:
        files.update(extra)
    return files


def t(name):
    def deco(fn):
        TESTS.append((name, fn))
        return fn
    return deco


TESTS = []


@t("干净 design 工程全绿")
def _(x):
    return run_case(full_files(), True)


@t("干净 review 工程全绿(mode=review)")
def _(x):
    return run_case(full_files(st=state(mode="review")), True)


@t("范围外项带理由可过")
def _(x):
    art = artifact()
    art["artifact"]["inventory"].append(
        {"id": "INV-9", "kind": "story", "title": "优惠券",
         "anchor": "decompose/output/catalog.md STORY-3.1",
         "in_scope": False, "note": "第二批拆解,用户 2026-10-07 拍板"})
    return run_case(full_files(art=art), True)


@t("超 8 文件被拦(XL 不存在)")
def _(x):
    art = artifact()
    art["artifact"]["phases"][0]["tasks"][0] = task("TASK-1.1", "L", 9, implements=("INV-3", "INV-4"))
    return run_case(full_files(art=art), False, "超过上限 8")


@t("档位与文件数不符被拦")
def _(x):
    art = artifact()
    art["artifact"]["phases"][0]["tasks"][1] = task("TASK-1.2", "S", 3, deps=("TASK-1.1",))
    return run_case(full_files(art=art), False, "档位与文件数不一致")


@t("验收标准超过 5 条被拦")
def _(x):
    art = artifact()
    art["artifact"]["phases"][0]["tasks"][1] = task(
        "TASK-1.2", "S", 2, deps=("TASK-1.1",),
        ac=("a", "b", "c", "d", "e", "f"))
    return run_case(full_files(art=art), False, "任务过大信号")


@t("验收标准为空被拦(schema)")
def _(x):
    art = artifact()
    art["artifact"]["phases"][0]["tasks"][1]["acceptance_criteria"] = []
    return run_case(full_files(art=art), False, "minItems")


@t("验证方式为空被拦(schema)")
def _(x):
    art = artifact()
    art["artifact"]["phases"][0]["tasks"][1]["verification"] = []
    return run_case(full_files(art=art), False, "minItems")


@t("文件清单为空被拦(schema)")
def _(x):
    art = artifact()
    art["artifact"]["phases"][0]["tasks"][1]["files_touched"] = []
    return run_case(full_files(art=art), False, "minItems")


@t("implements 为空被拦(schema:不留无落点任务)")
def _(x):
    art = artifact()
    art["artifact"]["phases"][0]["tasks"][1]["implements"] = []
    return run_case(full_files(art=art), False, "minItems")


@t("implements 悬空引用被拦")
def _(x):
    art = artifact()
    art["artifact"]["phases"][0]["tasks"][1]["implements"] = ["INV-99"]
    return run_case(full_files(art=art), False, "不在 inventory")


@t("依赖悬空引用被拦")
def _(x):
    art = artifact()
    art["artifact"]["phases"][0]["tasks"][1]["dependencies"] = ["TASK-9.9"]
    return run_case(full_files(art=art), False, "不存在")


@t("自依赖被拦")
def _(x):
    art = artifact()
    art["artifact"]["phases"][0]["tasks"][1]["dependencies"] = ["TASK-1.2"]
    return run_case(full_files(art=art), False, "依赖自己")


@t("依赖环被拦")
def _(x):
    art = artifact()
    tasks = art["artifact"]["phases"][0]["tasks"]
    tasks[1]["dependencies"] = ["TASK-1.3"]
    tasks[2]["dependencies"] = ["TASK-1.2"]
    return run_case(full_files(art=art), False, "存在环")


@t("文档序违反拓扑被拦")
def _(x):
    art = artifact()
    # TASK-2.1 排在 TASK-1.4 之后,但 1.4 依赖它(无反向边,纯顺序违规不构成环)
    art["artifact"]["phases"][0]["tasks"][3]["dependencies"] = ["TASK-1.2", "TASK-2.1"]
    return run_case(full_files(art=art), False, "文档顺序违反拓扑序")


@t("并行组内直接依赖被拦")
def _(x):
    art = artifact()
    tasks = art["artifact"]["phases"][0]["tasks"]
    tasks[1]["dependencies"] = ["TASK-1.1", "TASK-1.3"]
    return run_case(full_files(art=art), False, "并行组")


@t("并行组内传递依赖被拦")
def _(x):
    art = artifact()
    # TASK-2.2 -> TASK-1.4 -> TASK-1.2:无直接边 2.2->1.2,经传递可达,却同组
    art["artifact"]["phases"][0]["tasks"][1]["parallel_group"] = "g2"
    art["artifact"]["phases"][1]["tasks"][1]["parallel_group"] = "g2"
    return run_case(full_files(art=art), False, "并行组")


@t("范围内工作项漏拆还判 PASS 被拦")
def _(x):
    art = artifact()
    art["artifact"]["inventory"].append(
        {"id": "INV-8", "kind": "module_capability", "title": "取消订单",
         "anchor": "module/output/M1/module-detail.md exposes", "in_scope": True})
    return run_case(full_files(art=art), False, "门禁未达标")


@t("漏拆判 REVISE 是合法评审")
def _(x):
    art = artifact()
    art["artifact"]["inventory"].append(
        {"id": "INV-8", "kind": "module_capability", "title": "取消订单",
         "anchor": "module/output/M1/module-detail.md exposes", "in_scope": True})
    return run_case(full_files(art=art, ver=verification(verdict="REVISE", pct=80.0)), True)


@t("门禁数字人工填报不符被拦")
def _(x):
    art = artifact()
    art["artifact"]["inventory"].append(
        {"id": "INV-8", "kind": "module_capability", "title": "取消订单",
         "anchor": "module/output/M1/module-detail.md exposes", "in_scope": True})
    return run_case(full_files(art=art, ver=verification(verdict="REVISE", pct=100.0)),
                    False, "不接受人工填写")


@t("漏拆任务改分母(撤工作项)无 DECISION 背书被拦")
def _(x):
    art2 = artifact()
    art2["artifact"]["inventory"].pop()  # 撤掉 INV-4
    art2["artifact"]["phases"][0]["tasks"][0]["implements"] = ["INV-3"]  # 落点同步撤
    files = full_files(extra={
        "iterations/02-artifact.json": art2,
        "iterations/02-verification.json": verification(),
    })
    files["state.json"]["artifacts"].append("02-artifact.json")
    files["state.json"]["iteration"] = 2
    return run_case(files, False, "R9")


@t("改分母有 DECISION 背书可过")
def _(x):
    art2 = artifact()
    art2["artifact"]["inventory"].pop()
    art2["artifact"]["phases"][0]["tasks"][0]["implements"] = ["INV-3"]
    art2["evidence"].append(
        {"claim": "migration 脚手架撤出本轮 inventory,用户拍板延后", "type": "DECISION",
         "evidence": "用户 2026-10-07 会话拍板", "confidence": "high"})
    files = full_files(extra={
        "iterations/02-artifact.json": art2,
        "iterations/02-verification.json": verification(),
    })
    files["state.json"]["artifacts"].append("02-artifact.json")
    files["state.json"]["iteration"] = 2
    return run_case(files, True)


@t("迭代间换溯源锚点无 DECISION 背书被拦")
def _(x):
    art2 = artifact()
    art2["artifact"]["inventory"][1]["anchor"] = "arch/output 架构总则"  # INV-2 锚点被换
    files = full_files(extra={
        "iterations/02-artifact.json": art2,
        "iterations/02-verification.json": verification(),
    })
    files["state.json"]["artifacts"].append("02-artifact.json")
    files["state.json"]["iteration"] = 2
    return run_case(files, False, "R9")


@t("换锚点有 DECISION 背书可过")
def _(x):
    art2 = artifact()
    art2["artifact"]["inventory"][1]["anchor"] = "arch/output 架构总则"
    art2["evidence"].append(
        {"claim": "INV-2 溯源锚点由契约 C3 修正为 arch 架构总则,用户拍板", "type": "DECISION",
         "evidence": "用户 2026-10-07 会话拍板", "confidence": "high"})
    files = full_files(extra={
        "iterations/02-artifact.json": art2,
        "iterations/02-verification.json": verification(),
    })
    files["state.json"]["artifacts"].append("02-artifact.json")
    files["state.json"]["iteration"] = 2
    return run_case(files, True)


@t("iterations 文件未登记被拦")
def _(x):
    art2 = artifact()
    files = full_files(extra={"iterations/02-artifact.json": art2})
    return run_case(files, False, "R10")


@t("登记的文件不存在被拦")
def _(x):
    files = full_files()
    files["state.json"]["artifacts"].append("02-artifact.json")
    return run_case(files, False, "R10")


@t("FACT 空 evidence 被拦")
def _(x):
    art = artifact()
    art["evidence"][0]["evidence"] = ""
    return run_case(full_files(art=art), False, "R1")


@t("blocked 缺 replan_reason 被拦")
def _(x):
    art = artifact()
    art["status"] = "blocked"
    return run_case(full_files(art=art), False, "R2")


@t("非 WAITING_FOR_INPUT 携带 resume_to 被拦")
def _(x):
    st = state()
    st["resume_to"] = "EXECUTING"
    return run_case(full_files(st=st), False, "R3")


@t("WAITING_FOR_INPUT 缺 resume_to 被拦")
def _(x):
    st = state(status="WAITING_FOR_INPUT")
    return run_case(full_files(st=st), False, "R3")


@t("WAITING_FOR_UPSTREAM 缺 upstream_gaps 被拦")
def _(x):
    st = state(status="WAITING_FOR_UPSTREAM")
    return run_case(full_files(st=st), False, "R4")


@t("常态携带 upstream_gaps 被拦")
def _(x):
    st = state()
    st["upstream_gaps"] = [{"what": "协议未定", "upstream_anchor": "arch §4", "blocks": "TASK-2.1"}]
    return run_case(full_files(st=st), False, "R4")


@t("任务 id 重复被拦")
def _(x):
    art = artifact()
    art["artifact"]["phases"][1]["tasks"][0]["id"] = "TASK-1.2"
    return run_case(full_files(art=art), False, "任务 id 重复")


@t("工作项 id 重复被拦")
def _(x):
    art = artifact()
    art["artifact"]["inventory"].append(copy.deepcopy(inventory()[0]))
    return run_case(full_files(art=art), False, "工作项 id 重复")


@t("范围外项无理由被拦")
def _(x):
    art = artifact()
    art["artifact"]["inventory"].append(
        {"id": "INV-9", "kind": "story", "title": "优惠券",
         "anchor": "decompose/output/catalog.md STORY-3.1", "in_scope": False, "note": " "})
    return run_case(full_files(art=art), False, "范围收缩必须留痕")


@t("阶段缺检查点被拦(schema)")
def _(x):
    art = artifact()
    del art["artifact"]["phases"][1]["checkpoint"]
    return run_case(full_files(art=art), False, "checkpoint")


@t("非 UTF-8 文件优雅报错")
def _(x):
    files = full_files()
    files["iterations/01-plan.json"] = b"\xff\xfe\x00bad"
    return run_case(files, False, "无法读取/解析")


@t("iterations 里未知文件名被拦")
def _(x):
    return run_case(full_files(extra={"iterations/01-notes.json": {"x": 1}}),
                    False, "不匹配任何产物类型")


@t("REVISE 中间态跳过数字比对可过")
def _(x):
    art = artifact()
    art["artifact"]["inventory"].append(
        {"id": "INV-8", "kind": "module_capability", "title": "取消订单",
         "anchor": "module/output/M1/module-detail.md exposes", "in_scope": True})
    st = state(status="EXECUTING")
    # 旧 verification 声称 100 与新 artifact(83.3)不符,但 EXECUTING 是修订中间态
    return run_case(full_files(st=st, art=art, ver=verification(verdict="REVISE", pct=100.0)), True)


@t("verification 缺同迭代 artifact 被拦")
def _(x):
    files = full_files()
    del files["iterations/01-artifact.json"]
    files["state.json"]["artifacts"] = []
    return run_case(files, False, "缺少同迭代")


@t("规模枚举外取值被拦(schema:XL 不存在)")
def _(x):
    art = artifact()
    art["artifact"]["phases"][0]["tasks"][1]["size"] = "XL"
    return run_case(full_files(art=art), False, "不在枚举")


@t("state 缺门槛上游被拦(schema)")
def _(x):
    st = state()
    del st["arch_source"]
    return run_case(full_files(st=st), False, "arch_source")


@t("state 层 FACT 空 evidence 被拦")
def _(x):
    st = state()
    st["evidence"] = [
        {"claim": "任务范围覆盖 M1 全部能力", "type": "FACT", "evidence": "", "confidence": "high"}]
    return run_case(full_files(st=st), False, "R1")


@t("review 模式 WAITING_FOR_INPUT 缺 resume_to 被拦")
def _(x):
    st = state(status="WAITING_FOR_INPUT", mode="review")
    return run_case(full_files(st=st), False, "R3")


@t("mode 枚举外取值被拦(schema)")
def _(x):
    st = state(mode="audit")
    return run_case(full_files(st=st), False, "不在枚举")


def main():
    failures = []
    for name, fn in TESTS:
        err = fn(None)
        if err:
            failures.append((name, err))
            print(f"FAIL {name}")
        else:
            print(f"ok   {name}")
    print(f"\n{len(TESTS) - len(failures)}/{len(TESTS)} 通过")
    if failures:
        for name, err in failures:
            print(f"\n=== {name} ===\n{err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
