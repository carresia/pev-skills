"""收口链路回归测试。

两部分:
- 基线组:固定现行 validate.py 已有且 design.md 保留的行为(R1–R5、合法中间态、坏 JSON 必报错)。这些必须始终为绿。
- 缺口组:固定 design.md 的新契约,对应 proposal.md 背景里的原始事故;实现落地(2.3/2.7)之前按预期失败(RED),失败本身就是缺口的复现。

运行(skill 根目录): python3 -m unittest discover -s tests -t . -v
"""

import unittest

from tests import helpers as h


class CloseoutTestCase(unittest.TestCase):
    def setUp(self):
        self.pm = h.PmDir()
        self.addCleanup(self.pm.cleanup)

    def build_chain(self, status="VERIFYING", iteration=1, verdict="PASS", bind=False):
        """搭一条 plan+artifact+verification 链;bind=True 时写入与当前内容一致的 provenance。"""
        state = h.min_state(status=status, iteration=iteration,
                            evidence=[h.min_evidence()])
        self.pm.state = state
        plan = h.min_plan()
        artifact = h.min_artifact()
        self.pm.write_doc(iteration, "plan", plan)
        self.pm.write_doc(iteration, "artifact", artifact)
        ver = h.min_verification(verdict=verdict)
        if bind:
            ver["provenance"] = h.min_provenance(
                self.pm, iteration=iteration, plan=plan,
                artifact=artifact, state=state)
        self.pm.write_doc(iteration, "verification", ver)
        return plan, artifact, ver


class TestCurrentBehaviorBaseline(CloseoutTestCase):
    """design.md 明确保留的现行行为;始终为绿。"""

    def test_init_state_without_any_artifact_passes(self):
        # design:INIT 尚无产物是合法中间态
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_verifying_chain_without_verification_file_passes(self):
        # design:VERIFYING 尚未提交报告是合法中间态
        self.pm.state = h.min_state(status="VERIFYING", iteration=1,
                                    evidence=[h.min_evidence()])
        self.pm.flush_state()
        self.pm.write_doc(1, "plan", h.min_plan())
        self.pm.write_doc(1, "artifact", h.min_artifact())
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_revise_round_reusing_old_plan_passes(self):
        # design:REVISE 复用早先 Plan(第 2 轮只有 artifact+verification,没有 plan 文件)
        self.pm.state = h.min_state(status="VERIFYING", iteration=2,
                                    evidence=[h.min_evidence()])
        self.pm.flush_state()
        self.pm.write_doc(1, "plan", h.min_plan())
        self.pm.write_doc(2, "artifact", h.min_artifact())
        self.pm.write_doc(2, "verification", h.min_verification())
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_truncated_json_reported(self):
        # proposal:单个 JSON 文件写入不完整仍必须报错
        self.pm.write_raw("iterations/01-artifact.json", '{"status":"completed",')
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("01-artifact.json", proc.stdout)

    def test_unknown_iteration_filename_rejected(self):
        self.pm.write_raw("iterations/01-other.json", "{}")
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("01-other.json", proc.stdout)

    def test_r1_inference_without_evidence_rejected(self):
        self.pm.state = h.min_state(status="EXECUTING", iteration=1,
                                    evidence=[h.min_evidence(type_="INFERENCE",
                                                             evidence=None)])
        self.pm.flush_state()
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("R1", proc.stdout)

    def test_r2_blocked_without_reason_rejected(self):
        self.pm.state = h.min_state(status="EXECUTING", iteration=1)
        self.pm.flush_state()
        self.pm.write_doc(1, "artifact", h.min_artifact(status="blocked",
                                                        replan_reason=None))
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("R2", proc.stdout)

    def test_r2_blocked_with_reason_passes(self):
        self.pm.state = h.min_state(status="EXECUTING", iteration=1)
        self.pm.flush_state()
        self.pm.write_doc(1, "artifact", h.min_artifact(status="blocked"))
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_r3_waiting_without_resume_to_rejected(self):
        self.pm.state = h.min_state(status="WAITING_FOR_INPUT", iteration=1)
        self.pm.flush_state()
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("R3", proc.stdout)

    def test_r3_resume_to_outside_waiting_rejected(self):
        self.pm.state = h.min_state(status="PLANNING", iteration=1,
                                    resume_to="PLANNING")
        self.pm.flush_state()
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("R3", proc.stdout)

    def test_r4_unregistered_artifact_rejected(self):
        self.pm.state = h.min_state(status="EXECUTING", iteration=1)
        self.pm.flush_state()
        self.pm.write_doc(1, "artifact", h.min_artifact(), register=False)
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("R4", proc.stdout)

    def test_r4_registered_but_missing_file_rejected(self):
        self.pm.state = h.min_state(status="PLANNING", iteration=1,
                                    plans=["01-plan.json"])
        self.pm.flush_state()
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("R4", proc.stdout)
        self.assertIn("01-plan.json", proc.stdout)

    def test_r5_pass_with_required_changes_rejected(self):
        self.pm.state = h.min_state(status="VERIFYING", iteration=1,
                                    evidence=[h.min_evidence()])
        self.pm.flush_state()
        self.pm.write_doc(1, "plan", h.min_plan())
        self.pm.write_doc(1, "artifact", h.min_artifact())
        self.pm.write_doc(1, "verification",
                          h.min_verification(required_changes=["必须补 X"]))
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("R5", proc.stdout)

    def test_r5_revise_without_required_changes_rejected(self):
        self.pm.state = h.min_state(status="VERIFYING", iteration=1,
                                    evidence=[h.min_evidence()])
        self.pm.flush_state()
        self.pm.write_doc(1, "plan", h.min_plan())
        self.pm.write_doc(1, "artifact", h.min_artifact())
        self.pm.write_doc(1, "verification", h.min_verification(verdict="REVISE",
                                                                required_changes=[]))
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("R5", proc.stdout)


