"""恢复测试(原则⑤):在任意两步之间断电,重跑同一命令必须收敛;接手方仅凭磁盘可定位。"""

import json
import unittest

from tests.helpers import (
    RcDir, min_artifact, min_plan, min_state, min_verification, out_json,
    run_script, snapshot_for,
)


def read_state(rc):
    return json.loads((rc.root / "state.json").read_text(encoding="utf-8"))


def write_state(rc, state):
    rc.state = state
    rc.flush_state()


class TestInterruptedReplays(unittest.TestCase):
    """模拟"落盘后、后续步骤前"断电:磁盘处于中间态,重跑同一命令收敛。"""

    def setUp(self):
        self.rc = RcDir()

    def tearDown(self):
        self.rc.cleanup()

    def commit(self, sub, doc, name):
        draft = self.rc.write_draft(name, doc)
        return out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                   sub, str(draft)))

    def test_plan_persisted_but_not_registered_converges(self):
        """断点:plan 文件已落盘、登记册与状态未推进。"""
        self.rc.write_doc(1, "plan", min_plan())  # 只落文件
        payload = self.commit("plan", min_plan(), "plan.json")
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertIn("01-plan.json", state["plans"])
        self.assertEqual(state["status"], "EXECUTING")
        self.assertEqual(len(state["transitions"]), 1, "重跑不得追加重复事件")

    def test_artifact_persisted_but_state_not_advanced_converges(self):
        """断点:artifact 与快照已落盘、状态仍停在 EXECUTING。"""
        self.rc.advance_to("EXECUTING")
        self.rc.write_doc(1, "artifact", min_artifact())
        snap = snapshot_for(read_state(self.rc), min_plan(),
                            "iterations/01-plan.json", min_artifact(), 1)
        self.rc.write_doc(1, "verification-input", snap, register=False)
        payload = self.commit("artifact", min_artifact(), "artifact.json")
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "VERIFYING")
        self.assertEqual(len([t for t in state["transitions"]
                              if t["to"] == "VERIFYING"]), 1)

    def test_spec_published_but_state_not_completed_converges(self):
        """断点:spec.md 已发布、完成状态未写入(收口链最后一步前断电)。"""
        self.rc.advance_to("VERIFYING")
        snap = json.loads((self.rc.iter_dir / "01-verification-input.json")
                          .read_text(encoding="utf-8"))
        ver = min_verification("PASS", snap=snap)
        # 先正常收口拿到真实发布物,再手工把状态回拨到"发布后、完成写入前"
        first = self.commit("verification", ver, "verification.json")
        self.assertTrue(first["ok"], first)
        state = read_state(self.rc)
        state["status"] = "VERIFYING"
        state["transitions"] = [t for t in state["transitions"]
                                if t.get("event") != "complete"]
        write_state(self.rc, state)
        payload = self.commit("verification", ver, "verification.json")
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "COMPLETE")
        self.assertEqual(len([t for t in state["transitions"]
                              if t.get("event") == "complete"]), 1,
                         "重跑只允许一条 complete 事件")
        self.assertTrue(self.rc.spec_path().read_text(encoding="utf-8")
                        .startswith("# Spec:"), "重跑后发布物为确定性渲染结果")

    def test_partial_transitions_entry_never_exists(self):
        """状态与事件账本同一次原子写:不存在"状态已推进、账本缺失"的磁盘态。"""
        self.rc.advance_to("EXECUTING")
        payload = self.commit("artifact", min_artifact(), "artifact.json")
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["status"], "VERIFYING")
        self.assertTrue(state.get("transitions"), "状态推进必须伴随事件入账")


class TestPowerCutChain(unittest.TestCase):
    """N18:正常链每一道命令之间停留一次,用 validate 定位续跑点,再继续。"""

    def test_chain_is_resumable_at_every_boundary(self):
        rc = RcDir()
        try:
            plan = min_plan()
            art = min_artifact()
            steps = [
                ("commit plan", lambda: run_script(
                    "commit.py", "--rc-root", str(rc.root), "plan",
                    str(rc.write_draft("plan.json", plan)))),
                ("commit artifact", lambda: run_script(
                    "commit.py", "--rc-root", str(rc.root), "artifact",
                    str(rc.write_draft("artifact.json", art)))),
            ]
            expected_status = {"commit plan": "EXECUTING",
                               "commit artifact": "VERIFYING"}
            for name, run_step in steps:
                payload = out_json(run_step())
                self.assertTrue(payload["ok"], f"{name} 失败: {payload}")
                v = out_json(run_script("validate.py", "--rc-root", str(rc.root)))
                self.assertTrue(v["ok"], f"{name} 后 validate 应定位为可续跑态: {v}")
                self.assertEqual(v["status"], expected_status[name])
            # 最后一环:PASS 收口
            snap = json.loads((rc.iter_dir / "01-verification-input.json")
                              .read_text(encoding="utf-8"))
            payload = out_json(run_script(
                "commit.py", "--rc-root", str(rc.root), "verification",
                str(rc.write_draft("verification.json",
                                   min_verification("PASS", snap=snap)))))
            self.assertTrue(payload["ok"], payload)
            v = out_json(run_script("validate.py", "--rc-root", str(rc.root)))
            self.assertTrue(v["ok"], f"收口后 validate 应全绿: {v}")
            self.assertEqual(v["status"], "COMPLETE")
        finally:
            rc.cleanup()


if __name__ == "__main__":
    unittest.main()
