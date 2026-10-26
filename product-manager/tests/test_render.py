"""本地渲染器契约测试(design.md"本地渲染器契约"与"输出发布协议")。

全部在实现 scripts/render.py 之前编写;实现落地前按预期失败(RED)。
运行(skill 根目录): python3 -m unittest discover -s tests -t . -v
"""

import os
import shutil
import unittest

from tests import helpers as h

E1 = dict(claim="合成论断1", type_="FACT", evidence="activation_rate.csv")
E2 = dict(i=2, claim="合成论断2", type_="HYPOTHESIS", evidence=None,
          confidence="low")

EXPECTED_PRD = """# PRD: 合成 PRD:消息推送优化

## 1. 背景

留存数据显示新用户次周流失集中在首周内。（含证据引用）

## 2. 目标

- 业务目标：通过首周引导推送把次周留存率从 20% 提升到 25%
- Primary Metric: 次周留存率（baseline → target）
- Secondary Metrics: 
- Guardrail Metrics: 

## 3. 用户与场景

- 作为 新注册用户，我希望 收到首周引导推送，以便 更快完成关键动作。


## 4. 方案

首周第 1/3/5 天推送个性化引导（为什么对应根因：流失时点集中在第 2-4 天,引导推送对应补齐）

## 5. 功能范围

### In Scope
首周推送文案
频控策略

### Out of Scope
推送通道改造

## 6. 验证数据需求（埋点与口径）

本节定义上线后需要收集哪些数据来验证这个需求的价值。如果某个指标的口径在现有项目中不存在，对应的数据采集工作就是开发工作，必须列入第 5 节的 In Scope。

| 指标 | 口径定义 | 验证什么 | 数据来源 |
|---|---|---|---|
| 次周留存率 | 注册后第 7-14 天活跃占比 | 验证目标达成 | 现有埋点（现有 / 需新增） |


## 7. 风险与预案



## 8. 上线与验收

- 上线计划：灰度 10% 一周后全量
- 验收标准：次周留存率相对对照组提升不低于 3 个百分点"""

EXPECTED_DECISION = """# Decision: 合成决策:推送 vs 引导页改版

## 结论

首周推送的预期收益更高（confidence: high）

## 证据

| Claim | Type | Evidence |
|---|---|---|
| 合成论断1 | FACT | activation_rate.csv |
| 合成论断2 | HYPOTHESIS |  |


## 备选方案


### 首周推送
- 收益：留存 +3pp（confidence: high）
- 成本：2 人周
- 风险：频控打扰; 退订率上升

### 引导页改版
- 收益：留存 +1pp（confidence: medium）
- 成本：3 人周
- 风险：


## ROI 测算

预计 ROI 1.8(口径:留存增益折算)

## 决策建议

先做首周推送,两周后复测"""

EXPECTED_OPPORTUNITY = """# Product Opportunity: 合成机会:新用户激活

## 业务目标与指标

- Goal: 提升新用户激活率
- Target Metric: 激活率（baseline: 20% → target: 25%）

## 问题与根因

新用户首周无关键动作 → 缺少引导触点

## 证据（Evidence Ledger 摘要）

| Claim | Type | Evidence | Confidence |
|---|---|---|---|
| 合成论断1 | FACT | activation_rate.csv | high |
| 合成论断2 | HYPOTHESIS |  | low |


## 机会清单与优先级


### 首周推送引导（P0）
- 预期影响：激活率 +3pp
- 依据：E1
- 置信度：high


## 建议

优先做首周推送引导"""

EXPECTED_PLAN = """# Plan: 把新用户次周留存率从 20% 提升到 25%

## Understanding

流失集中在首周,疑与引导缺失相关。

## Known / Unknown / Assumptions

- **Known**: 次周留存率 20%
- **Unknown**: 流失根因
- **Assumptions**: 

## Steps

| ID | Objective | Action | Inputs | Expected Output | Success Criteria |
|---|---|---|---|---|---|
| P1 | 定位流失根因并起草方案 | draft | state.evidence | Artifact | B/C 类通过 |


## Final Deliverable

计划文档

## Stop Conditions

证据不足以支撑结论时停止"""


def expected_bytes(text):
    """统一断言:UTF-8、LF、恰一个末尾换行。"""
    return text + "\n"