class TestOriginalGapContract(CloseoutTestCase):
    """design.md 新契约。实现(2.3/2.7)之前预期失败——失败即复现 proposal 背景的原始缺口。"""

    def test_empty_completed_artifact_rejected(self):
        # scripting-audit §3 实测:{"status":"completed","artifact":{}} 现状被放行(B 类缺口)
        self.pm.state = h.min_state(status="EXECUTING", iteration=1)
        self.pm.flush_state()
        self.pm.write_doc(1, "plan", h.min_plan())
        self.pm.write_doc(1, "artifact", {"status": "completed", "artifact": {}})
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("01-artifact.json" in str(e.get("file", ""))
                            for e in payload["errors"]), payload["errors"])

    def test_complete_without_any_pass_rejected(self):
        # 01:44:40 事故形态:没有任何验证轮就写 COMPLETE
        self.pm.state = h.min_state(status="COMPLETE", iteration=1,
                                    evidence=[h.min_evidence()])
        self.pm.flush_state()
        self.pm.write_doc(1, "plan", h.min_plan())
        self.pm.write_doc(1, "artifact", h.min_artifact())
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["errors"])

    def test_complete_with_unbound_legacy_pass_warns_not_deliverable(self):
        # design:15 旧数据 COMPLETE+PASS 无 provenance——格式通过,但必须警告不可交付
        self.build_chain(status="COMPLETE", bind=False)
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertTrue(payload["ok"])
        self.assertTrue(any("不可交付" in str(w) for w in payload["warnings"]),
                        payload["warnings"])

    def test_artifact_modified_after_bound_pass_rejected(self):
        # 核心事故:PASS 落盘后 Artifact 被改写,旧 PASS 被沿用(proposal 背景 01:45:32)
        plan, artifact, ver = self.build_chain(status="VERIFYING", bind=True)
        artifact["artifact"]["title"] = "PASS 之后被改写的标题"
        self.pm.write_doc(1, "artifact", artifact)
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        self.assertIn("01-artifact", proc.stdout)

    def test_state_semantic_field_changed_after_bound_pass_rejected(self):
        # 仅改 state 语义字段(如 known)同样使绑定 PASS 失效
        plan, artifact, ver = self.build_chain(status="VERIFYING", bind=True)
        self.pm.state["known"] = self.pm.state.get("known", []) + ["PASS 之后追加的事实"]
        self.pm.flush_state()
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        self.assertIn("state.json", proc.stdout)

    def test_bound_and_consistent_chain_passes(self):
        # 对照:绑定且内容一致的合法链路必须通过(合法对照用例不必在旧版失败)
        self.build_chain(status="VERIFYING", bind=True)
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class TestReportTier(CloseoutTestCase):
    """任务 2.1:交付权威分级(P1 拆分,design §2.2)。

    Why:历史报告存的投影摘要对应验证当时,而投影没有历史快照;同轮任何一次合法
    语义追加(补证据)都会被"按当前投影复算"染成 P1,整轮永久无法收口(P0-1)。
    分级后:当轮权威(N==iteration)三摘要全复算;历史(N<iteration)只复算
    artifact/plan,投影不复算;N>iteration 属登记册对账口径,P1 不分级。
    """

    @staticmethod
    def tier(state, ver_name):
        import sys as _sys
        scripts = str(h.SKILL_ROOT / "scripts")
        if scripts not in _sys.path:
            _sys.path.insert(0, scripts)
        import validate as v
        return v.report_tier(state, ver_name)

    def test_report_tier_matrix(self):
        st = h.min_state(status="VERIFYING", iteration=4)
        self.assertEqual(self.tier(st, "iterations/04-verification.json"), "authority")
        self.assertEqual(self.tier(st, "iterations/03-verification.json"), "history")
        self.assertIsNone(self.tier(st, "iterations/05-verification.json"))
        self.assertIsNone(self.tier(st, "iterations/xx-verification.json"))
        self.assertIsNone(self.tier(h.min_state(status="VERIFYING", iteration=None),
                                    "iterations/01-verification.json"))

    def build_two_round_chain(self):
        """轮 1 完整链(绑定)+ 抬到轮 2(复用轮 1 Plan)前的现场。"""
        state1 = h.min_state(status="VERIFYING", iteration=1,
                             evidence=[h.min_evidence(1)])
        self.pm.state = state1
        plan1 = h.min_plan()
        art1 = h.min_artifact()
        self.pm.write_doc(1, "plan", plan1)
        self.pm.write_doc(1, "artifact", art1)
        ver1 = h.min_verification()
        ver1["provenance"] = h.min_provenance(self.pm, iteration=1, plan=plan1,
                                              artifact=art1, state=state1)
        self.pm.write_doc(1, "verification", ver1)
        return plan1, art1, ver1

    def test_history_report_projection_drift_not_flagged(self):
        # P0-1 核心解除:reopen/REVISE 后同轮追加证据,历史绑定报告不得再报 P1
        self.build_two_round_chain()
        # 原地演进(等价 reopen 后补证据):iteration 抬到 2、evidence 追加,登记册不动
        self.pm.state["iteration"] = 2
        self.pm.state["evidence"] = [h.min_evidence(1), h.min_evidence(2)]
        self.pm.flush_state()
        self.pm.write_doc(2, "artifact", h.min_artifact())
        self.pm.write_doc(2, "verification", h.min_verification())
        proc = h.run_validate(self.pm.root)
        payload = h.out_json(proc)
        self.assertEqual(proc.returncode, 0, payload)
        self.assertFalse(
            any(e.get("file") == "state.json" and "P1" in str(e.get("reason", ""))
                for e in payload["errors"]),
            payload["errors"])

    def test_history_artifact_tamper_still_p1_with_code(self):
        # 历史文件不可变的接棒防线:轮 1 artifact 被直接改写仍必须 P1,且带 code
        self.build_two_round_chain()
        art1 = h.min_artifact()
        art1["artifact"]["title"] = "历史轮被直接改写"
        self.pm.write_doc(1, "artifact", art1)
        self.pm.state["iteration"] = 2
        self.pm.flush_state()
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = h.out_json(proc)
        hits = [e for e in payload["errors"]
                if "01-artifact" in str(e.get("file", ""))
                and "P1" in str(e.get("reason", ""))]
        self.assertTrue(hits, payload["errors"])
        self.assertTrue(all(e.get("code") == "P1_PROVENANCE_MISMATCH" for e in hits),
                        payload["errors"])

    def test_authority_projection_mismatch_carries_code(self):
        # R10:当轮权威投影不符 → P1 错误必须携带 code(供脚本化消费)
        self.build_chain(status="VERIFYING", bind=True)
        self.pm.state["known"] = self.pm.state.get("known", []) + ["绑定后追加"]
        self.pm.flush_state()
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = h.out_json(proc)
        hits = [e for e in payload["errors"]
                if e.get("file") == "state.json" and "P1" in str(e.get("reason", ""))]
        self.assertTrue(hits, payload["errors"])
        self.assertTrue(all(e.get("code") == "P1_PROVENANCE_MISMATCH" for e in hits),
                        payload["errors"])

    def test_complete_closeout_pass_drift_still_p1(self):
        # 验收行:prd-2026-10-21/pm 形态(COMPLETE 收口 PASS 漂移)在合成夹具上仍 P1
        plan, artifact, ver = self.build_chain(status="COMPLETE", bind=True)
        artifact["artifact"]["title"] = "收口后被改写"
        self.pm.write_doc(1, "artifact", artifact)
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        payload = h.out_json(proc)
        hits = [e for e in payload["errors"]
                if "01-artifact" in str(e.get("file", ""))
                and "P1" in str(e.get("reason", ""))]
        self.assertTrue(hits, payload["errors"])
        self.assertTrue(all(e.get("code") == "P1_PROVENANCE_MISMATCH" for e in hits),
                        payload["errors"])


