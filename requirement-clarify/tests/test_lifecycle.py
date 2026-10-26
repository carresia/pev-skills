"""生命周期测试:init / commit plan|artifact / verdict 分叉 / state-update 恢复 / reopen / 上限。

每个测试名描述被验证的行为;夹具全部合成(见 helpers.py)。
"""

import json
import unittest

from tests.helpers import (
    RcDir, assert_protocol, min_artifact, min_ledger, min_plan,
    min_spec_body, min_state, min_verification, out_json, run_script,
    snapshot_for,
)


def read_state(rc):
    return json.loads((rc.root / "state.json").read_text(encoding="utf-8"))


def transitions(state):
    return state.get("transitions", [])


class TestInit(unittest.TestCase):
    def setUp(self):
        self.ws = RcDir(round_name="prd-2026-01-01")
        # init 要落到新轮次;去掉构造器预建的 rc 目录,模拟"尚无澄清轮"
        import shutil
        shutil.rmtree(self.ws.round)
        self.ws.round.mkdir(parents=True)

    def tearDown(self):
        self.ws.cleanup()

    def test_init_creates_round_with_state_and_points_to_planning(self):
        prd = self.ws.write_prd()
        obj = self.ws.write_draft("objective.json", {"goal": "降低登录失败率"})
        proc = run_script("init.py", "--workspace", str(self.ws.workspace),
                          "--prd-source", str(prd), "--objective", str(obj))
        payload = out_json(proc)
        assert_protocol(payload)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["status"], "INIT")
        self.assertEqual(payload["iteration"], 0)
        self.assertTrue((self.ws.round / "rc" / "state.json").is_file())
        state = read_state(self.ws)
        self.assertEqual(state["prd_source"], str(prd))
        self.assertEqual(payload["next"][0]["kind"], "draft")

    def test_init_uses_existing_round_when_prd_inside_pev(self):
        prd = self.ws.write_prd()  # 位于 .pev/prd-2026-01-01/pm/output/
        obj = self.ws.write_draft("objective.json", {"goal": "g"})
        proc = run_script("init.py", "--workspace", str(self.ws.workspace),
                          "--prd-source", str(prd), "--objective", str(obj))
        payload = out_json(proc)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue((self.ws.round / "rc" / "state.json").is_file())

    def test_init_is_idempotent_on_active_round(self):
        prd = self.ws.write_prd()
        obj = self.ws.write_draft("objective.json", {"goal": "g"})
        first = out_json(run_script("init.py", "--workspace", str(self.ws.workspace),
                                    "--prd-source", str(prd), "--objective", str(obj)))
        self.assertTrue(first["ok"])
        second = out_json(run_script("init.py", "--workspace", str(self.ws.workspace),
                                     "--prd-source", str(prd), "--objective", str(obj)))
        self.assertTrue(second["ok"])
        self.assertEqual(second["written"], [], "幂等续用不得重写 state")

    def test_init_locate_reports_rounds_without_blocking(self):
        prd = self.ws.write_prd()
        obj = self.ws.write_draft("objective.json", {"goal": "g"})
        run_script("init.py", "--workspace", str(self.ws.workspace),
                   "--prd-source", str(prd), "--objective", str(obj))
        payload = out_json(run_script("init.py", "--locate", "--workspace",
                                      str(self.ws.workspace)))
        assert_protocol(payload)
        self.assertTrue(payload["ok"])
        self.assertTrue(any("prd-2026-01-01" in w for w in payload["warnings"]),
                        payload["warnings"])

    def test_init_restart_archives_and_rebuilds(self):
        prd = self.ws.write_prd()
        obj = self.ws.write_draft("objective.json", {"goal": "g"})
        run_script("init.py", "--workspace", str(self.ws.workspace),
                   "--prd-source", str(prd), "--objective", str(obj))
        payload = out_json(run_script("init.py", "--workspace", str(self.ws.workspace),
                                      "--prd-source", str(prd), "--objective", str(obj),
                                      "--restart"))
        self.assertTrue(payload["ok"], payload)
        archives = [p.name for p in self.ws.round.iterdir()
                    if p.name.startswith("rc.bak-")]
        self.assertEqual(len(archives), 1, archives)
        self.assertTrue((self.ws.round / "rc" / "state.json").is_file())
        self.assertEqual(read_state(self.ws)["status"], "INIT")

    def test_init_without_goal_waits_for_input(self):
        prd = self.ws.write_prd()
        obj = self.ws.write_draft("objective.json", {})
        payload = out_json(run_script("init.py", "--workspace", str(self.ws.workspace),
                                      "--prd-source", str(prd), "--objective", str(obj)))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "WAITING_FOR_INPUT")
        state = read_state(self.ws)
        self.assertEqual(state["resume_to"], "PLANNING")
        self.assertEqual(payload["next"][0]["kind"], "ask-user")

    def test_init_without_prd_source_is_rejected(self):
        obj = self.ws.write_draft("objective.json", {"goal": "g"})
        payload = out_json(run_script("init.py", "--workspace", str(self.ws.workspace),
                                      "--objective", str(obj)))
        self.assertFalse(payload["ok"])