class RenderBase(unittest.TestCase):
    def setUp(self):
        self.pm = h.PmDir(state=h.min_state(
            status="VERIFYING", iteration=1,
            evidence=[h.min_evidence(**E1), h.min_evidence(**E2)]))
        self.addCleanup(self.pm.cleanup)
        self.plan = h.min_plan()
        self.pm.write_doc(1, "plan", self.plan)
        self.artifact = h.min_artifact()
        self.pm.write_doc(1, "artifact", self.artifact)

    def render(self, *flags):
        return h.run_script("render.py", "--pm-root", str(self.pm.root), *flags)

    def read_output(self, name="prd.md"):
        return (self.pm.root / "output" / name).read_text(encoding="utf-8")


class TestDeliverableSelection(RenderBase):
    """final_deliverable 规范映射:规则 (1) 字面引用 → (2) 别名精确匹配 → (3) 拒绝。"""

    def set_fd(self, fd):
        self.plan["final_deliverable"] = fd
        self.pm.write_doc(1, "plan", self.plan)

    def test_alias_each_template(self):
        bodies = {"PRD": h.min_artifact(), "决策文档": h.min_decision_artifact(),
                  "产品机会文档": h.min_opportunity_artifact(), "计划文档": None}
        for alias, out in [("PRD", "prd.md"), ("决策文档", "decision.md"),
                           ("产品机会文档", "product-opportunity.md"),
                           ("计划文档", "plan.md")]:
            with self.subTest(alias=alias):
                shutil.rmtree(self.pm.root / "output", ignore_errors=True)
                self.set_fd(alias)
                if bodies[alias] is not None:
                    self.pm.write_doc(1, "artifact", bodies[alias])
                proc = self.render()
                self.assertEqual(proc.returncode, 0, proc.stdout)
                self.assertEqual(h.out_json(proc)["written"], [f"output/{out}"])
                self.assertTrue((self.pm.root / "output" / out).is_file())

    def test_descriptive_reference_selects_named_template(self):
        # 现行真实 Plan 的描述性引用形态,规则 (1) 恰命中一个 name
        self.set_fd("templates/prd.md 渲染的 PRD（渲染到 output/ 目录）")
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(h.out_json(proc)["written"], ["output/prd.md"])

    def test_two_different_names_rejected_as_ambiguous(self):
        self.set_fd("对照 templates/prd.md 与 templates/decision.md 取舍")
        proc = self.render()
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(h.out_json(proc)["ok"])

    def test_out_of_set_template_name_rejected(self):
        self.set_fd("按 templates/weekly.md 出周报")
        proc = self.render()
        self.assertEqual(proc.returncode, 1)

    def test_path_traversal_rejected(self):
        self.set_fd("templates/../../../secrets.md")
        proc = self.render()
        self.assertEqual(proc.returncode, 1)

    def test_alias_match_is_case_sensitive_and_exact(self):
        self.set_fd("prd")
        proc = self.render()
        self.assertEqual(proc.returncode, 1)

    def test_unmatched_string_rejected_with_legal_set(self):
        self.set_fd("周报")
        proc = self.render()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("prd", proc.stdout)
        self.assertIn("decision", proc.stdout)


