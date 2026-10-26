"""incremental-implementation 反博弈回归测试(仅依赖 Python 标准库)。

每个用例构造一个临时 .pev 工程,断言 validate.py 的退出码与错误定位:
done 任务缺 commit/缺通过验证/验收漏条/未声明文件、deviation 缺理由、
registry 与上游任务集增删、覆盖不满还判 PASS、门禁数字人工填报不符、
改分母(删任务/放宽声明)无 DECISION 背书、登记册不符、空 evidence、
缺 replan_reason、状态门缺字段/多字段、基线 fail、failed 无 note,
都必须被拦下;干净产物(implement/audit/外部清单/带偏离/带延后/REVISE 中间态)
必须全绿通过;非 UTF-8 文件必须优雅报错而非崩溃。
"""

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
VALIDATE = SKILL / "scripts" / "validate.py"

SCORE_DIMS = ["coverage", "scope_discipline", "evidence_quality",
              "acceptance_alignment", "commit_discipline", "recoverability", "traceability"]

CRIT = {  # 上游三条任务的验收标准,registry 转录用同一份字面量
    "TASK-1.1": ["模型字段与 DDL 一一对应"],
    "TASK-1.2": ["201 返回订单体与契约 C3 一致", "空 title 返回 400"],
    "TASK-1.3": ["查询按创建时间倒序返回"],
}
FILES = {  # 上游三条任务的声明文件
    "TASK-1.1": ["src/orders/model.ts"],
    "TASK-1.2": ["src/orders/router.ts", "test/orders.test.ts"],
    "TASK-1.3": ["src/orders/query.ts"],
}


def upstream_artifact():
    """上游 tasks/ 结构化产物 fixture(planning-and-task-breakdown 的形状)。"""
    def t(tid, deps=()):
        return {"id": tid, "title": f"{tid} 实现",
                "description": "做什么、不做什么",
                "size": "S",
                "files_touched": FILES[tid],
                "acceptance_criteria": CRIT[tid],
                "verification": [{"how": "npm test", "kind": "test"}],
                "implements": ["INV-1"], "dependencies": list(deps),
                "trace": "arch/output 模块表 M1 行"}
    return {"status": "completed",
            "evidence": [{"claim": "c", "type": "FACT", "evidence": "arch §1", "confidence": "high"}],
            "artifact": {"inventory": [], "phases": [
                {"id": "PHASE-1", "title": "下单基础", "objective": "可下单",
                 "tasks": [t("TASK-1.1"), t("TASK-1.2", ("TASK-1.1",)), t("TASK-1.3")],
                 "checkpoint": {"checks": ["npm test 全绿"], "review_with_human": False}}]}}


def registry_entry(tid):
    return {"id": tid, "title": f"{tid} 实现",
            "files_touched": list(FILES[tid]),
            "acceptance_criteria": list(CRIT[tid]),
            "dependencies": [], "trace": f"tasks/iterations/01-artifact.json PHASE-1 {tid}"}


def record(tid, status="done", extra_files=(), deviate=False):
    rec = {
        "id": tid, "status": status,
        "commits": [tid.replace(".", "") + "a1b2c3d"],
        "files_changed": list(FILES[tid]) + list(extra_files),
        "tests": [{"how": "npm test -- --grep orders", "kind": "test", "result": "pass",
                   "evidence": "vitest 输出 'Tests: 8 passed (8)'"}],
        "acceptance_results": [
            {"criterion": c, "met": True,
             "evidence": f"test/orders.test.ts '@ {tid}' 通过"}
            for c in CRIT[tid]],
    }
    if deviate:
        rec["deviations"] = [{"path": extra_files[0],
                              "why": "路由挂载需登记一行,已批准(decisions#d1)"}]
    if status != "done":
        rec["note"] = "卡点与下一步说明"
    return rec


def artifact(records=None, registry=None):
    if records is None:
        records = [record("TASK-1.1"), record("TASK-1.2", extra_files=("src/middleware/auth.ts",), deviate=True),
                   record("TASK-1.3")]
    if registry is None:
        registry = [registry_entry(t) for t in ("TASK-1.1", "TASK-1.2", "TASK-1.3")]
    return {
        "status": "completed",
        "decisions": ["d1: TASK-1.2 偏离批准"],
        "evidence": [
            {"claim": "TASK-1.1 完成", "type": "FACT",
             "evidence": "commit a1b2c3d;npm test 输出 '8 passed'", "confidence": "high"},
            {"claim": "TASK-1.2 偏离经用户批准", "type": "DECISION",
             "evidence": "01-artifact decisions#d1", "confidence": "high"},
        ],
        "artifact": {
            "baseline": {"branch": "main", "commit": "e4f5a6b",
                         "checks": [{"what": "npm test", "result": "pass"},
                                    {"what": "npm run build", "result": "pass"}]},
            "task_registry": registry,
            "task_records": records,
        },
    }


