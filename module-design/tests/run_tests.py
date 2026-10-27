#!/usr/bin/env python3
"""module-design 反博弈回归测试(仅依赖 Python 标准库)。

针对 validate.py 的核心规则做最小冒烟:
  - 占位/未关闭措辞被拦截(R10)
  - DECISION 锚点伪造被拦截(R11)
  - finding 反向追溯的未声明上游条目被拦截(R12)
  - 适用红线未通过却判 PASS 被拦截(R13)
  - 新增架构外依赖被拦截(R5 边界守恒)
  - detail 缺 FMEA / brief 携带 FMEA 被拦截(R5)
  - 快照 exposes 未进分母被拦截(R7)
  - 交互承接替别人认领被拦截(R5)
  - module_reviews 缺模块 / REVISE 却整体 PASS 被拦截(R14)
  - Cross 未通过却整体 PASS 被拦截(R14)
  - 红线库缺失/损坏、报告缺红线部分、漏写库中一条均被拦截;
    报告逐条覆盖全库时通过(R13 全覆盖,consolidate T2-1)
  - 干净产物正常通过(无假阳性)

运行: python3 tests/run_tests.py
退出码: 0 = 全部通过;1 = 存在失败。
"""

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
VALIDATE = SKILL / "scripts" / "validate.py"

sys.path.insert(0, str(SKILL / "scripts"))
import validate as vd  # noqa: E402  单元级用例 patch 库路径用


def redline_entries(skip=()):
    """按真实红线库生成全覆盖条目(每条 applies=false);skip 指定漏写的 id。"""
    lib = json.loads((SKILL / "redlines" / "module-redlines.json")
                     .read_text(encoding="utf-8"))
    return [{"id": r["id"], "applies": False,
             "details": "不适用:本夹具为合成最小用例"}
            for r in lib["redlines"] if r["id"] not in skip]

ADV_DIMS = ["failure_modes", "consistency", "concurrency", "boundary_erosion",
            "hidden_coupling", "testability", "simpler_alternative"]
DFX_ALL = ["reliability", "testability", "maintainability", "observability", "security"]


def self_challenge():
    return [{"dimension": d, "finding": "", "disposition": "none"} for d in ADV_DIMS]


def plan():
    return {
        "goal": "g", "understanding": "u", "known": [], "unknown": [], "assumptions": [],
        "plan": [{"id": "step_1", "objective": "o", "action": "survey_architecture",
                  "inputs": [], "expected_output": "e", "success_criteria": "s"}],
        "final_deliverable": "f", "stop_conditions": [],
    }


def state(status="VERIFYING"):
    return {
        "objective": {"goal": "test"},
        "upstream_source": "arch/output/architecture.md",
        "upstream_kind": "architecture",
        "mode": "design",
        "status": status,
        "iteration": 1,
        "max_iterations": 5,
        "modules": [{"id": "M1", "design_mode": "detail", "design_status": "done",
                     "review_status": "pass"}],
        "cross": {"status": "passed"},
        "plans": ["01-plan.json"],
        "artifacts": ["01-artifact.json"],
        "evidence": [],
    }


def snapshot():
    return {
        "modules": [{
            "id": "M1", "name": "orders", "responsibility": "订单生命周期",
            "depends_on": ["M2"], "exposes": ["创建订单", "查询订单"],
            "owns_data": ["orders"],
        }],
        "interactions": [{"id": "I1", "scenario": "下单", "from": "M1", "to": "M2"}],
    }


