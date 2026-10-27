#!/usr/bin/env python3
"""behavior-decompose PEV 产物校验器(双端通用,仅依赖 Python 标准库)。

用法:
    python3 validate.py <PEV_DIR>      # PEV_DIR 为本 skill 工作目录,如 .pev/prd-2026-09-20/decompose/

按文件名后缀路由到 schemas/ 下对应 schema:
    state.json                    -> state.schema.json
    iterations/*-plan.json        -> plan.schema.json
    iterations/*-artifact.json    -> artifact.schema.json
    iterations/*-verification.json-> verification.schema.json

除 JSON Schema 子集(type/enum/required/properties/items/minItems/
minimum/maximum)外,强制以下语义规则——这些是状态机的硬约束,靠肉眼最容易漏:
    R1  Evidence 条目 type=FACT 或 DECISION 时,evidence 必须是非空字符串
        (FACT 证据=spec_source §x / .pev/<轮次>/rc/ 产物;DECISION 证据=精修/拍板锚点)
    R2  artifact.status ∈ {replan_required, blocked} 时,replan_reason 必填
    R3  state.status=WAITING_FOR_INPUT 时,resume_to 必填;
        其他 status 下 resume_to 必须不存在
    R4  state.status=WAITING_FOR_SPEC 时,spec_gaps 必须非空;
        其他 status 下 spec_gaps 必须为空
    R5  两级表态合并合法性。全局 category_defaults(applicable + inapplicable)与
        story 级 coverage_assessment(applicable_add / inapplicable_add)须满足:
        两级各自无重复、无交集;story 偏离不得与全局同侧重复(全局已适用的不得再
        applicable_add,全局已豁免的不得再 inapplicable_add);豁免必须附非空理由;
        全局豁免的 what 必须是 11 类之一。有效适用集 = 全局 applicable ∪ applicable_add
        − inapplicable_add,作为覆盖率分母——沉默的未决类别视为不适用(由 Verifier 审)
    R6  verification.coverage 的两个百分比必须等于**同迭代** artifact 直接算出的值
        (verification N ↔ artifact N,REVISE 轮的历史产物各比各的,不跨迭代聚合;
        同迭代 artifact 缺失时报错,不回退到其他迭代;打印的汇总覆盖率取最新迭代)。门禁数字来自脚本计算,不接受人工填写;
        声称值与算出的值不符即报错。verification.json 不存在时跳过本条
        (EXECUTING 阶段只有 artifact)。数字比对仅在 state.status ∈
        {VERIFYING, COMPLETE}(评审落点)强制:其余状态(REVISE 轮"artifact 已改、
        旧 verification 未覆盖"的中间态)盘上 verification 视为上一轮历史产物,
        跳过比对并打印说明,回到评审落点即恢复比对
    R7  多个迭代 artifact 并存时,相邻迭代的 category_defaults 结构(适用集+豁免类别集)
        必须一致;有变更必须在新迭代 Evidence Ledger 里有 DECISION 背书(claim/锚点
        提及 category_defaults 或所涉类别名)。防止"不改场景、只改分母"绕过覆盖门禁;
        豁免理由的措辞变化不影响分母,不查
    R8  verdict=PASS 的 verification,其同迭代 artifact 算出的门禁必须达标
        (scenario_category_pct ≥ 90 且 critical_risk_pct = 100)。门禁未过判 PASS 是
        无效评审,报错;REVISE/REPLAN/BLOCKED 不受限(门禁未过正是打回理由)
    R9  state.plans / state.artifacts 登记册(文件名,不存内容副本)与
        iterations/ 目录双向一致

通过时汇总输出:最新迭代覆盖率与门禁结论,以及逐 story 适用未覆盖清单
(已声明适用但没有场景证据的类别;非门禁,交 Verifier 逐条处置)。

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

# 覆盖率的两条轴。行为类"覆盖"= story 有该 class 的场景;风险类"覆盖"= story 有场景
# 在 covers 里声明了该风险类。风险类只在 P0/P1 story 上计入分母。
BEHAVIOR_CLASSES = ("normal", "exception", "boundary", "permission_state", "dependency")
RISK_CLASSES = ("security", "authorization", "funds", "privacy", "irreversible", "data_integrity")
ALL_CLASSES = BEHAVIOR_CLASSES + RISK_CLASSES
CRITICAL_PRIORITIES = {"P0", "P1"}
PCT_TOLERANCE = 0.05  # 允许 0.05 的舍入差(百分比四舍五入到一位小数)
GATE_SCENARIO_MIN = 90.0  # R8:场景类别覆盖门禁
GATE_CRITICAL_MIN = 100.0  # R8:P0/P1 风险类门禁

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


def iter_stories(artifact):
    """遍历 artifact 里的每个 story,产出 (story, json 路径)。"""
    body = artifact.get("artifact")
    if not isinstance(body, dict):
        return
    for ei, epic in enumerate(body.get("epics", [])):
        if not isinstance(epic, dict):
            continue
        for fi, feat in enumerate(epic.get("features", [])):
            if not isinstance(feat, dict):
                continue
            for si, story in enumerate(feat.get("stories", [])):
                if isinstance(story, dict):
                    yield story, f"$.artifact.epics[{ei}].features[{fi}].stories[{si}]"


def load_defaults(art):
    """取 artifact 的全局表态,返回 (全局适用集, 全局豁免集);结构非法时返回 (None, None)。"""
    body = art.get("artifact")
    if not isinstance(body, dict):
        return None, None
    defaults = body.get("category_defaults")
    if not isinstance(defaults, dict):
        return None, None
    g_app = defaults.get("applicable")
    g_inapp = defaults.get("inapplicable")
    if not isinstance(g_app, list) or not isinstance(g_inapp, list):
        return None, None
    return ({c for c in g_app if isinstance(c, str)},
            {i["what"] for i in g_inapp if isinstance(i, dict) and isinstance(i.get("what"), str)})


def effective_applicable(story, g_app):
    """两级合并:全局适用 ∪ story 增补 − story 豁免。"""
    ca = story.get("coverage_assessment")
    eff = set(g_app)
    if isinstance(ca, dict):
        for c in ca.get("applicable_add", []) or []:
            if isinstance(c, str):
                eff.add(c)
        for i in ca.get("inapplicable_add", []) or []:
            if isinstance(i, dict) and isinstance(i.get("what"), str):
                eff.discard(i["what"])
    return eff


def check_defaults_stability(artifacts, errs):
    """R7 — category_defaults 迭代间只许有 DECISION 背书的变更(防挪分母)。

    比较相邻迭代 artifact 的全局表态结构(适用集 + 豁免类别集);有变化时,新迭代
    Evidence Ledger 必须存在 type=DECISION 的条目且其 claim/锚点提及
    category_defaults 或被改变的类别名。豁免理由措辞变化不影响分母,不查。
    """
    if len(artifacts) < 2:
        return

    def structure(art):
        body = art.get("artifact")
        if not isinstance(body, dict):
            return None
        d = body.get("category_defaults")
        if not isinstance(d, dict):
            return None
        app, ina = d.get("applicable"), d.get("inapplicable")
        if not isinstance(app, list) or not isinstance(ina, list):
            return None
        return (frozenset(c for c in app if isinstance(c, str)),
                frozenset(i["what"] for i in ina
                          if isinstance(i, dict) and isinstance(i.get("what"), str)))

    for (prev_name, prev), (name, art) in zip(artifacts, artifacts[1:]):
        s_prev, s_new = structure(prev), structure(art)
        if s_prev is None or s_new is None or s_prev == s_new:
            continue
        changed = sorted((s_prev[0] ^ s_new[0]) | (s_prev[1] ^ s_new[1]))
        ledger = art.get("evidence") if isinstance(art.get("evidence"), list) else []
        backed = any(
            isinstance(e, dict) and e.get("type") == "DECISION"
            and isinstance(e.get("claim"), str)
            and ("category_defaults" in e["claim"]
                 or any(c in e["claim"] for c in changed)
                 or (isinstance(e.get("evidence"), str) and "category_defaults" in e["evidence"]))
            for e in ledger
        )
        if not backed:
            errs.add(name, "$.artifact.category_defaults",
                     f"R7: 全局表态在 {prev_name} → {name} 间变更(涉及 {changed})但无 DECISION 背书——"
                     "改分母必须留痕:在新迭代 Evidence Ledger 加 type=DECISION 条目,claim 提及 category_defaults 或所涉类别名")


def check_defaults(art, file, errs):
    """R5(全局层)— category_defaults 自身无重复、无交集、类别合法、理由非空。"""
    body = art.get("artifact")
    if not isinstance(body, dict):
        return None, None
    defaults = body.get("category_defaults")
    if not isinstance(defaults, dict):
        return None, None  # 缺字段/类型错已由 schema 报出
    g_app = defaults.get("applicable")
    g_inapp = defaults.get("inapplicable")
    if not isinstance(g_app, list) or not isinstance(g_inapp, list):
        return None, None
    prefix = "$.artifact.category_defaults"

    dup = sorted({c for c in g_app if isinstance(c, str) and g_app.count(c) > 1})
    if dup:
        errs.add(file, f"{prefix}.applicable", f"R5: 全局 applicable 类别重复 {dup}")

    whats = [i.get("what") for i in g_inapp if isinstance(i, dict)]
    dup_ex = sorted({w for w in whats if isinstance(w, str) and whats.count(w) > 1})
    if dup_ex:
        errs.add(file, f"{prefix}.inapplicable", f"R5: 全局豁免类别重复 {dup_ex}")
    bad = sorted(w for w in whats if isinstance(w, str) and w not in ALL_CLASSES)
    if bad:
        errs.add(file, f"{prefix}.inapplicable", f"R5: 全局豁免的 what 不是合法类别 {bad}")
    for idx, item in enumerate(g_inapp):
        if isinstance(item, dict) and item.get("what") in ALL_CLASSES:
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errs.add(file, f"{prefix}.inapplicable[{idx}].reason",
                         "R5: 全局豁免必须附项目级理由(如\"本项目无任何资金流\")")

    both = sorted(set(g_app) & {w for w in whats if isinstance(w, str)})
    if both:
        errs.add(file, prefix, f"R5: 类别同时出现在全局 applicable 与 inapplicable:{both}")

    return ({c for c in g_app if isinstance(c, str)},
            {w for w in whats if isinstance(w, str)})


def check_assessment(story, file, path, errs, g_app, g_inapp):
    """R5(story 层)— 偏离声明无重复、无交集、不与全局同侧重复、豁免有理由。"""
    ca = story.get("coverage_assessment")
    if not isinstance(ca, dict):
        return  # 可选字段,沉默豁免是合法状态
    adds, drops = ca.get("applicable_add") or [], ca.get("inapplicable_add") or []
    if not isinstance(adds, list) or not isinstance(drops, list):
        return  # 类型错已由 schema 报出
    app = [c for c in adds if isinstance(c, str)]
    inapp = [i["what"] for i in drops if isinstance(i, dict) and isinstance(i.get("what"), str)]
    prefix = f"{path}.coverage_assessment"

    for label, values in (("applicable_add", app), ("inapplicable_add", inapp)):
        dup = sorted({v for v in values if values.count(v) > 1})
        if dup:
            errs.add(file, f"{prefix}.{label}", f"R5: 类别重复 {dup}")

    both = sorted(set(app) & set(inapp))
    if both:
        errs.add(file, prefix, f"R5: 类别同时出现在 applicable_add 与 inapplicable_add:{both}")

    redundant_app = sorted(set(app) & g_app)
    if redundant_app:
        errs.add(file, f"{prefix}.applicable_add", f"R5: {redundant_app} 已在全局 applicable,无需逐 story 重复声明")

    redundant_inapp = sorted(set(inapp) & g_inapp)
    if redundant_inapp:
        errs.add(file, f"{prefix}.inapplicable_add", f"R5: {redundant_inapp} 已被全局豁免,无需逐 story 重复豁免")

    for i, item in enumerate(drops):
        if isinstance(item, dict) and item.get("what") in ALL_CLASSES:
            reason = item.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                errs.add(file, f"{prefix}.inapplicable_add[{i}].reason", "R5: story 级豁免必须附具体理由——\"不适用\"这类空泛写法不算,沉默豁免的未决类别无需任何声明")


def compute_coverage(artifacts):
    """R6 — 从 artifact 直接算出门禁百分比,返回 (scenario_category_pct, critical_risk_pct)。

    分母 = 两级合并后的有效适用集(全局 applicable ∪ applicable_add − inapplicable_add)。
    行为类覆盖 = story 有该 class 的场景;风险类覆盖 = 有场景在 covers 里声明了它,
    且只对 P0/P1 story 计入分母。分母为 0 记 100(无适用即无缺口)。
    """
    beh_app = beh_cov = risk_app = risk_cov = 0
    for _name, art in artifacts:
        g_app, _g_inapp = load_defaults(art)
        if g_app is None:
            continue
        for story, _path in iter_stories(art):
            scenarios = [s for s in story.get("scenarios", []) if isinstance(s, dict)]
            classes_present = {s.get("class") for s in scenarios}
            risks_present = {r for s in scenarios if isinstance(s.get("covers"), list) for r in s["covers"]}
            is_critical = story.get("priority") in CRITICAL_PRIORITIES
            for c in effective_applicable(story, g_app):
                if c in BEHAVIOR_CLASSES:
                    beh_app += 1
                    if c in classes_present:
                        beh_cov += 1
                elif c in RISK_CLASSES and is_critical:
                    risk_app += 1
                    if c in risks_present:
                        risk_cov += 1

    def pct(covered, applicable):
        return 100.0 if applicable == 0 else round(covered / applicable * 100, 1)

    return pct(beh_cov, beh_app), pct(risk_cov, risk_app)


def per_story_gaps(art):
    """逐 story 找出"已声明适用但没有场景证据"的类别,返回 [(story_id, [类别…])](只列非空)。

    行为类缺证据 = 没有 class 等于它的场景;风险类(仅 P0/P1)缺证据 = 没有场景在
    covers 里声明它。口径与 compute_coverage 一致。这不是门禁(总门禁 ≥90% 容忍
    少量残留),打印出来交 Verifier 逐条处置——单轮评审逐 story 扫有漏检风险
    (实测同一缺场景问题一轮漏抓一轮抓到),机械列出后不再依赖评审员的注意力。
    """
    g_app, _ = load_defaults(art)
    if g_app is None:
        return []
    gaps = []
    for story, _path in iter_stories(art):
        scenarios = [s for s in story.get("scenarios", []) if isinstance(s, dict)]
        classes_present = {s.get("class") for s in scenarios}
        risks_present = {r for s in scenarios if isinstance(s.get("covers"), list) for r in s["covers"]}
        is_critical = story.get("priority") in CRITICAL_PRIORITIES
        missing = [c for c in sorted(effective_applicable(story, g_app))
                   if (c in BEHAVIOR_CLASSES and c not in classes_present)
                   or (c in RISK_CLASSES and is_critical and c not in risks_present)]
        if missing:
            gaps.append((story.get("id", "?"), missing))
    return gaps


def semantic_rules(state, artifacts, errs):
    """R1-R4:schema 表达不了(或没表达)的状态机硬约束。"""
    # R1 — FACT/DECISION 必须带证据
    ledgers = [("state.json $.evidence", state.get("evidence", []))] if state else []
    for name, art in artifacts:
        ledgers.append((f"{name} $.evidence", art.get("evidence", [])))
    for path, entries in ledgers:
        for i, e in enumerate(entries):
            if isinstance(e, dict) and e.get("type") in ("FACT", "DECISION"):
                ev = e.get("evidence")
                if not isinstance(ev, str) or not ev.strip():
                    errs.add("", f"{path}[{i}]", "R1: type=FACT/DECISION 的条目必须有非空 evidence(FACT=spec_source§x/.pev/<轮次>/rc/ 产物,DECISION=精修/拍板锚点);无证据请标 HYPOTHESIS/UNKNOWN")

    # R2 — replan_required/blocked 必须给理由
    for name, art in artifacts:
        if art.get("status") in ("replan_required", "blocked"):
            reason = art.get("replan_reason")
            if not isinstance(reason, dict) or not reason:
                errs.add(name, "$.replan_reason", "R2: status 为 replan_required/blocked 时必须填写 replan_reason")

    # R3 — WAITING_FOR_INPUT 与 resume_to 互相锁定
    if state:
        status = state.get("status")
        resume = state.get("resume_to")
        if status == "WAITING_FOR_INPUT" and resume not in RESUME_STAGES:
            errs.add("state.json", "$.resume_to", "R3: status=WAITING_FOR_INPUT 时必须写 resume_to(PLANNING/EXECUTING/VERIFYING)")
        if status != "WAITING_FOR_INPUT" and resume is not None:
            errs.add("state.json", "$.resume_to", "R3: 仅 WAITING_FOR_INPUT 状态允许携带 resume_to,恢复后应清除")

    # R4 — WAITING_FOR_SPEC 与 spec_gaps 互相锁定
    if state:
        status = state.get("status")
        gaps = state.get("spec_gaps")
        if status == "WAITING_FOR_SPEC" and (not isinstance(gaps, list) or len(gaps) == 0):
            errs.add("state.json", "$.spec_gaps", "R4: status=WAITING_FOR_SPEC 时必须携带非空 spec_gaps(回上游的缺口清单)")
        if status != "WAITING_FOR_SPEC" and isinstance(gaps, list) and len(gaps) > 0:
            errs.add("state.json", "$.spec_gaps", "R4: 仅 WAITING_FOR_SPEC 状态允许携带非空 spec_gaps,上游更新恢复后应清空")

    # R11 — COMPLETE 与用户确认记录互相锁定(consolidate T2-2):
    # PASS 渲染后等用户确认期间停在 VERIFYING;未确认的 COMPLETE 不得让下游开始
    if state:
        status = state.get("status")
        conf = state.get("user_confirmation")
        has_conf = isinstance(conf, dict) and isinstance(conf.get("date"), str) and conf.get("date").strip()
        if status == "COMPLETE" and not has_conf:
            errs.add("state.json", "$.user_confirmation",
                     "R11: status=COMPLETE 但缺少用户确认记录 user_confirmation(date)——PASS 渲染后须等用户确认,未确认前停在 VERIFYING")
        if status != "COMPLETE" and conf is not None:
            errs.add("state.json", "$.user_confirmation",
                     "R11: user_confirmation 仅在 status=COMPLETE 时允许存在;确认即置 COMPLETE,等待确认期间停在 VERIFYING")


def main(argv):
    if len(argv) < 2:
        print("用法: python3 validate.py <PEV_DIR>   # 如 .pev/prd-2026-09-20/decompose/")
        return 1
    pev_dir = Path(argv[1])
    if not pev_dir.is_dir():
        print(f"错误: 目录 {pev_dir} 不存在")
        return 1

    errs = Errors()

    state = None
    state_path = pev_dir / "state.json"
    if not state_path.is_file():
        errs.add("state.json", "$", "缺失(state.json 必须存在)")
    else:
        state = load_json(state_path, errs)
        if state is not None:
            schema = json.loads((SCHEMA_DIR / "state.schema.json").read_text(encoding="utf-8"))
            validate(state, schema, "state.json", "$", errs)

    # R10 — 上游 spec_source 必须真实存在;指向变更目录交付副本时,
    # 同轮 rc 须已 PASS(交付只发生在 PASS 收口)。文件缺失或未经批准都
    # 是明确停止:不得改用其他轮次的 Spec。
    if state is not None:
        spec_source = state.get("spec_source")
        if isinstance(spec_source, str) and spec_source:
            if not Path(spec_source).is_file():
                errs.add("state.json", "$.spec_source",
                         f"R10: spec_source 指向的文件不存在({spec_source});"
                         "明确停止——不得改用其他轮次的 Spec,先补齐上游或修正路径")
            elif "openspec/changes" in Path(spec_source).as_posix():
                rc_state = pev_dir.parent / "rc" / "state.json"
                if rc_state.is_file():
                    try:
                        rc = json.loads(rc_state.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        rc = None
                    rc_status = rc.get("status") if isinstance(rc, dict) else None
                    if rc_status is not None and rc_status != "COMPLETE":
                        errs.add("state.json", "$.spec_source",
                                 f"R10: spec_source 指向变更目录的交付副本,但同轮 rc "
                                 f"status={rc_status} 尚未 PASS;上游未经当前批准,"
                                 "不得据此拆解,等待澄清轮收口")

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
            if schema_name == "artifact.schema.json":
                artifacts.append((f"iterations/{f.name}", doc))
            elif schema_name == "verification.schema.json":
                verifications.append((f"iterations/{f.name}", doc))

    semantic_rules(state, artifacts, errs)

    # R9 — 登记册与 iterations/ 目录双向一致(文件名对账,不存内容副本)
    if state:
        found = {"plans": set(), "artifacts": set()}
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
            for fname in sorted(found[key] - reg_set):
                errs.add(f"iterations/{fname}", "$",
                         f"R9: 文件存在于 iterations/ 但未登记进 state.{key}")
            for fname in sorted(reg_set - found[key]):
                errs.add("state.json", f"$.{key}",
                         f"R9: 登记的 {fname} 在 iterations/ 中不存在")

    # R5 — 两级表态合并合法性:全局层 + story 偏离层
    for name, art in artifacts:
        g_app, g_inapp = check_defaults(art, name, errs)
        if g_app is None:
            continue
        for story, path in iter_stories(art):
            check_assessment(story, name, path, errs, g_app, g_inapp)

    # R7 — 全局表态跨迭代一致性(变更须有 DECISION 背书)
    check_defaults_stability(artifacts, errs)

    # R6 — 门禁数字必须等于同迭代 artifact 算出的值(不跨迭代聚合)
    def iter_no(name):
        return Path(name).stem.split("-", 1)[0]

    art_by_iter = {iter_no(name): (name, art) for name, art in artifacts}
    latest = artifacts[-1] if artifacts else None
    # 数字比对只在评审落点强制:REVISE 轮"artifact 已改、旧 verification 未覆盖"的
    # 中间态里,盘上 verification 属于上一轮,比对必然不一致——那是流程正在修订,
    # 不是人工填报作弊。回到 VERIFYING 写入新评审(或 PASS 后 COMPLETE)即恢复比对。
    verify_fresh = state is not None and state.get("status") in ("VERIFYING", "COMPLETE")
    for name, doc in verifications:
        entry = art_by_iter.get(iter_no(name))
        if entry is None:
            errs.add(name, "$.coverage",
                     f"R6: 缺少同迭代 {iter_no(name)}-artifact.json,无法比对覆盖率"
                     "(verification 与 artifact 各比各的,不跨迭代)")
            continue
        scenario_pct, critical_pct = compute_coverage([entry])
        # R8 — PASS 必须过门禁;门禁未过的 REVISE/REPLAN/BLOCKED 是合法评审
        if doc.get("verdict") == "PASS" and (
                scenario_pct < GATE_SCENARIO_MIN - PCT_TOLERANCE
                or critical_pct < GATE_CRITICAL_MIN - PCT_TOLERANCE):
            errs.add(name, "$.verdict",
                     f"R8: verdict=PASS 但门禁未达标(scenario_category_pct={scenario_pct} 需≥{GATE_SCENARIO_MIN:g},"
                     f"critical_risk_pct={critical_pct} 需={GATE_CRITICAL_MIN:g})——应判 REVISE 并补覆盖,不得 PASS")
        coverage = doc.get("coverage")
        if not isinstance(coverage, dict):
            continue
        if not verify_fresh:
            continue
        for key, computed in (("scenario_category_pct", scenario_pct), ("critical_risk_pct", critical_pct)):
            claimed = coverage.get(key)
            if isinstance(claimed, (int, float)) and not isinstance(claimed, bool) and abs(claimed - computed) > PCT_TOLERANCE:
                errs.add(name, f"$.coverage.{key}", f"R6: 声称 {claimed},artifact 算出 {computed}——门禁数字必须来自脚本计算,不接受人工填写")

    if errs:
        print(f"校验失败,{len(errs)} 个问题:")
        for e in errs.items:
            print(f"  - {e}")
        return 1
    print(f"OK: {pev_dir} 全部产物通过 schema 与语义规则校验")
    if verifications and state is not None and not verify_fresh:
        print(f"注: state.status={state.get('status')} —— 盘上 verification 视为上一轮历史产物,"
              "跳过 R6 覆盖率数字比对(REVISE 中间态;进入 VERIFYING/COMPLETE 后恢复比对)")
    if latest is not None:
        scenario_pct, critical_pct = compute_coverage([latest])
        gate_ok = (scenario_pct >= GATE_SCENARIO_MIN - PCT_TOLERANCE
                   and critical_pct >= GATE_CRITICAL_MIN - PCT_TOLERANCE)
        print(f"覆盖率(脚本计算,最新迭代):scenario_category_pct={scenario_pct} critical_risk_pct={critical_pct} "
              f"门禁(≥90/100):{'通过' if gate_ok else '未通过'}")
        gaps = per_story_gaps(latest[1])
        if gaps:
            detail = ";".join(f"{sid} 缺 {', '.join(missing)}" for sid, missing in gaps)
            print(f"逐 story 适用未覆盖(交 Verifier 逐条处置,非门禁):{detail}")
        else:
            print("逐 story 适用未覆盖:无")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