def plan():
    return {
        "goal": "g", "understanding": "u", "known": [], "unknown": [], "assumptions": [],
        "plan": [{"id": "step_1", "objective": "o", "action": "survey_context",
                  "inputs": [], "expected_output": "e", "success_criteria": "s"}],
        "final_deliverable": "f", "stop_conditions": [],
    }


def state(status="VERIFYING", mode="implement", vcs="git"):
    return {
        "objective": {"goal": "test"},
        "plan_source": "tasks/output/task-plan.md",
        "aux_sources": [{"kind": "api_contract", "path": "api/output/D1/contracts.md"}],
        "vcs": vcs,
        "mode": mode,
        "status": status,
        "iteration": 1,
        "max_iterations": 5,
        "plans": ["01-plan.json"],
        "artifacts": ["01-artifact.json"],
        "evidence": [],
    }


def verification(verdict="PASS", pct=100.0, vio=0):
    return {
        "verdict": verdict,
        "scores": {d: 4 for d in SCORE_DIMS},
        "coverage": {"task_execution_pct": pct, "scope_violations": vio, "notes": ""},
        "strengths": [], "critical_issues": [], "warnings": [],
        "required_changes": [], "evidence_gaps": [], "confidence": "high",
    }


def run_case(files, expect_ok, expect_sub=None):
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = Path(tmp) / ".pev" / "prd-2026-10-07"
        for name, doc in files.items():
            path = round_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(doc, bytes):
                path.write_bytes(doc)
            else:
                path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(VALIDATE), str(round_dir / "impl")],
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


def full_files(st=None, art=None, ver=None, upstream=upstream_artifact(), extra=None):
    files = {
        "tasks/iterations/01-artifact.json": upstream,
        "impl/state.json": st if st is not None else state(),
        "impl/iterations/01-plan.json": plan(),
        "impl/iterations/01-artifact.json": art if art is not None else artifact(),
        "impl/iterations/01-verification.json": ver if ver is not None else verification(),
    }
    if upstream is None:
        del files["tasks/iterations/01-artifact.json"]
    if extra:
        files.update(extra)
    return files


def t(name):
    def deco(fn):
        TESTS.append((name, fn))
        return fn
    return deco


TESTS = []


@t("干净 implement 工程全绿(含偏离与上游对账)")
def _(x):
    return run_case(full_files(), True)


@t("干净 audit 工程全绿(mode=audit)")
def _(x):
    return run_case(full_files(st=state(mode="audit")), True)


@t("外部清单(无上游 tasks/)可过")
def _(x):
    return run_case(full_files(upstream=None), True)


@t("deferred 任务带理由可过")
def _(x):
    art = artifact()
    art["artifact"]["task_registry"][2]["deferred"] = True
    art["artifact"]["task_registry"][2]["note"] = "依赖后台服务未就绪,用户拍板延后"
    art["artifact"]["task_records"] = [record("TASK-1.1"),
                                       record("TASK-1.2", extra_files=("src/middleware/auth.ts",), deviate=True)]
    return run_case(full_files(art=art), True)


@t("deferred 任务无理由被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_registry"][2]["deferred"] = True
    art["artifact"]["task_records"] = [record("TASK-1.1"), record("TASK-1.2")]
    return run_case(full_files(art=art), False, "范围收缩必须留痕")


@t("done 任务无 commit 被拦(vcs=git)")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][0]["commits"] = []
    return run_case(full_files(art=art), False, "commit 证据")


@t("vcs=none 时无 commit 可过")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][0]["commits"] = []
    return run_case(full_files(st=state(vcs="none"), art=art), True)


