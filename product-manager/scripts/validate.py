#!/usr/bin/env python3
"""PEV 产物校验器(双端通用,仅依赖 Python 标准库,只读)。

用法:
    python3 validate.py --pm-root <pm 目录绝对路径>   # 推荐形式
    python3 validate.py <pm 目录>                     # 兼容旧位置参数形式

按文件名后缀路由到 schemas/ 下对应 schema:
    state.json                         -> state.schema.json
    iterations/*-plan.json             -> plan.schema.json
    iterations/*-artifact.json         -> artifact.schema.json
    iterations/*-verification.json     -> verification.schema.json
    iterations/*-verification-input.json -> verification-input.schema.json(不入登记册)

除 JSON Schema 子集(type/enum/required/properties/items/minItems/
minimum/maximum/pattern)外,强制以下语义规则——这些是状态机的硬约束:
    R1  Evidence 条目 type ∈ {FACT, INFERENCE} 时,evidence 必须是非空字符串
    R2  artifact.status ∈ {replan_required, blocked} 时,replan_reason 必填
    R3  state.status=WAITING_FOR_INPUT 时,resume_to 必填;
        其他 status 下 resume_to 必须不存在
    R4  state.plans / state.artifacts 登记册与 iterations/ 目录双向一致
    R5  verification.verdict=PASS 时 required_changes 必须为空,
        verdict=REVISE 时必须非空
    P1  verification.provenance 复算:按当前文件重算三摘要并与 provenance 比对,
        不一致时报冲突路径与恢复动作(已验证内容被改即失去交付资格)
    P2  COMPLETE 收口门:当前轮必须有 verification 且 verdict=PASS;
        完全没有验证记录却标 COMPLETE 是错误
    P3  未绑定中间态:当轮报告无 provenance 属合法中间态,结构通过,
        但须警告"不可消费 verdict、不可交付"
    P4  旧轮次(或 COMPLETE 旧数据)缺 provenance:格式或仍有效,但须警告
        "旧轮次缺绑定,格式或仍有效但不可交付",不得据此直接交付

退出码:0 = 结构通过(可能带警告);1 = 存在错误。
stdout 永远是单行紧凑 JSON(协议见 scripts/_common.py);本脚本保持只读,
不能发现代理有没有调用过它,也不能阻止绕过检查直接回复。
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Reporter, canonical_sha256, load_state, read_json, run, select_plan,
    state_projection,
)
from render import RenderError, TEMPLATES, load_waived, select_template, \
    validate_inputs  # noqa: E402

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

FILE_SCHEMAS = [
    ("-verification-input.json", "verification-input.schema.json"),
    ("-plan.json", "plan.schema.json"),
    ("-artifact.json", "artifact.schema.json"),
    ("-verification.json", "verification.schema.json"),
]

RESUME_STAGES = {"PLANNING", "EXECUTING", "VERIFYING"}

TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


def check_type(value, expected, file, path, errs):
    names = expected if isinstance(expected, list) else [expected]
    for name in names:
        py = TYPE_MAP.get(name)
        if py is None:
            continue  # 未知类型名,交给 schema 维护者,不在此报错
        if isinstance(value, bool) and py is not bool:
            continue  # bool 是 int 子类,不能算 integer/number
        if isinstance(value, py):
            return
    errs.error(file, path, f"类型应为 {'/'.join(names)},实际为 {type(value).__name__}")


def validate(value, schema, file, path, errs):
    if "type" in schema:
        check_type(value, schema["type"], file, path, errs)
    if "enum" in schema and value not in schema["enum"]:
        errs.error(file, path, f"取值 {value!r} 不在枚举 {schema['enum']} 内")
    if isinstance(value, str) and "pattern" in schema:
        if not re.search(schema["pattern"], value):
            errs.error(file, path, f"不匹配模式 {schema['pattern']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errs.error(file, path, f"缺少必填字段 {key!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                validate(value[key], sub, file, f"{path}.{key}", errs)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errs.error(file, path, f"元素数 {len(value)} 少于 minItems={schema['minItems']}")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(value):
                validate(item, item_schema, file, f"{path}[{i}]", errs)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.error(file, path, f"{value} 低于 minimum={schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.error(file, path, f"{value} 超过 maximum={schema['maximum']}")


def load_json(path, errs):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        errs.error(path.name, "$", f"无法读取/解析 JSON: {e}")
        return None


def semantic_rules(rep, state, artifacts, verifications, plan_files,
                   artifact_files):
    """R1–R5:schema 表达不了(或没表达)的状态机硬约束。"""
    # R1 — FACT/INFERENCE 必须带依据(state.evidence 是唯一 Ledger)
    if state:
        for i, e in enumerate(state.get("evidence", [])):
            if isinstance(e, dict) and e.get("type") in ("FACT", "INFERENCE"):
                ev = e.get("evidence")
                if not isinstance(ev, str) or not ev.strip():
                    rep.error("state.json", f"$.evidence[{i}]",
                              "R1: type=FACT/INFERENCE 的条目必须有非空 evidence(FACT=证据来源,INFERENCE=推理依据);无依据请标 HYPOTHESIS/UNKNOWN")

    # R2 — replan_required/blocked 必须给理由
    for name, art in artifacts:
        if art.get("status") in ("replan_required", "blocked"):
            reason = art.get("replan_reason")
            if not isinstance(reason, dict) or not reason:
                rep.error(name, "$.replan_reason", "R2: status 为 replan_required/blocked 时必须填写 replan_reason")

    # R3 — WAITING_FOR_INPUT 与 resume_to 互相锁定
    if state:
        status = state.get("status")
        resume = state.get("resume_to")
        if status == "WAITING_FOR_INPUT" and resume not in RESUME_STAGES:
            rep.error("state.json", "$.resume_to", "R3: status=WAITING_FOR_INPUT 时必须写 resume_to(PLANNING/EXECUTING/VERIFYING)")
        if status != "WAITING_FOR_INPUT" and resume is not None:
            rep.error("state.json", "$.resume_to", "R3: 仅 WAITING_FOR_INPUT 状态允许携带 resume_to,恢复后应清除")

    # R4 — 登记册与 iterations/ 目录双向一致(快照文件不参与登记册)
    if state:
        for key, files in (("plans", plan_files), ("artifacts", artifact_files)):
            reg = state.get(key, [])
            if not isinstance(reg, list):
                continue  # 类型错误已由 schema 报告
            reg_set = {x for x in reg if isinstance(x, str)}
            for name in sorted(files - reg_set):
                rep.error(name, "$", f"R4: 文件存在于 iterations/ 但未登记进 state.{key}")
            for name in sorted(reg_set - files):
                rep.error("state.json", f"$.{key}", f"R4: 登记的 {name} 在 iterations/ 中不存在")

    # R5 — PASS 不携带必改项;REVISE 必有必改项
    for name, ver in verifications:
        rc = ver.get("required_changes")
        n = len(rc) if isinstance(rc, list) else 0
        if ver.get("verdict") == "PASS" and n > 0:
            rep.error(name, "$.required_changes", "R5: verdict=PASS 时 required_changes 必须为空(有必改项应判 REVISE)")
        if ver.get("verdict") == "REVISE" and n == 0:
            rep.error(name, "$.required_changes", "R5: verdict=REVISE 时 required_changes 必须非空")


def ver_nn(name):
    """从 iterations/01-verification.json 形态的登记名提取整数轮次。"""
    m = re.search(r"(\d+)-verification\.json$", name)
    return int(m.group(1)) if m else None


def recompute_provenance(rep, state, pm_dir, ver_name, ver):
    """P1:按当前文件重算三摘要,与 provenance 比对;不一致报冲突路径与恢复动作。"""
    prov = ver.get("provenance")
    if not isinstance(prov, dict):
        return
    if prov.get("algorithm") != "sha256-v1":
        rep.error(ver_name, "$.provenance.algorithm",
                  "P1: provenance.algorithm 不是 sha256-v1,无法复算")
        return
    nn = ver_nn(ver_name)
    if nn is None:
        return
    hint = ("P1: provenance 复算不一致,已验证内容在检查后被改动,失去交付资格;"
            "恢复:按修订规则新建轮次重新验证,不得沿用旧 PASS")

    art_name = f"{nn:02d}-artifact.json"
    art_path = pm_dir / "iterations" / art_name
    art = read_json(art_path) if art_path.is_file() else None
    if art is None:
        rep.error(f"iterations/{art_name}", "$",
                  "P1: provenance 指向的当轮 Artifact 缺失或不可解析")
    elif canonical_sha256(art) != prov.get("artifact_sha256"):
        rep.error(f"iterations/{art_name}", "$", hint)

    plan_rel = prov.get("plan_path")
    plan_path = pm_dir / plan_rel if isinstance(plan_rel, str) else None
    plan = read_json(plan_path) if plan_path and plan_path.is_file() else None
    if plan is None:
        rep.error(plan_rel or "$.provenance.plan_path", "$",
                  "P1: provenance 指向的有效 Plan 缺失或不可解析")
    elif canonical_sha256(plan) != prov.get("plan_sha256"):
        rep.error(plan_rel, "$", hint)

    if canonical_sha256(state_projection(state or {})) != prov.get("state_projection_sha256"):
        rep.error("state.json", "$", hint + "(state 语义字段)")


def binding_gates(rep, state, verifications, iteration):
    """P2/P3/P4:COMPLETE 收口门与未绑定中间态警告。"""
    if state is None or not isinstance(iteration, int):
        return
    status = state.get("status")
    cur = next((v for n, v in verifications if ver_nn(n) == iteration), None)
    cur_name = f"{iteration:02d}-verification.json"

    # P4 — 历史轮缺绑定
    for name, ver in verifications:
        nn = ver_nn(name)
        if nn is not None and nn < iteration and "provenance" not in ver:
            rep.warn(f"{name}: 旧轮次缺绑定,格式或仍有效但不可交付")

    if cur is None:
        if status == "COMPLETE":
            rep.error(cur_name, "$",
                      "P2: state 为 COMPLETE 但当前轮 verification 不存在;"
                      "磁盘记录显示没有通过检查却标成 COMPLETE,须回退状态或补齐验证轮")
        return

    if "provenance" not in cur:
        if status == "COMPLETE":
            rep.warn(f"{cur_name}: 旧轮次缺绑定,格式或仍有效但不可交付")
        elif status == "VERIFYING":
            rep.warn(f"{cur_name}: 当轮报告未绑定,不可消费 verdict、不可交付")
        return

    if status == "COMPLETE" and cur.get("verdict") != "PASS":
        rep.error(cur_name, "$.verdict",
                  f"P2: state 为 COMPLETE 但当前轮 verdict 为 {cur.get('verdict')!r},"
                  "只有 PASS 可收口")


def check_b_c(rep, state, artifacts, iteration, pm_dir):
    """B 类(当前轮 completed 产物的模板必填集,豁免生效)与 C 类(可确定检查)。

    replan_required/blocked 产物不适用 B 类;历史轮只做 A 类与 P1 复算。
    """
    if state is None or not isinstance(iteration, int):
        return
    cur_name = f"iterations/{iteration:02d}-artifact.json"
    cur = next((d for n, d in artifacts if n == cur_name), None)
    if cur is None or cur.get("status") != "completed":
        return
    sel = select_plan(pm_dir, state, iteration)
    if sel is None:
        rep.error("state.json", "$.plans", "C: 找不到有效 Plan,B/C 类无从判定")
        return
    plan_doc = read_json(sel[1])
    if plan_doc is None:
        rep.error(sel[1].name, "$", "C: 有效 Plan 无法解析")
        return
    try:
        name = select_template(plan_doc.get("final_deliverable", ""))
    except RenderError as e:
        rep.error(sel[1].name, "$.final_deliverable", f"C: {e}")
        return
    try:
        waived = load_waived(cur)
    except RenderError as e:
        rep.error(cur_name, "$.waived_fields", str(e))
        waived = set()
    try:
        validate_inputs(cur.get("artifact"), TEMPLATES[name], waived,
                        cur_name, "$.artifact")
    except RenderError as e:
        rep.error(cur_name, getattr(e, "json_path", None), f"B: {e}")
    # C 类:Ledger id 全局唯一;引用模板的 evidence_ref 可解析
    ledger = [e for e in state.get("evidence", []) if isinstance(e, dict)]
    ids = [e.get("id") for e in ledger]
    if len(ids) != len(set(ids)):
        rep.error("state.json", "$.evidence", "C: Ledger id 存在重复")
    if "opportunities" in TEMPLATES[name].get("item_specs", {}):
        body = cur.get("artifact")
        idset = set(ids)
        for i, opp in enumerate(body.get("opportunities") or []
                                if isinstance(body, dict) else []):
            ref = opp.get("evidence_ref") if isinstance(opp, dict) else None
            if isinstance(ref, str) and ref.strip() and ref not in idset:
                rep.error(cur_name,
                          f"$.artifact.opportunities[{i}].evidence_ref",
                          f"C: evidence_ref {ref!r} 不在 Ledger 现存 id 中")


def parse_args(argv, rep):
    if not argv:
        rep.command_error("validate", "用法: python3 validate.py --pm-root <pm 目录绝对路径>(亦兼容旧位置参数形式)")
        return None
    if argv[0] == "--pm-root":
        return parse_pm_root_compat(argv, rep)
    if len(argv) != 1:
        rep.command_error("validate", "参数过多;用法: python3 validate.py <pm 目录>")
        return None
    path = Path(argv[0]).expanduser().resolve()
    rep.pm_root = str(path)
    return path


def parse_pm_root_compat(argv, rep):
    from _common import parse_pm_root
    return parse_pm_root(argv, "validate", rep)


def main():
    rep = Reporter("validate")
    pm_dir = parse_args(sys.argv[1:], rep)
    if pm_dir is None or rep.errors:
        return rep.emit()
    if not pm_dir.is_dir():
        rep.command_error("validate", f"目录 {pm_dir} 不存在")
        return rep.emit()

    state = load_state(pm_dir, rep)
    if state is not None:
        schema = json.loads((SCHEMA_DIR / "state.schema.json").read_text(encoding="utf-8"))
        validate(state, schema, "state.json", "$", rep)

    artifacts = []
    verifications = []
    plan_files, artifact_files = set(), set()
    iter_dir = pm_dir / "iterations"
    if iter_dir.is_dir():
        for f in sorted(iter_dir.glob("*.json")):
            schema_name = next((s for suffix, s in FILE_SCHEMAS if f.name.endswith(suffix)), None)
            if schema_name is None:
                rep.error(f.name, "$", "文件名不匹配任何产物类型(*-plan/*-artifact/*-verification/*-verification-input)")
                continue
            if schema_name == "plan.schema.json":
                plan_files.add(f.name)
            elif schema_name == "artifact.schema.json":
                artifact_files.add(f.name)
            doc = load_json(f, rep)
            if doc is None:
                continue
            schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
            validate(doc, schema, f"iterations/{f.name}", "$", rep)
            if schema_name == "artifact.schema.json":
                artifacts.append((f"iterations/{f.name}", doc))
            elif schema_name == "verification.schema.json":
                verifications.append((f"iterations/{f.name}", doc))

    semantic_rules(rep, state, artifacts, verifications, plan_files, artifact_files)

    check_b_c(rep, state, artifacts, rep.iteration, pm_dir)

    for name, ver in verifications:
        recompute_provenance(rep, state, pm_dir, name, ver)

    binding_gates(rep, state, verifications, rep.iteration)

    return rep.emit()


if __name__ == "__main__":
    sys.exit(run("validate", main))
