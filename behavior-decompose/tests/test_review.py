"""review.py 单一审查入口测试(improve-behavior-decompose-verification)。

覆盖任务矩阵:冻结输入与机器检查(1.2/1.3/2.1/2.3)、diff 与影响闭包(2.2)、
scope 规则与 full 批准(2.4)、candidate 提交与状态路由(3.2/3.3)、审查链与
COMPLETE 门禁(3.4/4.1/4.2)、中断恢复(5.3)。全部用临时目录 + 合成数据,
不触真实 .pev/ 运行目录。

约定:子进程端到端调用 scripts/review.py,断言退出码、结果 JSON 字段与盘上产物。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
REVIEW = SKILL_ROOT / "scripts" / "review.py"
VALIDATE = SKILL_ROOT / "scripts" / "validate.py"

RUBRIC_SHA_HINT = "rubric"


def run_review(decompose):
    return subprocess.run([sys.executable, str(REVIEW), str(decompose)],
                          capture_output=True, text=True)


def sha256_file(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def make_plan():
    return {
        "goal": "拆解登录", "understanding": "邮箱登录能力",
        "known": ["spec §1"], "unknown": [], "assumptions": [],
        "plan": [{"id": "p1", "objective": "拆 Epic", "action": "decompose",
                  "inputs": ["spec"], "expected_output": "行为目录",
                  "success_criteria": "story 溯源可达"}],
        "final_deliverable": "output/catalog.md", "stop_conditions": [],
    }


def make_story(sid="S1", title="邮箱登录", priority="P2"):
    return {
        "id": sid, "title": title, "points": 3, "priority": priority,
        "acceptance_criteria": ["ac1", "ac2", "ac3"],
        "scenarios": [
            {"class": "normal", "given": "已注册", "when": "提交正确邮箱密码", "then": "登录成功"},
            {"class": "exception", "given": "已注册", "when": "密码错误", "then": "报错"},
        ],
        "trace": "spec §1",
    }


def make_artifact(stories=None, dependencies=None):
    return {
        "status": "completed",
        "evidence": [{"claim": "S1 溯源", "type": "FACT",
                      "evidence": "spec §1", "confidence": "high"}],
        "artifact": {
            "category_defaults": {"applicable": ["normal", "exception"],
                                  "inapplicable": []},
            "epics": [{
                "id": "E1", "title": "账号能力", "scope": "账号",
                "success_criteria": "用户可登录",
                "features": [{
                    "id": "F1", "title": "登录",
                    "stories": stories if stories is not None else [make_story()],
                }],
            }],
            "dependencies": dependencies if dependencies is not None else [],
        },
    }


class ReviewFixture(unittest.TestCase):
    """合成一个处于 EXECUTING 末尾(artifact 已完成)的正常拆解运行。"""

    def setUp(self):
        import shutil
        self._shutil = shutil
        self.ws = Path(tempfile.mkdtemp(prefix="decompose-review-test-"))
        self.round = self.ws / ".pev" / "round-x"
        self.decompose = self.round / "decompose"
        self.decompose.mkdir(parents=True)
        self.spec = self.ws / "upstream" / "spec.md"
        self.spec.parent.mkdir(parents=True, exist_ok=True)
        self.spec.write_text("# Spec\n\n§1 用户可用邮箱登录。\n", encoding="utf-8")
        self.state = {
            "objective": {"goal": "拆解登录", "deadline": None},
            "spec_source": str(self.spec),
            "status": "EXECUTING",
            "iteration": 1,
            "max_iterations": 5,
            "plans": ["01-plan.json"],
            "artifacts": ["01-artifact.json"],
            "evidence": [],
        }
        write_json(self.decompose / "iterations" / "01-plan.json", make_plan())
        write_json(self.decompose / "iterations" / "01-artifact.json", make_artifact())

    def tearDown(self):
        self._shutil.rmtree(self.ws, ignore_errors=True)

    # -- 便捷写盘 -----------------------------------------------------------

    def flush_state(self, **over):
        self.state.update(over)
        write_json(self.decompose / "state.json", self.state)

    def artifact_path(self, n=1):
        return self.decompose / "iterations" / f"{n:02d}-artifact.json"

    def load_artifact(self, n=1):
        return json.loads(self.artifact_path(n).read_text(encoding="utf-8"))

    def save_artifact(self, art, n=1):
        write_json(self.artifact_path(n), art)

    def run_ok(self):
        proc = run_review(self.decompose)
        self.assertEqual(proc.returncode, 0,
                         f"exit={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}")
        return json.loads(proc.stdout)

    def run_fail(self):
        proc = run_review(self.decompose)
        self.assertNotEqual(proc.returncode, 0,
                            f"expected nonzero exit, stdout={proc.stdout}")
        return json.loads(proc.stdout)

    def review_dir(self, rid):
        return self.decompose / "reviews" / rid


class DispatchTest(ReviewFixture):
    """任务 1.2/1.3/2.1/2.3:首次派发、冻结输入、机器检查、幂等。"""

    def setUp(self):
        super().setUp()
        self.flush_state()

    def test_first_dispatch_generates_frozen_input(self):
        res = self.run_ok()
        self.assertEqual(res["status"], "DISPATCHED")
        inp = json.loads((self.review_dir("r001") / "input.json").read_text(encoding="utf-8"))
        # 命名输入:路径 + SHA-256(artifact/plan/upstream/rubric/protocol + ledger 投影)
        named = inp["named_inputs"]
        for key in ("artifact", "plan", "upstream", "rubric", "protocol"):
            self.assertIn(key, named, f"缺命名输入 {key}")
            self.assertTrue(named[key]["sha256"], f"{key} 哈希为空")
        self.assertEqual(named["artifact"]["sha256"],
                         sha256_file(self.artifact_path()))
        # 冻结当前 artifact 副本;不复制 plan/upstream/rubric/protocol 全文
        frozen = self.review_dir("r001") / "artifact.json"
        self.assertEqual(sha256_file(frozen), sha256_file(self.artifact_path()))
        for name in ("plan", "upstream", "rubric", "protocol"):
            self.assertFalse((self.review_dir("r001") / f"{name}.json").exists(),
                             f"不应复制 {name} 全文")
        # 候选 scope 与机器检查
        self.assertEqual(inp["scope"], "full")
        self.assertEqual(inp["coverage"]["scenario_category_pct"], 100.0)
        self.assertEqual(inp["coverage"]["critical_risk_pct"], 100.0)
        self.assertTrue(inp["checks"], "机器检查为空")
        for chk in inp["checks"]:
            for field in ("id", "required", "status", "detail"):
                self.assertIn(field, chk, f"检查缺字段 {field}")
            self.assertIn(chk["status"], ("pass", "fail", "skipped", "error"))
        self.assertTrue(inp["code_sha256"], "缺检查代码哈希")
        # 派发后停在 Verifier 语义审查;状态推进由脚本完成
        self.assertEqual(res["next_action"]["actor"], "verifier")
        state = json.loads((self.decompose / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "VERIFYING")

    def test_result_contract(self):
        res = self.run_ok()
        for key in ("ok", "status", "written", "errors", "warnings",
                    "next_action", "resume"):
            self.assertIn(key, res, f"结果缺字段 {key}")
        self.assertTrue(res["ok"])
        self.assertEqual(res["errors"], [])
        self.assertIn("review.py", res["resume"]["command"])

    def test_dispatch_idempotent(self):
        self.run_ok()
        first_sha = sha256_file(self.review_dir("r001") / "input.json")
        res = self.run_ok()
        self.assertEqual(res["status"], "DISPATCHED")
        self.assertEqual(sha256_file(self.review_dir("r001") / "input.json"), first_sha,
                         "同一输入重跑必须生成相同哈希")
        self.assertFalse(self.review_dir("r002").exists(), "不得新开 r002")

    def test_missing_upstream_fails_no_dispatch(self):
        self.state["spec_source"] = str(self.ws / "ghost" / "spec.md")
        self.flush_state()
        res = self.run_fail()
        self.assertFalse(res["ok"])
        self.assertTrue(any("spec" in e.lower() or "上游" in e for e in res["errors"]),
                        res["errors"])
        self.assertFalse(self.review_dir("r001").exists(), "缺输入不得派发")

    def test_bad_artifact_json_fails(self):
        (self.decompose / "iterations" / "01-artifact.json").write_text(
            "{broken", encoding="utf-8")
        res = self.run_fail()
        self.assertFalse(res["ok"])
        self.assertFalse(self.review_dir("r001").exists())

    def test_machine_check_failure_blocks_dispatch(self):
        art = self.load_artifact()
        art["artifact"]["dependencies"].append(
            {"from": "S9", "to": "S1", "type": "blocked-by"})
        self.save_artifact(art)
        res = self.run_fail()
        self.assertEqual(res["status"], "REJECTED")
        self.assertTrue(any("S9" in e for e in res["errors"]), res["errors"])
        # 检查失败时不派发 Verifier,也不留下可用待审输入
        self.assertNotEqual((res.get("next_action") or {}).get("actor"), "verifier")

    def test_dependency_cycle_fails(self):
        art = self.load_artifact()
        art["artifact"]["epics"][0]["features"][0]["stories"].append(make_story("S2"))
        art["artifact"]["dependencies"] = [
            {"from": "S1", "to": "S2", "type": "blocked-by"},
            {"from": "S2", "to": "S1", "type": "blocked-by"},
        ]
        self.save_artifact(art)
        res = self.run_fail()
        self.assertTrue(any("环" in e for e in res["errors"]), res["errors"])

    def test_named_input_missing_after_dispatch_invalidates(self):
        self.run_ok()
        self.spec.unlink()
        res = self.run_fail()
        self.assertFalse(res["ok"])
        self.assertTrue(res["errors"])

    def test_artifact_edit_regenerates_input(self):
        """命名输入的可确定变化:重新生成增量输入,不覆盖已提交历史。"""
        self.run_ok()
        first_sha = sha256_file(self.review_dir("r001") / "input.json")
        art = self.load_artifact()
        art["artifact"]["epics"][0]["features"][0]["stories"][0]["title"] = "邮箱登录改"
        self.save_artifact(art)
        res = self.run_ok()
        self.assertEqual(res["status"], "DISPATCHED")
        second_sha = sha256_file(self.review_dir("r001") / "input.json")
        self.assertNotEqual(first_sha, second_sha)
        # 冻结副本同步为新 artifact
        self.assertEqual(sha256_file(self.review_dir("r001") / "artifact.json"),
                         sha256_file(self.artifact_path()))


# ------------------------------------------------------------ 流程便捷助手

class FlowMixin:
    def reload_state(self):
        self.state = json.loads((self.decompose / "state.json").read_text(encoding="utf-8"))

    def dispatch(self):
        res = self.run_ok()
        self.assertEqual(res["status"], "DISPATCHED", res["errors"])
        rid = res["review"]["id"]
        return rid, json.loads((self.review_dir(rid) / "input.json").read_text(encoding="utf-8"))

    def coverage_pair(self, art=None):
        sys.path.insert(0, str(SKILL_ROOT / "scripts"))
        import validate as v
        s, c = v.compute_coverage([("x", art or self.load_artifact())])
        return {"scenario_category_pct": s, "critical_risk_pct": c}

    def commit_candidate(self, rid, verdict="PASS", scope="full", critical=None,
                         required=None, resolutions=None, blocked=None,
                         input_sha=None, coverage=None):
        cand = {
            "verdict": verdict, "scope": scope,
            "input_sha256": input_sha or sha256_file(self.review_dir(rid) / "input.json"),
            "scores": {"coverage": 4, "granularity": 4, "hierarchy": 4, "completeness": 4,
                       "actionability": 4, "scenario_coverage": 4, "traceability": 4},
            "coverage": coverage or self.coverage_pair(),
            "strengths": [], "critical_issues": critical or [],
            "warnings": [], "required_changes": required or [],
            "evidence_gaps": [], "confidence": "high",
            "resolutions": resolutions or [],
        }
        if blocked:
            cand["blocked"] = blocked
        write_json(self.review_dir(rid) / "candidate.json", cand)
        proc = run_review(self.decompose)
        return json.loads(proc.stdout), proc.returncode

    def revise_artifact(self, mutator):
        self.reload_state()
        art = self.load_artifact()
        mutator(art)
        self.save_artifact(art)
        self.state["status"] = "EXECUTING"
        self.flush_state()

    def baseline(self, verdict="PASS", critical=None, required=None):
        self.flush_state()
        rid, _inp = self.dispatch()
        res, rc = self.commit_candidate(rid, verdict=verdict, critical=critical, required=required)
        return rid, res, rc

    def confirm(self, rid, artifact_sha=None, digest=None):
        inp = json.loads((self.review_dir(rid) / "input.json").read_text(encoding="utf-8"))
        write_json(self.decompose / "reviews" / "confirmation.json", {
            "date": "2026-10-29", "note": "交付确认",
            "artifact_sha256": artifact_sha or inp["named_inputs"]["artifact"]["sha256"],
            "named_inputs_digest": digest or inp["named_inputs_digest"],
        })


class ScopeDiffTest(FlowMixin, ReviewFixture):
    """任务 2.2/2.4:确定性 diff、影响闭包、默认 delta、影响不明暂停、full 批准。"""

    def setUp(self):
        super().setUp()
        rid, _res, _rc = self.baseline()  # r001 full PASS 基线
        self.r1 = rid

    def test_revision_defaults_delta_with_diff(self):
        self.revise_artifact(
            lambda a: a["artifact"]["epics"][0]["features"][0]["stories"][0].__setitem__("title", "改"))
        rid, inp = self.dispatch()
        self.assertEqual(inp["scope"], "delta")
        changed = [e["id"] for e in inp["diff"]["stories"]["changed"]]
        self.assertIn("S1", changed)
        self.assertIn("S1", inp["impact_closure"]["affected_ids"])
        self.assertIn("F1", inp["impact_closure"]["parent_closure"])
        self.assertEqual(inp["previous_review"], "r001")
        # 冻结副本 = 当前 artifact
        self.assertEqual(sha256_file(self.review_dir(rid) / "artifact.json"),
                         sha256_file(self.artifact_path()))

    def test_numbering_reorg_stays_delta(self):
        def reorg(a):
            story = a["artifact"]["epics"][0]["features"][0]["stories"][0]
            story["id"] = "S2"
        self.revise_artifact(reorg)
        _rid, inp = self.dispatch()
        self.assertEqual(inp["scope"], "delta", "编号重排影响可确定,不自动 full")
        self.assertEqual(inp["diff"]["stories"]["removed"], ["S1"])
        self.assertEqual(inp["diff"]["stories"]["added"], ["S2"])

    def test_removed_id_still_mentioned_pauses(self):
        def reorg(a):
            story = a["artifact"]["epics"][0]["features"][0]["stories"][0]
            story["id"] = "S2"
            story["title"] = "替代 S1 的登录"
        self.revise_artifact(reorg)
        res = self.run_fail()
        self.assertEqual(res["status"], "PAUSED")
        self.assertTrue(any("自由文本" in e or "影响范围不确定" in e for e in res["errors"]),
                        res["errors"])
        self.assertFalse(self.review_dir("r002").joinpath("input.json").exists())

    def test_upstream_change_pauses_and_full_approval(self):
        self.spec.write_text("# Spec v2\n\n§1 用户可用邮箱登录。\n", encoding="utf-8")
        res = self.run_fail()
        self.assertEqual(res["status"], "PAUSED")
        self.assertTrue(any("上游" in e for e in res["errors"]), res["errors"])
        import re as _re
        digest = _re.search(r"named_inputs_digest=([0-9a-f]{64})", "\n".join(res["errors"])).group(1)
        # 过期/错误摘要的批准不生效
        write_json(self.decompose / "reviews" / "full-approval.json",
                   {"named_inputs_digest": "0" * 64, "source": "用户", "date": "2026-10-29"})
        res = self.run_fail()
        self.assertEqual(res["status"], "PAUSED", "批准未绑定当前输入哈希,不得再次 full")
        # 绑定正确的批准 → 再次 full
        write_json(self.decompose / "reviews" / "full-approval.json",
                   {"named_inputs_digest": digest, "source": "用户 2026-10-29 拍板", "date": "2026-10-29"})
        _rid, inp = self.dispatch()
        self.assertEqual(inp["scope"], "full")

    def test_plan_same_file_rewrite_pauses(self):
        self.reload_state()
        plan = json.loads((self.decompose / "iterations" / "01-plan.json").read_text(encoding="utf-8"))
        plan["assumptions"] = ["追加假设"]
        write_json(self.decompose / "iterations" / "01-plan.json", plan)
        res = self.run_fail()
        self.assertEqual(res["status"], "PAUSED")
        self.assertTrue(any("Plan" in e for e in res["errors"]), res["errors"])


class ReplanDeltaTest(FlowMixin, ReviewFixture):
    """REPLAN 后开新迭代,默认仍 delta;跨迭代 Plan 有可核验 diff。"""

    def test_replan_new_iteration_delta(self):
        self.flush_state()
        rid, _ = self.dispatch()
        res, rc = self.commit_candidate(rid, verdict="REPLAN")
        self.assertEqual(rc, 0, res["errors"])
        self.assertEqual(res["state_status"], "PLANNING")
        self.reload_state()
        self.assertEqual(self.state["iteration"], 2)
        # Planner 产出新迭代产物并登记
        plan = make_plan()
        plan["goal"] = "拆解登录 v2"
        write_json(self.decompose / "iterations" / "02-plan.json", plan)
        write_json(self.decompose / "iterations" / "02-artifact.json", make_artifact())
        self.state["plans"].append("02-plan.json")
        self.state["artifacts"].append("02-artifact.json")
        self.state["status"] = "EXECUTING"
        self.flush_state()
        rid2, inp = self.dispatch()
        self.assertEqual(inp["scope"], "delta", "REPLAN 后默认 delta,不自动 full")
        self.assertIsNotNone(inp["plan_diff"])
        self.assertIn("goal", inp["plan_diff"]["changed_keys"])
        self.assertEqual(inp["previous_review"], "r001")


class CommitRouteTest(FlowMixin, ReviewFixture):
    """任务 3.3:提交校验与状态路由。"""

    def setUp(self):
        super().setUp()
        self.flush_state()
        self.rid, _ = self.dispatch()

    def test_commit_pass_awaits_confirmation(self):
        res, rc = self.commit_candidate(self.rid, verdict="PASS")
        self.assertEqual(rc, 0, res["errors"])
        self.assertEqual(res["status"], "AWAIT_USER_CONFIRMATION")
        self.assertEqual(res["state_status"], "VERIFYING")
        out = self.decompose / "output" / "catalog.md"
        self.assertIn("S1", out.read_text(encoding="utf-8"))
        self.assertFalse((self.review_dir(self.rid) / "candidate.json").exists())
        review = json.loads((self.review_dir(self.rid) / "review.json").read_text(encoding="utf-8"))
        self.assertEqual(review["verdict"], "PASS")
        proj = json.loads((self.decompose / "iterations" / "01-verification.json").read_text(encoding="utf-8"))
        self.assertEqual(proj["verdict"], "PASS")
        self.reload_state()
        self.assertEqual(len(self.state["reviews"]), 1)

    def test_commit_revise_routes_executing_and_assigns_ids(self):
        res, rc = self.commit_candidate(
            self.rid, verdict="REVISE",
            critical=[{"severity": "BLOCKING", "what": "缺场景", "why": "门禁", "change": "补"}],
            required=[{"what": "AC 不足", "why": "欠定义", "change": "补 AC"}])
        self.assertEqual(rc, 0, res["errors"])
        self.assertEqual(res["status"], "COMMITTED")
        self.assertEqual(res["state_status"], "EXECUTING")
        review = json.loads((self.review_dir(self.rid) / "review.json").read_text(encoding="utf-8"))
        self.assertEqual([f["id"] for f in review["findings"]], ["F001", "F002"])

    def test_commit_replan_routes_planning(self):
        res, rc = self.commit_candidate(self.rid, verdict="REPLAN")
        self.assertEqual(rc, 0, res["errors"])
        self.assertEqual(res["state_status"], "PLANNING")
        self.reload_state()
        self.assertEqual(self.state["iteration"], 2)

    def test_commit_blocked_input_waiting(self):
        res, rc = self.commit_candidate(self.rid, verdict="BLOCKED")
        self.assertEqual(rc, 0, res["errors"])
        self.assertEqual(res["state_status"], "WAITING_FOR_INPUT")
        self.reload_state()
        self.assertEqual(self.state["resume_to"], "VERIFYING")

    def test_commit_blocked_spec_requires_gaps(self):
        res, rc = self.commit_candidate(
            self.rid, verdict="BLOCKED", blocked={"kind": "WAITING_FOR_SPEC"})
        self.assertNotEqual(rc, 0)
        self.assertEqual(res["status"], "REJECTED")
        self.assertFalse((self.review_dir(self.rid) / "review.json").exists(),
                         "校验失败不得留下半提交 review")

    def test_commit_blocked_spec_with_gaps_routes(self):
        res, rc = self.commit_candidate(
            self.rid, verdict="BLOCKED",
            blocked={"kind": "WAITING_FOR_SPEC",
                     "spec_gaps": [{"what": "登录方式未定", "spec_anchor": "§1", "blocks": "S1"}]})
        self.assertEqual(rc, 0, res["errors"])
        self.assertEqual(res["state_status"], "WAITING_FOR_SPEC")
        self.reload_state()
        self.assertTrue(self.state["spec_gaps"])
        proc = subprocess.run([sys.executable, str(VALIDATE), str(self.decompose)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout)  # R4 互锁满足

    def test_candidate_bad_input_sha_rejected(self):
        res, rc = self.commit_candidate(self.rid, input_sha="0" * 64)
        self.assertNotEqual(rc, 0)
        self.assertFalse((self.review_dir(self.rid) / "review.json").exists())

    def test_candidate_scope_mismatch_rejected(self):
        res, rc = self.commit_candidate(self.rid, scope="delta")
        self.assertNotEqual(rc, 0)
        self.assertIn("scope", "".join(res["errors"]))

    def test_pass_below_gate_rejected(self):
        art = self.load_artifact()
        art["artifact"]["epics"][0]["features"][0]["stories"][0]["scenarios"] = [
            {"class": "normal", "given": "g", "when": "w", "then": "t"}]
        self.save_artifact(art)
        self.run_ok()  # artifact 变化 → 重建待审输入(coverage 随之变化)
        res, rc = self.commit_candidate("r001", verdict="PASS")
        self.assertNotEqual(rc, 0)
        self.assertTrue(any("门禁" in e for e in res["errors"]), res["errors"])

    def test_delta_pass_missing_resolution_rejected(self):
        self.baseline(verdict="REVISE",
                      critical=[{"severity": "BLOCKING", "what": "缺", "why": "why", "change": "补"}])
        self.revise_artifact(lambda a: a["artifact"]["epics"][0]["features"][0]["stories"][0]
                             .__setitem__("title", "修复"))
        rid, inp = self.dispatch()
        self.assertEqual(inp["scope"], "delta")
        self.assertEqual([f["id"] for f in inp["open_findings"]], ["F001"])
        res, rc = self.commit_candidate(rid, verdict="PASS", scope="delta")
        self.assertNotEqual(rc, 0)
        self.assertTrue(any("核销" in e for e in res["errors"]), res["errors"])
        # 补上核销后可提交
        res, rc = self.commit_candidate(
            rid, verdict="PASS", scope="delta",
            resolutions=[{"finding_id": "F001", "resolved": True, "note": "已补场景"}])
        self.assertEqual(rc, 0, res["errors"])


class ChainCompleteTest(FlowMixin, ReviewFixture):
    """任务 3.4/4.1/4.2/5.3:审查链、COMPLETE 门禁、旧运行兼容、中断恢复。"""

    def cycle(self, verdict, scope, critical=None, required=None, resolutions=None):
        rid, _inp = self.dispatch()
        assert scope == _inp["scope"], f"期望 scope={scope},实际 {_inp['scope']}"
        return self.commit_candidate(rid, verdict=verdict, scope=scope,
                                     critical=critical, required=required,
                                     resolutions=resolutions)

    def test_full_revise_delta_revise_delta_pass_completes(self):
        """spec 场景:full REVISE → delta REVISE → delta PASS,必改项全核销后可完成。"""
        rid1, res, rc = self.baseline(
            verdict="REVISE",
            critical=[{"severity": "BLOCKING", "what": "缺场景", "why": "门禁", "change": "补"}])
        self.assertEqual(rc, 0, res["errors"])
        # 修订 1:未解决 F001,又引入 F002
        self.revise_artifact(lambda a: a["artifact"]["epics"][0]["features"][0]["stories"][0]
                             .__setitem__("title", "修复 1"))
        res, rc = self.cycle(
            "REVISE", "delta",
            required=[{"what": "AC 不足", "why": "欠定义", "change": "补 AC"}],
            resolutions=[{"finding_id": "F001", "resolved": False, "note": "尚未修复"}])
        self.assertEqual(rc, 0, res["errors"])
        self.assertEqual(res["state_status"], "EXECUTING")
        # 修订 2:两项都核销 → delta PASS
        self.revise_artifact(lambda a: a["artifact"]["epics"][0]["features"][0]["stories"][0]
                             .__setitem__("title", "修复 2"))
        res, rc = self.cycle("PASS", "delta",
                             resolutions=[{"finding_id": "F001", "resolved": True},
                                          {"finding_id": "F002", "resolved": True}])
        self.assertEqual(rc, 0, res["errors"])
        self.assertEqual(res["status"], "AWAIT_USER_CONFIRMATION")
        rid3 = res["review"]["id"]
        self.confirm(rid3)
        res = self.run_ok()
        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["state_status"], "COMPLETE")
        self.reload_state()
        self.assertEqual(self.state["user_confirmation"]["artifact_sha256"],
                         sha256_file(self.artifact_path()))
        # 历史 REVISE 保留,不要求全部历史为 PASS
        verdicts = [json.loads((self.decompose / e["path"]).read_text(encoding="utf-8"))["verdict"]
                    for e in self.state["reviews"]]
        self.assertEqual(verdicts, ["REVISE", "REVISE", "PASS"])
        # validate.py 全绿(R11 互锁)
        proc = subprocess.run([sys.executable, str(VALIDATE), str(self.decompose)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        # 完成后重跑:幂等停在已 COMPLETE
        res = self.run_ok()
        self.assertEqual(res["status"], "WAITING")

    def test_pass_with_unresolved_resolution_rejected(self):
        """最新 review 想 PASS 但旧必改项未关闭:提交被拒,不得进入 COMPLETE。"""
        self.baseline(verdict="REVISE",
                      critical=[{"severity": "BLOCKING", "what": "缺", "why": "w", "change": "c"}])
        self.revise_artifact(lambda a: a["artifact"]["epics"][0]["features"][0]["stories"][0]
                             .__setitem__("title", "修一半"))
        res, rc = self.cycle("PASS", "delta",
                             resolutions=[{"finding_id": "F001", "resolved": False}])
        self.assertNotEqual(rc, 0)
        self.assertTrue(any("未解决" in e for e in res["errors"]), res["errors"])

    def test_confirmation_wrong_artifact_sha_rejected(self):
        rid, res, rc = self.baseline()
        self.assertEqual(rc, 0, res["errors"])
        self.confirm(rid, artifact_sha="0" * 64)
        res = self.run_fail()
        self.assertTrue(any("artifact 哈希" in e for e in res["errors"]), res["errors"])
        self.reload_state()
        self.assertNotEqual(self.state["status"], "COMPLETE")

    def test_pass_then_artifact_edit_requires_new_review(self):
        """PASS 后编辑目录:不完成,重新审查;旧确认作废,重新确认后才 COMPLETE。"""
        rid1, res, rc = self.baseline()
        self.assertEqual(rc, 0, res["errors"])
        self.confirm(rid1)  # 用户先确认了……
        self.revise_artifact(lambda a: a["artifact"]["epics"][0]["features"][0]["stories"][0]
                             .__setitem__("title", "确认后又改"))  # ……之后又编辑
        res = self.run_ok()
        self.assertEqual(res["status"], "DISPATCHED")  # 不走完成,重新审查
        res, rc = self.cycle("PASS", "delta")
        self.assertEqual(rc, 0, res["errors"])
        rid2 = res["review"]["id"]
        res = self.run_fail()  # 旧确认绑 r001,对 r002 无效
        self.assertTrue(any("哈希" in e or "失效" in e for e in res["errors"]), res["errors"])
        self.confirm(rid2)
        res = self.run_ok()
        self.assertEqual(res["status"], "COMPLETED")

    def test_output_tamper_blocks_complete(self):
        rid, res, rc = self.baseline()
        self.assertEqual(rc, 0, res["errors"])
        out = self.decompose / "output" / "catalog.md"
        out.write_text(out.read_text(encoding="utf-8") + "\n<!-- 篡改 -->\n", encoding="utf-8")
        self.confirm(rid)
        res = self.run_fail()
        self.assertTrue(any("渲染不一致" in e for e in res["errors"]), res["errors"])

    def test_legacy_run_needs_full_approval(self):
        """旧运行只有无法绑定冻结输入的 verification:不得作基线,须批准 full。"""
        self.flush_state(status="VERIFYING")
        write_json(self.decompose / "iterations" / "01-verification.json", {
            "verdict": "PASS", "scores": {k: 4 for k in
                                          ["coverage", "granularity", "hierarchy", "completeness",
                                           "actionability", "scenario_coverage", "traceability"]},
            "coverage": self.coverage_pair(), "strengths": [], "critical_issues": [],
            "warnings": [], "required_changes": [], "evidence_gaps": [], "confidence": "high"})
        proc = subprocess.run([sys.executable, str(VALIDATE), str(self.decompose)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout)  # 旧文件仍可读(validate.py 兼容)
        res = self.run_fail()
        self.assertEqual(res["status"], "PAUSED")
        self.assertTrue(any("旧运行" in e for e in res["errors"]), res["errors"])
        import re as _re
        digest = _re.search(r"named_inputs_digest=([0-9a-f]{64})", "\n".join(res["errors"])).group(1)
        write_json(self.decompose / "reviews" / "full-approval.json",
                   {"named_inputs_digest": digest, "source": "用户批准重建基线", "date": "2026-10-29"})
        _rid, inp = self.dispatch()
        self.assertEqual(inp["scope"], "full")

    def test_history_tamper_detected(self):
        self.baseline(verdict="REVISE",
                      critical=[{"severity": "BLOCKING", "what": "缺", "why": "w", "change": "c"}])
        self.revise_artifact(lambda a: a["artifact"]["epics"][0]["features"][0]["stories"][0]
                             .__setitem__("title", "修复"))
        self.cycle("PASS", "delta", resolutions=[{"finding_id": "F001", "resolved": True}])
        # 篡改历史 review
        rj = self.decompose / "reviews" / "r001" / "review.json"
        doc = json.loads(rj.read_text(encoding="utf-8"))
        doc["verdict"] = "PASS"
        write_json(rj, doc)
        res = self.run_fail()
        self.assertTrue(any("SHA-256" in e or "篡改" in e for e in res["errors"]), res["errors"])

    def test_chain_break_detected(self):
        self.baseline(verdict="REVISE",
                      critical=[{"severity": "BLOCKING", "what": "缺", "why": "w", "change": "c"}])
        self.revise_artifact(lambda a: a["artifact"]["epics"][0]["features"][0]["stories"][0]
                             .__setitem__("title", "修复"))
        self.cycle("PASS", "delta", resolutions=[{"finding_id": "F001", "resolved": True}])
        # 断链:中环 r002 的冻结 input 被删,前后无法互证
        (self.decompose / "reviews" / "r002" / "input.json").unlink()
        res = self.run_fail()
        self.assertEqual(res["status"], "REJECTED")
        self.assertTrue(any("冻结输入" in e or "链" in e for e in res["errors"]), res["errors"])

    def test_interrupted_commit_recovered(self):
        """写边界中断:review.json 已落盘、登记/路由未写 → 重跑幂等补齐。"""
        rid, res, rc = self.baseline()
        self.assertEqual(rc, 0, res["errors"])
        self.assertEqual(res["status"], "AWAIT_USER_CONFIRMATION")
        # 模拟崩溃回滚:state 恢复到提交前(EXECUTING、无登记)
        state = json.loads((self.decompose / "state.json").read_text(encoding="utf-8"))
        state["reviews"] = []
        state["status"] = "EXECUTING"
        write_json(self.decompose / "state.json", state)
        res = self.run_ok()
        self.assertEqual(res["status"], "AWAIT_USER_CONFIRMATION")  # 补齐登记+路由后停对位置
        self.reload_state()
        self.assertEqual(len(self.state["reviews"]), 1)
        self.assertEqual(self.state["status"], "VERIFYING")
        # 再跑一次:幂等,不再变
        snapshot = json.dumps(self.state, sort_keys=True)
        res = self.run_ok()
        self.reload_state()
        self.assertEqual(json.dumps(self.state, sort_keys=True), snapshot)

    def test_complete_state_with_missing_history_detected(self):
        """state 已 COMPLETE 但审查历史缺失:复核不通过,不得当作完成。"""
        rid, res, rc = self.baseline()
        self.confirm(rid)
        res = self.run_ok()
        self.assertEqual(res["status"], "COMPLETED")
        import shutil
        shutil.rmtree(self.decompose / "reviews")
        self.reload_state()
        res = self.run_fail()
        self.assertTrue(any("COMPLETE" in e or "登记" in e for e in res["errors"]), res["errors"])


    def test_global_defaults_change_delta_and_dep_adjust(self):
        """全局表态(覆盖策略)变化与依赖调整:影响可确定,仍走 delta,影响闭包记录。"""
        self.baseline()
        def mutate(a):
            a["artifact"]["category_defaults"]["applicable"].append("boundary")
            a["artifact"]["epics"][0]["features"][0]["stories"].append(make_story("S2"))
            a["artifact"]["dependencies"].append(
                {"from": "S1", "to": "S2", "type": "blocked-by"})
        self.revise_artifact(mutate)
        _rid, inp = self.dispatch()
        self.assertEqual(inp["scope"], "delta")
        self.assertTrue(inp["diff"]["category_defaults_changed"])
        self.assertIn("S1", inp["impact_closure"]["affected_ids"], "全局策略变化须波及全部 story")
        self.assertIn("S2", inp["impact_closure"]["affected_ids"])
        self.assertTrue(any(e[:2] == ["S1", "S2"] for e in inp["diff"]["dependencies"]["added"]))

    def test_blocked_recovery_redispatches_delta(self):
        """BLOCKED 恢复:用户拍板(DECISION 入账本、回 VERIFYING)后重新派发,delta 生效。"""
        self.baseline(verdict="BLOCKED")
        self.reload_state()
        self.assertEqual(self.state["status"], "WAITING_FOR_INPUT")
        # 用户拍板 → 记 DECISION,清阻塞字段,回 VERIFYING
        self.state["evidence"].append(
            {"claim": "登录方式拍板", "type": "DECISION", "evidence": "用户 2026-10-29", "confidence": "high"})
        self.state["status"] = "VERIFYING"
        self.state.pop("resume_to", None)
        self.flush_state()
        rid, inp = self.dispatch()
        self.assertEqual(inp["scope"], "delta")
        self.assertTrue(any(c == "登录方式拍板" for c, _t in inp["ledger_diff"]["added"]),
                        inp["ledger_diff"])

    def test_refull_keeps_open_findings(self):
        """重新 full 换基线,不丢弃旧必改项:继承核销义务,未核销的 full PASS 被拒。"""
        self.baseline(verdict="REVISE",
                      critical=[{"severity": "BLOCKING", "what": "缺", "why": "w", "change": "c"}])
        self.spec.write_text("# Spec v2\n\n§1 用户可用邮箱登录。\n", encoding="utf-8")
        res = self.run_fail()  # 上游变化 → 暂停
        import re as _re
        digest = _re.search(r"named_inputs_digest=([0-9a-f]{64})", "\n".join(res["errors"])).group(1)
        write_json(self.decompose / "reviews" / "full-approval.json",
                   {"named_inputs_digest": digest, "source": "用户批准重新 full", "date": "2026-10-29"})
        rid, inp = self.dispatch()
        self.assertEqual(inp["scope"], "full")
        self.assertEqual([f["id"] for f in inp["open_findings"]], ["F001"],
                         "重新 full 必须继承未关闭必改项")
        res, rc = self.commit_candidate(rid, verdict="PASS", scope="full")  # 未核销 F001
        self.assertNotEqual(rc, 0)
        res, rc = self.commit_candidate(
            rid, verdict="PASS", scope="full",
            resolutions=[{"finding_id": "F001", "resolved": True, "note": "换基线时已修复"}])
        self.assertEqual(rc, 0, res["errors"])
        self.confirm(rid)
        res = self.run_ok()
        self.assertEqual(res["status"], "COMPLETED")


class PathSafetyTest(ReviewFixture):
    """登记册路径安全:穿越式文件名/路径不得把读写带出运行目录。"""

    def test_traversal_artifact_name_ignored(self):
        """artifacts 登记含 ../ 条目时不被选用,不读运行目录外的文件。"""
        outside = self.ws / "outside-artifact.json"
        write_json(outside, make_artifact())
        self.state["artifacts"] = ["../../outside-artifact.json"]
        self.flush_state()
        res = self.run_ok()
        self.assertEqual(res["status"], "WAITING")
        self.assertFalse(self.review_dir("r001").exists(), "不得据穿越路径派发审查")

    def test_traversal_review_registry_path_rejected(self):
        """reviews 登记册 path 非法(穿越)时整体拒绝。"""
        self.flush_state()
        self.state["reviews"] = [
            {"id": "r001", "path": "../../outside-review.json", "sha256": "0" * 64}]
        self.state["status"] = "VERIFYING"
        self.flush_state()
        res = self.run_fail()
        self.assertEqual(res["status"], "REJECTED")
        self.assertTrue(any("path 非法" in e for e in res["errors"]), res["errors"])


if __name__ == "__main__":
    unittest.main()
