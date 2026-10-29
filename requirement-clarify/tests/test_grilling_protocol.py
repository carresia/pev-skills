"""Grilling 交互协议测试:状态顺序、frontier 语义与超 4 题时的文本适配。"""

import json
import unittest
from pathlib import Path

from tests.helpers import RcDir, min_artifact, min_ledger, out_json, run_script

SKILL_ROOT = Path(__file__).resolve().parent.parent
SKILL_DOC = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
EXECUTOR_DOC = (SKILL_ROOT / "agents" / "executor.md").read_text(encoding="utf-8")
PLAYBOOK_DOC = (SKILL_ROOT / "playbooks" / "clarify.md").read_text(encoding="utf-8")

WAIT_FIRST = "先提交 status=\"blocked\" 的 Artifact，确认 state 为 WAITING_FOR_INPUT，再向用户提问"
RESUME_AFTER_ANSWER = "用户答复后先提交 state-update 恢复 EXECUTING，再重算 frontier 或进入锁定确认"
FRONTIER_COMPLETE = "当前 frontier 必须一次性包含所有前置条件已解决的未决问题"
UI_LIMIT = "AskUserQuestion 最多 4 题只是交互载体限制，不得改变 grilling frontier 的轮次语义"
TEXT_ROUND = "frontier 超过 4 题时不得使用 AskUserQuestion 压缩或拆分问题，必须用完整文本轮次一次性列出全部编号问题、推荐答案与处理路径"
DEPENDENCY = "依赖本轮未决答案的问题不得进入当前 frontier，必须留到后续轮次"
HANDLING_PATHS = "①回 PM 重新提需求 ②PM 补充需求 ③直接答复"
LOCKLIST = "frontier 清空后仍必须展示锁定决策清单，并取得用户共识确认"


class TestGrillingDocs(unittest.TestCase):
    def test_user_question_waits_before_ask_and_resumes_after_answer(self):
        for doc in (SKILL_DOC, EXECUTOR_DOC, PLAYBOOK_DOC):
            self.assertIn(WAIT_FIRST, doc)
            self.assertIn(RESUME_AFTER_ANSWER, doc)

    def test_frontier_is_complete_and_dependencies_wait(self):
        for doc in (SKILL_DOC, EXECUTOR_DOC, PLAYBOOK_DOC):
            self.assertIn(FRONTIER_COMPLETE, doc)
            self.assertIn(DEPENDENCY, doc)

    def test_four_question_ui_limit_never_splits_or_drops_frontier(self):
        for doc in (SKILL_DOC, EXECUTOR_DOC, PLAYBOOK_DOC):
            self.assertIn(UI_LIMIT, doc)
            self.assertIn(TEXT_ROUND, doc)

    def test_post_question_wait_wording_does_not_reappear(self):
        for doc in (SKILL_DOC, EXECUTOR_DOC, PLAYBOOK_DOC):
            self.assertNotIn("每轮问完", doc,
                             "问完再停靠会颠倒顺序，必须在提问前 WAITING")

    def test_large_text_round_keeps_recommendations_and_all_three_paths(self):
        for doc in (SKILL_DOC, EXECUTOR_DOC, PLAYBOOK_DOC):
            self.assertIn("每题保留推荐答案", doc)
            self.assertIn(HANDLING_PATHS, doc)
            self.assertIn(LOCKLIST, doc)


class TestGrillingRoundLifecycle(unittest.TestCase):
    def test_blocked_artifact_precedes_question_and_update_resumes_executing(self):
        rc = RcDir()
        try:
            rc.advance_to("EXECUTING")
            draft = rc.write_draft("artifact.json", min_artifact("blocked"))
            payload = out_json(run_script(
                "commit.py", "--rc-root", str(rc.root), "artifact", str(draft)))

            self.assertTrue(payload["ok"], payload)
            state = json.loads((rc.root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "WAITING_FOR_INPUT",
                             "向用户提问前必须已停靠等待输入")

            patch = rc.write_draft("patch.json", {
                "evidence": [min_ledger(type_="DECISION",
                                        evidence="01-artifact answers#q1")],
                "answers": [{"question": "q1", "answer": "采纳推荐",
                             "source": "用户答复"}],
            })
            payload = out_json(run_script(
                "commit.py", "--rc-root", str(rc.root), "state-update", str(patch)))

            self.assertTrue(payload["ok"], payload)
            state = json.loads((rc.root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "EXECUTING",
                             "用户答复入账后必须恢复执行，才能组织下一轮")
        finally:
            rc.cleanup()


if __name__ == "__main__":
    unittest.main()
