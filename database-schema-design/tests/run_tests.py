"""database-schema-design 反博弈回归测试(仅依赖 Python 标准库)。

每个用例构造一个临时 .pev 工程,断言 validate.py 的退出码与错误定位:
伪造的 DECISION 锚点、占位未关闭、越界实体、分母造假、替别人认领交互、
无依据索引、表不回指实体、缺规模假设、门禁人工填报不符、
红线未过判 PASS、红线漏条/重复等,都必须被拦下;
空 evidence、缺 replan_reason、状态门缺字段、登记册不符、自查缺维/无理由/
空代价、库 id 重复、VERIFYING 缺 cross、state 与产物各说各话
(mode/库集/deliverable_kind/评审状态不同步)也必须被拦下;非 UTF-8 文件
必须优雅报错而非崩溃;干净产物(单库/多模块单库/review/schema_request)必须全绿通过。
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

REDLINE_IDS = ["RED-01", "RED-02", "RED-03", "RED-04", "RED-05", "RED-06", "RED-07"]


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
        "stores": [{"id": "D1", "kind": "postgresql",
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
            "owns_data": ["orders 订单", "order_items 订单明细"],
        }],
        "interactions": [{"id": "I1", "scenario": "用户下单", "from": "external:web",
                          "to": "M1", "mode": "sync-call", "idempotency": "required"}],
    }


def designed_store(**overrides):
    doc = {
        "id": "D1", "name": "订单主库", "kind": "postgresql",
        "covered_entities": ["orders 订单", "order_items 订单明细"],
        "environment": {"dialect_version": "PostgreSQL 16", "charset": "utf8",
                        "scale": "日增 50 万,读写 10:1"},
        "access_patterns": [
            {"id": "D1-A1", "pattern": "按买家查订单列表", "frequency": "高频",
             "query_shape": "WHERE buyer_id=? ORDER BY created_at DESC"},
            {"id": "D1-A2", "pattern": "按订单号点查", "frequency": "高频",
             "query_shape": "WHERE order_no=?"},
        ],
        "tables": [
            {"id": "D1-T1", "name": "orders", "entity": "orders 订单",
             "purpose": "订单主表",
             "columns": "id BIGINT PK; order_no VARCHAR(32) UNIQUE NOT NULL; buyer_id BIGINT FK; amount DECIMAL(12,2) NOT NULL; status SMALLINT CHECK; created_at timestamptz",
             "pk": "BIGINT 自增:单库写入,无分片计划",
             "constraints": "UNIQUE(order_no); FK buyer_id→users(id) ON DELETE RESTRICT; CHECK status IN (0,1,2)",
             "why": "order_no 生成列承载业务语义,PK 不暴露",
             "trace": "FACT module M1 owns_data"},
            {"id": "D1-T2", "name": "order_items", "entity": "order_items 订单明细",
             "purpose": "订单明细行",
             "columns": "id BIGINT PK; order_id BIGINT FK; sku VARCHAR(64) NOT NULL; qty INT NOT NULL",
             "pk": "BIGINT 自增",
             "constraints": "FK order_id→orders(id) ON DELETE CASCADE; NOT NULL qty",
             "trace": "FACT module M1 owns_data"},
        ],
        "indexes": [
            {"id": "D1-I1", "table": "D1-T1", "definition": "INDEX (buyer_id, created_at DESC)",
             "serves": "D1-A1", "why": "买家维度列表排序"},
            {"id": "D1-I2", "table": "D1-T1", "definition": "UNIQUE INDEX (order_no)",
             "serves": "D1-A2", "why": "订单号点查 + 幂等去重"},
        ],
        "denormalization": [],
        "data_flow_commitments": [
            {"interaction": "I1", "role": "接收方", "schema_handling": "D1-I2 唯一索引承接幂等去重",
             "trace": "FACT arch 交互 I1"},
        ],
        "evolution": {"strategy": "expand-contract + Flyway 版本化",
                      "compat_rules": "删列/改类型/改约束=破坏性变更,先双写一个版本周期;UP/DOWN 成对;大表变更评估锁级别"},
        "tradeoffs": [{"decision": "主键自增 vs UUID", "choice": "BIGINT 自增",
                       "rationale": "单库写入,时间有序避免页分裂",
                       "cost": "跨库合并需映射表,暴露计数", "alternative": "UUIDv7 BINARY(16)"}],
        "self_challenge": self_challenge(),
    }
    doc.update(overrides)
    return doc


def mongo_store(**overrides):
    """MongoDB 库:用 document_shape + validator 替代关系型的 columns/pk/constraints。"""
    doc = {
        "id": "D1", "name": "订单文档库", "kind": "mongodb",
        "covered_entities": ["orders 订单", "order_items 订单明细"],
        "environment": {"dialect_version": "MongoDB 7.0",
                        "scale": "日增 50 万,读写 10:1"},
        "access_patterns": [
            {"id": "D1-A1", "pattern": "按买家查订单列表", "frequency": "高频",
             "query_shape": "find({user_id:?}).sort({created_at:-1})"},
        ],
        "tables": [
            {"id": "D1-T1", "name": "orders", "entity": "orders 订单",
             "purpose": "订单主文档(内嵌明细快照,order_items 随单读不单建集合)",
             "document_shape": "items:[{product_id,name_snapshot,qty,price_cents}] 内嵌;user_id 引用 users",
             "validator": "$jsonSchema: required user_id/status/total_cents;status enum;total_cents bsonType long minimum 0"},
        ],
        "indexes": [
            {"id": "D1-I1", "table": "D1-T1", "definition": "{user_id:1, created_at:-1}",
             "serves": "D1-A1", "why": "买家维度列表排序(ESR)"},
        ],
        "denormalization": [],
        "data_flow_commitments": [
            {"interaction": "I1", "role": "接收方", "schema_handling": "订单号唯一索引承接幂等去重",
             "trace": "FACT arch 交互 I1"},
        ],
        "evolution": {"strategy": "schema_version 字段 + 应用层显式迁移",
                      "compat_rules": "结构演进走 schema_version,读兼容写升级;无 ALTER TABLE"},
        "tradeoffs": [{"decision": "embed vs reference", "choice": "明细内嵌",
                       "rationale": "明细随单读、下单后不变、1:few",
                       "cost": "无法独立分页/单独更新单条明细", "alternative": "reference + $lookup"}],
        "self_challenge": self_challenge(),
    }
    doc.update(overrides)
    return doc


def mongo_state(status="VERIFYING"):
    st = state(status)
    st["stores"][0]["kind"] = "mongodb"
    return st


def artifact(store=None, **overrides):
    st = designed_store() if store is None else store
    doc = {
        "status": "completed",
        "evidence": [],
        "artifact": {
            "deliverable_kind": "db_schemas",
            "input_summary": {
                "goal": "g",
                "target_stores": ["D1"],
                "upstream_snapshot": snapshot(),
                "upstream_items": [
                    {"id": "M1-D1", "item": "orders 订单", "anchor": "module/output/M1/ owned_data_handling 节"},
                    {"id": "M1-D2", "item": "order_items 订单明细", "anchor": "module/output/M1/ owned_data_handling 节"},
                    {"id": "I1", "item": "用户下单", "anchor": "arch 关键交互表 I1 行"},
                ],
            },
            "stores": [st],
            "risks": [],
            "upstream_mapping": [
                {"upstream_item": "M1-D1", "store_id": "D1", "trace": "t"},
                {"upstream_item": "M1-D2", "store_id": "D1", "trace": "t"},
                {"upstream_item": "I1", "store_id": "D1", "trace": "t"},
            ],
            "downstream_deliverables": {},
        },
    }
    doc.update(overrides)
    return doc


def verification(verdict="PASS", **overrides):
    scores = {"upstream_conformance": 4, "schema_clarity": 4, "consistency": 4,
              "compatibility": 4, "tradeoff_honesty": 4, "simplicity": 4, "traceability": 4}
    doc = {
        "verdict": verdict,
        "scores": dict(scores),
        "store_reviews": [{"store_id": "D1", "verdict": "PASS",
                           "scores": dict(scores), "critical_issues": []}],
        "cross_review": {"verdict": "pass", "checked_items": ["命名与概念一致"], "findings": []},
        "gates": {"stores_complete": True, "entities_within_upstream": True,
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
        "upstream_kind": "schema_doc",
        "upstream_source": "schema.sql",
        "stores": [],
    })
    return st


def review_artifact(**overrides):
    findings = [
        {"id": "F1", "dimension": "failure_modes", "finding": "金额列用了 DOUBLE",
         "severity": "HIGH", "evidence_anchor": "orders.total DOUBLE", "recommendation": "改 DECIMAL(12,2)"},
    ]
    findings += [{"dimension": d, "finding": "", "severity": "NONE"}
                 for d in ADV_DIMS if d != "failure_modes"]
    doc = {
        "status": "completed",
        "evidence": [],
        "artifact": {
            "deliverable_kind": "db_review",
            "input_summary": {"goal": "review", "target_stores": []},
            "review_findings": findings,
        },
    }
    doc.update(overrides)
    return doc


def review_verification(verdict="PASS", **overrides):
    scores = {"upstream_conformance": 4, "schema_clarity": 4, "consistency": 4,
              "compatibility": 4, "tradeoff_honesty": 4, "simplicity": 4, "traceability": 4}
    doc = {
        "verdict": verdict,
        "scores": dict(scores),
        "store_reviews": [],
        "cross_review": {"verdict": "pass", "checked_items": [], "findings": []},
        "gates": {"stores_complete": True, "entities_within_upstream": True,
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
    db = project / ".pev" / "prd-1" / "db"
    (db / "iterations").mkdir(parents=True)
    return project, db


def write_files(db, state_doc, art_doc, ver_doc):
    (db / "state.json").write_text(json.dumps(state_doc), encoding="utf-8")
    (db / "iterations" / "01-plan.json").write_text(json.dumps(plan()), encoding="utf-8")
    (db / "iterations" / "01-artifact.json").write_text(json.dumps(art_doc), encoding="utf-8")
    (db / "iterations" / "01-verification.json").write_text(json.dumps(ver_doc), encoding="utf-8")


def run(db):
    proc = subprocess.run([sys.executable, str(VALIDATE), str(db)],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout


def check(name, db, want_pass, must_contain=None):
    code, out = run(db)
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
    with tempfile.TemporaryDirectory(prefix="db-review-") as tmp:
        root = Path(tmp)

        _, db = make_case(root, "t1")
        art = artifact()
        art["artifact"]["stores"][0]["tables"][0]["purpose"] = "待定"
        write_files(db, state(), art, verification("PASS"))
        results.append(check("T1 占位未关闭(R10)", db, False, "R10"))

        _, db = make_case(root, "t2")
        art = artifact(evidence=[{"claim": "user chose X", "type": "DECISION",
                                  "evidence": "01-artifact decisions#d99",
                                  "confidence": "high"}],
                       decisions=[])
        write_files(db, state(), art, verification("PASS"))
        results.append(check("T2 伪造 DECISION 锚点(R11)", db, False, "decisions#d99"))

        _, db = make_case(root, "t3")
        ver = verification("REVISE", findings=[{
            "id": "F1", "severity": "HIGH", "what": "w", "why": "y",
            "what_must_change": "c", "affected_upstream_items": ["M1-D9"],
            "dimension": "misuse_potential",
        }])
        write_files(db, state(), artifact(), ver)
        results.append(check("T3 finding 未声明上游(R12)", db, False, "R12"))

        _, db = make_case(root, "t4")
        ver = verification("PASS", redlines=[{
            "id": "RED-01", "applies": True, "passed": False, "details": "含未声明实体的表",
        }])
        write_files(db, state(), artifact(), ver)
        results.append(check("T4 红线未过判 PASS(R13)", db, False, "R13"))

        _, db = make_case(root, "t5")
        st = designed_store()
        st["covered_entities"] = ["orders 订单", "order_items 订单明细", "users 用户"]
        write_files(db, state(), artifact(st), verification("REVISE"))
        results.append(check("T5 承接上游声明外实体(R5 守恒)", db, False, "上游声明外的实体"))

        _, db = make_case(root, "t6")
        st = designed_store()
        del st["evolution"]  # detail 却无演进策略
        write_files(db, state(), artifact(st), verification("REVISE"))
        results.append(check("T6 detail 缺 evolution(R5)", db, False, "evolution"))

        _, db = make_case(root, "t7")
        art = artifact()
        # 快照有两条 owns_data,分母只声明一条
        art["artifact"]["input_summary"]["upstream_items"] = [
            {"id": "M1-D1", "item": "orders 订单", "anchor": "a"},
            {"id": "I1", "item": "用户下单", "anchor": "a"},
        ]
        art["artifact"]["upstream_mapping"] = [
            {"upstream_item": "M1-D1", "store_id": "D1", "trace": "t"},
            {"upstream_item": "I1", "store_id": "D1", "trace": "t"},
        ]
        write_files(db, state(), art, verification("REVISE"))
        results.append(check("T7 承接实体未进分母(R7)", db, False, "分母不全"))

        _, db = make_case(root, "t8")
        art = artifact()
        # 快照交互 I1 改为 M2→M3,D1(owner M1)却认领它
        art["artifact"]["input_summary"]["upstream_snapshot"]["interactions"] = [
            {"id": "I1", "scenario": "支付回调", "from": "M2", "to": "M3"}]
        write_files(db, state(), art, verification("REVISE"))
        results.append(check("T8 替别人认领交互(R5)", db, False, "参与方"))

        _, db = make_case(root, "t9")
        ver = verification("PASS")
        ver["store_reviews"] = []  # 缺 D1 评审
        write_files(db, state(), artifact(), ver)
        results.append(check("T9 store_reviews 缺库(R14)", db, False, "R14"))

        _, db = make_case(root, "t10")
        ver = verification("PASS")
        ver["cross_review"] = {"verdict": "revise", "checked_items": [], "findings": [{
            "id": "X1", "severity": "HIGH", "what": "w", "why": "y",
            "what_must_change": "c", "affected_stores": ["D1"]}]}
        write_files(db, state(), artifact(), ver)
        results.append(check("T10 Cross 未过判 PASS(R14)", db, False, "R14"))

        _, db = make_case(root, "t11")
        write_files(db, state(), artifact(), verification("PASS"))
        results.append(check("T11 干净产物通过(单库)", db, True))

        # 多模块实体落同一个库
        _, db = make_case(root, "t11b")
        art = artifact()
        art["artifact"]["input_summary"]["upstream_snapshot"]["modules"].append(
            {"id": "M2", "name": "users", "owns_data": ["users 用户"]})
        art["artifact"]["input_summary"]["upstream_items"].append(
            {"id": "M2-D1", "item": "users 用户", "anchor": "module/output/M2/ owned_data_handling 节"})
        art["artifact"]["upstream_mapping"].append(
            {"upstream_item": "M2-D1", "store_id": "D1", "trace": "t"})
        st = designed_store()
        st["covered_entities"].append("users 用户")
        st["tables"].append({"id": "D1-T3", "name": "users", "entity": "users 用户",
                             "purpose": "用户资料",
                             "columns": "id BIGINT PK; email VARCHAR(128) UNIQUE NOT NULL",
                             "pk": "BIGINT 自增", "constraints": "UNIQUE(email)"})
        art["artifact"]["stores"] = [st]
        write_files(db, state(), art, verification("PASS"))
        results.append(check("T11b 多模块实体落单库通过", db, True))

        _, db = make_case(root, "t13")
        ver = verification("PASS")
        ver["gates"]["upstream_mapped"] = False  # 人工填报,与脚本计算不符
        write_files(db, state(), artifact(), ver)
        results.append(check("T13 门禁人工填报不符(R6)", db, False, "R6"))

        project, db = make_case(root, "t14")
        (project / "module.md").write_text("M1 owns_data orders 订单 and 参与交互 I1", encoding="utf-8")
        excerpt = "M1 owns_data orders 订单"
        art = artifact(evidence=[{"claim": "上游声明 M1 拥有订单数据", "type": "FACT",
                                  "evidence": "module.md owned_data_handling 节", "confidence": "high",
                                  "source": {"path": "module.md", "excerpt": excerpt,
                                             "digest": "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest()}}])
        write_files(db, state(), art, verification("PASS"))
        results.append(check("T14 新鲜证据来源通过", db, True))

        # review 模式回归
        _, db = make_case(root, "t15")
        write_files(db, review_state(), review_artifact(), review_verification("PASS"))
        results.append(check("T15 review 干净产物通过", db, True))

        _, db = make_case(root, "t16")
        art = review_artifact()
        art["artifact"]["review_findings"] = [
            f for f in art["artifact"]["review_findings"]
            if f.get("dimension") != "consistency"
        ]
        write_files(db, review_state(), art, review_verification("REVISE"))
        results.append(check("T16 review 缺维度(R8)", db, False, "评审缺少维度"))

        _, db = make_case(root, "t17")
        art = review_artifact()
        for f in art["artifact"]["review_findings"]:
            if f.get("finding"):
                f["evidence_anchor"] = ""
        write_files(db, review_state(), art, review_verification("REVISE"))
        results.append(check("T17 review 非空 finding 缺锚点(R8)", db, False, "evidence_anchor"))

        # R1-R4 / R9 / design 侧 R8 / 库 id 唯一 / cross 必备
        _, db = make_case(root, "t18")
        art = artifact(evidence=[
            {"claim": "上游声明", "type": "FACT", "evidence": None, "confidence": "high"},
            {"claim": "用户拍板", "type": "DECISION", "evidence": "  ", "confidence": "high"}])
        write_files(db, state(), art, verification("REVISE"))
        results.append(check("T18 FACT/DECISION 空 evidence(R1)", db, False, "R1"))

        _, db = make_case(root, "t19")
        write_files(db, state(), artifact(status="replan_required"), verification("REVISE"))
        results.append(check("T19 replan_required 缺 replan_reason(R2)", db, False, "R2"))

        _, db = make_case(root, "t20")
        write_files(db, state("WAITING_FOR_INPUT"), artifact(), verification("REVISE"))
        results.append(check("T20 WAITING_FOR_INPUT 缺 resume_to(R3)", db, False, "R3"))

        _, db = make_case(root, "t21")
        write_files(db, state("WAITING_FOR_UPSTREAM"), artifact(), verification("REVISE"))
        results.append(check("T21 WAITING_FOR_UPSTREAM 缺 upstream_gaps(R4)", db, False, "R4"))

        _, db = make_case(root, "t22")
        st = state()
        st["artifacts"] = ["01-artifact.json", "02-artifact.json"]  # 02 不存在
        write_files(db, st, artifact(), verification("REVISE"))
        results.append(check("T22 登记册与目录不一致(R9)", db, False, "R9"))

        _, db = make_case(root, "t23")
        st = designed_store()
        st["self_challenge"] = [e for e in self_challenge() if e["dimension"] != "concurrency"]
        write_files(db, state(), artifact(st), verification("REVISE"))
        results.append(check("T23 自查缺维(R8)", db, False, "R8"))

        _, db = make_case(root, "t24")
        st = designed_store()
        st["self_challenge"][0] = {"dimension": "failure_modes", "finding": "发现 X",
                                   "disposition": "accepted_risk"}  # 无 rationale
        write_files(db, state(), artifact(st), verification("REVISE"))
        results.append(check("T24 接受风险无理由(R8)", db, False, "R8"))

        _, db = make_case(root, "t25")
        st = designed_store()
        st["tradeoffs"] = [{"decision": "d", "choice": "c", "rationale": "r", "cost": ""}]
        write_files(db, state(), artifact(st), verification("REVISE"))
        results.append(check("T25 取舍代价为空(R8)", db, False, "R8"))

        _, db = make_case(root, "t26")
        art = artifact()
        art["artifact"]["stores"] = [designed_store(), designed_store()]  # 同 id D1
        write_files(db, state(), art, verification("REVISE"))
        results.append(check("T26 库 id 重复(R5)", db, False, "库 id 重复"))

        _, db = make_case(root, "t27")
        st = state()
        del st["cross"]  # VERIFYING 却无 cross
        write_files(db, st, artifact(), verification("REVISE"))
        results.append(check("T27 VERIFYING 缺 cross(R15)", db, False, "R15"))

        # R13 完整性 / 非 UTF-8 / R16 state↔产物对账
        _, db = make_case(root, "t28")
        write_files(db, state(), artifact(), verification("PASS"))
        (db / "state.json").write_bytes(b'\xff\xfe{"status": "VERIFYING"}')  # 非 UTF-8 字节
        results.append(check("T28 非 UTF-8 state.json 优雅报错", db, False, "无法读取/解析"))

        _, db = make_case(root, "t29")
        ver = verification("PASS")
        ver["redlines"] = redlines_ok()[:6]  # 漏 RED-07
        write_files(db, state(), artifact(), ver)
        results.append(check("T29 红线漏条未处置(R13)", db, False, "未逐条处置"))

        _, db = make_case(root, "t30")
        ver = verification("PASS")
        rl = redlines_ok()
        rl[1] = dict(rl[0])  # RED-01 重复
        ver["redlines"] = rl
        write_files(db, state(), artifact(), ver)
        results.append(check("T30 红线 id 重复(R13)", db, False, "红线 id 重复"))

        _, db = make_case(root, "t31")
        st = review_state()
        st["stores"] = state()["stores"]  # review 却带库
        write_files(db, st, review_artifact(), review_verification("PASS"))
        results.append(check("T31 review 模式 stores 非空(R16)", db, False, "review 模式 stores 必须置空"))

        _, db = make_case(root, "t32")
        st = state()
        st["upstream_kind"] = "schema_doc"  # design 却消费 schema_doc
        write_files(db, st, artifact(), verification("REVISE"))
        results.append(check("T32 design 模式 schema_doc(R16)", db, False, "design 模式不消费 schema_doc"))

        _, db = make_case(root, "t33")
        st = state("COMPLETE")
        st["cross"] = {"status": "not_started"}  # COMPLETE 却未过 Cross
        write_files(db, st, artifact(), verification("PASS"))
        results.append(check("T33 COMPLETE 但 Cross 未过(R16)", db, False, "cross.status 未记 passed"))

        _, db = make_case(root, "t34")
        art = artifact()
        st2 = designed_store()
        st2["id"] = "D2"
        st2["name"] = "第二数据库"
        art["artifact"]["stores"] = [designed_store(), st2]  # 目标只有 D1
        write_files(db, state(), art, verification("REVISE"))
        results.append(check("T34 设计目标外数据库(R5)", db, False, "目标外的数据库"))

        _, db = make_case(root, "t35")
        st = state()
        st["stores"][0]["review_status"] = "revise"  # 与 verdict=PASS 矛盾
        write_files(db, st, artifact(), verification("PASS"))
        results.append(check("T35 review_status 与 verdict 矛盾(R16)", db, False, "与评审 verdict='PASS' 矛盾"))

        _, db = make_case(root, "t36")
        write_files(db, state(), review_artifact(), verification("PASS"))  # design 配 db_review
        results.append(check("T36 mode 与 deliverable_kind 不符(R16)", db, False, "deliverable_kind"))

        _, db = make_case(root, "t37")
        st = state()
        st["stores"].append({"id": "D2", "kind": "mongodb",
                             "design_status": "done", "review_status": "pass"})
        write_files(db, st, artifact(), verification("PASS"))  # artifact 目标仍只有 D1
        results.append(check("T37 target 与 state.stores 不一致(R16)", db, False, "不一致"))

        # db 特有:索引依据 / 表回指实体 / 环境门槛 / schema_request
        _, db = make_case(root, "t38")
        st = designed_store()
        st["indexes"][0]["serves"] = "D1-A9"  # 不存在的 access pattern
        write_files(db, state(), artifact(st), verification("REVISE"))
        results.append(check("T38 索引无依据(R5)", db, False, "无依据索引"))

        _, db = make_case(root, "t39")
        st = designed_store()
        st["tables"][1]["entity"] = "users 用户"  # 不在 covered_entities
        write_files(db, state(), artifact(st), verification("REVISE"))
        results.append(check("T39 表不回指承接实体(R5)", db, False, "covered_entities"))

        _, db = make_case(root, "t40")
        st = designed_store()
        st["environment"]["scale"] = ""  # 规模假设缺失
        write_files(db, state(), artifact(st), verification("REVISE"))
        results.append(check("T40 环境缺规模假设(R5)", db, False, "scale"))

        _, db = make_case(root, "t42")
        st = state()
        st["upstream_kind"] = "schema_request"  # 口述/DDL 上游合法路径
        art = artifact(evidence=[{"claim": "用户口述实体清单:orders/order_items",
                                  "type": "DECISION", "evidence": "01-artifact decisions#d1",
                                  "confidence": "high"}],
                       decisions=[{"id": "d1", "decision": "实体清单以口述为准"}])
        write_files(db, st, art, verification("PASS"))
        results.append(check("T42 schema_request 口述上游通过", db, True))

        # MongoDB kind:document_shape + validator 替代 columns/pk/constraints
        _, db = make_case(root, "t43")
        write_files(db, mongo_state(), artifact(mongo_store()), verification("PASS"))
        results.append(check("T43 mongodb 用 document_shape+validator 通过", db, True))

        _, db = make_case(root, "t44")
        st = mongo_store()
        st["tables"][0]["validator"] = ""  # 缺 validator
        write_files(db, mongo_state(), artifact(st), verification("REVISE"))
        results.append(check("T44 mongodb 缺 validator(R5)", db, False, "validator"))

        _, db = make_case(root, "t46")
        write_files(db, state("COMPLETE"), artifact(), verification("PASS"))
        results.append(check("T46 COMPLETE 缺用户确认被拦截(R17)", db, False,
                             "user_confirmation"))

        _, db = make_case(root, "t47")
        st = state("COMPLETE")
        st["user_confirmation"] = {"date": "2026-10-27"}
        write_files(db, st, artifact(), verification("PASS"))
        results.append(check("T47 COMPLETE 带确认记录通过(R17)", db, True))

        # 随包金样示例必须始终通过校验(防腐坏)
        example_db = SKILL / "examples" / "design-single-pg"
        code, out = run(example_db)
        ok = code == 0
        print(f"  [{'PASS' if ok else 'FAIL'}] T45 随包金样示例通过 exit={code}")
        if not ok:
            print(f"        stdout: {out[:2000]}")
        results.append(ok)

    print()
    passed = sum(results)
    print(f"{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