def designed_module(**overrides):
    doc = {
        "id": "M1", "name": "orders", "design_mode": "detail",
        "responsibility": "订单生命周期(承接架构)", "not_responsible": [],
        "depends_on": ["M2"],
        "internal_components": [
            {"id": "M1-C1", "name": "lifecycle", "responsibility": "状态机管理",
             "hides": "状态转换规则与合法迁移表", "trace": "FACT 架构模块划分表 M1"},
        ],
        "core_flows": [
            {"id": "M1-F1", "name": "下单", "steps": "C1 校验→落库→发出事件",
             "failure_handling": "幂等键去重", "trace": "FACT 架构交互 I1"},
        ],
        "exposes_realization": [
            {"expose": "创建订单", "component_id": "M1-C1", "trace": "t"},
            {"expose": "查询订单", "component_id": "M1-C1", "trace": "t"},
        ],
        "owned_data_handling": [
            {"data": "orders", "handling": "状态机内单一写路径,逻辑级无表结构", "trace": "t"},
        ],
        "interaction_commitments": [
            {"interaction": "I1", "role": "发起方", "internal_handling": "C1 完成后调用 M2", "trace": "t"},
        ],
        "dfx": [{"x": x, "design": f"{x} 设计点:C1 内具体机制", "trace": "t"} for x in DFX_ALL],
        "fmea": [{"component_id": "M1-C1", "failure_mode": "依赖 M2 超时",
                  "effect": "下单卡住", "detection": "超时告警", "mitigation": "重试+幂等"}],
        "tradeoffs": [{"decision": "状态机 vs 自由状态字段", "choice": "状态机",
                       "rationale": "可校验", "cost": "新增迁移表维护", "alternative": "自由字段"}],
        "self_challenge": self_challenge(),
    }
    doc.update(overrides)
    return doc


def artifact(module=None, **overrides):
    mod = designed_module() if module is None else module
    doc = {
        "status": "completed",
        "evidence": [],
        "artifact": {
            "deliverable_kind": "module_designs",
            "input_summary": {
                "goal": "g",
                "target_modules": ["M1"],
                "architecture_snapshot": snapshot(),
                "upstream_items": [
                    {"id": "M1-R", "item": "订单生命周期", "anchor": "architecture.md 模块划分表 M1"},
                    {"id": "M1-E1", "item": "创建订单", "anchor": "architecture.md 模块划分表 M1 exposes"},
                    {"id": "M1-E2", "item": "查询订单", "anchor": "architecture.md 模块划分表 M1 exposes"},
                ],
            },
            "modules": [mod],
            "risks": [],
            "upstream_mapping": [
                {"upstream_item": "M1-R", "module_id": "M1", "trace": "t"},
                {"upstream_item": "M1-E1", "module_id": "M1", "trace": "t"},
                {"upstream_item": "M1-E2", "module_id": "M1", "trace": "t"},
            ],
            "downstream_deliverables": {},
        },
    }
    doc.update(overrides)
    return doc


def verification(verdict="PASS", **overrides):
    doc = {
        "verdict": verdict,
        "scores": {"architecture_conformance": 4, "internal_clarity": 4,
                   "information_hiding": 4, "tradeoff_honesty": 4,
                   "dfx_readiness": 4, "simplicity": 4, "traceability": 4},
        "module_reviews": [{"module_id": "M1", "verdict": "PASS",
                            "scores": {"architecture_conformance": 4, "internal_clarity": 4,
                                       "information_hiding": 4, "tradeoff_honesty": 4,
                                       "dfx_readiness": 4, "simplicity": 4, "traceability": 4},
                            "critical_issues": []}],
        "cross_review": {"verdict": "pass", "checked_interactions": ["I1"], "findings": []},
        "gates": {"modules_complete": True, "deps_within_architecture": True,
                  "upstream_mapped": True, "findings_disposed": True,
                  "cross_consistent": True, "notes": ""},
        "strengths": [], "critical_issues": [], "warnings": [],
        "required_changes": [], "evidence_gaps": [], "confidence": "high",
        "redlines": redline_entries(),
    }
    doc.update(overrides)
    return doc


def make_case(root, name):
    project = root / name
    module = project / ".pev" / "prd-1" / "module"
    (module / "iterations").mkdir(parents=True)
    return project, module


def write_files(module, state_doc, art_doc, ver_doc):
    (module / "state.json").write_text(json.dumps(state_doc), encoding="utf-8")
    (module / "iterations" / "01-plan.json").write_text(json.dumps(plan()), encoding="utf-8")
    (module / "iterations" / "01-artifact.json").write_text(json.dumps(art_doc), encoding="utf-8")
    (module / "iterations" / "01-verification.json").write_text(json.dumps(ver_doc), encoding="utf-8")


