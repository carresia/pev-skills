#!/usr/bin/env python3
"""architecture-design 反博弈回归测试(仅依赖 Python 标准库)。

针对 validate.py 的 R10/R11/R12/R13 做最小冒烟:
  - 占位/未关闭措辞被拦截(R10)
  - DECISION 锚点与 source 回读新鲜度被拦截(R11)
  - finding 反向追溯的未声明上游条目被拦截(R12)
  - 适用红线未通过却判 PASS 被拦截(R13)
  - 干净产物与新鲜 source 正常通过(无假阳性)

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

ADV_DIMS = ["failure_modes", "consistency", "concurrency", "boundary_erosion",
            "migration_rollback", "scale_cliff", "simpler_alternative"]

STYLE = {
    "choice": "modular monolith",
    "rationale": "single team, simple",
    "rejected_simpler": "script",
    "rejected_complexer": "microservices",
}


def self_challenge():
    return [{"dimension": d, "finding": "", "disposition": "none"} for d in ADV_DIMS]


def plan():
    return {
        "goal": "g", "understanding": "u", "known": [], "unknown": [], "assumptions": [],
        "plan": [{"id": "step_1", "objective": "o", "action": "survey_upstream",
                  "inputs": [], "expected_output": "e", "success_criteria": "s"}],
        "final_deliverable": "f", "stop_conditions": [],
    }


def state(status="VERIFYING", mode="design"):
    return {
        "objective": {"goal": "test"},
        "upstream_source": "catalog.md",
        "upstream_kind": "catalog",
        "mode": mode,
        "status": status,
        "iteration": 1,
        "max_iterations": 5,
        "plans": ["01-plan.json"],
        "artifacts": ["01-artifact.json"],
        "evidence": [],
    }


def artifact(**overrides):
    doc = {
        "status": "completed",
        "evidence": [],
        "artifact": {
            "deliverable_kind": "architecture",
            "input_summary": {"upstream_items": [
                {"id": "U1", "item": "feature", "anchor": "catalog.md §E1"},
            ]},
            "style": dict(STYLE),
            "modules": [{"id": "M1", "name": "core", "responsibility": "owns orders",
                         "depends_on": [], "owns_data": ["orders"]}],
            "data_ownership": [{"data": "orders", "owner": "M1",
                                "writers": ["M1"], "readers": []}],
            "tradeoffs": [{"decision": "sync vs async", "choice": "sync",
                           "rationale": "simpler", "cost": "latency", "alternative": "async"}],
            "self_challenge": self_challenge(),
            "upstream_mapping": [{"upstream_item": "U1", "module_id": "M1", "trace": "trace"}],
        },
    }
    doc.update(overrides)
    return doc


def verification(verdict="PASS", **overrides):
    doc = {
        "verdict": verdict,
        "scores": {"upstream_coverage": 4, "boundary_clarity": 4, "ownership": 4,
                   "tradeoff_honesty": 4, "failure_readiness": 4, "simplicity": 4,
                   "traceability": 4},
        "gates": {"dependency_acyclic": True, "unique_owners": True,
                  "upstream_mapped": True, "findings_disposed": True, "notes": ""},
        "strengths": [], "critical_issues": [], "warnings": [],
        "required_changes": [], "evidence_gaps": [], "confidence": "high",
    }
    doc.update(overrides)
    return doc


def make_case(root, name):
    project = root / name
    arch = project / ".pev" / "prd-1" / "arch"
    (arch / "iterations").mkdir(parents=True)
    return project, arch


def write_files(arch, state_doc, art_doc, ver_doc):
    (arch / "state.json").write_text(json.dumps(state_doc), encoding="utf-8")
    (arch / "iterations" / "01-plan.json").write_text(json.dumps(plan()), encoding="utf-8")
    (arch / "iterations" / "01-artifact.json").write_text(json.dumps(art_doc), encoding="utf-8")
    (arch / "iterations" / "01-verification.json").write_text(json.dumps(ver_doc), encoding="utf-8")


def run(arch):
    proc = subprocess.run([sys.executable, str(VALIDATE), str(arch)],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout


def check(name, arch, want_pass, must_contain=None):
    code, out = run(arch)
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


def sha256_digest(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="arch-review-") as tmp:
        root = Path(tmp)

        _, arch = make_case(root, "t1")
        art = artifact()
        art["artifact"]["style"]["rationale"] = "待定"
        art["artifact"]["tradeoffs"][0]["cost"] = "待确认"
        write_files(arch, state(), art, verification("PASS"))
        results.append(check("T1 占位未关闭(R10)", arch, False, "R10"))

        _, arch = make_case(root, "t2")
        art = artifact(evidence=[{"claim": "user chose X", "type": "DECISION",
                                  "evidence": "01-artifact decisions#d99",
                                  "confidence": "high"}],
                       decisions=[])
        write_files(arch, state(), art, verification("PASS"))
        results.append(check("T2 伪造 DECISION 锚点(R11)", arch, False, "decisions#d99"))

        project, arch = make_case(root, "t3")
        (project / "spec.md").write_text("upstream requires 100k DAU", encoding="utf-8")
        art = artifact(evidence=[{"claim": "upstream 100k DAU", "type": "FACT",
                                  "evidence": "spec.md §7", "confidence": "high",
                                  "source": {"path": "spec.md", "excerpt": "999k DAU"}}])
        write_files(arch, state(), art, verification("PASS"))
        results.append(check("T3 陈旧证据来源(R11)", arch, False, "excerpt 不在来源文件中"))

        _, arch = make_case(root, "t4")
        ver = verification("REVISE", findings=[{
            "id": "F1", "severity": "HIGH", "what": "w", "why": "y",
            "what_must_change": "c", "affected_upstream_items": ["U9"],
            "dimension": "ownership",
        }])
        write_files(arch, state(), artifact(), ver)
        results.append(check("T4 finding 未声明上游(R12)", arch, False, "R12"))

        _, arch = make_case(root, "t5")
        ver = verification("PASS", redlines=[{
            "id": "RED-02", "applies": True, "passed": False, "details": "orders 双写无 owner",
        }])
        write_files(arch, state(), artifact(), ver)
        results.append(check("T5 红线未过判 PASS(R13)", arch, False, "R13"))

        _, arch = make_case(root, "t6")
        write_files(arch, state(), artifact(), verification("PASS"))
        results.append(check("T6 干净产物通过", arch, True))

        project, arch = make_case(root, "t7")
        (project / "spec.md").write_text("upstream requires 100k DAU", encoding="utf-8")
        excerpt = "100k DAU"
        art = artifact(evidence=[{"claim": "upstream 100k DAU", "type": "FACT",
                                  "evidence": "spec.md §7", "confidence": "high",
                                  "source": {"path": "spec.md", "excerpt": excerpt,
                                             "digest": sha256_digest(excerpt)}}])
        write_files(arch, state(), art, verification("PASS"))
        results.append(check("T7 新鲜证据来源通过", arch, True))

        _, arch = make_case(root, "t8")
        st = state("COMPLETE")  # PASS 已渲染但用户未确认
        write_files(arch, st, artifact(), verification("PASS"))
        results.append(check("T8 COMPLETE 缺用户确认被拦截", arch, False,
                             "user_confirmation"))

        _, arch = make_case(root, "t9")
        st = state("COMPLETE")
        st["user_confirmation"] = {"date": "2026-10-27", "note": "用户看过并确认"}
        write_files(arch, st, artifact(), verification("PASS"))
        results.append(check("T9 COMPLETE 带确认记录通过", arch, True))

    print()
    passed = sum(results)
    print(f"{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