class TestPrdRendering(RenderBase):
    def test_full_document_bytes(self):
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.read_output(), expected_bytes(EXPECTED_PRD))

    def test_deterministic_rerender_identical_bytes(self):
        first = self.read_output() if self.render().returncode == 0 else None
        self.assertIsNotNone(first)
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.read_output(), first)

    def test_missing_required_field_no_publish_and_old_preserved(self):
        self.assertEqual(self.render().returncode, 0)
        old = self.read_output()
        self.artifact["artifact"].pop("launch_plan")
        self.pm.write_doc(1, "artifact", self.artifact)
        proc = self.render()
        self.assertEqual(proc.returncode, 1)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("launch_plan" in str(e.get("json_path", ""))
                            for e in payload["errors"]), payload["errors"])
        self.assertEqual(self.read_output(), old)

    def test_optional_empty_renders_empty_inline(self):
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("- Secondary Metrics: \n", self.read_output())

    def test_waived_required_field_renders_empty(self):
        self.artifact["artifact"].pop("launch_plan")
        self.artifact["waived_fields"] = [
            {"field": "launch_plan", "reason": "本次为内部预研,无上线动作",
             "source": "2026-10-23"}]
        self.pm.write_doc(1, "artifact", self.artifact)
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("- 上线计划：\n", self.read_output())

    def test_malformed_waiver_entry_rejected(self):
        self.artifact["artifact"].pop("launch_plan")
        self.artifact["waived_fields"] = [{"field": "launch_plan"}]
        self.pm.write_doc(1, "artifact", self.artifact)
        proc = self.render()
        self.assertEqual(proc.returncode, 1)

    def test_duplicate_waiver_field_rejected(self):
        self.artifact["artifact"].pop("launch_plan")
        self.artifact["waived_fields"] = [
            {"field": "launch_plan", "reason": "a", "source": "2026-10-23"},
            {"field": "launch_plan", "reason": "b", "source": "2026-10-23"}]
        self.pm.write_doc(1, "artifact", self.artifact)
        proc = self.render()
        self.assertEqual(proc.returncode, 1)

    def test_unreplaced_placeholder_in_value_rejected(self):
        self.artifact["artifact"]["title"] = "带占位符 {{hack}} 的标题"
        self.pm.write_doc(1, "artifact", self.artifact)
        proc = self.render()
        self.assertEqual(proc.returncode, 1)

    def test_inline_specials_escaped(self):
        self.artifact["artifact"]["solution"] = "推送 *首周* 引导 `码` [链] <b>"
        self.pm.write_doc(1, "artifact", self.artifact)
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn(
            "推送 \\*首周\\* 引导 \\`码\\` \\[链\\] \\<b\\>（为什么对应根因",
            self.read_output())

    def test_scalar_newline_flattened_inline(self):
        self.artifact["artifact"]["goal"] = "两行目标\n第二行"
        self.pm.write_doc(1, "artifact", self.artifact)
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("- 业务目标：两行目标 第二行\n", self.read_output())

    def test_table_cell_escapes_pipe_backslash_newline(self):
        self.artifact["artifact"]["validation_metrics"][0] = {
            "name": "率|表", "definition": "含\\反斜杠", "purpose": "两\n行",
            "source": "现有埋点"}
        self.pm.write_doc(1, "artifact", self.artifact)
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("| 率\\|表 | 含\\\\反斜杠 | 两 行 | 现有埋点（现有 / 需新增） |",
                      self.read_output())


class TestDecisionRendering(RenderBase):
    def setUp(self):
        super().setUp()
        self.plan["final_deliverable"] = "决策文档"
        self.pm.write_doc(1, "plan", self.plan)
        self.artifact = h.min_decision_artifact()
        self.pm.write_doc(1, "artifact", self.artifact)

    def test_full_document_bytes(self):
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.read_output("decision.md"),
                         expected_bytes(EXPECTED_DECISION))

    def test_empty_evidence_zero_rows(self):
        self.pm.state["evidence"] = []
        self.pm.flush_state()
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        out = self.read_output("decision.md")
        self.assertIn("| Claim | Type | Evidence |\n|---|---|---|\n\n", out)


class TestOpportunityRendering(RenderBase):
    def setUp(self):
        super().setUp()
        self.plan["final_deliverable"] = "产品机会文档"
        self.pm.write_doc(1, "plan", self.plan)
        self.artifact = h.min_opportunity_artifact()
        self.pm.write_doc(1, "artifact", self.artifact)

    def test_full_document_bytes(self):
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.read_output("product-opportunity.md"),
                         expected_bytes(EXPECTED_OPPORTUNITY))

    def test_number_scalar_rendered_plain(self):
        self.artifact["artifact"]["baseline"] = 0.2
        self.pm.write_doc(1, "artifact", self.artifact)
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("（baseline: 0.2 → target: 25%）",
                      self.read_output("product-opportunity.md"))


class TestPlanRendering(RenderBase):
    def setUp(self):
        super().setUp()
        self.plan["final_deliverable"] = "计划文档"
        self.pm.write_doc(1, "plan", self.plan)

    def test_full_document_bytes(self):
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.read_output("plan.md"),
                         expected_bytes(EXPECTED_PLAN))