class TestCommitPlan(unittest.TestCase):
    def setUp(self):
        self.rc = RcDir()

    def tearDown(self):
        self.rc.cleanup()

    def commit_plan(self, plan=None):
        draft = self.rc.write_draft("plan.json", plan or min_plan())
        return out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                   "plan", str(draft)))

    def test_plan_commit_persists_registers_and_enters_executing(self):
        payload = self.commit_plan()
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["status"], "EXECUTING")
        self.assertTrue((self.rc.iter_dir / "01-plan.json").is_file())
        state = read_state(self.rc)
        self.assertIn("01-plan.json", state["plans"])
        self.assertEqual(state["status"], "EXECUTING")
        self.assertEqual(transitions(state)[-1]["to"], "EXECUTING")
        self.assertEqual(payload["next"][0]["kind"], "draft")

    def test_plan_violating_value_first_is_rejected(self):
        plan = min_plan()
        plan["plan"] = [s for s in plan["plan"] if s["action"] != "interrogate_value"]
        payload = self.commit_plan(plan)
        self.assertFalse(payload["ok"])
        self.assertFalse((self.rc.iter_dir / "01-plan.json").exists(),
                         "被拒草稿不得落盘")
        self.assertEqual(read_state(self.rc)["status"], "INIT")

    def test_plan_commit_outside_planning_stage_is_rejected(self):
        self.rc.advance_to("EXECUTING")
        payload = self.commit_plan()
        self.assertFalse(payload["ok"])
        self.assertEqual(read_state(self.rc)["status"], "EXECUTING")


class TestCommitArtifact(unittest.TestCase):
    def setUp(self):
        self.rc = RcDir()
        self.rc.advance_to("EXECUTING")

    def tearDown(self):
        self.rc.cleanup()

    def commit_artifact(self, art):
        draft = self.rc.write_draft("artifact.json", art)
        return out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                   "artifact", str(draft)))

    def test_completed_artifact_enters_verifying_and_freezes_snapshot(self):
        payload = self.commit_artifact(min_artifact())
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["status"], "VERIFYING")
        self.assertTrue((self.rc.iter_dir / "01-artifact.json").is_file())
        snap_path = self.rc.iter_dir / "01-verification-input.json"
        self.assertTrue(snap_path.is_file(), "completed 提交必须自动冻结验证输入快照")
        state = read_state(self.rc)
        self.assertEqual(transitions(state)[-1]["to"], "VERIFYING")
        self.assertEqual(payload["next"][0]["kind"], "dispatch-verifier")

    def test_artifact_evidence_is_synced_into_ledger(self):
        art = min_artifact(evidence=[min_ledger(type_="DECISION",
                                                evidence="01-artifact answers#q1")])
        self.commit_artifact(art)
        state = read_state(self.rc)
        types = [e["type"] for e in state.get("evidence", [])]
        self.assertIn("DECISION", types, "DECISION 须自动并入 state.evidence")

    def test_replan_branch_returns_to_planning_with_next_iteration(self):
        payload = self.commit_artifact(min_artifact("replan_required"))
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "PLANNING")
        self.assertEqual(state["iteration"], 1)
        self.assertEqual(payload["next"][0]["kind"], "draft")

    def test_blocked_branch_waits_with_resume_point(self):
        payload = self.commit_artifact(min_artifact("blocked"))
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "WAITING_FOR_INPUT")
        self.assertEqual(state["resume_to"], "EXECUTING")
        self.assertEqual(payload["next"][0]["kind"], "ask-user")

    def test_blocked_without_reason_is_rejected(self):
        art = min_artifact("blocked")
        art.pop("replan_reason")
        payload = self.commit_artifact(art)
        self.assertFalse(payload["ok"])
        self.assertEqual(read_state(self.rc)["status"], "EXECUTING")