if __name__ == "__main__":
    unittest.main()


class SnapshotTestCase(CloseoutTestCase):
    """快照与绑定公共夹具:一条已登记 plan+artifact、尚无 verification 的当轮。"""

    def build_round(self, status="VERIFYING", iteration=1):
        state = h.min_state(status=status, iteration=iteration,
                            evidence=[h.min_evidence()])
        self.pm.state = state
        plan = h.min_plan()
        artifact = h.min_artifact()
        self.pm.write_doc(iteration, "plan", plan)
        self.pm.write_doc(iteration, "artifact", artifact)
        return state, plan, artifact

    def run_rp(self, *flags):
        return h.run_script("record_provenance.py",
                            "--pm-root", str(self.pm.root), *flags)

    def snap_path(self, n=1):
        return self.pm.iter_dir / f"{n:02d}-verification-input.json"

    def ver_path(self, n=1):
        return self.pm.iter_dir / f"{n:02d}-verification.json"

    def expected_snapshot(self, state, plan, artifact, iteration=1):
        return {
            "algorithm": "sha256-v1",
            "iteration": iteration,
            "plan_path": f"iterations/{iteration:02d}-plan.json",
            "artifact_sha256": h.canonical_sha256(artifact),
            "plan_sha256": h.canonical_sha256(plan),
            "state_projection_sha256": h.canonical_sha256(
                h.state_projection(state)),
        }


