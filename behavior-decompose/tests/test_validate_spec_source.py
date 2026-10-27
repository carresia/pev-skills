"""spec_source 校验测试(consolidate T1-5):R10 上游存在性与批准态。

变更目录交付副本(openspec/changes/<name>/spec.md)是 OpenSpec 工作流的
spec_source 形态;文件缺失或同轮 rc 尚未 PASS 时必须明确报错,
不得改用其他轮次的 Spec。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
VALIDATE = SKILL_ROOT / "scripts" / "validate.py"


def run_validate(pev_dir):
    return subprocess.run([sys.executable, str(VALIDATE), str(pev_dir)],
                          capture_output=True, text=True)


class SpecSourceFixture(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="decompose-test-"))
        self.round = self.ws / ".pev" / "round-2026-10-27"
        self.decompose = self.round / "decompose"
        self.decompose.mkdir(parents=True)
        self.state = {
            "objective": {"goal": "降低登录失败率", "deadline": None},
            "spec_source": "",
            "status": "INIT",
            "iteration": 0,
            "max_iterations": 5,
        }

    def tearDown(self):
        import shutil
        shutil.rmtree(self.ws, ignore_errors=True)

    def flush_state(self):
        (self.decompose / "state.json").write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    def seed_rc_output_spec(self, status=None):
        spec = self.round / "rc" / "output" / "spec.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text("# Spec\n", encoding="utf-8")
        if status is not None:
            (self.round / "rc" / "state.json").write_text(
                json.dumps({"status": status}, ensure_ascii=False) + "\n",
                encoding="utf-8")
        return spec

    def seed_change_dir_spec(self):
        spec = self.ws / "openspec" / "changes" / "demo" / "spec.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text("# Spec\n", encoding="utf-8")
        return spec


class R10Test(SpecSourceFixture):
    def test_existing_rc_output_spec_passes(self):
        self.state["spec_source"] = str(self.seed_rc_output_spec())
        self.flush_state()
        proc = run_validate(self.decompose)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_missing_spec_source_file_fails(self):
        self.state["spec_source"] = str(self.ws / "ghost" / "spec.md")
        self.flush_state()
        proc = run_validate(self.decompose)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("不得改用其他轮次", proc.stdout)

    def test_complete_without_user_confirmation_fails(self):
        """T2-2:PASS 渲染后未确认的 COMPLETE 不得放行(R11 互锁)。"""
        self.state["spec_source"] = str(self.seed_rc_output_spec())
        self.state["status"] = "COMPLETE"
        self.flush_state()
        proc = run_validate(self.decompose)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("user_confirmation", proc.stdout)

    def test_complete_with_user_confirmation_passes(self):
        self.state["spec_source"] = str(self.seed_rc_output_spec())
        self.state["status"] = "COMPLETE"
        self.state["user_confirmation"] = {"date": "2026-10-27"}
        self.flush_state()
        proc = run_validate(self.decompose)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_change_dir_spec_with_complete_rc_passes(self):
        self.seed_rc_output_spec(status="COMPLETE")
        self.state["spec_source"] = str(self.seed_change_dir_spec())
        self.flush_state()
        proc = run_validate(self.decompose)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_change_dir_spec_with_unapproved_rc_fails(self):
        self.seed_rc_output_spec(status="VERIFYING")
        self.state["spec_source"] = str(self.seed_change_dir_spec())
        self.flush_state()
        proc = run_validate(self.decompose)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("尚未", proc.stdout)

    def test_change_dir_spec_without_rc_dir_passes(self):
        """用户直接提供文档(无同轮 rc)场景:只查存在性。"""
        self.state["spec_source"] = str(self.seed_change_dir_spec())
        self.flush_state()
        proc = run_validate(self.decompose)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