class TestCommitVerificationBranches(unittest.TestCase):
    def setUp(self):
        self.rc = RcDir()
        self.rc.advance_to("VERIFYING")
        self.snap = json.loads(
            (self.rc.iter_dir / "01-verification-input.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.rc.cleanup()

    def commit_verification(self, ver):
        draft = self.rc.write_draft("verification.json", ver)
        return out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                   "verification", str(draft)))

    def test_revise_branch_advances_iteration_without_publishing(self):
        payload = self.commit_verification(min_verification("REVISE", snap=self.snap))
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "EXECUTING")
        self.assertEqual(state["iteration"], 1)
        self.assertFalse(self.rc.spec_path().exists(), "REVISE 不得触发渲染")
        self.assertEqual(payload["next"][0]["kind"], "draft")

    def test_replan_branch_returns_to_planning(self):
        payload = self.commit_verification(min_verification("REPLAN", snap=self.snap))
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "PLANNING")
        self.assertEqual(state["iteration"], 1)

    def test_blocked_verdict_waits_for_input(self):
        payload = self.commit_verification(min_verification("BLOCKED", snap=self.snap))
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "WAITING_FOR_INPUT")
        self.assertEqual(state["resume_to"], "VERIFYING")

    def test_report_without_snapshot_echo_is_rejected(self):
        payload = self.commit_verification(min_verification("REVISE"))
        self.assertFalse(payload["ok"], "报告必须复述快照")

    def test_report_with_stale_snapshot_echo_is_rejected(self):
        stale = dict(self.snap)
        stale["artifact_sha256"] = "0" * 64
        payload = self.commit_verification(min_verification("REVISE", snap=stale))
        self.assertFalse(payload["ok"], "复述与盘上快照不一致的报告不可提交")

    def test_wrong_stage_submission_is_rejected(self):
        self.rc.state["status"] = "EXECUTING"
        self.rc.flush_state()
        payload = self.commit_verification(min_verification("REVISE", snap=self.snap))
        self.assertFalse(payload["ok"])


class TestStateUpdate(unittest.TestCase):
    def setUp(self):
        self.rc = RcDir()

    def tearDown(self):
        self.rc.cleanup()

    def state_update(self, patch):
        draft = self.rc.write_draft("patch.json", patch)
        return out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                   "state-update", str(draft)))

    def blocked_executing(self):
        self.rc.advance_to("EXECUTING")
        self.commit_blocked()
        self.rc.state["status"] = "WAITING_FOR_INPUT"
        self.rc.state["resume_to"] = "EXECUTING"
        self.rc.flush_state()

    def commit_blocked(self):
        art = min_artifact("blocked", unresolved=[{"question": "q1"}])
        draft = self.rc.write_draft("artifact.json", art)
        return out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                   "artifact", str(draft)))

    def test_answer_resume_restores_stage_and_merges_answers(self):
        self.blocked_executing()
        payload = self.state_update({
            "evidence": [min_ledger(2, "DECISION", "锁定 10 分钟",
                                    "01-artifact answers#q1")],
            "answers": [{"question": "q1", "answer": "锁定 10 分钟",
                         "source": "用户答复"}],
        })
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "EXECUTING")
        self.assertNotIn("resume_to", state)
        art = json.loads((self.rc.iter_dir / "01-artifact.json").read_text(encoding="utf-8"))
        self.assertEqual(art["answers"][0]["question"], "q1", "答复须并入当前 Artifact")
        self.assertEqual(payload["next"][0]["kind"], "draft")

    def test_invalidate_plan_returns_to_planning_with_next_iteration(self):
        self.blocked_executing()
        payload = self.state_update({"invalidate_plan": True})
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "PLANNING")
        self.assertEqual(state["iteration"], 1)

    def test_back_to_prd_sets_gaps_and_waits_for_prd(self):
        self.blocked_executing()
        payload = self.state_update({
            "back_to_prd": True,
            "prd_gaps": [{"question": "验证码失败率的口径?",
                          "prd_anchor": "PRD §6"}],
        })
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "WAITING_FOR_PRD")
        self.assertEqual(len(state["prd_gaps"]), 1)

    def test_prd_refreshed_clears_gaps_and_replans(self):
        self.rc.state = min_state(status="WAITING_FOR_PRD", iteration=1,
                                  prd_gaps=[{"question": "q", "prd_anchor": "§6"}])
        self.rc.flush_state()
        payload = self.state_update({"prd_refreshed": True})
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "PLANNING")
        self.assertEqual(state["iteration"], 2)
        self.assertEqual(state["prd_gaps"], [])

    def test_state_update_after_complete_is_frozen(self):
        self.rc.state = min_state(status="COMPLETE", iteration=1)
        self.rc.flush_state()
        payload = self.state_update({"evidence": [min_ledger(9)]})
        self.assertFalse(payload["ok"], "COMPLETE 后语义写入冻结,续工作须 reopen")


