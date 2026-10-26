#!/usr/bin/env python3
"""本地渲染器:从 PASS 轮 JSON 确定性渲染最终交付物(design.md"本地渲染器契约")。

用法:
    python3 render.py --pm-root <pm 目录绝对路径>            # 渲染并发布
    python3 render.py --pm-root <pm 目录绝对路径> --check    # 只做字节比对,不写盘
    python3 render.py --pm-root <pm 目录绝对路径> --prune    # 仅清理 output/ 残留 .md

JSON 是权威数据,Markdown 是只读派生产物;本脚本绝不修改来源 JSON。
stdout 永远是单行紧凑 JSON(协议见 scripts/_common.py)。
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Reporter, SKILL_ROOT, load_state, parse_pm_root, run, select_plan,
)

TEMPLATE_NAMES = ("prd", "decision", "product-opportunity", "plan")
ALIASES = {"PRD": "prd", "决策文档": "decision",
           "产品机会文档": "product-opportunity", "计划文档": "plan"}

# design.md 渲染契约映射表:必填/可选与列表项结构(唯一事实源)
TEMPLATES = {
    "prd": {
        "ctx": "artifact",
        "required_scalar": ("title", "background", "goal", "primary_metric",
                            "solution", "solution_rationale", "launch_plan",
                            "acceptance"),
        "required_array": ("in_scope", "out_of_scope"),
        "item_specs": {
            "user_stories": {"scalar": ("user", "action", "value"), "array": ()},
            "validation_metrics": {"scalar": ("name", "definition", "purpose", "source"),
                                   "array": ()},
        },
        "optional_array": ("secondary_metrics", "guardrail_metrics", "risks"),
        "state_loops": {},
    },
    "decision": {
        "ctx": "artifact",
        "required_scalar": ("title", "conclusion", "confidence", "recommendation"),
        "required_array": (),
        "item_specs": {
            "solutions": {"scalar": ("name", "benefit", "benefit_confidence", "cost"),
                          "array": ("risks",)},
        },
        "optional_scalar": ("roi",),
        "state_loops": {"evidence": {"scalar": ("claim", "type"),
                                     "array": (), "nullable": ("evidence",)}},
    },
    "product-opportunity": {
        "ctx": "artifact",
        "required_scalar": ("title", "goal", "metric", "baseline", "target",
                            "problem", "root_cause", "recommendation"),
        "required_array": (),
        "item_specs": {
            "opportunities": {"scalar": ("name", "priority", "impact",
                                         "evidence_ref", "confidence"),
                              "array": ()},
        },
        "optional_scalar": (),
        "state_loops": {"evidence": {"scalar": ("claim", "type", "confidence"),
                                     "array": (), "nullable": ("evidence",)}},
    },
    "plan": {
        "ctx": "plan",
        "required_scalar": ("goal", "understanding", "final_deliverable"),
        "required_array": ("plan",),
        "item_specs": {
            "plan": {"scalar": ("id", "objective", "action", "expected_output",
                                "success_criteria"),
                     "array": ("inputs",)},
        },
        "optional_array": ("known", "unknown", "assumptions", "stop_conditions"),
        "state_loops": {},
    },
}

EACH_RE = re.compile(r"\{\{#each (\w+)\}\}(.*?)\{\{/each\}\}", re.S)
VAR_RE = re.compile(r"\{\{(\w+)\}\}")
REF_RE = re.compile(r"templates/([A-Za-z0-9._\-]+)\.md")


class RenderError(Exception):
    def __init__(self, reason, json_path=None):
        super().__init__(reason)
        self.json_path = json_path


def select_template(final_deliverable):
    """规则 (1) 字面引用恰一 → (2) 别名精确匹配 → (3) 拒绝。"""
    text = final_deliverable.strip()
    names = REF_RE.findall(text)
    for name in names:
        if name not in TEMPLATE_NAMES:
            raise RenderError(
                f"templates/ 引用了不支持的模板 {name!r},合法集合: {list(TEMPLATE_NAMES)}")
    if names:
        unique = sorted(set(names))
        if len(unique) > 1:
            raise RenderError(f"final_deliverable 引用了多个模板 {unique},歧义拒绝")
        return unique[0]
    if text in ALIASES:
        return ALIASES[text]
    raise RenderError(
        f"无法从 final_deliverable 确定模板;合法形式:templates/<name>.md 引用"
        f"(name ∈ {list(TEMPLATE_NAMES)})或精确别名 {sorted(ALIASES)}")


def esc_cell(value):
    value = value.replace("\\", "\\\\").replace("|", "\\|")
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")


def esc_inline(value):
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
    return re.sub(r"([\\*_`\[\]<>])", r"\\\1", value)


def scalar_str(value, json_path=None):
    """标量占位符只接受字符串或数字;bool/null/对象在这里就拒绝。"""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise RenderError(f"占位符只接受字符串或数字,实际为 {type(value).__name__}",
                          json_path=json_path)
    return str(value)


def format_value(value, ctx, var, nullable):
    if value is None:
        if var in nullable:
            return ""
        raise RenderError(f"占位符 {{{{{var}}}}} 的值为 null", json_path=f"$.{var}")
    if isinstance(value, list):
        parts = [scalar_str(v, json_path=f"$.{var}") for v in value]
        joined = "\n".join(parts) if ctx == "block" else "; ".join(parts)
        return joined
    text = scalar_str(value)
    if ctx == "block":
        return text
    if ctx == "cell":
        return esc_cell(text)
    return esc_inline(text)


def substitute(text, scopes, nullable=(), empty_ok=()):
    """按行替换 {{var}}:表格行用单元格转义,独占一行的用正文逐字,其余行内转义。

    empty_ok 中的变量缺席时渲染为空文本/零行(可选字段、豁免字段),不编造内容。
    """
    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        is_table = line.lstrip().startswith("|")

        def repl(m, line=line, stripped=stripped, is_table=is_table):
            var = m.group(1)
            ctx = "block" if stripped == m.group(0) else ("cell" if is_table else "inline")
            for scope in scopes:
                if var in scope:
                    return format_value(scope[var], ctx, var, nullable)
            if var in empty_ok:
                return ""
            raise RenderError(f"占位符 {{{{{var}}}}} 无对应数据",
                              json_path=f"$.{var}")

        out.append(VAR_RE.sub(repl, line))
    return "\n".join(out)


def expand_loops(text, ctx_data, state, spec, source_desc, empty_ok=()):
    """展开 {{#each 集合}}(不支持嵌套);集合数据按模板声明取自正文或 state.evidence。"""
    m = EACH_RE.search(text)
    while m:
        name = m.group(1)
        body = m.group(2)
        if "{{#each" in body:
            raise RenderError("不支持嵌套循环")
        if name in spec["state_loops"]:
            item_spec = spec["state_loops"][name]
            items = state.get("evidence", [])
            nullable = item_spec["nullable"]
        elif name in spec["item_specs"]:
            item_spec = spec["item_specs"][name]
            items = ctx_data.get(name)
            nullable = ()
            if not isinstance(items, list) or not items:
                raise RenderError(f"{source_desc} 的 {name} 不能为空")
        else:
            raise RenderError(f"模板使用了未支持的循环集合 {name!r}")
        rendered = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise RenderError(f"{name}[{i}] 必须是对象")
            rendered.append(substitute(body, [item, ctx_data], nullable, empty_ok))
        text = text[:m.start()] + "".join(rendered) + text[m.end():]
        m = EACH_RE.search(text)
    return text


def check_nonempty_scalar(value):
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_inputs(data, spec, waived, source_file, base_path):
    """必填存在、类型正确且非空;豁免字段按可选处理;可选字段若出现须类型正确。"""
    def err(path, reason):
        raise RenderError(reason, json_path=path)

    for field in spec.get("required_scalar", ()):
        if field in waived:
            continue
        if field not in data:
            err(f"{base_path}.{field}", "缺少必填字段")
        if not check_nonempty_scalar(data[field]):
            err(f"{base_path}.{field}", "必填字段须为非空字符串或数字")
    for field in spec.get("required_array", ()):
        if field in waived:
            continue
        v = data.get(field)
        if not isinstance(v, list) or not v:
            err(f"{base_path}.{field}", "必填数组不能为空")
    for field in spec.get("optional_scalar", ()):
        if field in data and not check_nonempty_scalar(data[field]):
            err(f"{base_path}.{field}", "可选标量须为非空字符串或数字")
    for field in spec.get("optional_array", ()) + spec.get("nullable_array", ()):
        if field in data and not isinstance(data[field], list):
            err(f"{base_path}.{field}", "可选字段须为数组")
    for coll, item_spec in spec.get("item_specs", {}).items():
        if coll == "plan" and "plan" in waived:
            continue
        items = data.get(coll)
        if not isinstance(items, list) or not items:
            err(f"{base_path}.{coll}", "必填数组不能为空")
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                err(f"{base_path}.{coll}[{i}]", "列表项必须是对象")
            for f in item_spec["scalar"]:
                if f not in item or not check_nonempty_scalar(item[f]):
                    err(f"{base_path}.{coll}[{i}].{f}", "列表项缺少非空标量字段")
            for f in item_spec["array"]:
                if f not in item or not isinstance(item[f], list):
                    err(f"{base_path}.{coll}[{i}].{f}", "列表项缺少数组字段")


def load_waived(artifact):
    waived = artifact.get("waived_fields")
    if waived is None:
        return set()
    if not isinstance(waived, list):
        raise RenderError("$.waived_fields 必须为数组")
    names = set()
    for i, w in enumerate(waived):
        if (not isinstance(w, dict)
                or not all(isinstance(w.get(k), str) and w.get(k, "").strip()
                           for k in ("field", "reason", "source"))):
            raise RenderError(
                f"$.waived_fields[{i}] 须含非空 field/reason/source 三字段")
        if w["field"] in names:
            raise RenderError(f"$.waived_fields[{i}] 字段 {w['field']!r} 重复豁免")
        names.add(w["field"])
    return names


def select_plan_path(pm_root, state, iteration, rep):
    """编号不超过当前 iteration 的最新已登记 Plan;失败时记错误。"""
    sel = select_plan(pm_root, state, iteration)
    if sel is None:
        rep.error("state.json", "$.plans",
                  f"找不到编号不超过 {iteration} 的已登记 Plan 文件,无法渲染")
        return None
    return sel[1]


def load_json(path, rep, json_path="$"):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        rep.error(str(path.relative_to(rep.pm_root and Path(rep.pm_root) or path.parent)),
                  json_path, f"无法读取/解析: {e}")
        return None


def residue_files(output_dir, out_name):
    if not output_dir.is_dir():
        return []
    return sorted(p for p in output_dir.glob("*.md") if p.name != out_name)


def render_document(name, plan_doc, artifact, state, rep, plan_path, artifact_name):
    spec = TEMPLATES[name]
    template_path = SKILL_ROOT / "templates" / f"{name}.md"
    try:
        template_text = template_path.read_text(encoding="utf-8")
    except OSError as e:
        rep.error(f"templates/{name}.md", None, f"无法读取模板: {e}")
        return None

    if spec["ctx"] == "plan":
        ctx_data = plan_doc
        source_file = plan_path.name
        base = "$"
        waived = set()
    else:
        ctx_data = artifact.get("artifact")
        source_file = artifact_name
        base = "$.artifact"
        if not isinstance(ctx_data, dict):
            rep.error(f"iterations/{artifact_name}", "$.artifact",
                      "artifact 正文必须是对象")
            return None
        try:
            waived = load_waived(artifact)
        except RenderError as e:
            rep.error(f"iterations/{artifact_name}", "$.waived_fields", str(e))
            return None

    try:
        validate_inputs(ctx_data, spec, waived, source_file, base)
        empty_ok = (set(spec.get("optional_scalar", ()))
                    | set(spec.get("optional_array", ()))
                    | set(spec.get("nullable_array", ()))
                    | waived)
        text = expand_loops(template_text, ctx_data, state, spec, source_file,
                            empty_ok=empty_ok)
        text = substitute(text, [ctx_data], empty_ok=empty_ok)
        if "{{" in text:
            raise RenderError("输出中残留未替换占位符,拒绝发布")
    except RenderError as e:
        rep.error(source_file, getattr(e, "json_path", None), str(e))
        return None
    text = re.sub(r"\n+$", "\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    if not text.endswith("\n"):
        text += "\n"
    return text


def main():
    argv = sys.argv[1:]
    mode = "publish"
    if "--check" in argv and "--prune" in argv:
        rep = Reporter("render")
        rep.command_error("render", "--check 与 --prune 不能同时使用")
        return rep.emit()
    if "--check" in argv:
        mode, command = "check", "render --check"
    elif "--prune" in argv:
        mode, command = "prune", "render --prune"
    else:
        command = "render"
    rep = Reporter(command)

    pm = parse_pm_root([a for a in argv if a not in ("--check", "--prune")],
                       command, rep)
    if pm is None or rep.errors:
        return rep.emit()
    state = load_state(pm, rep)
    if state is None:
        return rep.emit()
    iteration = rep.iteration
    if not isinstance(iteration, int) or iteration < 1:
        rep.error("state.json", "$.iteration",
                  f"iteration 须为正整数才能定位本轮产物,实际为 {iteration!r}")
        return rep.emit()

    plan_path = select_plan_path(pm, state, iteration, rep)
    if plan_path is None:
        return rep.emit()
    plan_doc = load_json(plan_path, rep)
    if plan_doc is None:
        return rep.emit()

    try:
        name = select_template(plan_doc.get("final_deliverable", ""))
    except RenderError as e:
        rep.error(plan_path.name, "$.final_deliverable", str(e))
        return rep.emit()
    out_name = f"{name}.md"
    output_dir = pm / "output"

    if mode == "prune":
        for p in residue_files(output_dir, out_name):
            p.unlink()
            rep.deleted.append(str(p.relative_to(pm)))
        return rep.emit()

    artifact = None
    artifact_name = None
    if TEMPLATES[name]["ctx"] == "artifact":
        artifact_name = f"{iteration:02d}-artifact.json"
        registry = state.get("artifacts")
        if not isinstance(registry, list) or artifact_name not in registry:
            rep.error("state.json", "$.artifacts",
                      f"当前轮 {artifact_name} 未登记,无法渲染")
            return rep.emit()
        artifact = load_json(pm / "iterations" / artifact_name, rep)
        if artifact is None:
            return rep.emit()

    text = render_document(name, plan_doc, artifact, state, rep,
                           plan_path, artifact_name)
    if text is None:
        return rep.emit()
    expected = text.encode("utf-8")

    residue = residue_files(output_dir, out_name)
    target = output_dir / out_name

    if mode == "check":
        for p in residue:
            rep.error(f"output/{p.name}", None,
                      "output/ 存在与当前交付物无关的残留文件,须先 --prune")
        if not target.is_file():
            rep.error(f"output/{out_name}", None, "最终文档缺失,须先渲染发布")
        elif target.read_bytes() != expected:
            rep.error(f"output/{out_name}", None,
                      "已发布文档与当前来源数据不一致(过期或手工修改),须重新渲染")
        return rep.emit()

    for p in residue:
        rep.error(f"output/{p.name}", None,
                  f"output/ 存在残留文件 {p.name},拒绝发布;清理动作: render.py --prune")
    if rep.errors:
        return rep.emit()

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        tmp = output_dir / ".render.tmp"
        tmp.write_bytes(expected)
        os.replace(tmp, target)
    except OSError as e:
        rep.error(f"output/{out_name}", None, f"写入失败,旧文件保持原状: {e}")
        tmp = output_dir / ".render.tmp"
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        return rep.emit()

    rep.written.append(f"output/{out_name}")
    rep.next.append({
        "kind": "command",
        "cwd": str(SKILL_ROOT),
        "argv": ["scripts/transition.py", "--pm-root", str(pm), "complete"],
    })
    return rep.emit()


if __name__ == "__main__":
    sys.exit(run("render", main))