class TestSnapshotContract(SnapshotTestCase):
    """iterations/<N>-verification-input.json 快照契约(design:23)。"""

    def test_snapshot_written_with_exact_fields(self):
        state, plan, artifact = self.build_round()
        proc = self.run_rp()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertTrue(payload["ok"])
        snap = __import__("json").loads(self.snap_path().read_text(encoding="utf-8"))
        self.assertEqual(snap, self.expected_snapshot(state, plan, artifact))
        self.assertEqual(payload["written"], ["iterations/01-verification-input.json"])
        self.assertEqual(len(payload["next"]), 1)
        nxt = payload["next"][0]
        self.assertEqual(nxt["kind"], "dispatch-verifier")
        self.assertEqual(nxt["snapshot"], "iterations/01-verification-input.json")
        self.assertEqual(nxt["artifact"], "iterations/01-artifact.json")
        self.assertEqual(nxt["plan"], "iterations/01-plan.json")

    def test_snapshot_rerun_idempotent_no_rewrite(self):
        self.build_round()
        self.assertEqual(self.run_rp().returncode, 0)
        before = self.snap_path().read_bytes()
        proc = self.run_rp()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(h.out_json(proc)["written"], [])
        self.assertEqual(self.snap_path().read_bytes(), before)

    def test_snapshot_rewritten_when_source_changed_before_binding(self):
        # 中断恢复两分支之一:派发后输入变更、尚无绑定 PASS → 原位重写快照重新派发
        state, plan, artifact = self.build_round()
        self.assertEqual(self.run_rp().returncode, 0)
        artifact["artifact"]["title"] = "派发之后被改写"
        self.pm.write_doc(1, "artifact", artifact)
        proc = self.run_rp()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertEqual(payload["written"], ["iterations/01-verification-input.json"])
        snap = __import__("json").loads(self.snap_path().read_text(encoding="utf-8"))
        self.assertEqual(snap["artifact_sha256"], h.canonical_sha256(artifact))

    def test_snapshot_rewrite_refused_after_binding(self):
        # 绑定 PASS 后快照与同编号产物一律只读,修订须新建轮次
        state, plan, artifact = self.build_round()
        self.assertEqual(self.run_rp().returncode, 0)
        ver = h.min_verification()
        ver["verification_input"] = self.expected_snapshot(state, plan, artifact)
        self.pm.write_doc(1, "verification", ver)
        self.assertEqual(self.run_rp("--bind").returncode, 0)
        before = self.snap_path().read_bytes()
        artifact["artifact"]["title"] = "绑定之后再改"
        self.pm.write_doc(1, "artifact", artifact)
        proc = self.run_rp()
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(h.out_json(proc)["ok"])
        self.assertEqual(self.snap_path().read_bytes(), before)

    def test_snapshot_file_passes_validate_without_registry(self):
        self.build_round()
        self.assertEqual(self.run_rp().returncode, 0)
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 0, proc.stdout)