class TestCheckAndPrune(RenderBase):
    def test_check_passes_after_publish(self):
        self.render()
        proc = self.render("--check")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue(h.out_json(proc)["ok"])

    def test_check_detects_hand_edit(self):
        self.render()
        with open(self.pm.root / "output" / "prd.md", "a", encoding="utf-8") as f:
            f.write("手工追加的一行\n")
        proc = self.render("--check")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("prd.md", proc.stdout)

    def test_check_detects_missing_output(self):
        self.render()
        (self.pm.root / "output" / "prd.md").unlink()
        proc = self.render("--check")
        self.assertEqual(proc.returncode, 1)

    def test_check_detects_stale_output_after_source_change(self):
        self.render()
        self.artifact["artifact"]["title"] = "PASS 之后被改写的标题"
        self.pm.write_doc(1, "artifact", self.artifact)
        proc = self.render("--check")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("prd.md", proc.stdout)

    def test_check_rejects_residue_files(self):
        self.render()
        (self.pm.root / "output" / "old-thing.md").write_text("旧交付残留\n",
                                                             encoding="utf-8")
        proc = self.render("--check")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("old-thing.md", proc.stdout)

    def test_publish_refuses_residue_and_names_file(self):
        out_dir = self.pm.root / "output"
        out_dir.mkdir()
        (out_dir / "old-thing.md").write_text("旧交付残留\n", encoding="utf-8")
        proc = self.render()
        self.assertEqual(proc.returncode, 1)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("old-thing.md" in str(e.get("reason", "")) + str(e.get("file", ""))
                            for e in payload["errors"]), payload["errors"])
        self.assertFalse((out_dir / "prd.md").exists())

    def test_prune_deletes_only_residue(self):
        out_dir = self.pm.root / "output"
        out_dir.mkdir()
        (out_dir / "old-thing.md").write_text("旧交付残留\n", encoding="utf-8")
        proc = self.render("--prune")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(h.out_json(proc)["deleted"], ["output/old-thing.md"])
        self.assertFalse((out_dir / "old-thing.md").exists())
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_prune_idempotent(self):
        self.render("--prune")
        proc = self.render("--prune")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(h.out_json(proc)["deleted"], [])

    def test_write_failure_preserves_published_file(self):
        self.render()
        old = self.read_output()
        out_dir = self.pm.root / "output"
        os.chmod(out_dir, 0o555)
        self.addCleanup(os.chmod, out_dir, 0o755)
        proc = self.render()
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.read_output(), old)
        self.assertEqual(sorted(p.name for p in out_dir.iterdir()), ["prd.md"])


class TestProtocol(RenderBase):
    def test_success_payload_shape(self):
        proc = self.render()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        payload = h.out_json(proc)
        for key in ("ok", "command", "pm_root", "skill_root", "status",
                    "iteration", "written", "deleted", "errors", "warnings",
                    "next"):
            self.assertIn(key, payload, key)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["written"], ["output/prd.md"])
        self.assertEqual(payload["deleted"], [])
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["status"], "VERIFYING")
        self.assertEqual(payload["iteration"], 1)
        self.assertEqual(len(payload["next"]), 1)
        nxt = payload["next"][0]
        self.assertEqual(nxt["kind"], "command")
        self.assertEqual(nxt["argv"][0], "scripts/transition.py")
        self.assertIn("complete", nxt["argv"])

    def test_failure_payload_shape(self):
        self.artifact["artifact"].pop("launch_plan")
        self.pm.write_doc(1, "artifact", self.artifact)
        proc = self.render()
        self.assertEqual(proc.returncode, 1)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["errors"])
        for e in payload["errors"]:
            self.assertIn("file", e)
            self.assertIn("json_path", e)
            self.assertIn("reason", e)

    def test_missing_pm_root_arg_reported_in_protocol(self):
        proc = h.run_script("render.py")
        self.assertEqual(proc.returncode, 1)
        payload = h.out_json(proc)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["errors"])

    def test_aux_modes_return_empty_next(self):
        self.render()
        for flags in (["--check"], ["--prune"]):
            with self.subTest(flags=flags):
                payload = h.out_json(self.render(*flags))
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["next"], [])


if __name__ == "__main__":
    unittest.main()
