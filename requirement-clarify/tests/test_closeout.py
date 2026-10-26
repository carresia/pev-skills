"""收口测试:PASS 单命令收口链、交付资格门(N02–N06/N13)、渲染确定性、协议形状。"""

import json
import unittest

from tests.helpers import (
    RcDir, assert_protocol, min_artifact, min_plan, min_state,
    min_verification, out_json, run_script, snapshot_for,
)


def read_state(rc):
    return json.loads((rc.root / "state.json").read_text(encoding="utf-8"))


class CloseoutFixture(unittest.TestCase):
    """推进到 VERIFYING(快照已冻结),随时可提交 PASS 报告。"""

    def setUp(self):
        self.rc = RcDir()
        self.rc.advance_to("VERIFYING")
        self.snap = json.loads(
            (self.rc.iter_dir / "01-verification-input.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.rc.cleanup()

    def commit_pass(self, ver=None):
        ver = ver or min_verification("PASS", snap=self.snap)
        draft = self.rc.write_draft("verification.json", ver)
        return out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                   "verification", str(draft)))


class TestPassCloseout(CloseoutFixture):
    def test_single_pass_commit_publishes_and_completes(self):
        payload = self.commit_pass()
        self.assertTrue(payload["ok"], payload)
        spec = self.rc.spec_path()
        self.assertTrue(spec.is_file(), "PASS 提交须在同一命令内发布 spec.md")
        text = spec.read_text(encoding="utf-8")
        self.assertIn("滑块验证码改造工程 Spec", text, "标题须来自 artifact")
        self.assertIn("滑块失败 3 次锁定 10 分钟", text, "rules 循环须展开")
        self.assertIn("滑块通过率", text, "data_metrics 表格行须展开")
        self.assertNotIn("{{", text, "发布物不得残留占位符")
        state = read_state(self.rc)
        self.assertEqual(state["status"], "COMPLETE")
        self.assertEqual(state["transitions"][-1]["event"], "complete")
        report = json.loads(
            (self.rc.iter_dir / "01-verification.json").read_text(encoding="utf-8"))
        self.assertIn("provenance", report, "收口前必须完成绑定复算并写入 provenance")
        self.assertTrue(any(n.get("kind") == "stop" for n in payload["next"]),
                        payload["next"])

    def test_render_is_deterministic_across_runs(self):
        self.commit_pass()
        first = self.rc.spec_path().read_bytes()
        import shutil
        second_ws = RcDir()
        try:
            shutil.rmtree(second_ws.round / "rc")
            shutil.copytree(self.rc.root, second_ws.round / "rc")
            plan = json.loads((second_ws.iter_dir / "01-plan.json").read_text(encoding="utf-8"))
            art = json.loads((second_ws.iter_dir / "01-artifact.json").read_text(encoding="utf-8"))
            state = read_state(second_ws)
            snap = snapshot_for(state, plan, "iterations/01-plan.json", art, 1)
            (second_ws.iter_dir / "01-verification-input.json").write_text(
                json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            ver = min_verification("PASS", snap=snap)
            draft = second_ws.write_draft("verification.json", ver)
            payload = out_json(run_script("commit.py", "--rc-root",
                                          str(second_ws.root), "verification",
                                          str(draft)))
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(second_ws.spec_path().read_bytes(), first,
                             "同来源两次渲染必须逐字节一致")
        finally:
            second_ws.cleanup()

    def test_input_drift_after_snapshot_refuses_pass(self):
        art_path = self.rc.iter_dir / "01-artifact.json"
        art = json.loads(art_path.read_text(encoding="utf-8"))
        art["artifact"]["title"] = "被改动过的标题"
        art_path.write_text(json.dumps(art, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        payload = self.commit_pass()
        self.assertFalse(payload["ok"], "快照后输入被改,PASS 须作废")
        self.assertFalse(self.rc.spec_path().exists(), "拒付不得发布")
        self.assertEqual(read_state(self.rc)["status"], "VERIFYING")

    def test_pass_rerun_after_complete_reports_done_without_duplicate(self):
        self.commit_pass()
        state_before = read_state(self.rc)
        entries_before = len(state_before["transitions"])
        payload = self.commit_pass()
        self.assertTrue(payload["ok"], "同一 PASS 命令重跑应判已完成")
        state = read_state(self.rc)
        self.assertEqual(len(state["transitions"]), entries_before,
                         "重跑不得追加事件")
        self.assertEqual(state["iteration"], state_before["iteration"])


class TestDeliverabilityGates(unittest.TestCase):
    def setUp(self):
        self.rc = RcDir()

    def tearDown(self):
        self.rc.cleanup()

    def validate(self):
        proc = run_script("validate.py", "--rc-root", str(self.rc.root))
        return out_json(proc), proc.returncode

    def test_complete_without_pass_report_is_not_deliverable(self):
        self.rc.state = min_state(status="COMPLETE", iteration=1)
        self.rc.flush_state()
        payload, code = self.validate()
        self.assertEqual(code, 1, "N02: 无当前 PASS 报告不得交付")
        self.assertFalse(payload["ok"])
        self.assertTrue(any("PASS" in e.get("reason", "") or "验证" in e.get("reason", "")
                            for e in payload["errors"]), payload["errors"])

    def test_complete_with_revise_report_is_not_deliverable(self):
        self.rc.state = min_state(status="COMPLETE", iteration=1)
        self.rc.flush_state()
        self.rc.write_doc(1, "verification", min_verification("REVISE"),
                          register=False)
        payload, code = self.validate()
        self.assertEqual(code, 1, "N03: REVISE 报告不支持交付")

    def test_wrong_round_pass_is_refused_at_commit(self):
        self.rc.advance_to("VERIFYING")
        old_snap = {"algorithm": "rc-sha256-v1", "iteration": 1,
                    "plan_path": "iterations/01-plan.json",
                    "artifact_sha256": "1" * 64, "plan_sha256": "2" * 64,
                    "state_projection_sha256": "3" * 64}
        ver = min_verification("PASS", snap=old_snap)
        draft = self.rc.write_draft("verification.json", ver)
        payload = out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                      "verification", str(draft)))
        self.assertFalse(payload["ok"], "N04: 复述他人快照(错轮/错来源)的报告不可提交")

    def test_drift_after_complete_fails_validate(self):
        self.rc.advance_to("VERIFYING")
        snap = json.loads((self.rc.iter_dir / "01-verification-input.json")
                          .read_text(encoding="utf-8"))
        draft = self.rc.write_draft("verification.json",
                                    min_verification("PASS", snap=snap))
        payload = out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                      "verification", str(draft)))
        self.assertTrue(payload["ok"], payload)
        art_path = self.rc.iter_dir / "01-artifact.json"
        art = json.loads(art_path.read_text(encoding="utf-8"))
        art["artifact"]["title"] = "PASS 后被手改"
        art_path.write_text(json.dumps(art, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        result, code = self.validate()
        self.assertEqual(code, 1, "N05: 绑定后输入被改,当前 PASS 失效")

    def test_hand_edited_spec_fails_validate(self):
        self.rc.advance_to("VERIFYING")
        snap = json.loads((self.rc.iter_dir / "01-verification-input.json")
                          .read_text(encoding="utf-8"))
        draft = self.rc.write_draft("verification.json",
                                    min_verification("PASS", snap=snap))
        payload = out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                      "verification", str(draft)))
        self.assertTrue(payload["ok"], payload)
        spec = self.rc.spec_path()
        spec.write_text(spec.read_text(encoding="utf-8").replace("滑块", "拉块"),
                        encoding="utf-8")
        result, code = self.validate()
        self.assertEqual(code, 1, "N06: 手改发布物必须被逐字节比对发现")

    def test_legacy_complete_without_provenance_is_readable_but_not_deliverable(self):
        self.rc.state = min_state(status="COMPLETE", iteration=0)
        self.rc.flush_state()
        self.rc.write_doc(1, "verification", min_verification("PASS"),
                          register=False)  # 无 provenance、无 verification_input
        self.rc.spec_path().parent.mkdir(parents=True, exist_ok=True)
        self.rc.spec_path().write_text("# 旧 Spec\n", encoding="utf-8")
        payload, code = self.validate()
        self.assertFalse(payload["ok"], "N13: 缺有效绑定的旧 COMPLETE 不可交付")
        self.assertTrue(any("provenance" in e.get("reason", "")
                            or "绑定" in e.get("reason", "")
                            for e in payload["errors"]), payload["errors"])


class TestValidateProtocol(unittest.TestCase):
    def setUp(self):
        self.rc = RcDir()

    def tearDown(self):
        self.rc.cleanup()

    def test_validate_outputs_protocol_json(self):
        payload = out_json(run_script("validate.py", "--rc-root", str(self.rc.root)))
        assert_protocol(payload)
        self.assertTrue(payload["ok"])

    def test_validate_reports_registry_drift_as_error(self):
        state = read_state(self.rc)
        state["plans"] = ["01-plan.json"]  # 登记了不存在的文件
        self.rc.state = state
        self.rc.flush_state()
        payload, code = self.validate_out()
        self.assertEqual(code, 1)
        self.assertTrue(any("R10" in e.get("reason", "") for e in payload["errors"]),
                        payload["errors"])

    def validate_out(self):
        proc = run_script("validate.py", "--rc-root", str(self.rc.root))
        return out_json(proc), proc.returncode

    def test_missing_state_file_is_an_error(self):
        (self.rc.root / "state.json").unlink()
        payload, code = self.validate_out()
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
