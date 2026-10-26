#!/usr/bin/env python3
"""requirement-clarify PEV 产物校验器(双端通用,仅依赖 Python 标准库)。

用法:
    python3 validate.py <PEV_DIR>      # PEV_DIR 为本 skill 工作目录,如 .pev/prd-2026-09-20/rc/

按文件名后缀路由到 schemas/ 下对应 schema:
    state.json                    -> state.schema.json
    iterations/*-plan.json        -> plan.schema.json
    iterations/*-artifact.json    -> artifact.schema.json
    iterations/*-verification.json-> verification.schema.json

除 JSON Schema 子集(type/enum/required/properties/items/minItems/
minimum/maximum)外,强制以下语义规则——这些是状态机的硬约束,靠肉眼最容易漏:
    R1  Evidence 条目 type=FACT 或 DECISION 时,evidence 必须是非空字符串
        (FACT 证据=PRD §x / .pev/<轮次>/pm/ 产物 / 代码文件;DECISION 证据=澄清记录锚点)
    R2  artifact.status ∈ {replan_required, blocked} 时,replan_reason 必须至少有一个
        非空字符串字段(空对象或全 null 不算填了理由)
    R3  state.status=WAITING_FOR_INPUT 时,resume_to 必填;
        其他 status 下 resume_to 必须不存在
    R4  state.status=WAITING_FOR_PRD 时,prd_gaps 必须非空;
        其他 status 下 prd_gaps 必须为空
    R5  价值先行(核心不变量 #1):(a) 任一 Plan 的 action 顺序必须非递减
        (interrogate_value → interrogate_ambiguity → draft);(b) 首个 Plan
        若含 interrogate_ambiguity,其前必须有 interrogate_value
    R6  artifact.status=completed 时,artifact 正文必须是非空对象(空壳不算完成)
    R7  verdict 必须与内容一致:REVISE → required_changes 非空(Executor 按它修订);
        REPLAN → critical_issues 或 evidence_gaps 非空(Planner 按它重规划)
    R8  state.status=COMPLETE 的前提:output/spec.md 存在且非空(真交付了),
        且 iteration ≤ max_iterations(SKILL.md §8:超限不得宣称完成)
    R9  artifact.status=completed 时 unresolved 必须为空(还有未决问题就该 blocked)
    R10 state.plans / state.artifacts 登记册(文件名,不存内容副本)与
        iterations/ 目录双向一致

退出码:0 = 全部通过;1 = 存在错误(错误明细逐条打印到 stdout)。
"""

import json
import sys
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

FILE_SCHEMAS = [
    ("-plan.json", "plan.schema.json"),
    ("-artifact.json", "artifact.schema.json"),
    ("-verification.json", "verification.schema.json"),
]

RESUME_STAGES = {"PLANNING", "EXECUTING", "VERIFYING"}

# 核心不变量 #1「价值先行」的可机检形式
ACTION_ORDER = {"interrogate_value": 0, "interrogate_ambiguity": 1, "draft": 2}


def plan_actions(plan_doc):
    """取出 Plan 中可识别的 action 序列。"""
    return [s.get("action") for s in plan_doc.get("plan", [])
            if isinstance(s, dict) and s.get("action") in ACTION_ORDER]


def plan_ordinal(name):
    """iterations/<N>-plan.json -> N;取不到排到最后。"""
    head = Path(name).name.split("-", 1)[0]
    return int(head) if head.isdigit() else 1 << 30

TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


class Errors:
    def __init__(self):
        self.items = []

    def add(self, file, path, message):
        self.items.append(f"{file} {path}: {message}")

    def __len__(self):
        return len(self.items)


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
    errs.add(file, path, f"类型应为 {'/'.join(names)},实际为 {type(value).__name__}")