class TestReopen(unittest.TestCase):
    def setUp(self):
        self.rc = RcDir()
        self.rc.state = min_state(status="COMPLETE", iteration=1)
        self.rc.flush_state()
        self.rc.advance_to("VERIFYING")  # 落盘 01-plan/01-artifact(编号仍 01,夹具从简)
        # 手工落一份已绑定 PASS 的历史报告,模拟已收口轮
        self.rc.write_doc(1, "verification",
                          min_verification("PASS", snap={"algorithm": "rc-sha256-v1"},
                                           provenance={"algorithm": "rc-sha256-v1"}),
                          register=False)
        self.rc.state["status"] = "COMPLETE"
        self.rc.flush_state()

    def tearDown(self):
        self.rc.cleanup()

    def reopen(self, note="修订 §4 规则"):
        return out_json(run_script("reopen.py", "--rc-root", str(self.rc.root),
                                   "--note", note))

    def test_reopen_increments_once_and_returns_to_executing(self):
        before = read_state(self.rc)
        payload = self.reopen()
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["iteration"], before["iteration"] + 1)
        self.assertEqual(state["status"], "EXECUTING")
        self.assertTrue((self.rc.iter_dir / "01-verification.json").is_file(),
                        "历史报告不删除")

    def test_reopen_requires_note(self):
        payload = out_json(run_script("reopen.py", "--rc-root", str(self.rc.root)))
        self.assertFalse(payload["ok"])

    def test_reopen_same_note_rerun_is_idempotent(self):
        self.reopen()
        state_after_first = read_state(self.rc)
        payload = self.reopen()
        self.assertTrue(payload["ok"], "同 note 重跑应判已执行")
        state = read_state(self.rc)
        self.assertEqual(state["iteration"], state_after_first["iteration"],
                         "重跑不得再次递增")

    def test_reopen_from_active_non_complete_round_is_rejected(self):
        self.reopen()  # 现在 EXECUTING
        payload = self.reopen("再开一次")
        self.assertFalse(payload["ok"], "活跃轮不走 reopen;继续正常流程")


class TestIterationCap(unittest.TestCase):
    def setUp(self):
        self.rc = RcDir()
        self.rc.state = min_state(status="VERIFYING", iteration=1, max_iterations=1)
        self.rc.flush_state()
        plan = min_plan()
        art = min_artifact()
        self.rc.write_doc(1, "plan", plan)
        self.rc.write_doc(2, "artifact", art)
        snap = snapshot_for(self.rc.state, plan, "iterations/01-plan.json", art, 2)
        self.rc.write_doc(2, "verification-input", snap, register=False)

    def tearDown(self):
        self.rc.cleanup()

    def test_revise_over_limit_is_refused_without_transition(self):
        draft = self.rc.write_draft("verification.json", min_verification(
            "REVISE",
            snap=json.loads((self.rc.iter_dir / "02-verification-input.json")
                            .read_text(encoding="utf-8"))))
        payload = out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                      "verification", str(draft)))
        self.assertFalse(payload["ok"])
        state = read_state(self.rc)
        self.assertEqual(state["iteration"], 1, "超限不得递增")
        self.assertEqual(state["status"], "VERIFYING")
        self.assertTrue(any(n.get("kind") == "stop" for n in payload["next"]),
                        payload["next"])


class TestProtocolShapes(unittest.TestCase):
    def test_every_command_emits_single_line_json_protocol(self):
        rc = RcDir()
        try:
            plan_draft = rc.write_draft("plan.json", min_plan())
            for args in (
                ("init.py", "--locate", "--workspace", str(rc.workspace)),
                ("commit.py", "--rc-root", str(rc.root), "plan", str(plan_draft)),
                ("validate.py", "--rc-root", str(rc.root)),
            ):
                proc = run_script(*args)
                payload = out_json(proc)
                assert_protocol(payload)
                self.assertIsInstance(payload["ok"], bool)
        finally:
            rc.cleanup()


if __name__ == "__main__":
    unittest.main()