def run(module):
    proc = subprocess.run([sys.executable, str(VALIDATE), str(module)],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout


def check(name, module, want_pass, must_contain=None):
    code, out = run(module)
    ok = (code == 0) if want_pass else (code != 0)
    detail = ""
    if must_contain:
        hit = must_contain in out
        ok = ok and (hit if not want_pass else True)
        detail = f"(含 '{must_contain}': {'是' if hit else '否'})"
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} exit={code} {detail}")
    if not ok:
        print(f"        stdout: {out[:2000]}")
    return ok


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="module-review-") as tmp:
        root = Path(tmp)

        _, module = make_case(root, "t1")
        art = artifact()
        art["artifact"]["modules"][0]["responsibility"] = "待定"
        write_files(module, state(), art, verification("PASS"))
        results.append(check("T1 占位未关闭(R10)", module, False, "R10"))

        _, module = make_case(root, "t2")
        art = artifact(evidence=[{"claim": "user chose X", "type": "DECISION",
                                  "evidence": "01-artifact decisions#d99",
                                  "confidence": "high"}],
                       decisions=[])
        write_files(module, state(), art, verification("PASS"))
        results.append(check("T2 伪造 DECISION 锚点(R11)", module, False, "decisions#d99"))

        _, module = make_case(root, "t3")
        ver = verification("REVISE", findings=[{
            "id": "F1", "severity": "HIGH", "what": "w", "why": "y",
            "what_must_change": "c", "affected_upstream_items": ["M1-E9"],
            "dimension": "information_hiding",
        }])
        write_files(module, state(), artifact(), ver)
        results.append(check("T3 finding 未声明上游(R12)", module, False, "R12"))

        _, module = make_case(root, "t4")
        ver = verification("PASS", redlines=[{
            "id": "RED-01", "applies": True, "passed": False, "details": "M1 偷读 M2 的表",
        }])
        write_files(module, state(), artifact(), ver)
        results.append(check("T4 红线未过判 PASS(R13)", module, False, "R13"))

        _, module = make_case(root, "t5")
        mod = designed_module()
        mod["depends_on"] = ["M2", "M3"]  # M3 不在架构声明里
        write_files(module, state(), artifact(mod), verification("REVISE"))
        results.append(check("T5 新增架构外依赖(R5 守恒)", module, False, "架构声明外的依赖"))

        _, module = make_case(root, "t6")
        mod = designed_module()
        mod["fmea"] = []  # detail 却无 FMEA
        write_files(module, state(), artifact(mod), verification("REVISE"))
        results.append(check("T6 detail 缺 FMEA(R5)", module, False, "FMEA"))

        _, module = make_case(root, "t7")
        art = artifact()
        # 快照有两条 exposes,分母只声明一条
        art["artifact"]["input_summary"]["upstream_items"] = [
            {"id": "M1-R", "item": "订单生命周期", "anchor": "a"},
            {"id": "M1-E1", "item": "创建订单", "anchor": "a"},
        ]
        art["artifact"]["upstream_mapping"] = [
            {"upstream_item": "M1-R", "module_id": "M1", "trace": "t"},
            {"upstream_item": "M1-E1", "module_id": "M1", "trace": "t"},
        ]
        write_files(module, state(), art, verification("REVISE"))
        results.append(check("T7 exposes 未进分母(R7)", module, False, "分母不全"))

        _, module = make_case(root, "t8")
        # M2 设计里替 M1 认领交互(用一个 M2 模块设计构造)
        art = artifact()
        art["artifact"]["input_summary"]["target_modules"] = ["M1"]
        art["artifact"]["modules"][0]["interaction_commitments"] = [
            {"interaction": "I1", "role": "发起方", "internal_handling": "x"}]
        # 快照交互 I1 是 M1→M2,M1 是参与方;改成一个 M1 不参与的交互来触发
        art["artifact"]["input_summary"]["architecture_snapshot"]["interactions"] = [
            {"id": "I1", "scenario": "支付回调", "from": "M2", "to": "M3"}]
        write_files(module, state(), art, verification("REVISE"))
        results.append(check("T8 替别人认领交互(R5)", module, False, "参与方"))

        _, module = make_case(root, "t9")
        ver = verification("PASS")
        ver["module_reviews"] = []  # 缺 M1 评审
        write_files(module, state(), artifact(), ver)
        results.append(check("T9 module_reviews 缺模块(R14)", module, False, "R14"))

        _, module = make_case(root, "t10")
        ver = verification("PASS")
        ver["cross_review"] = {"verdict": "revise", "checked_interactions": [], "findings": [{
            "id": "X1", "severity": "HIGH", "what": "w", "why": "y",
            "what_must_change": "c", "affected_modules": ["M1"]}]}
        write_files(module, state(), artifact(), ver)
        results.append(check("T10 Cross 未过判 PASS(R14)", module, False, "R14"))

        _, module = make_case(root, "t11")
        write_files(module, state(), artifact(), verification("PASS"))
        results.append(check("T11 干净产物通过", module, True))

        project, module = make_case(root, "t12")
        (project / "arch.md").write_text("M1 owns orders and exposes 创建订单", encoding="utf-8")
        excerpt = "M1 owns orders"
        art = artifact(evidence=[{"claim": "架构声明 M1 拥有 orders", "type": "FACT",
                                  "evidence": "arch.md 模块划分表", "confidence": "high",
                                  "source": {"path": "arch.md", "excerpt": excerpt,
                                             "digest": "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest()}}])
        write_files(module, state(), art, verification("PASS"))
        results.append(check("T12 新鲜证据来源通过", module, True))

        _, module = make_case(root, "t15")
        ver = verification("PASS")
        ver["redlines"] = []  # 报告缺红线部分
        write_files(module, state(), artifact(), ver)
        results.append(check("T15 报告缺红线部分被拦截(R13)", module, False,
                             "缺少红线部分"))

        _, module = make_case(root, "t16")
        ver = verification("PASS", redlines=redline_entries(skip={"RED-05"}))
        write_files(module, state(), artifact(), ver)
        results.append(check("T16 漏写库中一条红线被拦截(R13)", module, False,
                             "RED-05"))

        _, module = make_case(root, "t19")
        write_files(module, state("COMPLETE"), artifact(), verification("PASS"))
        results.append(check("T19 COMPLETE 缺用户确认被拦截(R15)", module, False,
                             "user_confirmation"))

        _, module = make_case(root, "t20")
        st = state("COMPLETE")
        st["user_confirmation"] = {"date": "2026-10-27"}
        write_files(module, st, artifact(), verification("PASS"))
        results.append(check("T20 COMPLETE 带确认记录通过(R15)", module, True))

        # 单元级:红线库缺失/损坏时 check_redlines 必须拒绝(不静默放过)
        def unit_library_case(label, redlines_dir):
            saved = vd.REDLINES_DIR
            vd.REDLINES_DIR = redlines_dir
            try:
                errs = vd.Errors()
                vd.check_redlines(verification("PASS"),
                                  "iterations/01-verification.json", errs)
                hit = any("红线库" in getattr(e, "message", str(e))
                          for e in errs.items)
            finally:
                vd.REDLINES_DIR = saved
            ok = bool(len(errs)) and hit
            print(f"  [{'PASS' if ok else 'FAIL'}] {label} "
                  f"errors={len(errs)}")
            if not ok:
                for e in errs.items:
                    print(f"        {getattr(e, 'message', e)}")
            return ok

        results.append(unit_library_case(
            "T17 红线库缺失被拦截(R13)", root / "no-such-redlines"))
        broken = root / "broken-redlines"
        broken.mkdir()
        (broken / "module-redlines.json").write_text("{not json",
                                                     encoding="utf-8")
        results.append(unit_library_case(
            "T18 红线库损坏被拦截(R13)", broken))

    print()
    passed = sum(results)
    print(f"{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
