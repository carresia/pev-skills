"""渲染内容测试:实施决策/测试决策/Out of Scope 段(consolidate T1-15)。

直接测 render_lib 单元:三段有数据时渲染进文档,旧数据缺字段时兼容,
条目缺必填子字段时拒绝,同数据两次渲染逐字节一致。
"""

import re
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from render_lib import RenderError, render_spec  # noqa: E402
from tests.helpers import min_spec_body  # noqa: E402

STATE = {"prd_source": "pm/output/prd.md"}


def body_with_new_sections():
    body = min_spec_body(
        implementation_decisions=[
            {"decision": "验证码组件独立为 auth-code 模块,对外仅暴露 verify 接口",
             "source": "澄清决定"}],
        test_decisions=[
            {"behavior": "滑块失败 3 次后用户可见短信降级入口",
             "verification": "端到端用例驱动真实登录页断言入口出现"}],
        out_of_scope=[
            {"item": "短信服务供应商切换", "reason": "本变更不动供应商合同"}],
    )
    return body


class RenderNewSectionsTest(unittest.TestCase):
    def test_new_sections_render_into_spec(self):
        text = render_spec(body_with_new_sections(), STATE, "spec")
        self.assertIn("Implementation Decisions", text)
        self.assertIn("auth-code 模块", text)
        self.assertIn("Test Decisions", text)
        self.assertIn("短信降级入口", text)
        self.assertIn("Out of Scope", text)
        self.assertIn("短信服务供应商切换", text)

    def test_absent_new_fields_still_render(self):
        """2026-10-27 前的数据形态(无新字段)必须继续渲染成功。

        段标题常驻(与 open_questions 空集合先例一致),空集合渲染零行:
        标题与下一节标题之间只剩空行,显式表达"此段未提供"。
        """
        text = render_spec(min_spec_body(), STATE, "spec")
        for title, nxt in [
            ("## 10. Implementation Decisions", "## 11."),
            ("## 11. Test Decisions", "## 12."),
            ("## 12. Out of Scope", "## 13."),
        ]:
            with self.subTest(title=title):
                m = re.search(
                    re.escape(title) + r"[^\n]*\n(.*?)\n" + re.escape(nxt),
                    text, re.S)
                self.assertIsNotNone(m, f"missing section {title}")
                self.assertEqual(m.group(1).strip(), "")

    def test_missing_item_field_rejected(self):
        cases = {
            "implementation_decisions": [
                {"decision": "无来源的决策"}],  # 缺 source
            "test_decisions": [
                {"behavior": "只有行为没有验证方式"}],  # 缺 verification
            "out_of_scope": [
                {"item": "只有条目没有原因"}],  # 缺 reason
        }
        for coll, items in cases.items():
            with self.subTest(coll=coll):
                body = min_spec_body(**{coll: items})
                with self.assertRaises(RenderError) as ctx:
                    render_spec(body, STATE, "spec")
                self.assertIn(coll, str(ctx.exception.json_path))

    def test_deterministic_with_new_fields(self):
        body = body_with_new_sections()
        self.assertEqual(render_spec(body, STATE, "spec"),
                         render_spec(body, STATE, "spec"))


if __name__ == "__main__":
    unittest.main()
