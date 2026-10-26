"""api-and-interface-design 反博弈回归测试(仅依赖 Python 标准库)。

每个用例构造一个临时 .pev 工程,断言 validate.py 的退出码与错误定位:
伪造的 DECISION 锚点、占位未关闭、越界能力、分母造假、替别人认领交互、
brief 携带完整 schema、门禁人工填报不符、红线未过判 PASS、红线漏条/重复等,都必须被拦下;
空 evidence、缺 replan_reason、状态门缺字段、登记册不符、自查缺维/无理由/
空代价、契约面 id 重复、VERIFYING 缺 cross、state 与产物各说各话
(mode/面集/deliverable_kind/评审状态不同步)也必须被拦下;非 UTF-8 文件
必须优雅报错而非崩溃;干净产物必须全绿通过。
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
            "misuse_potential", "compatibility", "simpler_alternative"]

REDLINE_IDS = ["RED-01", "RED-02", "RED-03", "RED-04", "RED-05"]


def redlines_ok():
    return [{"id": rid, "applies": True, "passed": True, "details": "检查通过"}
            for rid in REDLINE_IDS]


def self_challenge():
    return [{"dimension": d, "finding": "", "disposition": "none"} for d in ADV_DIMS]


def plan():
    return {
        "goal": "g", "understanding": "u", "known": [], "unknown": [], "assumptions": [],
        "plan": [{"id": "step_1", "objective": "o", "action": "survey_upstream",
                  "inputs": [], "expected_output": "e", "success_criteria": "s"}],
        "final_deliverable": "f", "stop_conditions": [],
    }


def state(status="VERIFYING"):
    return {
        "objective": {"goal": "test"},
        "upstream_source": "module/output/M1/module-detail.md",
        "upstream_kind": "module_design",
        "mode": "design",
        "status": status,
        "iteration": 1,
        "max_iterations": 5,
        "contracts": [{"id": "C1", "kind": "rest", "depth": "detail",
                       "design_status": "done", "review_status": "pass"}],
        "cross": {"status": "passed"},
        "plans": ["01-plan.json"],
        "artifacts": ["01-artifact.json"],
        "evidence": [],
    }


def snapshot():
    return {
        "modules": [{
            "id": "M1", "name": "orders", "exposes": ["创建订单", "查询订单"],
            "owns_data": ["orders"],
        }],
        "interactions": [{"id": "I1", "scenario": "用户下单", "from": "external:web",
                          "to": "M1", "mode": "sync-call", "idempotency": "required"}],
    }


def designed_contract(**overrides):
    doc = {
        "id": "C1", "name": "订单对外 REST API", "kind": "rest", "depth": "detail",
        "owner_module": "M1",
        "covered_capabilities": ["创建订单", "查询订单"],
        "operations": [
            {"id": "C1-O1", "name": "POST /api/v1/orders", "purpose": "创建订单",
             "capability": "创建订单",
             "request": "{title, description?}", "response": "{id, title, status}",
             "errors": ["422 VALIDATION_ERROR", "409 DUPLICATE"],
             "idempotency": "Idempotency-Key header 去重", "trace": "FACT module M1 exposes"},
            {"id": "C1-O2", "name": "GET /api/v1/orders", "purpose": "查询订单列表",
             "capability": "查询订单",
             "request": "?page&pageSize&status", "response": "{data[], pagination}",
             "errors": [], "pagination": "page/pageSize/totalItems",
             "trace": "FACT module M1 exposes"},
        ],
        "interaction_commitments": [
            {"interaction": "I1", "role": "接收方", "contract_handling": "C1-O1 承接用户下单",
             "trace": "FACT arch 交互 I1"},
        ],
        "error_model": {"strategy": "HTTP 状态码 + 结构化错误体",
                        "codes": ["VALIDATION_ERROR", "DUPLICATE", "NOT_FOUND"],
                        "example": "{\"error\": {\"code\": \"DUPLICATE\", \"message\": \"...\"}}"},
        "versioning": {"strategy": "URL 路径版本 /v1,加法优先(One-Version)",
                       "compat_rules": "删字段/改类型/改语义=破坏性变更,须先弃用一个版本周期"},
        "tradeoffs": [{"decision": "路径版本 vs header 版本", "choice": "路径版本",
                       "rationale": "可见可调试", "cost": "URL 膨胀,跨版本链接断",
                       "alternative": "header 版本"}],
        "self_challenge": self_challenge(),
    }
    doc.update(overrides)
    return doc


def artifact(contract=None, **overrides):
    con = designed_contract() if contract is None else contract
    doc = {
        "status": "completed",
        "evidence": [],
        "artifact": {
            "deliverable_kind": "api_contracts",
            "input_summary": {
                "goal": "g",
                "target_contracts": ["C1"],
                "upstream_snapshot": snapshot(),
                "upstream_items": [
                    {"id": "M1-E1", "item": "创建订单", "anchor": "module/output/M1/ 下游交付物节"},
                    {"id": "M1-E2", "item": "查询订单", "anchor": "module/output/M1/ 下游交付物节"},
                    {"id": "I1", "item": "用户下单", "anchor": "arch 关键交互表 I1 行"},
                ],
            },
            "contracts": [con],
            "risks": [],
            "upstream_mapping": [
                {"upstream_item": "M1-E1", "contract_id": "C1", "trace": "t"},
                {"upstream_item": "M1-E2", "contract_id": "C1", "trace": "t"},
                {"upstream_item": "I1", "contract_id": "C1", "trace": "t"},
            ],
            "downstream_deliverables": {},
        },
    }
    doc.update(overrides)
    return doc


def verification(verdict="PASS", **overrides):
    scores = {"upstream_conformance": 4, "contract_clarity": 4, "consistency": 4,
              "compatibility": 4, "tradeoff_honesty": 4, "simplicity": 4, "traceability": 4}
    doc = {
        "verdict": verdict,
        "scores": dict(scores),
        "contract_reviews": [{"contract_id": "C1", "verdict": "PASS",
                              "scores": dict(scores), "critical_issues": []}],
        "cross_review": {"verdict": "pass", "checked_items": ["错误语义统一"], "findings": []},
        "gates": {"contracts_complete": True, "capabilities_within_upstream": True,
                  "upstream_mapped": True, "findings_disposed": True,
                  "cross_consistent": True, "notes": ""},
        "redlines": redlines_ok(),
        "strengths": [], "critical_issues": [], "warnings": [],
        "required_changes": [], "evidence_gaps": [], "confidence": "high",
    }
    doc.update(overrides)
    return doc


def review_state(status="VERIFYING"):
    st = state(status)
    st.update({
        "mode": "review",
        "upstream_kind": "contract_doc",
        "upstream_source": "contract.md",
        "contracts": [],
    })
    return st


def review_artifact(**overrides):
    findings = [
        {"id": "F1", "dimension": "failure_modes", "finding": "错误模型未落到 code 表",
         "severity": "HIGH", "evidence_anchor": "§3 错误语义", "recommendation": "补 code 表"},
    ]
    findings += [{"dimension": d, "finding": "", "severity": "NONE"}
                 for d in ADV_DIMS if d != "failure_modes"]
    doc = {
        "status": "completed",
        "evidence": [],
        "artifact": {
            "deliverable_kind": "api_review",
            "input_summary": {"goal": "review", "target_contracts": []},
            "review_findings": findings,
        },
    }
    doc.update(overrides)
    return doc


def review_verification(verdict="PASS", **overrides):
    scores = {"upstream_conformance": 4, "contract_clarity": 4, "consistency": 4,
              "compatibility": 4, "tradeoff_honesty": 4, "simplicity": 4, "traceability": 4}
    doc = {
        "verdict": verdict,
        "scores": dict(scores),
        "contract_reviews": [],
        "cross_review": {"verdict": "pass", "checked_items": [], "findings": []},
        "gates": {"contracts_complete": True, "capabilities_within_upstream": True,
                  "upstream_mapped": True, "findings_disposed": True,
                  "cross_consistent": True, "notes": ""},
        "redlines": redlines_ok(),
        "strengths": [], "critical_issues": [], "warnings": [],
        "required_changes": [], "evidence_gaps": [], "confidence": "high",
    }
    doc.update(overrides)
    return doc


def make_case(root, name):
    project = root / name
    api = project / ".pev" / "prd-1" / "api"
    (api / "iterations").mkdir(parents=True)
    return project, api


def write_files(api, state_doc, art_doc, ver_doc):
    (api / "state.json").write_text(json.dumps(state_doc), encoding="utf-8")
    (api / "iterations" / "01-plan.json").write_text(json.dumps(plan()), encoding="utf-8")
    (api / "iterations" / "01-artifact.json").write_text(json.dumps(art_doc), encoding="utf-8")
    (api / "iterations" / "01-verification.json").write_text(json.dumps(ver_doc), encoding="utf-8")


def run(api):
    proc = subprocess.run([sys.executable, str(VALIDATE), str(api)],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout


def check(name, api, want_pass, must_contain=None):
    code, out = run(api)
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
    with tempfile.TemporaryDirectory(prefix="api-review-") as tmp:
        root = Path(tmp)

        _, api = make_case(root, "t1")
        art = artifact()
        art["artifact"]["contracts"][0]["operations"][0]["purpose"] = "待定"
        write_files(api, state(), art, verification("PASS"))
        results.append(check("T1 占位未关闭(R10)", api, False, "R10"))

        _, api = make_case(root, "t2")
        art = artifact(evidence=[{"claim": "user chose X", "type": "DECISION",
                                  "evidence": "01-artifact decisions#d99",
                                  "confidence": "high"}],
                       decisions=[])
        write_files(api, state(), art, verification("PASS"))
        results.append(check("T2 伪造 DECISION 锚点(R11)", api, False, "decisions#d99"))

        _, api = make_case(root, "t3")
        ver = verification("REVISE", findings=[{
            "id": "F1", "severity": "HIGH", "what": "w", "why": "y",
            "what_must_change": "c", "affected_upstream_items": ["M1-E9"],
            "dimension": "misuse_potential",
        }])
        write_files(api, state(), artifact(), ver)
        results.append(check("T3 finding 未声明上游(R12)", api, False, "R12"))

        _, api = make_case(root, "t4")
        ver = verification("PASS", redlines=[{
            "id": "RED-01", "applies": True, "passed": False, "details": "契约含未声明端点",
        }])
        write_files(api, state(), artifact(), ver)
        results.append(check("T4 红线未过判 PASS(R13)", api, False, "R13"))

        _, api = make_case(root, "t5")
        con = designed_contract()
        con["covered_capabilities"] = ["创建订单", "查询订单", "删除订单"]
        write_files(api, state(), artifact(con), verification("REVISE"))
        results.append(check("T5 承接上游声明外能力(R5 守恒)", api, False, "上游声明外的能力"))

        _, api = make_case(root, "t6")
        con = designed_contract()
        del con["error_model"]  # detail 却无错误模型
        write_files(api, state(), artifact(con), verification("REVISE"))
        results.append(check("T6 detail 缺错误模型(R5)", api, False, "error_model"))

        _, api = make_case(root, "t7")
        art = artifact()
        # 快照有两条 exposes,分母只声明一条
        art["artifact"]["input_summary"]["upstream_items"] = [
            {"id": "M1-E1", "item": "创建订单", "anchor": "a"},
            {"id": "I1", "item": "用户下单", "anchor": "a"},
        ]
        art["artifact"]["upstream_mapping"] = [
            {"upstream_item": "M1-E1", "contract_id": "C1", "trace": "t"},
            {"upstream_item": "I1", "contract_id": "C1", "trace": "t"},
        ]
        write_files(api, state(), art, verification("REVISE"))
        results.append(check("T7 承接能力未进分母(R7)", api, False, "分母不全"))

        _, api = make_case(root, "t8")
        art = artifact()
        # 快照交互 I1 改为 M2→M3,C1(owner M1)却认领它
        art["artifact"]["input_summary"]["upstream_snapshot"]["interactions"] = [
            {"id": "I1", "scenario": "支付回调", "from": "M2", "to": "M3"}]
        write_files(api, state(), art, verification("REVISE"))
        results.append(check("T8 替别人认领交互(R5)", api, False, "参与方"))

        _, api = make_case(root, "t9")
        ver = verification("PASS")
        ver["contract_reviews"] = []  # 缺 C1 评审
        write_files(api, state(), artifact(), ver)
        results.append(check("T9 contract_reviews 缺契约面(R14)", api, False, "R14"))

        _, api = make_case(root, "t10")
        ver = verification("PASS")
        ver["cross_review"] = {"verdict": "revise", "checked_items": [], "findings": [{
            "id": "X1", "severity": "HIGH", "what": "w", "why": "y",
            "what_must_change": "c", "affected_contracts": ["C1"]}]}
        write_files(api, state(), artifact(), ver)
        results.append(check("T10 Cross 未过判 PASS(R14)", api, False, "R14"))

        _, api = make_case(root, "t11")
        write_files(api, state(), artifact(), verification("PASS"))
        results.append(check("T11 干净产物通过(detail)", api, True))

        _, api = make_case(root, "t11b")
        con = designed_contract()
        con["depth"] = "brief"
        for o in con["operations"]:
            o["request"] = ""
            o["response"] = ""
        del con["error_model"]
        del con["versioning"]
        st = state()
        st["contracts"][0]["depth"] = "brief"
        write_files(api, st, artifact(con), verification("PASS"))
        results.append(check("T11b 干净产物通过(brief)", api, True))

        _, api = make_case(root, "t12")
        con = designed_contract()
        con["depth"] = "brief"  # brief 却带完整 schema
        write_files(api, state(), artifact(con), verification("REVISE"))
        results.append(check("T12 brief 携带完整 schema(R5)", api, False, "brief 模式"))

        _, api = make_case(root, "t13")
        ver = verification("PASS")
        ver["gates"]["upstream_mapped"] = False  # 人工填报,与脚本计算不符
        write_files(api, state(), artifact(), ver)
        results.append(check("T13 门禁人工填报不符(R6)", api, False, "R6"))

        project, api = make_case(root, "t14")
        (project / "module.md").write_text("M1 exposes 创建订单 and 参与交互 I1", encoding="utf-8")
        excerpt = "M1 exposes 创建订单"
        art = artifact(evidence=[{"claim": "上游声明 M1 暴露创建订单", "type": "FACT",
                                  "evidence": "module.md 下游交付物节", "confidence": "high",
                                  "source": {"path": "module.md", "excerpt": excerpt,
                                             "digest": "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest()}}])
        write_files(api, state(), art, verification("PASS"))
        results.append(check("T14 新鲜证据来源通过", api, True))

        # review 模式回归
        _, api = make_case(root, "t15")
        write_files(api, review_state(), review_artifact(), review_verification("PASS"))
        results.append(check("T15 review 干净产物通过", api, True))

        _, api = make_case(root, "t16")
        art = review_artifact()
        art["artifact"]["review_findings"] = [
            f for f in art["artifact"]["review_findings"]
            if f.get("dimension") != "consistency"
        ]
        write_files(api, review_state(), art, review_verification("REVISE"))
        results.append(check("T16 review 缺维度(R8)", api, False, "评审缺少维度"))

        _, api = make_case(root, "t17")
        art = review_artifact()
        for f in art["artifact"]["review_findings"]:
            if f.get("finding"):
                f["evidence_anchor"] = ""
        write_files(api, review_state(), art, review_verification("REVISE"))
        results.append(check("T17 review 非空 finding 缺锚点(R8)", api, False, "evidence_anchor"))

        # R1-R4 / R9 / design 侧 R8 / 契约面 id 唯一 / cross 必备
        _, api = make_case(root, "t18")
        art = artifact(evidence=[
            {"claim": "上游声明", "type": "FACT", "evidence": None, "confidence": "high"},
            {"claim": "用户拍板", "type": "DECISION", "evidence": "  ", "confidence": "high"}])
        write_files(api, state(), art, verification("REVISE"))
        results.append(check("T18 FACT/DECISION 空 evidence(R1)", api, False, "R1"))

        _, api = make_case(root, "t19")
        write_files(api, state(), artifact(status="replan_required"), verification("REVISE"))
        results.append(check("T19 replan_required 缺 replan_reason(R2)", api, False, "R2"))

        _, api = make_case(root, "t20")
        write_files(api, state("WAITING_FOR_INPUT"), artifact(), verification("REVISE"))
        results.append(check("T20 WAITING_FOR_INPUT 缺 resume_to(R3)", api, False, "R3"))

        _, api = make_case(root, "t21")
        write_files(api, state("WAITING_FOR_UPSTREAM"), artifact(), verification("REVISE"))
        results.append(check("T21 WAITING_FOR_UPSTREAM 缺 upstream_gaps(R4)", api, False, "R4"))

        _, api = make_case(root, "t22")
        st = state()
        st["artifacts"] = ["01-artifact.json", "02-artifact.json"]  # 02 不存在
        write_files(api, st, artifact(), verification("REVISE"))
        results.append(check("T22 登记册与目录不一致(R9)", api, False, "R9"))

        _, api = make_case(root, "t23")
        con = designed_contract()
        con["self_challenge"] = [e for e in self_challenge() if e["dimension"] != "concurrency"]
        write_files(api, state(), artifact(con), verification("REVISE"))
        results.append(check("T23 自查缺维(R8)", api, False, "R8"))

        _, api = make_case(root, "t24")
        con = designed_contract()
        con["self_challenge"][0] = {"dimension": "failure_modes", "finding": "发现 X",
                                    "disposition": "accepted_risk"}  # 无 rationale
        write_files(api, state(), artifact(con), verification("REVISE"))
        results.append(check("T24 接受风险无理由(R8)", api, False, "R8"))

        _, api = make_case(root, "t25")
        con = designed_contract()
        con["tradeoffs"] = [{"decision": "d", "choice": "c", "rationale": "r", "cost": ""}]
        write_files(api, state(), artifact(con), verification("REVISE"))
        results.append(check("T25 取舍代价为空(R8)", api, False, "R8"))

        _, api = make_case(root, "t26")
        art = artifact()
        art["artifact"]["contracts"] = [designed_contract(), designed_contract()]  # 同 id C1
        write_files(api, state(), art, verification("REVISE"))
        results.append(check("T26 契约面 id 重复(R5)", api, False, "契约面 id 重复"))

        _, api = make_case(root, "t27")
        st = state()
        del st["cross"]  # VERIFYING 却无 cross
        write_files(api, st, artifact(), verification("REVISE"))
        results.append(check("T27 VERIFYING 缺 cross(R15)", api, False, "R15"))

        # R13 完整性 / 非 UTF-8 / R16 state↔产物对账
        _, api = make_case(root, "t28")
        write_files(api, state(), artifact(), verification("PASS"))
        (api / "state.json").write_bytes(b'\xff\xfe{"status": "VERIFYING"}')  # 非 UTF-8 字节
        results.append(check("T28 非 UTF-8 state.json 优雅报错", api, False, "无法读取/解析"))

        _, api = make_case(root, "t29")
        ver = verification("PASS")
        ver["redlines"] = redlines_ok()[:4]  # 漏 RED-05
        write_files(api, state(), artifact(), ver)
        results.append(check("T29 红线漏条未处置(R13)", api, False, "未逐条处置"))

        _, api = make_case(root, "t30")
        ver = verification("PASS")
        rl = redlines_ok()
        rl[1] = dict(rl[0])  # RED-01 重复
        ver["redlines"] = rl
        write_files(api, state(), artifact(), ver)
        results.append(check("T30 红线 id 重复(R13)", api, False, "红线 id 重复"))

        _, api = make_case(root, "t31")
        st = review_state()
        st["contracts"] = state()["contracts"]  # review 却带契约面
        write_files(api, st, review_artifact(), review_verification("PASS"))
        results.append(check("T31 review 模式 contracts 非空(R16)", api, False, "review 模式 contracts 必须置空"))

        _, api = make_case(root, "t32")
        st = state()
        st["upstream_kind"] = "contract_doc"  # design 却消费 contract_doc
        write_files(api, st, artifact(), verification("REVISE"))
        results.append(check("T32 design 模式 contract_doc(R16)", api, False, "design 模式不消费 contract_doc"))

        _, api = make_case(root, "t33")
        st = state("COMPLETE")
        st["cross"] = {"status": "not_started"}  # COMPLETE 却未过 Cross
        write_files(api, st, artifact(), verification("PASS"))
        results.append(check("T33 COMPLETE 但 Cross 未过(R16)", api, False, "cross.status 未记 passed"))

        _, api = make_case(root, "t34")
        art = artifact()
        con2 = designed_contract()
        con2["id"] = "C2"
        con2["name"] = "第二契约面"
        art["artifact"]["contracts"] = [designed_contract(), con2]  # 目标只有 C1
        write_files(api, state(), art, verification("REVISE"))
        results.append(check("T34 设计目标外契约面(R5)", api, False, "目标外的契约面"))

        _, api = make_case(root, "t35")
        st = state()
        st["contracts"][0]["review_status"] = "revise"  # 与 verdict=PASS 矛盾
        write_files(api, st, artifact(), verification("PASS"))
        results.append(check("T35 review_status 与 verdict 矛盾(R16)", api, False, "与评审 verdict='PASS' 矛盾"))

        _, api = make_case(root, "t36")
        write_files(api, state(), review_artifact(), verification("PASS"))  # design 配 api_review
        results.append(check("T36 mode 与 deliverable_kind 不符(R16)", api, False, "deliverable_kind"))

        _, api = make_case(root, "t37")
        st = state()
        st["contracts"].append({"id": "C2", "kind": "event", "depth": "brief",
                                "design_status": "done", "review_status": "pass"})
        write_files(api, st, artifact(), verification("PASS"))  # artifact 目标仍只有 C1
        results.append(check("T37 target 与 state.contracts 不一致(R16)", api, False, "不一致"))

    print()
    passed = sum(results)
    print(f"{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