class TestProvenanceBinding(SnapshotTestCase):
    """--bind:报告复述一致 + 复算一致才写 provenance(design:23/25)。"""

    def bind_ready(self):
        state, plan, artifact = self.build_round()
        self.assertEqual(self.run_rp().returncode, 0)
        snap = self.expected_snapshot(state, plan, artifact)
        ver = h.min_verification()
        ver["verification_input"] = dict(snap)
        self.pm.write_doc(1, "verification", ver)
        return state, plan, artifact, snap, ver

    def test_bind_writes_provenance_and_returns_verdict_step(self):
        state, plan, artifact, snap, ver = self.bind_ready()
        proc = self.run_rp("--bind")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertTrue(payload["ok"])
        saved = __import__("json").loads(self.ver_path().read_text(encoding="utf-8"))
        self.assertEqual(saved["provenance"], {
            "algorithm": "sha256-v1",
            "plan_path": snap["plan_path"],
            "artifact_sha256": snap["artifact_sha256"],
            "plan_sha256": snap["plan_sha256"],
            "state_projection_sha256": snap["state_projection_sha256"],
        })
        self.assertEqual(payload["written"], ["iterations/01-verification.json"])
        self.assertEqual(payload["next"][0]["kind"], "command")
        self.assertIn("verdict", payload["next"][0]["argv"])

    def test_bind_idempotent_when_already_bound_consistent(self):
        self.bind_ready()
        self.assertEqual(self.run_rp("--bind").returncode, 0)
        before = self.ver_path().read_bytes()
        proc = self.run_rp("--bind")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.ver_path().read_bytes(), before)

    def test_bind_rejects_missing_restatement(self):
        state, plan, artifact = self.build_round()
        self.assertEqual(self.run_rp().returncode, 0)
        self.pm.write_doc(1, "verification", h.min_verification())
        proc = self.run_rp("--bind")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(h.out_json(proc)["ok"])
        saved = __import__("json").loads(self.ver_path().read_text(encoding="utf-8"))
        self.assertNotIn("provenance", saved)

    def test_bind_rejects_wrong_restatement(self):
        state, plan, artifact, snap, ver = self.bind_ready()
        ver["verification_input"]["artifact_sha256"] = "0" * 64
        self.pm.write_doc(1, "verification", ver)
        proc = self.run_rp("--bind")
        self.assertEqual(proc.returncode, 1)

    def test_bind_rejects_source_changed_after_dispatch(self):
        # 复算不一致:报冲突路径,不作废快照;恢复是重写快照重新派发,不手改报告
        state, plan, artifact, snap, ver = self.bind_ready()
        artifact["artifact"]["title"] = "派发之后被改写"
        self.pm.write_doc(1, "artifact", artifact)
        proc = self.run_rp("--bind")
        self.assertEqual(proc.returncode, 1)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("01-artifact" in str(e.get("file", ""))
                            for e in payload["errors"]), payload["errors"])
        saved = __import__("json").loads(self.ver_path().read_text(encoding="utf-8"))
        self.assertNotIn("provenance", saved)

    def test_bind_requires_submitted_report(self):
        self.build_round()
        self.assertEqual(self.run_rp().returncode, 0)
        proc = self.run_rp("--bind")
        self.assertEqual(proc.returncode, 1)


class TestValidateProtocol(CloseoutTestCase):
    """validate.py 的 JSON 协议与新语义(2.3 范围;B/C 类归 2.7)。"""

    def test_ok_payload_shape(self):
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "INIT")
        self.assertEqual(payload["iteration"], 0)
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["next"], [])

    def test_unbound_current_report_warns_not_deliverable_in_verifying(self):
        self.build_chain(status="VERIFYING", bind=False)
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertTrue(payload["ok"])
        self.assertTrue(any("不可交付" in str(w) for w in payload["warnings"]),
                        payload["warnings"])

    def test_legacy_complete_pass_without_provenance_warns(self):
        # 即 design:15 旧数据口径:格式通过 + 明确不可交付
        self.build_chain(status="COMPLETE", bind=False)
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        self.assertTrue(any("旧轮次缺绑定" in str(w) for w in payload["warnings"]),
                        payload["warnings"])

    def test_bound_pass_with_current_state_passes_validate(self):
        self.build_chain(status="VERIFYING", bind=True)
        proc = h.run_validate(self.pm.root)
        self.assertEqual(proc.returncode, 0, proc.stdout)