def validate(value, schema, file, path, errs):
    if "type" in schema:
        check_type(value, schema["type"], file, path, errs)
    if "enum" in schema and value not in schema["enum"]:
        errs.add(file, path, f"取值 {value!r} 不在枚举 {schema['enum']} 内")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errs.add(file, path, f"缺少必填字段 {key!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                validate(value[key], sub, file, f"{path}.{key}", errs)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errs.add(file, path, f"元素数 {len(value)} 少于 minItems={schema['minItems']}")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(value):
                validate(item, item_schema, file, f"{path}[{i}]", errs)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.add(file, path, f"{value} 低于 minimum={schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.add(file, path, f"{value} 超过 maximum={schema['maximum']}")


def load_json(path, errs):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        errs.add(path.name, "$", f"无法读取/解析 JSON: {e}")
        return None


def check_rule_tables(errs):
    """R3/R5 依赖的常量表必须与 schema 的 enum 一致。

    不一致时规则不是"报错"而是"静默失效"——plan_actions() 会把 ACTION_ORDER 里
    没有的 action 直接滤掉,R5 就再也看不见那一步。所以这里必须大声拦。
    """
    def enum_of(schema_name, *path):
        doc = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
        for key in path:
            doc = doc[key]
        return doc["enum"]

    try:
        actions = set(enum_of("plan.schema.json", "properties", "plan", "items",
                              "properties", "action"))
        stages = {s for s in enum_of("state.schema.json", "properties", "resume_to") if s}
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        errs.add("schemas", "$", f"无法读取 schema 以核对规则表: {e}")
        return

    if actions != set(ACTION_ORDER):
        errs.add("plan.schema.json", "$.properties.plan.items.properties.action.enum",
                 f"与 validate.py 的 ACTION_ORDER 不一致(差异 {sorted(actions ^ set(ACTION_ORDER))});"
                 f"不同步会让 R5 静默漏检,必须同时改两处")
    if stages != RESUME_STAGES:
        errs.add("state.schema.json", "$.properties.resume_to.enum",
                 f"与 validate.py 的 RESUME_STAGES 不一致(差异 {sorted(stages ^ RESUME_STAGES)});"
                 f"不同步会让 R3 失配,必须同时改两处")


def semantic_rules(state, plans, artifacts, verifications, pev_dir, errs):
    """R1-R10:schema 表达不了(或没表达)的状态机硬约束。"""
    # R1 — FACT/DECISION 必须带证据
    ledgers = [("state.json", state.get("evidence", []))] if state else []
    for name, art in artifacts:
        ledgers.append((name, art.get("evidence", [])))
    for file, entries in ledgers:
        for i, e in enumerate(entries):
            if isinstance(e, dict) and e.get("type") in ("FACT", "DECISION"):
                ev = e.get("evidence")
                if not isinstance(ev, str) or not ev.strip():
                    errs.add(file, f"$.evidence[{i}]", "R1: type=FACT/DECISION 的条目必须有非空 evidence(FACT=PRD§x/.pev/<轮次>/pm/ 产物/代码文件,DECISION=澄清记录锚点);无证据请标 HYPOTHESIS/UNKNOWN")

    # R2 — replan_required/blocked 必须给理由
    for name, art in artifacts:
        if art.get("status") in ("replan_required", "blocked"):
            reason = art.get("replan_reason")
            # 字段可为 null(见 artifact.schema.json),故"非空 dict"不等于"填了理由":
            # 必须至少有一个非空字符串字段,否则 {"problem": null} 就能蒙混过关。
            if not isinstance(reason, dict) or not any(
                isinstance(v, str) and v.strip() for v in reason.values()
            ):
                errs.add(name, "$.replan_reason",
                         "R2: status 为 replan_required/blocked 时 replan_reason 必须至少填写一个非空字段"
                         "(problem / why_invalid / new_information / recommended)")

    # R3 — WAITING_FOR_INPUT 与 resume_to 互相锁定
    if state:
        status = state.get("status")
        resume = state.get("resume_to")
        if status == "WAITING_FOR_INPUT" and resume not in RESUME_STAGES:
            errs.add("state.json", "$.resume_to", "R3: status=WAITING_FOR_INPUT 时必须写 resume_to(PLANNING/EXECUTING/VERIFYING)")
        if status != "WAITING_FOR_INPUT" and resume is not None:
            errs.add("state.json", "$.resume_to", "R3: 仅 WAITING_FOR_INPUT 状态允许携带 resume_to,恢复后应清除")

    # R4 — WAITING_FOR_PRD 与 prd_gaps 互相锁定
    if state:
        status = state.get("status")
        gaps = state.get("prd_gaps")
        if status == "WAITING_FOR_PRD" and (not isinstance(gaps, list) or len(gaps) == 0):
            errs.add("state.json", "$.prd_gaps", "R4: status=WAITING_FOR_PRD 时必须携带非空 prd_gaps(回 PM 的问题清单)")
        if status != "WAITING_FOR_PRD" and isinstance(gaps, list) and len(gaps) > 0:
            errs.add("state.json", "$.prd_gaps", "R4: 仅 WAITING_FOR_PRD 状态允许携带非空 prd_gaps,PRD 更新恢复后应清空")

    # R5 — 价值先行(核心不变量 #1)
    # (a) 任一 Plan 内 action 顺序不得回退
    for name, pl in plans:
        seq = plan_actions(pl)
        for i in range(1, len(seq)):
            if ACTION_ORDER[seq[i]] < ACTION_ORDER[seq[i - 1]]:
                errs.add(name, f"$.plan[{i}].action",
                         f"R5: 违反核心不变量#1「价值先行」——{seq[i]} 排在 {seq[i - 1]} 之后;"
                         f"顺序必须是 interrogate_value → interrogate_ambiguity → draft")
                break
    # (b) 首个 Plan 必须先问价值,再问落地模糊。
    #     后续 Plan 是增量重规划(REPLAN / WAITING_FOR_PRD 恢复只重规划受影响批次),
    #     可以只含 interrogate_ambiguity,因此只对首个 Plan 强制。
    if plans:
        name, first = min(plans, key=lambda p: plan_ordinal(p[0]))
        seq = plan_actions(first)
        if "interrogate_ambiguity" in seq:
            i = seq.index("interrogate_ambiguity")
            if "interrogate_value" not in seq[:i]:
                errs.add(name, f"$.plan[{i}].action",
                         "R5: 违反核心不变量#1「价值先行」——首个 Plan 必须先做 "
                         "interrogate_value(为什么做/价值假设/不做会怎样/成功长什么样),"
                         "再进入 interrogate_ambiguity")

    # R6 — status=completed 不得交空壳
    for name, art in artifacts:
        if art.get("status") == "completed":
            body = art.get("artifact")
            if not isinstance(body, dict) or not body:
                errs.add(name, "$.artifact",
                         "R6: status=completed 时必须交付非空 artifact 正文,空壳不算完成")

    # R7 — verdict 必须与内容一致,否则下游拿到的是空指令(REVISE 空转直到耗尽迭代)
    for name, ver in verifications:
        verdict = ver.get("verdict")
        if verdict == "REVISE" and not ver.get("required_changes"):
            errs.add(name, "$.required_changes",
                     "R7: verdict=REVISE 时 required_changes 必须非空——Executor 按它修订,空则无从下手")
        if verdict == "REPLAN" and not (ver.get("critical_issues") or ver.get("evidence_gaps")):
            errs.add(name, "$.critical_issues",
                     "R7: verdict=REPLAN 时 critical_issues 或 evidence_gaps 必须非空——Planner 按它重规划")
        # BLOCKED 不强制:其问题清单在 artifact.unresolved,由 SKILL.md §5 呈给用户

    # R8 — COMPLETE 的前提:真交付了,且没超迭代上限
    if state and state.get("status") == "COMPLETE":
        spec = pev_dir / "output" / "spec.md"
        try:
            body = spec.read_text(encoding="utf-8").strip()
        except OSError:
            body = ""
        if not body:
            errs.add("state.json", "$.status",
                     "R8: status=COMPLETE 但 output/spec.md 不存在或为空——没有交付物不算完成")
        it, mx = state.get("iteration"), state.get("max_iterations")
        if isinstance(it, int) and isinstance(mx, int) and it > mx:
            errs.add("state.json", "$.iteration",
                     f"R8: iteration={it} 已超过 max_iterations={mx},按 SKILL.md §8 不得宣称完成")

    # R9 — completed 不得携带未决问题(agents/executor.md Rule 4:有未决就应 blocked)
    for name, art in artifacts:
        if art.get("status") == "completed" and art.get("unresolved"):
            errs.add(name, "$.unresolved",
                     "R9: status=completed 时 unresolved 必须为空——仍有未决问题应置 status=blocked")

    # R10 — 登记册与 iterations/ 目录双向一致(文件名对账,不存内容副本)
    if state:
        found = {"plans": set(), "artifacts": set()}
        iter_dir = pev_dir / "iterations"
        if iter_dir.is_dir():
            for f in iter_dir.glob("*.json"):
                if f.name.endswith("-plan.json"):
                    found["plans"].add(f.name)
                elif f.name.endswith("-artifact.json"):
                    found["artifacts"].add(f.name)
        for key in ("plans", "artifacts"):
            reg = state.get(key, [])
            if not isinstance(reg, list):
                continue  # 类型错误已由 schema 报告
            reg_set = {x for x in reg if isinstance(x, str)}
            for name in sorted(found[key] - reg_set):
                errs.add(f"iterations/{name}", "$",
                         f"R10: 文件存在于 iterations/ 但未登记进 state.{key}")
            for name in sorted(reg_set - found[key]):
                errs.add("state.json", f"$.{key}",
                         f"R10: 登记的 {name} 在 iterations/ 中不存在")


def main(argv):
    if len(argv) < 2:
        print("用法: python3 validate.py <PEV_DIR>   # 如 .pev/prd-2026-09-20/rc/")
        return 1
    pev_dir = Path(argv[1])
    if not pev_dir.is_dir():
        print(f"错误: 目录 {pev_dir} 不存在")
        return 1

    errs = Errors()
    check_rule_tables(errs)

    state = None
    state_path = pev_dir / "state.json"
    if not state_path.is_file():
        errs.add("state.json", "$", "缺失(state.json 必须存在)")
    else:
        state = load_json(state_path, errs)
        if state is not None:
            schema = json.loads((SCHEMA_DIR / "state.schema.json").read_text(encoding="utf-8"))
            validate(state, schema, "state.json", "$", errs)

    plans = []
    artifacts = []
    verifications = []
    iter_dir = pev_dir / "iterations"
    if iter_dir.is_dir():
        for f in sorted(iter_dir.glob("*.json")):
            schema_name = next((s for suffix, s in FILE_SCHEMAS if f.name.endswith(suffix)), None)
            if schema_name is None:
                errs.add(f.name, "$", "文件名不匹配任何产物类型(*-plan/*-artifact/*-verification)")
                continue
            doc = load_json(f, errs)
            if doc is None:
                continue
            schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
            validate(doc, schema, f"iterations/{f.name}", "$", errs)
            if schema_name == "plan.schema.json":
                plans.append((f"iterations/{f.name}", doc))
            elif schema_name == "artifact.schema.json":
                artifacts.append((f"iterations/{f.name}", doc))
            elif schema_name == "verification.schema.json":
                verifications.append((f"iterations/{f.name}", doc))

    semantic_rules(state, plans, artifacts, verifications, pev_dir, errs)

    if errs:
        print(f"校验失败,{len(errs)} 个问题:")
        for e in errs.items:
            print(f"  - {e}")
        return 1
    print(f"OK: {pev_dir} 全部产物通过 schema 与语义规则校验")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
