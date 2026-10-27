"""交付登记测试(consolidate T1-6):deliver_to 登记、PASS 双发布、
冲突拒绝、手改检测、旧轮次(无登记)兼容。

deliver_to 存相对 workspace 的 POSIX 路径;执行状态与决策记录仍在
.pev/<轮次>/rc/,只有 spec.md 额外交付到变更目录。
"""

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from render_lib import render_spec  # noqa: E402
from tests.helpers import (
    RcDir, assert_protocol, min_verification, out_json, run_script,
)

CHANGE_DIR_REL = "openspec/changes/demo"


def read_state(rc):
    return json.loads((rc.root / "state.json").read_text(encoding="utf-8"))


class InitDeliverToTest(unittest.TestCase):
    def setUp(self):
        self.rc = RcDir()
        # RcDir 预置了活跃 state;init 需要空轮(与 test_lifecycle 同法清掉)
        import shutil
        shutil.rmtree(self.rc.round)
        self.rc.round.mkdir(parents=True)
        self.prd = self.rc.write_prd()
        self.change_dir = self.rc.workspace / "openspec" / "changes" / "demo"
        self.change_dir.mkdir(parents=True)

    def tearDown(self):
        self.rc.cleanup()

    def _objective(self):
        return self.rc.write_draft("objective.json", {"goal": "降低登录失败率"})

    def test_init_registers_deliver_to_in_state(self):
        payload = out_json(run_script(
            "init.py", "--workspace", str(self.rc.workspace),
            "--prd-source", str(self.prd), "--objective", str(self._objective()),
            "--deliver-to", CHANGE_DIR_REL))
        assert_protocol(payload)
        self.assertTrue(payload["ok"], payload)
        state = read_state(self.rc)
        self.assertEqual(state["deliver_to"], CHANGE_DIR_REL)

    def test_init_rejects_missing_change_dir(self):
        payload = out_json(run_script(
            "init.py", "--workspace", str(self.rc.workspace),
            "--prd-source", str(self.prd), "--objective", str(self._objective()),
            "--deliver-to", "openspec/changes/ghost"))
        self.assertFalse(payload["ok"])
        self.assertIn("ghost", json.dumps(payload, ensure_ascii=False))


class DeliverFixture(unittest.TestCase):
    """推进到 VERIFYING 且已登记 deliver_to,随时可提交 PASS。"""

    def setUp(self):
        self.rc = RcDir()
        self.rc.advance_to("VERIFYING")
        self.rc.state["deliver_to"] = CHANGE_DIR_REL
        self.rc.flush_state()
        self.change_dir = self.rc.workspace / CHANGE_DIR_REL
        self.change_dir.mkdir(parents=True, exist_ok=True)
        self.snap = json.loads(
            (self.rc.iter_dir / "01-verification-input.json").read_text(
                encoding="utf-8"))

    def tearDown(self):
        self.rc.cleanup()

    def commit_pass(self):
        draft = self.rc.write_draft("verification.json",
                                    min_verification("PASS", snap=self.snap))
        return out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                   "verification", str(draft)))

    def delivered(self):
        return (self.change_dir / "spec.md").read_bytes()

    def test_pass_publishes_to_both_locations(self):
        payload = self.commit_pass()
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(self.delivered(),
                         self.rc.spec_path().read_bytes())
        self.assertEqual(read_state(self.rc)["status"], "COMPLETE")

    def test_conflict_refuses_and_keeps_both_untouched(self):
        occupied = self.change_dir / "spec.md"
        occupied.write_text("其他轮次已交付的内容", encoding="utf-8")
        payload = self.commit_pass()
        self.assertFalse(payload["ok"], payload)
        errors = json.dumps(payload, ensure_ascii=False)
        self.assertIn("spec.md", errors)
        self.assertEqual(occupied.read_text(encoding="utf-8"),
                         "其他轮次已交付的内容")
        self.assertFalse(self.rc.spec_path().exists(),
                         "冲突时收口整体失败,原发布物也不得写入")

    def test_preexisting_identical_target_passes(self):
        """目标已有相同字节(如上一轮同内容发布)不判冲突,幂等通过。"""
        art = json.loads((self.rc.iter_dir / "01-artifact.json")
                         .read_text(encoding="utf-8"))
        expected = render_spec(art["artifact"], read_state(self.rc),
                               "iterations/01-artifact.json").encode("utf-8")
        (self.change_dir / "spec.md").write_bytes(expected)
        payload = self.commit_pass()
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(self.delivered(), expected)

    def test_validate_flags_hand_edited_delivery(self):
        self.assertTrue(self.commit_pass()["ok"])
        (self.change_dir / "spec.md").write_text("手工改过的交付物",
                                                 encoding="utf-8")
        payload = out_json(run_script("validate.py", "--rc-root",
                                      str(self.rc.root)))
        self.assertFalse(payload["ok"], payload)
        self.assertIn("交付副本", json.dumps(payload, ensure_ascii=False))


class LegacyNoDeliverToTest(unittest.TestCase):
    def setUp(self):
        self.rc = RcDir()
        self.rc.advance_to("VERIFYING")
        self.snap = json.loads(
            (self.rc.iter_dir / "01-verification-input.json").read_text(
                encoding="utf-8"))

    def tearDown(self):
        self.rc.cleanup()

    def test_pass_without_deliver_to_keeps_legacy_behavior(self):
        draft = self.rc.write_draft("verification.json",
                                    min_verification("PASS", snap=self.snap))
        payload = out_json(run_script("commit.py", "--rc-root", str(self.rc.root),
                                      "verification", str(draft)))
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(self.rc.spec_path().is_file())
        demo = self.rc.workspace / CHANGE_DIR_REL / "spec.md"
        self.assertFalse(demo.exists())


if __name__ == "__main__":
    unittest.main()
