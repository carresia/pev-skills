"""Spec 确定性渲染库(改编自 product-manager/scripts/render.py 渲染核心)。

templates/spec.md 是唯一交付模板;JSON 是权威数据,Markdown 是只读派生物。
数据来源:artifact.artifact 正文 + state.prd_source;同一来源两次渲染逐字节一致。
本模块是库,由 commit.py 的 PASS 收口链内部调用,不是模型命令。
"""

import re

from _common import SKILL_ROOT

# spec.md 模板契约映射表:必填标量 / 必填循环集合 / 允许为空的循环集合(唯一事实源)
SPEC_TEMPLATE = {
    "required_scalar": ("title", "background_summary", "objective_summary",
                        "scope_summary", "eng_scope_addenda",
                        "prd_ref_user_stories", "behavior_detail",
                        "tracking_acceptance", "always", "ask_first", "never"),
    "required_loops": ("rules", "permissions", "exceptions", "nfrs",
                       "data_metrics", "acceptance"),
    "optional_loops": ("open_questions",  # 问题全部闭环后允许为空,渲染为零行
                       # 2026-10-27(T1-15):三段决策内容,允许为空——缺依据时
                       # 不得为填段虚构决策,由下游技能指出缺口
                       "implementation_decisions", "test_decisions",
                       "out_of_scope"),
    "item_required": {
        "rules": ("rule", "source"),
        "permissions": ("rule", "source"),
        "exceptions": ("case", "handling", "source"),
        "nfrs": ("requirement", "source"),
        "data_metrics": ("name", "definition", "status", "code_evidence",
                         "work_item"),
        "acceptance": ("criteria",),
        "open_questions": ("question", "owner"),
        "implementation_decisions": ("decision", "source"),
        "test_decisions": ("behavior", "verification"),
        "out_of_scope": ("item", "reason"),
    },
    "state_scalars": ("prd_source",),  # 取自 state 而非 artifact 正文的标量
}

EACH_RE = re.compile(r"\{\{#each (\w+)\}\}(.*?)\{\{/each\}\}", re.S)
VAR_RE = re.compile(r"\{\{(\w+)\}\}")


class RenderError(Exception):
    def __init__(self, reason, json_path=None):
        super().__init__(reason)
        self.json_path = json_path


def check_nonempty_scalar(value):
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def esc_cell(value):
    value = value.replace("\\", "\\\\").replace("|", "\\|")
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")


def esc_inline(value):
    # 换行保留(2026-10-28:多行标量渲染为真实换行;表格单元格仍走 esc_cell 压平)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"([\\*_`\[\]<>])", r"\\\1", value)


def scalar_str(value, json_path=None):
    """标量占位符只接受字符串或数字;bool/null/对象在这里就拒绝。"""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise RenderError(f"占位符只接受字符串或数字,实际为 {type(value).__name__}",
                          json_path=json_path)
    return str(value)


def format_value(value, ctx, var):
    if value is None:
        raise RenderError(f"占位符 {{{{{var}}}}} 的值为 null", json_path=f"$.{var}")
    if isinstance(value, list):
        parts = [scalar_str(v, json_path=f"$.{var}") for v in value]
        return "\n".join(parts) if ctx == "block" else "; ".join(parts)
    text = scalar_str(value)
    if ctx == "block":
        return text
    if ctx == "cell":
        return esc_cell(text)
    return esc_inline(text)


def substitute(text, scopes):
    """按行替换 {{var}}:表格行用单元格转义,独占一行的用正文逐字,其余行内转义。"""
    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        is_table = line.lstrip().startswith("|")

        def repl(m, line=line, stripped=stripped, is_table=is_table):
            var = m.group(1)
            ctx = "block" if stripped == m.group(0) else ("cell" if is_table else "inline")
            for scope in scopes:
                if var in scope:
                    return format_value(scope[var], ctx, var)
            raise RenderError(f"占位符 {{{{{var}}}}} 无对应数据",
                              json_path=f"$.{var}")

        out.append(VAR_RE.sub(repl, line))
    return "\n".join(out)


def expand_loops(text, body, state):
    """展开 {{#each 集合}}(不支持嵌套);集合数据一律取自 artifact 正文。"""
    m = EACH_RE.search(text)
    while m:
        name = m.group(1)
        body_text = m.group(2)
        if "{{#each" in body_text:
            raise RenderError("不支持嵌套循环")
        if name in SPEC_TEMPLATE["required_loops"]:
            items = body.get(name)
            empty_ok = False
        elif name in SPEC_TEMPLATE["optional_loops"]:
            items = body.get(name, [])
            empty_ok = True
        else:
            raise RenderError(f"模板使用了未支持的循环集合 {name!r}")
        if not isinstance(items, list) or (not items and not empty_ok):
            raise RenderError(f"$.artifact.{name} 不能为空",
                              json_path=f"$.artifact.{name}")
        rendered = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise RenderError(f"$.artifact.{name}[{i}] 必须是对象",
                                  json_path=f"$.artifact.{name}[{i}]")
            rendered.append(substitute(body_text, [item, body, state]))
        text = text[:m.start()] + "".join(rendered) + text[m.end():]
        m = EACH_RE.search(text)
    return text


def validate_body(body, artifact_name):
    """必填标量与循环集合存在、类型正确且非空(交付内容级检查,先于渲染)。"""
    base = f"iterations/{artifact_name}"

    def err(path, reason):
        raise RenderError(reason, json_path=path)

    if not isinstance(body, dict):
        err(f"{base}$.artifact", "artifact 正文必须是对象")
    for field in SPEC_TEMPLATE["required_scalar"]:
        if field not in body:
            err(f"{base}$.artifact.{field}", "缺少必填字段")
        if not check_nonempty_scalar(body[field]):
            err(f"{base}$.artifact.{field}", "必填字段须为非空字符串或数字")
    for coll in SPEC_TEMPLATE["required_loops"] + SPEC_TEMPLATE["optional_loops"]:
        if coll in SPEC_TEMPLATE["optional_loops"] and coll not in body:
            continue
        items = body.get(coll)
        if not isinstance(items, list):
            err(f"{base}$.artifact.{coll}", "循环集合须为数组")
        for f in SPEC_TEMPLATE["item_required"][coll]:
            for i, item in enumerate(items):
                if f not in item or not check_nonempty_scalar(item[f]):
                    err(f"{base}$.artifact.{coll}[{i}].{f}",
                        "列表项缺少非空标量字段")


def load_template():
    path = SKILL_ROOT / "templates" / "spec.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise RenderError(f"无法读取模板 templates/spec.md: {e}")


def render_spec(body, state, artifact_name):
    """从 artifact 正文 + state 确定性渲染 Spec 文本;任何缺漏抛 RenderError。"""
    validate_body(body, artifact_name)
    text = expand_loops(load_template(), body, state)
    text = substitute(text, [body, state])
    if "{{" in text:
        raise RenderError("输出中残留未替换占位符,拒绝发布")
    text = re.sub(r"\n+$", "\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    if not text.endswith("\n"):
        text += "\n"
    return text
