"""生命周期脚本测试:init / commit / transition(design.md"流程脚本与写入权")。

先于实现编写(RED)。场景对应 design.md"交接链路与验收场景"表的全部行;
另含调用预算断言与协议输出断言(成功/失败/幂等重跑三类)。
运行(skill 根目录): python3 -m unittest discover -s tests -t . -v
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import helpers as h


class LifecycleBase(unittest.TestCase):
    """每个用例一个独立 workspace;init.py 在其中建 .pev/prd-<日期>/pm/。"""

    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="nana-lc-"))
        self.addCleanup(shutil.rmtree, self.ws, ignore_errors=True)
        self.calls = []

    def call(self, script, *args):
        self.calls.append(script)
        return h.run_script(script, *args)

    def run_next(self, payload, *extra):
        """执行 payload['next'] 中第一条 command 类指令,返回其结果。"""
        nxt = next(n for n in payload["next"] if n["kind"] == "command")
        script = nxt["argv"][0].split("/")[-1]
        return self.call(script, *nxt["argv"][1:], *extra)

    def init(self, goal="把新用户次周留存率从 20% 提升到 25%", **obj):
        objective = {"goal": goal, "target_metric": "次周留存率",
                     "baseline": 0.20}
        objective.update(obj)
        draft = self.ws / "objective.json"
        draft.write_text(json.dumps(objective, ensure_ascii=False),
                         encoding="utf-8")
        proc = self.call("init.py", "--objective", str(draft),
                        "--workspace", str(self.ws))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        return h.out_json(proc)

    def draft(self, name, obj):
        path = self.ws / name
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return path

    def plan_draft(self, name="plan.json", final_deliverable="PRD", **over):
        return self.draft(name, h.min_plan(final_deliverable=final_deliverable,
                                           **over))

    def artifact_draft(self, name="artifact.json", **over):
        return self.draft(name, h.min_artifact(**over))

    def read_state(self, payload):
        return json.loads((Path(payload["pm_root"]) / "state.json")
                          .read_text(encoding="utf-8"))

    def snapshot(self, payload):
        pm = Path(payload["pm_root"])
        n = payload["iteration"]
        return json.loads((pm / "iterations" / f"{n:02d}-verification-input.json")
                          .read_text(encoding="utf-8"))

    def report_draft(self, payload, verdict="PASS", **over):
        ver = h.min_verification(verdict=verdict, **over)
        ver["verification_input"] = self.snapshot(payload)
        return self.draft(f"report-{verdict.lower()}.json", ver)

    def reach_verifying(self, payload):
        """从建轮一路推到 VERIFYING(已绑 PASS 前),返回最新 payload。

        事件面合并(任务 2.9)后:init 建轮即 PLANNING;commit plan/artifact
        成功即自动转移,无独立 transition 命令。
        """
        p = payload
        p = h.out_json(self.call(
            "commit.py", "--pm-root", p["pm_root"],
            "plan", str(self.plan_draft())))        # commit plan → EXECUTING
        p = h.out_json(self.call(
            "commit.py", "--pm-root", p["pm_root"],
            "artifact", str(self.artifact_draft())))  # commit artifact → VERIFYING
        p = h.out_json(self.call(
            "record_provenance.py", "--pm-root", p["pm_root"]))
        return p

    def bind_pass(self, payload):
        """提交 PASS 报告——收口折叠(任务 2.10)后,commit verification
        一步完成绑定/转移/PASS 收口(render+validate+COMPLETE)。"""
        return h.out_json(self.call(
            "commit.py", "--pm-root", payload["pm_root"],
            "verification", str(self.report_draft(payload, "PASS"))))

    def forge_status(self, p, status):
        """直接改写 state 的 status 字段(夹具捷径;supersede 等无前置依赖的
        转移测试用它构造源状态)。"""
        pm = Path(p["pm_root"])
        state = json.loads((pm / "state.json").read_text(encoding="utf-8"))
        state["status"] = status
        if status == "WAITING_FOR_INPUT":
            state["resume_to"] = "PLANNING"
        else:
            state.pop("resume_to", None)
        (pm / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return p


class TestInitAndLocate(LifecycleBase):
    def test_init_creates_round_and_state(self):
        payload = self.init()
        pm = Path(payload["pm_root"])
        self.assertTrue((pm / "state.json").is_file())
        state = self.read_state(payload)
        # 事件面合并(任务 2.9):建轮即 PLANNING、iteration=1,不停留 INIT
        self.assertEqual(state["status"], "PLANNING")
        self.assertEqual(state["iteration"], 1)
        self.assertEqual(state["max_iterations"], 5)
        self.assertNotIn("transitions", state, "init 不追加 transitions 条目")
        self.assertEqual(payload["next"][0]["kind"], "draft")
        self.assertEqual(payload["next"][0]["target"], "plan")

    def test_init_goal_missing_waits(self):
        payload = self.init(goal="")
        state = self.read_state(payload)
        self.assertEqual(state["status"], "WAITING_FOR_INPUT")
        self.assertEqual(state["resume_to"], "PLANNING")
        self.assertEqual(state["iteration"], 1)
        self.assertTrue(any(n["kind"] == "ask-user" for n in payload["next"]))

    def test_init_metric_baseline_optional(self):
        # target_metric 缺失与 baseline 为 null 是 schema 合法状态,仅提示不阻断
        payload = self.init(target_metric=None, baseline=None)
        self.assertEqual(self.read_state(payload)["status"], "PLANNING")
        self.assertTrue(payload["warnings"], "缺失项应有 warnings 提示")

    def test_init_idempotent_same_goal_reports_not_rebuilds(self):
        first = self.init()
        before = (Path(first["pm_root"]) / "state.json").read_bytes()
        second = self.init()
        self.assertEqual(second["pm_root"], first["pm_root"])
        self.assertEqual((Path(first["pm_root"]) / "state.json").read_bytes(),
                         before)

    def test_init_new_goal_same_day_appends_seq(self):
        self.init(goal="目标甲")
        second = self.init(goal="目标乙")
        self.assertTrue(second["pm_root"].rstrip("/").endswith("-2/pm"),
                        second["pm_root"])

    def test_locate_reports_latest_round(self):
        self.init()
        proc = self.call("init.py", "--locate", "--workspace", str(self.ws))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertEqual(payload["status"], "PLANNING")


class TestNormalChain(LifecycleBase):
    def test_full_chain_to_complete(self):
        p = self.init()
        p = self.reach_verifying(p)
        self.assertEqual(p["status"], "VERIFYING")
        p = self.bind_pass(p)
        # 收口折叠(任务 2.10):commit verification 一步到 COMPLETE
        self.assertEqual(p["status"], "COMPLETE")
        self.assertIn("iterations/01-verification.json", p["written"])
        self.assertIn("output/prd.md", p["written"])
        self.assertEqual(p["next"][0]["kind"], "deliver", p["next"])
        state = self.read_state(p)
        self.assertEqual(state["iteration"], 1)
        # 事件面合并后:init 不写 transitions;转移条目仍按 v1 事件名记录
        kinds = [t["event"] for t in state["transitions"]]
        self.assertEqual(kinds, ["plan-validated", "artifact-validated",
                                 "verdict", "complete"])
        # 投影摘要不受收口动作影响:transitions/COMPLETE 写入前后一致
        snap = self.snapshot(p)
        ver = json.loads((Path(p["pm_root"]) / "iterations" / "01-verification.json")
                         .read_text(encoding="utf-8"))
        self.assertEqual(ver["provenance"]["state_projection_sha256"],
                         snap["state_projection_sha256"])

    def test_call_budget_normal_chain(self):
        # design §8:正常链固定 5 次调用(init/commit plan/commit artifact/
        # record_provenance/commit verification);无显式 validate.py
        p = self.init()
        p = self.reach_verifying(p)
        p = self.bind_pass(p)
        self.assertEqual(p["status"], "COMPLETE")
        counted = [c for c in self.calls]
        self.assertEqual(len(counted), 5, counted)
        self.assertNotIn("validate.py", counted)

    def test_state_update_appends_ledger_and_known(self):
        p = self.init()  # 建轮即 PLANNING
        patch = self.draft("patch.json", {
            "known": ["合成背景事实"],
            "evidence": [h.min_evidence(i=1)],
        })
        proc = self.call("commit.py", "--pm-root", p["pm_root"],
                        "state-update", str(patch))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        state = self.read_state(h.out_json(proc))
        self.assertEqual(state["known"], ["合成背景事实"])
        self.assertEqual(state["evidence"][0]["id"], "E1")

    def test_state_update_rejects_lifecycle_fields(self):
        p = self.init()  # PLANNING
        patch = self.draft("bad-patch.json", {"status": "EXECUTING"})
        proc = self.call("commit.py", "--pm-root", p["pm_root"],
                        "state-update", str(patch))
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(h.out_json(proc)["ok"])

    def test_revise_reuses_plan_no_new_plan_file(self):
        p = self.init()
        p = self.reach_verifying(p)
        # REVISE 报告经 commit verification 自动转移(+1 回 EXECUTING)
        rev = h.min_verification(verdict="REVISE",
                                 required_changes=["补齐次级指标口径"])
        rev["verification_input"] = self.snapshot(p)
        self.draft("report-revise.json", rev)
        p = h.out_json(self.call(
            "commit.py", "--pm-root", p["pm_root"],
            "verification", str(self.ws / "report-revise.json")))
        self.assertEqual(p["status"], "EXECUTING")
        self.assertEqual(p["iteration"], 2)
        pm = Path(p["pm_root"])
        self.assertFalse((pm / "iterations" / "02-plan.json").exists())
        self.assertTrue((pm / "iterations" / "01-plan.json").exists())


class TestGuardsAndOverwrite(LifecycleBase):
    def setUp(self):
        super().setUp()
        self.p = self.init()  # 建轮即 PLANNING

    def to_executing(self):
        p = h.out_json(self.call("commit.py", "--pm-root", self.p["pm_root"],
                                "plan", str(self.plan_draft())))
        self.p = p
        return p

    def test_commit_wrong_stage_rejected(self):
        # PLANNING 阶段提交 artifact:编号=1=当前轮,但阶段不匹配 → 拒绝
        proc = self.call("commit.py", "--pm-root", self.p["pm_root"],
                        "artifact", str(self.artifact_draft()))
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(h.out_json(proc)["ok"])

    def test_illegal_event_lists_current_state(self):
        proc = self.call("transition.py", "--pm-root", self.p["pm_root"],
                        "complete")
        self.assertEqual(proc.returncode, 1)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["errors"])

    def test_unknown_event_rejected(self):
        proc = self.call("transition.py", "--pm-root", self.p["pm_root"],
                        "no-such-event")
        self.assertEqual(proc.returncode, 1)

    def test_history_round_preserved_on_replan(self):
        # REPLAN 后新提交编号由当前轮分配;历史轮(01-plan)结构上不可触及、字节不变
        p = self.to_executing()
        plan_before = (Path(p["pm_root"]) / "iterations" / "01-plan.json") \
            .read_bytes()
        # 首个产物即 replan_required:提交即自动 executor-replan(+1 回 PLANNING)
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "artifact",
                                str(self.artifact_draft(
                                    name="replan.json",
                                    status="replan_required"))))
        self.assertEqual(p["iteration"], 2)
        self.assertEqual(p["status"], "PLANNING")
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "plan", str(self.plan_draft())))
        self.assertEqual(p["written"], ["iterations/02-plan.json"])
        self.assertEqual((Path(p["pm_root"]) / "iterations" / "01-plan.json")
                         .read_bytes(), plan_before)
        self.assertEqual(self.read_state(p)["plans"],
                         ["01-plan.json", "02-plan.json"])

    def test_blocked_artifact_revisions_in_place(self):
        p = self.to_executing()
        blocked = self.artifact_draft(name="blocked.json", status="blocked")
        # 提交 blocked 产物即自动 executor-blocked 转移
        p2 = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                 "artifact", str(blocked)))
        self.assertEqual(p2["status"], "WAITING_FOR_INPUT")
        self.assertEqual(p2["iteration"], 1)
        self.assertEqual(self.read_state(p2)["resume_to"], "EXECUTING")
        # 用户补数后 resume 回 EXECUTING;修订后的 completed 原位覆盖同名文件
        p3 = h.out_json(self.call("transition.py", "--pm-root", p2["pm_root"],
                                 "resume"))
        self.assertEqual(p3["status"], "EXECUTING")
        self.assertIsNone(self.read_state(p3).get("resume_to"))
        p4 = h.out_json(self.call("commit.py", "--pm-root", p3["pm_root"],
                                 "artifact", str(self.artifact_draft())))
        self.assertEqual(p4["status"], "VERIFYING")
        self.assertEqual(p4["next"][0]["kind"], "command")
        self.assertTrue(any("record_provenance" in a
                            for a in p4["next"][0]["argv"]), p4["next"])

    def test_blocked_report_reeval_distinguishes_reports(self):
        # BLOCKED 报告重评:同轮新报告原位覆盖;重跑 verdict 以 ref_sha256 区分
        p = self.reach_verifying(self.p)
        rev = h.min_verification(verdict="BLOCKED")
        rev["verification_input"] = self.snapshot(p)
        self.draft("report-blocked.json", rev)
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "verification",
                                str(self.ws / "report-blocked.json")))
        self.assertEqual(p["status"], "WAITING_FOR_INPUT")
        self.assertEqual(self.read_state(p)["resume_to"], "VERIFYING")
        # 重跑同一 BLOCKED 报告:verdict 转移已发生,判已执行退出 0
        again = self.call("commit.py", "--pm-root", p["pm_root"],
                          "verification",
                          str(self.ws / "report-blocked.json"))
        self.assertEqual(again.returncode, 0, again.stdout)
        p = h.out_json(self.call("transition.py", "--pm-root", p["pm_root"],
                                "resume"))
        self.assertEqual(p["status"], "VERIFYING")
        # 新报告(内容不同)原位覆盖同名 verification 并重新绑定+收口
        rev2 = h.min_verification(verdict="PASS")
        rev2["verification_input"] = self.snapshot(p)
        rev2["strengths"] = ["复评后证据充分"]
        self.draft("report-pass.json", rev2)
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "verification",
                                str(self.ws / "report-pass.json")))
        self.assertEqual(p["status"], "COMPLETE", "复评 PASS 一步收口")

    def test_overwrite_refused_after_bound_pass(self):
        p = self.reach_verifying(self.p)
        p = self.bind_pass(p)
        proc = self.call("commit.py", "--pm-root", p["pm_root"],
                        "artifact", str(self.artifact_draft(
                            name="artifact2.json")))
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("绑定", proc.stdout)


class TestBoundariesAndRerun(LifecycleBase):
    def setUp(self):
        super().setUp()
        self.p = self.init()  # 建轮即 PLANNING iter1

    def test_commit_rerun_converges_from_partial_states(self):
        # 边界中断恢复:重跑同一 commit 命令收敛(登记册回滚→重写;完整→幂等)
        p = h.out_json(self.call("commit.py", "--pm-root", self.p["pm_root"],
                                "plan", str(self.plan_draft())))
        self.assertEqual(p["status"], "EXECUTING")
        # (a) 转移已落盘但登记册被模拟回滚:重跑同命令按已执行分支收敛
        pm = Path(p["pm_root"])
        state = self.read_state(p)
        state["plans"] = []
        (pm / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        p2 = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                 "plan", str(self.plan_draft())))
        self.assertEqual(p2["status"], "EXECUTING")
        self.assertEqual(self.read_state(p2)["plans"], ["01-plan.json"])
        # (b) 完整提交后的幂等重跑:判已执行,退出 0,不重复转移
        p3 = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                 "plan", str(self.plan_draft())))
        self.assertTrue(p3["ok"])
        entries = [t for t in self.read_state(p3)["transitions"]
                   if t["event"] == "plan-validated"]
        self.assertEqual(len(entries), 1)

    def test_commit_rerun_after_success_no_double_increment(self):
        # 合并转移后:重跑同一 commit 命令按事件身份判已执行,转移不重复
        p = h.out_json(self.call("commit.py", "--pm-root", self.p["pm_root"],
                                "plan", str(self.plan_draft())))
        self.assertEqual(p["status"], "EXECUTING")
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "artifact",
                                str(self.artifact_draft(status="replan_required",
                                                        name="replan.json"))))
        self.assertEqual(p["status"], "PLANNING")
        self.assertEqual(p["iteration"], 2)
        # 重跑同一 replan 提交:判已执行,iteration 不二次 +1
        again = self.call("commit.py", "--pm-root", p["pm_root"],
                          "artifact",
                          str(self.artifact_draft(status="replan_required",
                                                  name="replan.json")))
        self.assertEqual(again.returncode, 0, again.stdout)
        p2 = h.out_json(again)
        self.assertEqual(p2["iteration"], 2)
        self.assertEqual(p2["status"], "PLANNING")

    def test_resume_rerun_after_resume_to_cleared(self):
        p = self.p
        # PLANNING 无已登记 Plan 时 need-input 合法
        p = h.out_json(self.call("transition.py", "--pm-root", p["pm_root"],
                                "need-input"))
        self.assertEqual(p["status"], "WAITING_FOR_INPUT")
        p2 = h.out_json(self.call("transition.py", "--pm-root", p["pm_root"],
                                 "resume"))
        self.assertEqual(p2["status"], "PLANNING")
        p3 = h.out_json(self.call("transition.py", "--pm-root", p["pm_root"],
                                 "resume"))
        self.assertEqual(p3["status"], "PLANNING", "重跑判已恢复")
        self.assertEqual(p3["iteration"], 1)

    def test_invalidating_resume_goes_replan(self):
        p = h.out_json(self.call("transition.py", "--pm-root",
                                self.p["pm_root"], "need-input"))
        p = h.out_json(self.call("transition.py", "--pm-root", p["pm_root"],
                                "resume", "--invalidate-plan"))
        self.assertEqual(p["status"], "PLANNING")
        self.assertEqual(p["iteration"], 2)

    def test_upper_limit_writes_stopped_and_authorized_resume(self):
        # 5/5 正常完成后 reopen 需 +1:构造已到 5/5 的场景直接断言越上限
        p = self.p
        for i in range(4):
            p = h.out_json(self.call("transition.py", "--pm-root",
                                    p["pm_root"], "need-input"))
            p = h.out_json(self.call("transition.py", "--pm-root",
                                    p["pm_root"], "resume",
                                    "--invalidate-plan"))
        # 当前 iteration=5(1 次首轮 + 4 次 REPLAN);回到 WAITING 再触发第 6 轮
        p = h.out_json(self.call("transition.py", "--pm-root", p["pm_root"],
                                "need-input"))
        payload = h.out_json(self.call("transition.py", "--pm-root",
                                      p["pm_root"], "resume",
                                      "--invalidate-plan"))
        self.assertEqual(payload["status"], "STOPPED")
        self.assertTrue(any(n["kind"] == "stop" for n in payload["next"]),
                        payload["next"])
        state = self.read_state(payload)
        self.assertEqual(state["iteration"], 5)
        # 授权恢复(2.9 并入 resume --raise-limit):提额 +1 回 PLANNING
        p = h.out_json(self.call("transition.py", "--pm-root",
                                payload["pm_root"], "resume",
                                "--raise-limit", "7"))
        self.assertEqual(p["status"], "PLANNING")
        self.assertEqual(p["iteration"], 6)
        self.assertEqual(self.read_state(p)["max_iterations"], 7)


class TestCompleteGuard(LifecycleBase):
    """收口守卫在折叠后的载体:快照缺失、PASS 后内容变化(R2)、5/5 收口(R13)。"""

    def test_verification_refuses_without_snapshot(self):
        # 没有验证输入(未派发 Verifier)就交 PASS:结构上不可收口
        p = self.init()
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "plan", str(self.plan_draft())))
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "artifact", str(self.artifact_draft())))
        report = h.min_verification(verdict="PASS")
        self.draft("report-nosnap.json", report)
        proc = self.call("commit.py", "--pm-root", p["pm_root"],
                        "verification", str(self.ws / "report-nosnap.json"))
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertFalse(h.out_json(proc)["ok"])

    def test_rerun_after_pass_content_change_rejected_by_p1(self):
        # R2:COMPLETE 后 artifact 被绕过脚本改写,重跑收口命令被 P1 拒绝
        p = self.init()
        p = self.reach_verifying(p)
        p = self.bind_pass(p)
        self.assertEqual(p["status"], "COMPLETE")
        pm = Path(p["pm_root"])
        art = json.loads((pm / "iterations" / "01-artifact.json")
                         .read_text(encoding="utf-8"))
        art["artifact"]["title"] = "收口之后被改写"
        (pm / "iterations" / "01-artifact.json").write_text(
            json.dumps(art, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        proc = self.call("commit.py", "--pm-root", p["pm_root"],
                        "verification", str(self.ws / "report-pass.json"))
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("P1" in str(e.get("reason", ""))
                            for e in payload["errors"]), payload["errors"])

    def test_complete_55_passes(self):
        # 5/5 轮 PASS 正常完成,不因等于上限误判
        p = self.init()  # PLANNING iteration=1
        for _ in range(4):
            p = h.out_json(self.call("transition.py", "--pm-root",
                                    p["pm_root"], "need-input"))
            p = h.out_json(self.call("transition.py", "--pm-root",
                                    p["pm_root"], "resume",
                                    "--invalidate-plan"))
        self.assertEqual(p["iteration"], 5)
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "plan", str(self.plan_draft())))
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "artifact", str(self.artifact_draft())))
        p = h.out_json(self.call("record_provenance.py", "--pm-root",
                                p["pm_root"]))
        p = h.out_json(self.call(
            "commit.py", "--pm-root", p["pm_root"],
            "verification", str(self.report_draft(p, "PASS"))))
        self.assertEqual(p["status"], "COMPLETE")
        self.assertEqual(p["iteration"], 5)


class TestProtocolShapes(LifecycleBase):
    def test_failure_payload_shape(self):
        proc = self.call("transition.py", "--pm-root",
                        str(self.ws / "nope"), "need-input")
        self.assertEqual(proc.returncode, 1)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        for key in ("command", "pm_root", "skill_root", "status", "iteration",
                    "written", "deleted", "errors", "warnings", "next"):
            self.assertIn(key, payload)

    def test_success_and_idempotent_payload_shapes(self):
        p = self.init()
        self.assertTrue(p["ok"])
        p2 = self.init()
        self.assertTrue(p2["ok"])          # 幂等重跑 ok=true
        self.assertEqual(p2["written"], [])


class TestCloseoutReplays(LifecycleBase):
    """磁盘守卫回放:语义字段被绕过脚本改写、手改 output 后重渲染覆盖。"""

    def test_ledger_change_on_disk_blocks_closeout_rerun(self):
        # R3 同型:收口后 state 语义字段被直接改写(模拟中断窗口的语义修改),
        # 重跑收口命令被 P1 拦住——交付资格由磁盘一致性守卫
        p = self.init()
        p = self.reach_verifying(p)
        p = self.bind_pass(p)
        pm = Path(p["pm_root"])
        state = self.read_state(p)
        state.setdefault("evidence", []).append(h.min_evidence(i=2))
        (pm / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        proc = self.call("commit.py", "--pm-root", p["pm_root"],
                        "verification", str(self.ws / "report-pass.json"))
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = h.out_json(proc)
        self.assertTrue(any("P1" in str(e.get("reason", ""))
                            for e in payload["errors"]), payload["errors"])

    def test_hand_edited_output_replaced_by_rerender(self):
        # 纯渲染修复路径:手工改动被重新渲染覆盖,不修改来源 JSON
        p = self.init()
        p = self.reach_verifying(p)  # VERIFYING 即可渲染,无需验证报告
        self.call("render.py", "--pm-root", p["pm_root"])
        out = Path(p["pm_root"]) / "output" / "prd.md"
        out.write_text(out.read_text(encoding="utf-8") + "手工追加\n",
                       encoding="utf-8")
        proc = self.call("render.py", "--pm-root", p["pm_root"])
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertNotIn("手工追加", out.read_text(encoding="utf-8"))
        proc = self.call("render.py", "--pm-root", p["pm_root"], "--check")
        self.assertEqual(proc.returncode, 0, proc.stdout)


class TestReviewFixes(LifecycleBase):
    """2026-10-23 评审修复:定位排序、终局轮次复用、提额校验、文档命令完整性。"""

    def test_locate_sorts_numeric_suffix(self):
        # prd-...-10 会被字符串排序判早于 prd-...-9
        pev = self.ws / ".pev"
        for seq in (9, 10):
            pm = pev / f"prd-2026-10-23-{seq}" / "pm"
            pm.mkdir(parents=True)
            (pm / "state.json").write_text(json.dumps(
                {"objective": {"goal": "g"}, "status": "INIT",
                 "iteration": 0, "max_iterations": 5}), encoding="utf-8")
        proc = self.call("init.py", "--locate", "--workspace", str(self.ws))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue(h.out_json(proc)["pm_root"].endswith(
            "prd-2026-10-23-10/pm"), h.out_json(proc)["pm_root"])

    def test_init_same_goal_terminal_round_starts_new_seq(self):
        first = self.init(goal="目标甲")
        state_path = Path(first["pm_root"]) / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["status"] = "COMPLETE"
        state_path.write_text(json.dumps(state, ensure_ascii=False),
                              encoding="utf-8")
        second = self.init(goal="目标甲")
        self.assertNotEqual(second["pm_root"], first["pm_root"])
        self.assertTrue(second["pm_root"].rstrip("/").endswith("-2/pm"))
        self.assertEqual(self.read_state(second)["status"], "PLANNING")

    def test_init_active_round_idempotent_next_follows_status(self):
        first = self.init(goal="目标甲")
        second = self.init(goal="目标甲")
        self.assertEqual(second["pm_root"], first["pm_root"])
        # 建轮即 PLANNING:幂等续用时 next 指向起草 Plan
        self.assertTrue(any(n["kind"] == "draft" and n.get("target") == "plan"
                            for n in second["next"]), second["next"])

    def test_authorized_resume_rejects_non_increase(self):
        p = self.init()  # PLANNING iter1
        for _ in range(4):
            p = h.out_json(self.call("transition.py", "--pm-root",
                                    p["pm_root"], "need-input"))
            p = h.out_json(self.call("transition.py", "--pm-root",
                                    p["pm_root"], "resume",
                                    "--invalidate-plan"))
        p = h.out_json(self.call("transition.py", "--pm-root",
                                p["pm_root"], "need-input"))
        p = h.out_json(self.call("transition.py", "--pm-root",
                                p["pm_root"], "resume",
                                "--invalidate-plan"))
        self.assertEqual(p["status"], "STOPPED")
        proc = self.call("transition.py", "--pm-root", p["pm_root"],
                         "resume", "--raise-limit", "5")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertFalse(h.out_json(proc)["ok"])

    def test_skill_md_command_examples_carry_pm_root(self):
        text = (h.SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        import re
        subcommands = (r"(--pm-root|plan|artifact|verification|state-update|"
                       r"verdict|complete|resume|reopen|authorized-resume|"
                       r"need-input|start-planning|plan-validated|"
                       r"artifact-validated|executor-replan|executor-blocked|"
                       r"--bind|--prune|--check)")
        pat = (r"`[^`\n]*\b(commit|transition|record_provenance)\.py "
               + subcommands + r"[^`\n]*`")
        self.assertGreaterEqual(len(re.findall(pat, text)), 4,
                                "SKILL.md 应含完整命令示例")
        for m in re.finditer(pat, text):
            self.assertIn("--pm-root", m.group(0), m.group(0))


def proc_next_kind(payload):
    return payload["next"][0]["kind"]


class TestSupersede(LifecycleBase):
    """任务 2.4:supersede 事件与 SUPERSEDED 终态(design §4)。

    Why:轮次此前没有废弃出口——悬挂 EXECUTING 轮只能靠改目标串骗过去重
    (P0-2)。supersede 给出显式换轮语义:冻结旧轮、证据保全、iteration 不变;
    继任关系由 init --carry-from 单向记录。
    """

    NOTE = "用户改为京东+淘宝且淘宝优先"

    def supersede(self, pm_root, note=None):
        args = ["transition.py", "--pm-root", str(pm_root), "supersede"]
        if note is not None:
            args += ["--note", note]
        return self.call(*args)

    def codes(self, proc):
        return [e.get("code") for e in h.out_json(proc)["errors"]]

    def test_supersede_from_each_source_status(self):
        # 任何状态(活轮与 COMPLETE/STOPPED 挂起轮)→ SUPERSEDED,iteration 不变
        for status in ("INIT", "PLANNING", "EXECUTING", "VERIFYING",
                       "WAITING_FOR_INPUT", "COMPLETE", "STOPPED"):
            with self.subTest(status=status):
                p = self.forge_status(self.init(), status)
                proc = self.supersede(p["pm_root"], self.NOTE)
                self.assertEqual(proc.returncode, 0, proc.stdout)
                payload = h.out_json(proc)
                self.assertEqual(payload["status"], "SUPERSEDED")
                state = self.read_state(payload)
                self.assertEqual(state["status"], "SUPERSEDED")
                self.assertEqual(state["iteration"], 1,
                                 "supersede 不改变 iteration(建轮即 1)")
                last = state["transitions"][-1]
                self.assertEqual(last["event"], "supersede")
                self.assertEqual(last["to"], "SUPERSEDED")
                self.assertIsInstance(last["param"], dict)
                self.assertEqual(last["param"], {"note": self.NOTE})

    def test_supersede_note_required(self):
        p = self.init()
        proc = self.supersede(p["pm_root"])
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("E_NOTE_REQUIRED", self.codes(proc))

    def test_all_writes_frozen_after_superseded(self):
        # R7:SUPERSEDED 上一切写入 E_FROZEN_STATE(state-update/产物提交/其他事件)
        p = self.init()  # 建轮即 PLANNING iter1
        p = h.out_json(self.supersede(p["pm_root"], self.NOTE))
        patch = self.draft("patch.json", {"known": ["补写"]})
        proc = self.call("commit.py", "--pm-root", p["pm_root"],
                         "state-update", str(patch))
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("E_FROZEN_STATE", self.codes(proc))
        proc = self.call("commit.py", "--pm-root", p["pm_root"],
                         "plan", str(self.plan_draft()))
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("E_FROZEN_STATE", self.codes(proc))
        proc = self.call("transition.py", "--pm-root", p["pm_root"], "need-input")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("E_FROZEN_STATE", self.codes(proc))

    def test_supersede_idempotent_rerun(self):
        # 三分支:同 note 重跑 → done;不同 note → 非幂等重跑,冻结拒绝
        p = self.init()
        p = h.out_json(self.supersede(p["pm_root"], self.NOTE))
        n_trans = len(self.read_state(p)["transitions"])
        again = self.supersede(p["pm_root"], self.NOTE)
        self.assertEqual(again.returncode, 0, again.stdout)
        payload = h.out_json(again)
        self.assertEqual(payload["status"], "SUPERSEDED")
        self.assertTrue(any("重跑" in w for w in payload["warnings"]),
                        payload["warnings"])
        self.assertEqual(len(self.read_state(payload)["transitions"]), n_trans)
        other = self.supersede(p["pm_root"], "不同的废弃原因")
        self.assertEqual(other.returncode, 1, other.stdout)
        self.assertIn("E_FROZEN_STATE", self.codes(other))

    def test_superseded_state_passes_validate(self):
        # state.schema.json 枚举须含 SUPERSEDED(否则收口后 validate 全红)
        p = self.init()
        p = h.out_json(self.supersede(p["pm_root"], self.NOTE))
        proc = h.run_validate(Path(p["pm_root"]))
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_init_same_goal_after_superseded_starts_new_round(self):
        # R17:SUPERSEDED 不在活跃集,同目标 init 放行新轮
        first = self.init(goal="目标甲")
        p = h.out_json(self.supersede(first["pm_root"], self.NOTE))
        second = self.init(goal="目标甲")
        self.assertNotEqual(second["pm_root"], first["pm_root"])
        self.assertTrue(second["pm_root"].rstrip("/").endswith("-2/pm"),
                        second["pm_root"])
        self.assertEqual(self.read_state(second)["status"], "PLANNING")


class TestCarryFromAndLocate(LifecycleBase):
    """任务 2.5:carry-from 携账本与 locate 全轮汇报(design §4.1/§5.2)。

    Why:换轮后账本被人为分割到多轮(重放轮 2 弃轮重建的痛点);继任轮经
    --carry-from 携八字段语义投影,审计连续。locate 此前只报最新轮,悬挂轮
    与改名轮永不入汇报(改名轮 round_sort_key 返回 ("",-1) 恒不入选)——
    全轮清单+警告让存量现场可见、可点名。
    """

    def build_round_with_content(self, goal="旧目标"):
        p = self.init(goal=goal)  # 建轮即 PLANNING iter1
        patch = self.draft("patch-old.json", {
            "known": ["旧轮事实"],
            "evidence": [h.min_evidence(1), h.min_evidence(2)],
        })
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                 "state-update", str(patch)))
        return p

    def carry_init(self, goal, old_name):
        draft = self.draft("objective-carry.json",
                           {"goal": goal, "target_metric": "次周留存率",
                            "baseline": 0.20})
        proc = self.call("init.py", "--objective", str(draft),
                         "--workspace", str(self.ws), "--carry-from", old_name)
        return proc

    def write_round(self, name, status, iteration):
        pm = self.ws / ".pev" / name / "pm"
        pm.mkdir(parents=True)
        st = h.min_state(status=status, iteration=iteration)
        (pm / "state.json").write_text(
            json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_carry_from_terminal_source_carries_projection(self):
        # R17:三种终态源(SUPERSEDED 经真实事件,COMPLETE/STOPPED 直造)携账本
        for status, via in (("COMPLETE", "forge"), ("STOPPED", "forge"),
                            ("SUPERSEDED", "supersede")):
            with self.subTest(status=status):
                p = self.build_round_with_content()
                if via == "supersede":
                    p = h.out_json(self.call(
                        "transition.py", "--pm-root", p["pm_root"],
                        "supersede", "--note", "目标变更"))
                else:
                    self.forge_status(p, status)
                old_name = Path(p["pm_root"]).parent.name
                proc = self.carry_init(f"新目标甲-{status}", old_name)
                self.assertEqual(proc.returncode, 0, proc.stdout)
                payload = h.out_json(proc)
                state = self.read_state(payload)
                self.assertEqual(state["carried_from"], old_name)
                self.assertEqual(state["objective"]["goal"], f"新目标甲-{status}")
                self.assertEqual([e["id"] for e in state["evidence"]],
                                 ["E1", "E2"], "evidence id 保留")
                self.assertIn("旧轮事实", state["known"])
                self.assertNotIn("transitions", state, "登记册/日志不携入")
                self.assertEqual(state["iteration"], 1,
                                 "继任轮建轮即 iteration=1(新预算)")

    def test_carry_from_active_source_rejected(self):
        # 活轮源不给携账本:活轮该 resume/reopen,不是换轮
        p = self.build_round_with_content()  # PLANNING,活跃
        old_name = Path(p["pm_root"]).parent.name
        proc = self.carry_init("新目标乙", old_name)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = h.out_json(proc)
        self.assertTrue(any(e.get("code") == "E_CARRY_SOURCE_ACTIVE"
                            for e in payload["errors"]), payload["errors"])
        rounds = list((self.ws / ".pev").glob("prd-*/pm/state.json"))
        self.assertEqual(len(rounds), 1, "拒绝时不得创建新轮")

    def test_locate_full_inventory_and_hanging_warning(self):
        # R18:全轮清单 + 悬挂警告(非终态且非被选中的最新轮)
        self.write_round("prd-2026-01-01", "EXECUTING", 4)
        self.write_round("prd-2026-01-02", "COMPLETE", 3)
        latest = self.init(goal="今日目标")
        today = Path(latest["pm_root"]).parent.name
        proc = self.call("init.py", "--locate", "--workspace", str(self.ws))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertEqual(payload["pm_root"], latest["pm_root"])
        joined = "\n".join(payload["warnings"])
        for name in ("prd-2026-01-01", "prd-2026-01-02", today):
            self.assertIn(name, joined, "全轮清单必须含每个轮次")
        self.assertTrue(any("悬挂" in w and "prd-2026-01-01" in w
                            for w in payload["warnings"]), payload["warnings"])
        self.assertFalse(any("悬挂" in w and today in w
                             for w in payload["warnings"]),
                         "被选中的最新轮不是悬挂轮")

    def test_locate_renamed_round_reported_not_selected(self):
        # R19:改名轮不参与自动选择,但必须出现在汇报清单
        self.write_round("prd-2026-01-01", "EXECUTING", 2)
        self.write_round("prd-2026-01-05-test", "COMPLETE", 1)
        proc = self.call("init.py", "--locate", "--workspace", str(self.ws))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertTrue(payload["pm_root"].endswith("prd-2026-01-01/pm"),
                        payload["pm_root"])
        self.assertTrue(any("prd-2026-01-05-test" in w and "命名不匹配" in w
                            for w in payload["warnings"]), payload["warnings"])

    def test_locate_all_unmatched_reports_none_locatable(self):
        # R19:仅存改名轮时明确报"无可自动定位轮次",由用户点名
        self.write_round("prd-2026-01-05-test", "COMPLETE", 1)
        proc = self.call("init.py", "--locate", "--workspace", str(self.ws))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertIsNone(payload["pm_root"])
        joined = "\n".join(payload["warnings"])
        self.assertIn("无可自动定位", joined)
        self.assertIn("prd-2026-01-05-test", joined)


class TestEventSurfaceMerge(LifecycleBase):
    """任务 2.9:事件面合并(design §1.1,R29/R13/R16)。

    Why:模型此前要在 13 个 transition 子命令里选阶段推进事件,存在忘跑与
    错跑窗口(P0-3)。合并后:阶段推进随产物提交自动发生,authorized-resume
    并入 resume --raise-limit;transitions 日志仍按 v1 事件名记录。
    """

    def events(self, p):
        return [t["event"] for t in self.read_state(p)["transitions"]]

    def test_commit_plan_transfers_to_executing(self):
        p = self.init()
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "plan", str(self.plan_draft())))
        self.assertEqual(p["status"], "EXECUTING")
        self.assertEqual(p["iteration"], 1)
        state = self.read_state(p)
        last = state["transitions"][-1]
        self.assertEqual(last["event"], "plan-validated")
        self.assertEqual((last["from"], last["to"]), ("PLANNING", "EXECUTING"))
        self.assertTrue(p["next"][0]["kind"] == "draft"
                        and p["next"][0]["target"] == "artifact", p["next"])

    def test_commit_artifact_completed_transfers_to_verifying(self):
        p = self.init()
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "plan", str(self.plan_draft())))
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "artifact", str(self.artifact_draft())))
        self.assertEqual(p["status"], "VERIFYING")
        last = self.read_state(p)["transitions"][-1]
        self.assertEqual(last["event"], "artifact-validated")
        self.assertTrue(any("record_provenance" in a for a in p["next"][0]["argv"]),
                        p["next"])

    def test_commit_artifact_replan_transfers_with_increment(self):
        p = self.init()
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "plan", str(self.plan_draft())))
        p = h.out_json(self.call(
            "commit.py", "--pm-root", p["pm_root"], "artifact",
            str(self.artifact_draft(status="replan_required",
                                    name="replan.json"))))
        self.assertEqual(p["status"], "PLANNING")
        self.assertEqual(p["iteration"], 2)
        last = self.read_state(p)["transitions"][-1]
        self.assertEqual(last["event"], "executor-replan")

    def test_commit_artifact_blocked_transfers_to_waiting(self):
        p = self.init()
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "plan", str(self.plan_draft())))
        p = h.out_json(self.call(
            "commit.py", "--pm-root", p["pm_root"], "artifact",
            str(self.artifact_draft(status="blocked", name="blocked.json"))))
        self.assertEqual(p["status"], "WAITING_FOR_INPUT")
        self.assertEqual(p["iteration"], 1)
        self.assertEqual(self.read_state(p)["resume_to"], "EXECUTING")
        self.assertEqual(self.read_state(p)["transitions"][-1]["event"],
                         "executor-blocked")

    def test_commit_plan_rerun_idempotent_and_draft_change_rejected(self):
        # 重跑同草稿判已执行退出 0;EXECUTING 下重提不同 plan 草稿按阶段不匹配拒绝
        p = self.init()
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "plan", str(self.plan_draft())))
        again = self.call("commit.py", "--pm-root", p["pm_root"],
                          "plan", str(self.plan_draft()))
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertTrue(any("重跑" in w for w in h.out_json(again)["warnings"]))
        self.assertEqual(self.events(p).count("plan-validated"), 1)
        other = self.call("commit.py", "--pm-root", p["pm_root"],
                          "plan", str(self.plan_draft(
                              name="plan2.json", understanding="不同的草稿")))
        self.assertEqual(other.returncode, 1, other.stdout)
        self.assertIn("阶段不匹配", other.stdout)

    def test_commit_artifact_completed_rerun_idempotent(self):
        p = self.init()
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "plan", str(self.plan_draft())))
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "artifact", str(self.artifact_draft())))
        again = self.call("commit.py", "--pm-root", p["pm_root"],
                          "artifact", str(self.artifact_draft()))
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(self.events(p).count("artifact-validated"), 1)

    def test_resume_raise_limit_records_new_max(self):
        # R13/R16:authorized-resume 并入 resume --raise-limit,param 记新上限
        p = self.init()
        for _ in range(4):
            p = h.out_json(self.call("transition.py", "--pm-root",
                                    p["pm_root"], "need-input"))
            p = h.out_json(self.call("transition.py", "--pm-root",
                                    p["pm_root"], "resume",
                                    "--invalidate-plan"))
        p = h.out_json(self.call("transition.py", "--pm-root", p["pm_root"],
                                "need-input"))
        p = h.out_json(self.call("transition.py", "--pm-root", p["pm_root"],
                                "resume", "--invalidate-plan"))
        self.assertEqual(p["status"], "STOPPED")
        p = h.out_json(self.call("transition.py", "--pm-root", p["pm_root"],
                                "resume", "--raise-limit", "7"))
        self.assertEqual(p["status"], "PLANNING")
        self.assertEqual(p["iteration"], 6)
        state = self.read_state(p)
        self.assertEqual(state["max_iterations"], 7)
        last = state["transitions"][-1]
        self.assertEqual(last["event"], "authorized-resume")
        self.assertEqual(last["param"], 7)

    def test_merged_events_removed_from_transition_surface(self):
        # 命令面裁撤:六事件不再是 transition 子命令,报非法事件
        p = self.init()
        for event in ("start-planning", "plan-validated",
                      "artifact-validated", "executor-replan",
                      "executor-blocked", "authorized-resume"):
            with self.subTest(event=event):
                proc = self.call("transition.py", "--pm-root", p["pm_root"],
                                 event)
                self.assertEqual(proc.returncode, 1, proc.stdout)
                self.assertIn("非法事件", proc.stdout)


class TestCloseoutFold(LifecycleBase):
    """任务 2.10:收口折叠(design §2.3,R30)。

    Why:收口四步(--bind/verdict/render/complete)之间没有模型判断,拆开只
    制造中断窗口与"未绑定报告"中间态,verdict 值还要模型从报告抄进命令。
    折叠后 verdict 从报告字段读取,一条命令收敛;中断按报告与状态的组合
    分支恢复。
    """

    def to_bound_pass_not_complete(self):
        """构造"已绑定 PASS、尚未收口"的中断窗口现场(绕过脚本直写)。"""
        p = self.init()
        p = self.reach_verifying(p)
        pm = Path(p["pm_root"])
        snap = self.snapshot(p)
        ver = h.min_verification(verdict="PASS")
        ver["verification_input"] = snap
        ver["provenance"] = {k: snap[k] for k in
                             ("algorithm", "plan_path", "artifact_sha256",
                              "plan_sha256", "state_projection_sha256")}
        (pm / "iterations" / "01-verification.json").write_text(
            json.dumps(ver, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        draft = h.min_verification(verdict="PASS")
        draft["verification_input"] = snap
        self.draft("report-pass.json", draft)
        return p

    def commit_ver(self, p, name="report-pass.json"):
        return self.call("commit.py", "--pm-root", p["pm_root"],
                         "verification", str(self.ws / name))

    def test_converge_from_unbound_report_on_disk(self):
        # 边界①:报告已落盘未绑定 → 重跑同命令补绑定并收口
        p = self.init()
        p = self.reach_verifying(p)
        snap = self.snapshot(p)
        ver = h.min_verification(verdict="PASS")
        ver["verification_input"] = snap
        (Path(p["pm_root"]) / "iterations" / "01-verification.json").write_text(
            json.dumps(ver, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        draft = h.min_verification(verdict="PASS")
        draft["verification_input"] = snap
        self.draft("report-pass.json", draft)
        proc = self.commit_ver(p)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(h.out_json(proc)["status"], "COMPLETE")

    def test_converge_from_bound_untransferred(self):
        # 边界②:已绑定未转移(状态仍 VERIFYING)→ 重跑即收口,条目不重复
        p = self.to_bound_pass_not_complete()
        proc = self.commit_ver(p)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertEqual(payload["status"], "COMPLETE")
        events = [t["event"] for t in self.read_state(payload)["transitions"]]
        self.assertEqual(events.count("verdict"), 1)
        self.assertEqual(events.count("complete"), 1)

    def test_converge_from_rendered_not_complete(self):
        # 边界③:已渲染未 COMPLETE → 重跑收口,已发布字节不被改写
        p = self.to_bound_pass_not_complete()
        self.assertEqual(
            self.call("render.py", "--pm-root", p["pm_root"]).returncode, 0)
        out = Path(p["pm_root"]) / "output" / "prd.md"
        before = out.read_bytes()
        proc = self.commit_ver(p)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(h.out_json(proc)["status"], "COMPLETE")
        self.assertEqual(out.read_bytes(), before)

    def test_complete_rerun_exits_zero(self):
        # 边界④:已 COMPLETE → 判已执行退出 0,不重复收口条目
        p = self.init()
        p = self.reach_verifying(p)
        p = self.bind_pass(p)
        self.assertEqual(p["status"], "COMPLETE")
        again = self.commit_ver(p)
        self.assertEqual(again.returncode, 0, again.stdout)
        payload = h.out_json(again)
        self.assertTrue(any("重跑" in w for w in payload["warnings"]),
                        payload["warnings"])
        events = [t["event"] for t in self.read_state(payload)["transitions"]]
        self.assertEqual(events.count("complete"), 1)

    def test_pass_content_change_in_window_rejected(self):
        # R30/R2:中断窗口内内容变化,重跑被 P1 拒绝,不写 COMPLETE
        p = self.to_bound_pass_not_complete()
        pm = Path(p["pm_root"])
        art = json.loads((pm / "iterations" / "01-artifact.json")
                         .read_text(encoding="utf-8"))
        art["artifact"]["title"] = "窗口内被改写"
        (pm / "iterations" / "01-artifact.json").write_text(
            json.dumps(art, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        proc = self.commit_ver(p)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = h.out_json(proc)
        self.assertTrue(any("P1" in str(e.get("reason", ""))
                            for e in payload["errors"]), payload["errors"])
        self.assertEqual(payload["status"], "VERIFYING")

    def test_revise_at_limit_writes_stopped_with_evidence(self):
        # REVISE 越上限:报告与登记留证,写 STOPPED 拒绝转移
        p = self.init()  # PLANNING iter1
        for _ in range(4):
            p = h.out_json(self.call("transition.py", "--pm-root",
                                    p["pm_root"], "need-input"))
            p = h.out_json(self.call("transition.py", "--pm-root",
                                    p["pm_root"], "resume",
                                    "--invalidate-plan"))
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "plan", str(self.plan_draft())))
        p = h.out_json(self.call("commit.py", "--pm-root", p["pm_root"],
                                "artifact", str(self.artifact_draft())))
        p = h.out_json(self.call("record_provenance.py", "--pm-root",
                                p["pm_root"]))
        rev = h.min_verification(verdict="REVISE")
        rev["verification_input"] = self.snapshot(p)
        self.draft("report-revise.json", rev)
        proc = self.call("commit.py", "--pm-root", p["pm_root"],
                        "verification", str(self.ws / "report-revise.json"))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertEqual(payload["status"], "STOPPED")
        self.assertTrue((Path(p["pm_root"]) / "iterations" /
                         "05-verification.json").is_file(), "报告留证")
        self.assertTrue(any(n["kind"] == "stop" for n in payload["next"]),
                        payload["next"])

    def test_bound_pass_overwrite_refused_in_window(self):
        # 同号覆盖守卫:绑定 PASS 存在时,不同内容的报告提交被拒
        p = self.to_bound_pass_not_complete()
        rev = h.min_verification(verdict="REVISE")
        rev["verification_input"] = self.snapshot(p)
        self.draft("report-revise.json", rev)
        proc = self.call("commit.py", "--pm-root", p["pm_root"],
                        "verification", str(self.ws / "report-revise.json"))
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("绑定", proc.stdout)
        self.assertEqual(h.out_json(proc)["status"], "VERIFYING")


if __name__ == "__main__":
    unittest.main()