@t("done 任务测试无 pass 项被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][0]["tests"][0]["result"] = "fail"
    return run_case(full_files(art=art), False, "result=pass")


@t("done 任务测试 evidence 空被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][0]["tests"][0]["evidence"] = ""
    return run_case(full_files(art=art), False, "全绿")


@t("验收对照缺一条被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][1]["acceptance_results"] = \
        art["artifact"]["task_records"][1]["acceptance_results"][:1]
    return run_case(full_files(art=art), False, "验收对照与 registry 验收标准集合不一致")


@t("done 验收 met=false 被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][0]["acceptance_results"][0]["met"] = False
    return run_case(full_files(art=art), False, "met=true")


@t("验收 evidence 空被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][0]["acceptance_results"][0]["evidence"] = " "
    return run_case(full_files(art=art), False, "空对照")


@t("未声明文件被拦(范围纪律)")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][0] = record("TASK-1.1", extra_files=("src/rogue.ts",))
    return run_case(full_files(art=art), False, "范围纪律")


@t("未声明文件有 deviation 可过")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][0] = record("TASK-1.1", extra_files=("src/types.ts",), deviate=True)
    return run_case(full_files(art=art), True)


@t("deviation 缺 why 被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][0] = record("TASK-1.1", extra_files=("src/types.ts",))
    art["artifact"]["task_records"][0]["deviations"] = [{"path": "src/types.ts", "why": ""}]
    return run_case(full_files(art=art), False, "偏离必须写明 why")


@t("registry 与上游任务集增删被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_registry"] = [registry_entry(t) for t in ("TASK-1.1", "TASK-1.2")]
    art["artifact"]["task_records"] = art["artifact"]["task_records"][:2]
    return run_case(full_files(art=art), False, "task_registry 与上游 tasks/ 任务集不一致")


@t("任务没做完还判 PASS 被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_records"] = art["artifact"]["task_records"][:2]
    return run_case(full_files(art=art), False, "门禁未达标")


@t("任务没做完判 REVISE 是合法评审")
def _(x):
    art = artifact()
    art["artifact"]["task_records"] = art["artifact"]["task_records"][:2]
    return run_case(full_files(art=art, ver=verification(verdict="REVISE", pct=66.7, vio=0)), True)


@t("覆盖率人工填报不符被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_records"] = art["artifact"]["task_records"][:2]
    return run_case(full_files(art=art, ver=verification(verdict="REVISE", pct=100.0, vio=0)),
                    False, "不接受人工填写")


@t("scope_violations 人工填报不符被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][0] = record("TASK-1.1", extra_files=("src/rogue.ts",))
    return run_case(full_files(art=art, ver=verification(verdict="REVISE", pct=100.0, vio=0)),
                    False, "不接受人工填写")


@t("scope_violations=0 但实际违规被拦(即便填报一致也不许 PASS)")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][0] = record("TASK-1.1", extra_files=("src/rogue.ts",))
    return run_case(full_files(art=art, ver=verification(verdict="PASS", pct=100.0, vio=0)),
                    False, "R8")


@t("删任务改分母无 DECISION 背书被拦")
def _(x):
    art2 = artifact()
    art2["artifact"]["task_registry"].pop()  # 撤 TASK-1.3
    art2["artifact"]["task_records"] = [record("TASK-1.1"),
                                        record("TASK-1.2", extra_files=("src/middleware/auth.ts",), deviate=True)]
    files = full_files(extra={
        "impl/iterations/02-artifact.json": art2,
        "impl/iterations/02-verification.json": verification(),
    })
    files["impl/state.json"]["artifacts"].append("02-artifact.json")
    files["impl/state.json"]["iteration"] = 2
    return run_case(files, False, "R9")


@t("改分母有 DECISION 背书可过(上游同步撤任务)")
def _(x):
    up2 = upstream_artifact()
    up2["artifact"]["phases"][0]["tasks"].pop()  # 上游 v2 撤了 TASK-1.3
    art2 = artifact()
    art2["artifact"]["task_registry"].pop()
    art2["artifact"]["task_records"] = [record("TASK-1.1"),
                                        record("TASK-1.2", extra_files=("src/middleware/auth.ts",), deviate=True)]
    art2["evidence"].append(
        {"claim": "TASK-1.3 撤出本轮 registry(上游清单 v2 已删该任务),用户拍板", "type": "DECISION",
         "evidence": "用户 2026-10-07 会话拍板", "confidence": "high"})
    files = full_files(extra={
        "tasks/iterations/02-artifact.json": up2,  # 上游 REPLAN,validate 取最新
        "impl/iterations/02-artifact.json": art2,
        "impl/iterations/02-verification.json": verification(),
    })
    files["impl/state.json"]["artifacts"].append("02-artifact.json")
    files["impl/state.json"]["iteration"] = 2
    return run_case(files, True)


@t("放宽声明范围(files_touched 偷偷加文件)无背书被拦")
def _(x):
    art2 = artifact()
    art2["artifact"]["task_registry"][0]["files_touched"].append("src/rogue.ts")
    art2["artifact"]["task_records"][0] = record("TASK-1.1", extra_files=("src/rogue.ts",))
    files = full_files(extra={
        "impl/iterations/02-artifact.json": art2,
        "impl/iterations/02-verification.json": verification(),
    })
    files["impl/state.json"]["artifacts"].append("02-artifact.json")
    files["impl/state.json"]["iteration"] = 2
    return run_case(files, False, "R9")


@t("iterations 文件未登记被拦")
def _(x):
    art2 = artifact()
    files = full_files(extra={"impl/iterations/02-artifact.json": art2})
    return run_case(files, False, "R10")


@t("登记的文件不存在被拦")
def _(x):
    files = full_files()
    files["impl/state.json"]["artifacts"].append("02-artifact.json")
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


@t("WAITING_FOR_INPUT 缺 resume_to 被拦")
def _(x):
    return run_case(full_files(st=state(status="WAITING_FOR_INPUT")), False, "R3")


@t("非 WAITING_FOR_INPUT 携带 resume_to 被拦")
def _(x):
    st = state()
    st["resume_to"] = "EXECUTING"
    return run_case(full_files(st=st), False, "R3")


@t("WAITING_FOR_UPSTREAM 缺 upstream_gaps 被拦")
def _(x):
    return run_case(full_files(st=state(status="WAITING_FOR_UPSTREAM")), False, "R4")


@t("常态携带 upstream_gaps 被拦")
def _(x):
    st = state()
    st["upstream_gaps"] = [{"what": "清单漏任务", "upstream_anchor": "tasks §2", "blocks": "TASK-2.1"}]
    return run_case(full_files(st=st), False, "R4")


@t("执行记录悬空(不在 registry)被拦")
def _(x):
    art = artifact()
    rogue = copy.deepcopy(art["artifact"]["task_records"][2])
    rogue["id"] = "TASK-9.9"
    art["artifact"]["task_records"].append(rogue)
    return run_case(full_files(art=art), False, "不在 task_registry")


@t("执行记录 id 重复被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][2] = record("TASK-1.1")
    return run_case(full_files(art=art), False, "执行记录 id 重复")


@t("registry id 重复被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_registry"].append(copy.deepcopy(registry_entry("TASK-1.1")))
    return run_case(full_files(art=art), False, "任务 id 重复")


@t("基线检查 fail 被拦")
def _(x):
    art = artifact()
    art["artifact"]["baseline"]["checks"][0]["result"] = "fail"
    return run_case(full_files(art=art), False, "基线检查未过")


@t("failed 任务无 note 被拦")
def _(x):
    art = artifact()
    art["artifact"]["task_records"][2] = record("TASK-1.3", status="failed")
    del art["artifact"]["task_records"][2]["note"]
    return run_case(full_files(art=art, ver=verification(verdict="REVISE", pct=66.7, vio=0)),
                    False, "note")


@t("非 UTF-8 文件优雅报错")
def _(x):
    files = full_files()
    files["impl/iterations/01-plan.json"] = b"\xff\xfe\x00bad"
    return run_case(files, False, "无法读取/解析")


@t("iterations 里未知文件名被拦")
def _(x):
    return run_case(full_files(extra={"impl/iterations/01-notes.json": {"x": 1}}),
                    False, "不匹配任何产物类型")


@t("REVISE 中间态跳过数字比对可过")
def _(x):
    art = artifact()
    art["artifact"]["task_records"] = art["artifact"]["task_records"][:2]
    st = state(status="EXECUTING")
    # 旧 verification 声称 100 与新 artifact(66.7)不符,但 EXECUTING 是修订中间态
    return run_case(full_files(st=st, art=art, ver=verification(verdict="REVISE", pct=100.0, vio=0)), True)


@t("verification 缺同迭代 artifact 被拦")
def _(x):
    files = full_files()
    del files["impl/iterations/01-artifact.json"]
    files["impl/state.json"]["artifacts"] = []
    return run_case(files, False, "缺少同迭代")


@t("上游结构化产物损坏被拦")
def _(x):
    files = full_files()
    files["tasks/iterations/01-artifact.json"] = b"{ not json"
    return run_case(files, False, "上游")


@t("vcs 枚举外取值被拦(schema)")
def _(x):
    return run_case(full_files(st=state(vcs="svn")), False, "不在枚举")


@t("state 缺门槛上游被拦(schema)")
def _(x):
    st = state()
    del st["plan_source"]
    return run_case(full_files(st=st), False, "plan_source")


@t("baseline 缺 checks 被拦(schema)")
def _(x):
    art = artifact()
    art["artifact"]["baseline"]["checks"] = []
    return run_case(full_files(art=art), False, "minItems")


@t("task_records 为空数组可过(尚未执行,早期状态)")
def _(x):
    art = artifact()
    art["artifact"]["task_records"] = []
    st = state(status="EXECUTING")
    return run_case(full_files(st=st, art=art, ver=verification(verdict="REVISE", pct=0.0, vio=0)), True)


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
