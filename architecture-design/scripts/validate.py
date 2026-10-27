#!/usr/bin/env python3
"""architecture-design PEV 产物校验器(双端通用,仅依赖 Python 标准库)。

用法:
    python3 validate.py <PEV_DIR>      # PEV_DIR 为本 skill 工作目录,如 .pev/prd-2026-09-20/arch/

按文件名后缀路由到 schemas/ 下对应 schema:
    state.json                    -> state.schema.json
    iterations/*-plan.json        -> plan.schema.json
    iterations/*-artifact.json    -> artifact.schema.json
    iterations/*-verification.json-> verification.schema.json

除 JSON Schema 子集(type/enum/required/properties/items/minItems/
minimum/maximum)外,强制以下语义规则——这些是状态机的硬约束,靠肉眼最容易漏:
    R1  Evidence 条目 type=FACT/DECISION 时 evidence 必须是非空字符串
        (FACT 证据=upstream_source §x / .pev/<轮次>/ 家族产物 / 代码路径;
        DECISION 证据=拍板/精修锚点)。本 skill 的 INFERENCE 是一等公民
        (溯源三档之一),同样必须带非空推理依据;三者缺证据 → 报错。
        HYPOTHESIS/UNKNOWN 允许 evidence 为 null。
    R2  artifact.status ∈ {replan_required, blocked} 时,replan_reason 必填
    R3  state.status=WAITING_FOR_INPUT 时,resume_to 必填;
        其他 status 下 resume_to 必须不存在
    R4  state.status=WAITING_FOR_UPSTREAM 时,upstream_gaps 必须非空;
        其他 status 下 upstream_gaps 必须为空
    R5  依赖结构。architecture kind:模块 id 唯一;depends_on 只引用存在的
        模块 id;依赖图无环;interactions 的 from/to 为模块 id 或 external:
        前缀。option_decision kind:候选 id 唯一且 ≥2;
        recommendation.option_id 指向存在的候选
    R6  所有权结构(architecture kind):data_ownership 每条 owner 非空且为
        存在的模块 id;同一数据不得有两个不同 owner;模块 owns_data 与
        data_ownership 表双向一致;writers 存在时必须含 owner。
        非 owner 写方不是错误,打印清单交 Verifier 逐条质询
    R7  覆盖对账(architecture/option_decision kind,review kind 声明了
        upstream_items 时同样适用):upstream_mapping 的 upstream_item 与
        module_id 引用必须存在;upstream_items 每条被 mapping 引用 ≥1 次
        (双向对账)。声明全不全由 Verifier 对照上游文件审——脚本只对账
        声明过的条目
    R8  verdict=PASS 的 verification,其同迭代 artifact 算出的四个门禁必须
        全绿。门禁未过判 PASS 是无效评审,报错;REVISE/REPLAN/BLOCKED
        不受限(门禁未过正是打回理由)。四个门禁的布尔必须照抄脚本输出
        (评审落点 state.status ∈ {VERIFYING, COMPLETE} 时逐位比对;
        其余状态盘上 verification 视为上一轮历史产物,跳过比对并打印说明)
    R9  state.plans / state.artifacts 登记册(文件名,不存内容副本)与
        iterations/ 目录双向一致
    R10 completed 的 artifact 不得残留占位/未关闭措辞(TODO/TBD/FIXME、
        [待确认]、[待补充]、<待写入>、decision_required、待定/待确认 等);
        未关闭语义应走 status=blocked + unresolved,而不是埋在正文里。
    R11 证据可解析与回读新鲜度:DECISION 证据若引用 decisions#<id>,锚点必须
        真实存在于某个 artifact 的 decisions;evidence 带 source{path,excerpt,
        digest} 时回读来源文件校验 excerpt 命中与摘要一致(来源缺失/变化/伪造
        即 stale)。
    R12 verification.findings 的反向追溯:每条 finding 必须带非空
        affected_upstream_items,且每个 id 回指同迭代 artifact 声明过的
        upstream_items(未声明即打回)。
    R13 红线库:verification.redlines 的红线 id 必须在红线库中;适用红线
        (applies=true)未通过(passed=false)时不得判 PASS——红线独立于评分。

四个门禁的布尔按 deliverable_kind 计算(不适用时按 True 计并注明):
    dependency_acyclic —— 结构门。architecture:R5 模块部分;option_decision:
        R5 候选部分;review_report:True(schema 枚举已保证维度合法)
    unique_owners      —— 所有权门。architecture:R6 全部;其他 kind:True
    upstream_mapped    —— 覆盖门。architecture/option_decision:R7 且
        upstream_items 非空;review_report:声明了才对账,未声明 True
    findings_disposed  —— 诚实门。architecture:self_challenge 7 维全齐且
        处置合法 + tradeoffs 全部 cost 非空 + style 四字段非空;
        option_decision:每候选 cost 非空 + evaluation 每行覆盖全部候选 +
        recommendation 合法;review_report:review_findings 7 维全齐 + 非空
        finding 的 evidence_anchor 非空 + 空 finding 的 severity=NONE

通过时汇总输出:最新迭代的四门禁结论,以及交 Verifier 逐条处置的残留清单
(非 owner 写方、accepted_risk 条目、对账未覆盖项)。

退出码:0 = 全部通过;1 = 存在错误(错误明细逐条打印到 stdout)。
"""

import hashlib
import json
import re
import sys
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
REDLINES_DIR = Path(__file__).resolve().parent.parent / "redlines"

FILE_SCHEMAS = [
    ("-plan.json", "plan.schema.json"),
    ("-artifact.json", "artifact.schema.json"),
    ("-verification.json", "verification.schema.json"),
]

RESUME_STAGES = {"PLANNING", "EXECUTING", "VERIFYING"}

# 对抗 7 维(self_challenge 与 review_findings 共用,与 rubric 一致)
ADVERSARIAL_DIMS = ("failure_modes", "consistency", "concurrency",
                    "boundary_erosion", "migration_rollback", "scale_cliff",
                    "simpler_alternative")

TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}

# R10 — 占位/未关闭措辞(仅对 status=completed 的 artifact 扫描)。
# 单词边界匹配大小写不敏感的 TODO/TBD/FIXME;其余为括号占位、蛇形待决标记与
# 中文"待定/待确认"(完成态产物出现即视为未关闭语义)。
PLACEHOLDER_WORD_RE = re.compile(r"\b(TODO|TBD|FIXME)\b", re.IGNORECASE)
PLACEHOLDER_SUBSTR = (
    "[待补充]", "[待写入]", "[待确认]", "[待定]", "[用户待补充]", "<待写入>",
    "decision_required", "needs_user_decision", "awaiting_user_decision",
    "待定", "待确认",
)


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


def body_of(art):
    b = art.get("artifact")
    return b if isinstance(b, dict) else {}


def kind_of(art):
    return body_of(art).get("deliverable_kind", "")


def as_list(value):
    return value if isinstance(value, list) else []


def nonempty_str(value):
    return isinstance(value, str) and value.strip()


def find_cycles(nodes, edges):
    """Kahn 拓扑:返回 (是否存在环, [成环节点])。edges: id -> set(依赖的 id)。"""
    indeg = {n: 0 for n in nodes}
    for n, deps in edges.items():
        for d in deps:
            indeg[n] += 1
    queue = [n for n, d in indeg.items() if d == 0]
    seen = 0
    while queue:
        n = queue.pop()
        seen += 1
        for m, deps in edges.items():
            if n in deps:
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)
    if seen == len(nodes):
        return False, []
    return True, sorted(n for n, d in indeg.items() if d > 0)


def check_module_graph(body, file, errs):
    """R5(architecture)— 模块 id 唯一、依赖引用合法、无环、交互引用合法。"""
    modules = [m for m in as_list(body.get("modules")) if isinstance(m, dict)]
    ids = [m.get("id") for m in modules if isinstance(m.get("id"), str)]
    id_set = set(ids)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errs.add(file, "$.artifact.modules", f"R5: 模块 id 重复 {dup}")

    edges = {}
    for i, m in enumerate(modules):
        mid = m.get("id")
        deps = as_list(m.get("depends_on"))
        bad = sorted({d for d in deps if isinstance(d, str)} - id_set)
        if bad:
            errs.add(file, f"$.artifact.modules[{i}].depends_on",
                     f"R5: 引用了不存在的模块 id {bad}")
        if isinstance(mid, str) and mid in id_set:
            edges[mid] = {d for d in deps if isinstance(d, str) and d in id_set and d != mid}
    has_cycle, cyclic = find_cycles(id_set, edges)
    if has_cycle:
        errs.add(file, "$.artifact.modules",
                 f"R5: 模块依赖图存在环(涉及 {cyclic})——环内边界无法执行,必须拆解或重挂")

    for i, it in enumerate(as_list(body.get("interactions"))):
        if not isinstance(it, dict):
            continue
        for field in ("from", "to"):
            v = it.get(field)
            if isinstance(v, str) and not v.startswith("external:") and id_set and v not in id_set:
                errs.add(file, f"$.artifact.interactions[{i}].{field}",
                         f"R5: {v!r} 既不是模块 id 也不是 external: 前缀——外部参与方请写 external:<名称>")


def check_option_structure(body, file, errs):
    """R5(option_decision)— 候选 id 唯一且 ≥2、推荐指向存在候选。"""
    options = [o for o in as_list(body.get("options")) if isinstance(o, dict)]
    ids = [o.get("id") for o in options if isinstance(o.get("id"), str)]
    if len(options) < 2:
        errs.add(file, "$.artifact.options",
                 f"R5: 选型候选只有 {len(options)} 个(<2)——单候选没有选型可言,要么补候选要么改走 design")
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errs.add(file, "$.artifact.options", f"R5: 候选 id 重复 {dup}")
    rec = body.get("recommendation")
    if isinstance(rec, dict) and nonempty_str(rec.get("option_id")):
        if rec["option_id"] not in set(ids):
            errs.add(file, "$.artifact.recommendation.option_id",
                     f"R5: 推荐指向不存在的候选 {rec['option_id']!r}")


def check_ownership(body, file, errs, residuals):
    """R6(architecture)— owner 合法且唯一、与 owns_data 双向一致、owner 在写方。"""
    modules = [m for m in as_list(body.get("modules")) if isinstance(m, dict)]
    id_set = {m.get("id") for m in modules if isinstance(m.get("id"), str)}
    rows = [r for r in as_list(body.get("data_ownership")) if isinstance(r, dict)]

    owner_by_data = {}
    for i, r in enumerate(rows):
        data, owner = r.get("data"), r.get("owner")
        if not nonempty_str(owner):
            errs.add(file, f"$.artifact.data_ownership[{i}].owner",
                     "R6: owner 为空——无主数据是一致性 bug 的出生地")
            continue
        if id_set and owner not in id_set:
            errs.add(file, f"$.artifact.data_ownership[{i}].owner",
                     f"R6: owner {owner!r} 不是存在的模块 id")
            continue
        if data in owner_by_data and owner_by_data[data] != owner:
            errs.add(file, f"$.artifact.data_ownership[{i}]",
                     f"R6: 数据 {data!r} 出现两个不同 owner({owner_by_data[data]} 与 {owner})——共享写必须归一个 owner")
        owner_by_data[data] = owner

        writers = as_list(r.get("writers"))
        if writers and owner not in writers:
            errs.add(file, f"$.artifact.data_ownership[{i}].writers",
                     f"R6: owner {owner} 不在写方列表——挂名所有权管不住写路径")
        foreign = [w for w in writers if isinstance(w, str) and w != owner]
        if foreign:
            residuals.append(f"数据 {data!r} 存在非 owner 写方 {foreign}(交 Verifier 逐条质询)")

    for i, m in enumerate(modules):
        mid = m.get("id")
        declared = {d for d in as_list(m.get("owns_data")) if isinstance(d, str)}
        for d in declared:
            if d in owner_by_data and owner_by_data[d] != mid:
                errs.add(file, f"$.artifact.modules[{i}].owns_data",
                         f"R6: {mid} 声明拥有 {d!r},但所有权表记 owner 为 {owner_by_data[d]}——两边不一致")
        for d, o in owner_by_data.items():
            if o == mid and d not in declared:
                errs.add(file, f"$.artifact.modules[{i}].owns_data",
                         f"R6: 所有权表记 {mid} 拥有 {d!r},但模块 owns_data 未声明——双向对账失败")


def check_mapping(body, file, errs, residuals):
    """R7 — upstream_items 与 upstream_mapping 双向对账(引用合法 + 无漏映射)。"""
    items = [u for u in as_list((body.get("input_summary") or {}).get("upstream_items"))
             if isinstance(u, dict)]
    item_ids = [u.get("id") for u in items if isinstance(u.get("id"), str)]
    item_set = set(item_ids)

    modules = [m for m in as_list(body.get("modules")) if isinstance(m, dict)]
    options = [o for o in as_list(body.get("options")) if isinstance(o, dict)]
    landing_ids = ({m.get("id") for m in modules if isinstance(m.get("id"), str)}
                   | {o.get("id") for o in options if isinstance(o.get("id"), str)})

    mapped = set()
    for i, mp in enumerate(as_list(body.get("upstream_mapping"))):
        if not isinstance(mp, dict):
            continue
        u, m = mp.get("upstream_item"), mp.get("module_id")
        if u not in item_set:
            errs.add(file, f"$.artifact.upstream_mapping[{i}].upstream_item",
                     f"R7: 引用了未声明的上游条目 {u!r}——落点必须挂在 upstream_items 声明过的条目上")
        if landing_ids and m not in landing_ids:
            errs.add(file, f"$.artifact.upstream_mapping[{i}].module_id",
                     f"R7: 落点 {m!r} 不是存在的模块/候选 id")
        if u in item_set:
            mapped.add(u)

    missing = sorted(item_set - mapped)
    if missing:
        errs.add(file, "$.artifact.upstream_mapping",
                 f"R7: 上游条目 {missing} 声明了却无架构落点——要么补映射,要么从 upstream_items 删除(并交 Verifier 审删除理由)")


def check_self_challenge(body, file, errs):
    """R8 诚实门(architecture)— 7 维全齐、处置合法、accepted_risk 有理由。"""
    entries = [e for e in as_list(body.get("self_challenge")) if isinstance(e, dict)]
    covered = {e.get("dimension") for e in entries if isinstance(e.get("dimension"), str)}
    missing = [d for d in ADVERSARIAL_DIMS if d not in covered]
    if missing:
        errs.add(file, "$.artifact.self_challenge",
                 f"R8: 自查缺少维度 {missing}——7 维必须逐维占位,无发现也要写空 finding 证明扫过")
    for i, e in enumerate(entries):
        finding, disp = e.get("finding"), e.get("disposition")
        empty = not nonempty_str(finding)
        if empty and disp != "none":
            errs.add(file, f"$.artifact.self_challenge[{i}]",
                     "R8: finding 为空时 disposition 只能是 none")
        if not empty and disp not in ("fixed", "accepted_risk"):
            errs.add(file, f"$.artifact.self_challenge[{i}]",
                     "R8: 有发现必须处置(fixed / accepted_risk),不许悬空")
        if disp == "accepted_risk" and not nonempty_str(e.get("rationale")):
            errs.add(file, f"$.artifact.self_challenge[{i}].rationale",
                     "R8: 接受风险必须写理由——没有理由的接受是遗忘,不是决策")


def check_option_honesty(body, file, errs):
    """R8 诚实门(option_decision)— 候选代价、评估覆盖、推荐合法。"""
    options = [o for o in as_list(body.get("options")) if isinstance(o, dict)]
    ids = {o.get("id") for o in options if isinstance(o.get("id"), str)}
    for i, o in enumerate(options):
        if not nonempty_str(o.get("cost")):
            errs.add(file, f"$.artifact.options[{i}].cost",
                     "R8: 候选缺真实代价——只写收益的候选是广告,不是评估对象")
    for i, ev in enumerate(as_list(body.get("evaluation"))):
        if not isinstance(ev, dict):
            continue
        scores = ev.get("scores") if isinstance(ev.get("scores"), dict) else {}
        uncovered = sorted(ids - set(scores))
        if uncovered:
            errs.add(file, f"$.artifact.evaluation[{i}].scores",
                     f"R8: 评估行未覆盖候选 {uncovered}——每维必须给全部候选打分")
    rec = body.get("recommendation")
    if not (isinstance(rec, dict) and nonempty_str(rec.get("option_id"))):
        errs.add(file, "$.artifact.recommendation",
                 "R8: 缺推荐(option_id 非空)——选型必须给出可执行的结论")


def check_review_findings(body, file, errs):
    """R8 诚实门(review_report)— 7 维全齐、发现带锚点、空发现标 NONE。"""
    findings = [f for f in as_list(body.get("review_findings")) if isinstance(f, dict)]
    covered = {f.get("dimension") for f in findings if isinstance(f.get("dimension"), str)}
    missing = [d for d in ADVERSARIAL_DIMS if d not in covered]
    if missing:
        errs.add(file, "$.artifact.review_findings",
                 f"R8: 评审缺少维度 {missing}——无发现也要占位,证明扫过而非漏扫")
    for i, f in enumerate(findings):
        finding, sev = f.get("finding"), f.get("severity")
        empty = not nonempty_str(finding)
        if empty and sev != "NONE":
            errs.add(file, f"$.artifact.review_findings[{i}]",
                     "R8: finding 为空时 severity 只能是 NONE")
        if not empty:
            if sev == "NONE":
                errs.add(file, f"$.artifact.review_findings[{i}].severity",
                         "R8: 有发现却不定级——发现必须带 severity")
            if not nonempty_str(f.get("evidence_anchor")):
                errs.add(file, f"$.artifact.review_findings[{i}].evidence_anchor",
                         "R8: 锚不到设计文档具体位置的印象分是意见,不是发现")


def check_tradeoff_cost(body, file, errs):
    for i, t in enumerate(as_list(body.get("tradeoffs"))):
        if isinstance(t, dict) and not nonempty_str(t.get("cost")):
            errs.add(file, f"$.artifact.tradeoffs[{i}].cost",
                     "R8: 取舍缺代价——不说放弃什么的取舍不是取舍")


def check_style_fields(body, file, errs):
    style = body.get("style") if isinstance(body.get("style"), dict) else {}
    for field in ("choice", "rationale", "rejected_simpler", "rejected_complexer"):
        if not nonempty_str(style.get(field)):
            errs.add(file, f"$.artifact.style.{field}",
                     f"R8: 风格决策缺 {field}——选了什么/为什么/为什么不更简与更繁,四问缺一不可")


def compute_gates(art, residuals):
    """按 deliverable_kind 算四个门禁,返回 ({四布尔}, 明细)。结构错误只报一次:
    先跑无副作用的检查版,错误已进 errs 的在这里按 False 计。"""
    body = body_of(art)
    kind = kind_of(art)
    details = []

    if kind == "architecture":
        modules = [m for m in as_list(body.get("modules")) if isinstance(m, dict)]
        ids = [m.get("id") for m in modules if isinstance(m.get("id"), str)]
        id_set = set(ids)
        dup_free = len(ids) == len(id_set)
        edges = {}
        refs_ok = True
        for m in modules:
            mid = m.get("id")
            deps = as_list(m.get("depends_on"))
            if any(isinstance(d, str) and d not in id_set for d in deps):
                refs_ok = False
            if isinstance(mid, str) and mid in id_set:
                edges[mid] = {d for d in deps if isinstance(d, str) and d in id_set}
        cyclic, _ = find_cycles(id_set, edges)
        dep_ok = dup_free and refs_ok and not cyclic
        if not dep_ok:
            details.append("模块结构:依赖引用/环检查未过")

        own_ok = True
        owner_by_data = {}
        for r in [r for r in as_list(body.get("data_ownership")) if isinstance(r, dict)]:
            o, d, w = r.get("owner"), r.get("data"), as_list(r.get("writers"))
            if not (nonempty_str(o) and o in id_set):
                own_ok = False
            if d in owner_by_data and owner_by_data[d] != o:
                own_ok = False
            if w and o not in w:
                own_ok = False
            owner_by_data[d] = o
        for m in modules:
            mid = m.get("id")
            declared = {d for d in as_list(m.get("owns_data")) if isinstance(d, str)}
            for d in declared:
                if d in owner_by_data and owner_by_data[d] != mid:
                    own_ok = False
            for d, o in owner_by_data.items():
                if o == mid and d not in declared:
                    own_ok = False
        if not own_ok:
            details.append("所有权:owner 唯一/双向一致/写方检查未过")
    elif kind == "option_decision":
        options = [o for o in as_list(body.get("options")) if isinstance(o, dict)]
        ids = [o.get("id") for o in options if isinstance(o.get("id"), str)]
        id_set = set(ids)
        rec = body.get("recommendation")
        dep_ok = (len(options) >= 2 and len(ids) == len(id_set)
                  and isinstance(rec, dict) and rec.get("option_id") in id_set)
        if not dep_ok:
            details.append("候选结构:≥2/id 唯一/推荐合法 检查未过")
        own_ok = True
    else:  # review_report
        dep_ok = own_ok = True

    # 覆盖门:architecture/option_decision 必须声明并对账;review 声明了才对账
    items = [u for u in as_list((body.get("input_summary") or {}).get("upstream_items"))
             if isinstance(u, dict)]
    item_ids = {u.get("id") for u in items if isinstance(u.get("id"), str)}
    if kind in ("architecture", "option_decision"):
        if not item_ids:
            map_ok = False
            details.append("覆盖:upstream_items 为空(覆盖检查无分母)")
        else:
            map_ok = _mapping_consistent(body, item_ids)
            if not map_ok:
                details.append("覆盖:映射双向对账未过")
    else:
        map_ok = _mapping_consistent(body, item_ids) if item_ids else True

    if kind == "architecture":
        honest = _self_challenge_ok(body) and _tradeoffs_ok(body) and _style_ok(body)
        if not honest:
            details.append("诚实:自查 7 维/取舍代价/风格四问 检查未过")
    elif kind == "option_decision":
        honest = (_options_cost_ok(body) and _evaluation_ok(body)
                  and isinstance(body.get("recommendation"), dict)
                  and nonempty_str(body.get("recommendation", {}).get("option_id"))
                  and _tradeoffs_ok(body))
        if not honest:
            details.append("诚实:候选代价/评估覆盖/推荐 检查未过")
    else:
        honest = _findings_ok(body)
        if not honest:
            details.append("诚实:评审 7 维/锚点/定级 检查未过")

    return ({"dependency_acyclic": dep_ok, "unique_owners": own_ok,
             "upstream_mapped": map_ok, "findings_disposed": honest}, details)


def _mapping_consistent(body, item_ids):
    modules = [m for m in as_list(body.get("modules")) if isinstance(m, dict)]
    options = [o for o in as_list(body.get("options")) if isinstance(o, dict)]
    landing = ({m.get("id") for m in modules if isinstance(m.get("id"), str)}
               | {o.get("id") for o in options if isinstance(o.get("id"), str)})
    mapped = set()
    for mp in as_list(body.get("upstream_mapping")):
        if not isinstance(mp, dict):
            return False
        if mp.get("upstream_item") not in item_ids:
            return False
        if landing and mp.get("module_id") not in landing:
            return False
        mapped.add(mp.get("upstream_item"))
    return item_ids <= mapped


def _self_challenge_ok(body):
    entries = [e for e in as_list(body.get("self_challenge")) if isinstance(e, dict)]
    covered = {e.get("dimension") for e in entries}
    if any(d not in covered for d in ADVERSARIAL_DIMS):
        return False
    for e in entries:
        empty = not nonempty_str(e.get("finding"))
        if empty and e.get("disposition") != "none":
            return False
        if not empty and e.get("disposition") not in ("fixed", "accepted_risk"):
            return False
        if e.get("disposition") == "accepted_risk" and not nonempty_str(e.get("rationale")):
            return False
    return True


def _tradeoffs_ok(body):
    return all(nonempty_str(t.get("cost"))
               for t in as_list(body.get("tradeoffs")) if isinstance(t, dict)) or not as_list(body.get("tradeoffs"))


def _style_ok(body):
    style = body.get("style") if isinstance(body.get("style"), dict) else {}
    return all(nonempty_str(style.get(f)) for f in
               ("choice", "rationale", "rejected_simpler", "rejected_complexer"))


def _options_cost_ok(body):
    return all(nonempty_str(o.get("cost"))
               for o in as_list(body.get("options")) if isinstance(o, dict))


def _evaluation_ok(body):
    options = [o for o in as_list(body.get("options")) if isinstance(o, dict)]
    ids = {o.get("id") for o in options if isinstance(o.get("id"), str)}
    for ev in as_list(body.get("evaluation")):
        if not isinstance(ev, dict):
            return False
        scores = ev.get("scores") if isinstance(ev.get("scores"), dict) else {}
        if not ids <= set(scores):
            return False
    return True


def _findings_ok(body):
    findings = [f for f in as_list(body.get("review_findings")) if isinstance(f, dict)]
    covered = {f.get("dimension") for f in findings}
    if any(d not in covered for d in ADVERSARIAL_DIMS):
        return False
    for f in findings:
        empty = not nonempty_str(f.get("finding"))
        if empty and f.get("severity") != "NONE":
            return False
        if not empty and (f.get("severity") == "NONE"
                          or not nonempty_str(f.get("evidence_anchor"))):
            return False
    return True


def semantic_rules(state, artifacts, errs):
    """R1-R4:schema 表达不了(或没表达)的状态机硬约束。"""
    # R1 — FACT/DECISION/INFERENCE 必须带证据或依据
    ledgers = [("state.json $.evidence", state.get("evidence", []))] if state else []
    for name, art in artifacts:
        ledgers.append((f"{name} $.evidence", art.get("evidence", [])))
    for path, entries in ledgers:
        for i, e in enumerate(entries):
            if isinstance(e, dict) and e.get("type") in ("FACT", "DECISION", "INFERENCE"):
                ev = e.get("evidence")
                hint = {
                    "FACT": "上游 §x / .pev/<轮次>/ 家族产物 / 代码路径",
                    "DECISION": "拍板/精修锚点,如 01-artifact decisions#d2",
                    "INFERENCE": "推理依据:引用了哪些 FACT/数据",
                }[e["type"]]
                if not isinstance(ev, str) or not ev.strip():
                    errs.add("", f"{path}[{i}]",
                             f"R1: type={e['type']} 的条目必须有非空 evidence({hint});"
                             "无证据请标 HYPOTHESIS/UNKNOWN")

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

    # R4 — WAITING_FOR_UPSTREAM 与 upstream_gaps 互相锁定
    if state:
        status = state.get("status")
        gaps = state.get("upstream_gaps")
        if status == "WAITING_FOR_UPSTREAM" and (not isinstance(gaps, list) or len(gaps) == 0):
            errs.add("state.json", "$.upstream_gaps", "R4: status=WAITING_FOR_UPSTREAM 时必须携带非空 upstream_gaps(回上游的缺口清单)")
        if status != "WAITING_FOR_UPSTREAM" and isinstance(gaps, list) and len(gaps) > 0:
            errs.add("state.json", "$.upstream_gaps", "R4: 仅 WAITING_FOR_UPSTREAM 状态允许携带非空 upstream_gaps,上游更新恢复后应清空")

    # R14 — COMPLETE 与用户确认记录互相锁定(consolidate T2-2):
    # PASS 渲染后等用户确认期间停在 VERIFYING;未确认的 COMPLETE 不得让下游开始
    if state:
        status = state.get("status")
        conf = state.get("user_confirmation")
        has_conf = isinstance(conf, dict) and isinstance(conf.get("date"), str) and conf.get("date").strip()
        if status == "COMPLETE" and not has_conf:
            errs.add("state.json", "$.user_confirmation",
                     "R14: status=COMPLETE 但缺少用户确认记录 user_confirmation(date)——"
                     "PASS 渲染后须等用户确认,未确认前停在 VERIFYING")
        if status != "COMPLETE" and conf is not None:
            errs.add("state.json", "$.user_confirmation",
                     "R14: user_confirmation 仅在 status=COMPLETE 时允许存在;确认即置 COMPLETE,"
                     "等待确认期间停在 VERIFYING")


def normalize_text(value):
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def sha256_hex(value):
    return "sha256:" + hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def find_project_root(pev_dir):
    """从 arch 工作目录向上定位项目根(含 .pev 的目录的父目录)。找不到返回 None。"""
    current = Path(pev_dir).resolve()
    for candidate in [current, *current.parents]:
        if candidate.name == ".pev":
            return candidate.parent
    return None


def iter_string_paths(value, prefix="$"):
    """递归产出 (json_path, 字符串值),用于内容级占位扫描。"""
    if isinstance(value, str):
        yield prefix, value
    elif isinstance(value, dict):
        for key, sub in value.items():
            yield from iter_string_paths(sub, f"{prefix}.{key}")
    elif isinstance(value, list):
        for i, sub in enumerate(value):
            yield from iter_string_paths(sub, f"{prefix}[{i}]")


def find_placeholders(text):
    hits = {m.group(0).upper() for m in PLACEHOLDER_WORD_RE.finditer(text)}
    for token in PLACEHOLDER_SUBSTR:
        if token in text:
            hits.add(token)
    return sorted(hits)


def upstream_item_ids_of(art):
    body = body_of(art)
    items = as_list((body.get("input_summary") or {}).get("upstream_items"))
    return {u.get("id") for u in items if isinstance(u, dict) and isinstance(u.get("id"), str)}


def check_no_placeholders(art, name, errs):
    """R10 — completed 的 artifact 不得残留占位/未关闭措辞;打回/阻塞态允许。"""
    if art.get("status") != "completed":
        return
    for path, text in iter_string_paths(art, "$"):
        hits = find_placeholders(text)
        if hits:
            errs.add(name, path,
                     f"R10: 产物已 completed 但仍含占位/未关闭措辞 {hits}"
                     "——要么关闭,要么置 status=blocked 并写入 unresolved")


def check_evidence_source(src, base, project_root, errs):
    """R11b — source 回读校验:路径存在、excerpt 命中、摘要一致(新鲜度)。"""
    path_val = src.get("path")
    excerpt = src.get("excerpt")
    digest = src.get("digest")
    if not nonempty_str(path_val) or not nonempty_str(excerpt):
        errs.add("", f"{base}.source", "R11: source 存在时必须含非空 path 与 excerpt")
        return
    excerpt_n = normalize_text(excerpt)
    resolved = Path(path_val)
    if not resolved.is_absolute():
        if project_root is None:
            errs.add("", f"{base}.source.path",
                     "R11: 无法定位项目根目录(未找到 .pev),相对来源路径无法解析")
            return
        resolved = project_root / resolved
    if not resolved.is_file():
        errs.add("", f"{base}.source.path", f"R11: 证据来源文件不存在:{resolved}")
        return
    try:
        text = normalize_text(resolved.read_text(encoding="utf-8"))
    except OSError as exc:
        errs.add("", f"{base}.source.path", f"R11: 证据来源不可读:{exc}")
        return
    if excerpt_n not in text:
        errs.add("", f"{base}.source.excerpt", "R11: excerpt 不在来源文件中(来源已变化或摘录伪造)")
        return
    if nonempty_str(digest) and digest != "pending" and sha256_hex(excerpt_n) != digest:
        errs.add("", f"{base}.source.digest", "R11: source.digest 与 excerpt 摘要不一致(来源已变化)")


def check_evidence_resolvable(state, artifacts, pev_dir, errs):
    """R11 — 证据可解析:DECISION 锚点 decisions#<id> 必须真实存在;source 回读新鲜度。"""
    decision_ids = set()
    for _name, art in artifacts:
        for d in as_list(art.get("decisions")):
            if isinstance(d, dict) and nonempty_str(d.get("id")):
                decision_ids.add(d["id"])

    ledgers = []
    if state:
        ledgers.append(("state.json $.evidence", state.get("evidence", [])))
    for name, art in artifacts:
        ledgers.append((f"{name} $.evidence", art.get("evidence", [])))

    project_root = find_project_root(pev_dir)
    for path, entries in ledgers:
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                continue
            base = f"{path}[{i}]"
            if e.get("type") == "DECISION" and isinstance(e.get("evidence"), str):
                for anchor in re.findall(r"decisions#([A-Za-z0-9_-]+)", e["evidence"]):
                    if anchor not in decision_ids:
                        errs.add("", f"{base}.evidence",
                                 f"R11: DECISION 锚点 decisions#{anchor} 找不到对应 decisions 条目"
                                 f"(已登记: {sorted(decision_ids) or '无'})")
            src = e.get("source")
            if isinstance(src, dict):
                check_evidence_source(src, base, project_root, errs)


def check_finding_trace(doc, artifact, name, errs):
    """R12 — 结构化发现必须携带 affected_upstream_items 并回指声明过的上游条目。"""
    findings = as_list(doc.get("findings"))
    if not findings:
        return
    valid_ids = upstream_item_ids_of(artifact)
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            continue
        base = f"$.findings[{i}]"
        if not nonempty_str(f.get("id")):
            errs.add(name, base, "R12: finding 缺少 id")
        for field in ("what", "why", "what_must_change"):
            if not nonempty_str(f.get(field)):
                errs.add(name, f"{base}.{field}",
                         f"R12: finding 缺少 {field}(反向追溯要求 What/Why/What must change 完整)")
        affected = as_list(f.get("affected_upstream_items"))
        if not affected:
            errs.add(name, f"{base}.affected_upstream_items",
                     "R12: finding 必须携带非空 affected_upstream_items(否则 REVISE 无法定位卡住的需求)")
        for uid in affected:
            if not isinstance(uid, str) or not uid.strip():
                errs.add(name, f"{base}.affected_upstream_items", "R12: 受影响上游条目 id 非法")
            elif valid_ids and uid not in valid_ids:
                errs.add(name, f"{base}.affected_upstream_items",
                         f"R12: 引用未声明的上游条目 {uid!r}(声明过的: {sorted(valid_ids)})")


def load_redline_library():
    path = REDLINES_DIR / "architecture-redlines.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return as_list(data.get("redlines"))


def check_redlines(doc, name, errs):
    """R13 — 红线库:红线 id 必须在库中;适用红线未通过不得判 PASS(红线独立于评分)。"""
    redlines = as_list(doc.get("redlines"))
    if not redlines:
        return
    library = load_redline_library()
    known = {r.get("id") for r in library} if library is not None else None
    verdict = doc.get("verdict")
    for i, r in enumerate(redlines):
        if not isinstance(r, dict):
            continue
        base = f"$.redlines[{i}]"
        rid = r.get("id")
        if not nonempty_str(rid):
            errs.add(name, base, "R13: 红线缺少 id")
            continue
        if known is not None and rid not in known:
            errs.add(name, f"{base}.id", f"R13: 红线 {rid!r} 不在红线库中(可用: {sorted(known)})")
        if not nonempty_str(r.get("details")):
            errs.add(name, f"{base}.details", "R13: 红线必须写 details(为什么适用/不适用、结论依据)")
        if r.get("applies") is True:
            passed = r.get("passed")
            if not isinstance(passed, bool):
                errs.add(name, f"{base}.passed", "R13: 适用红线(applies=true)必须显式写 passed 布尔")
            elif passed is False and verdict == "PASS":
                errs.add(name, f"{base}.passed",
                         f"R13: 适用红线 {rid} 未通过却判 verdict=PASS——红线独立于评分,任一适用红线不过不得 PASS")


def main(argv):
    if len(argv) < 2:
        print("用法: python3 validate.py <PEV_DIR>   # 如 .pev/prd-2026-09-20/arch/")
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
    check_evidence_resolvable(state, artifacts, pev_dir, errs)

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

    # R5-R8 — 结构/所有权/覆盖/诚实:错误进 errs,门禁布尔留给对账
    residuals = []
    for name, art in artifacts:
        check_no_placeholders(art, name, errs)
        body, kind = body_of(art), kind_of(art)
        if kind == "architecture":
            check_module_graph(body, name, errs)
            check_ownership(body, name, errs, residuals)
            check_mapping(body, name, errs, residuals)
            check_self_challenge(body, name, errs)
            check_tradeoff_cost(body, name, errs)
            check_style_fields(body, name, errs)
        elif kind == "option_decision":
            check_option_structure(body, name, errs)
            check_mapping(body, name, errs, residuals)
            check_option_honesty(body, name, errs)
            check_tradeoff_cost(body, name, errs)
        elif kind == "review_report":
            check_review_findings(body, name, errs)
            if as_list((body.get("input_summary") or {}).get("upstream_items")):
                check_mapping(body, name, errs, residuals)
        else:
            errs.add(name, "$.artifact.deliverable_kind",
                     f"未知 deliverable_kind {kind!r}")

    # R6/R8 — 门禁布尔照抄脚本;PASS 必须全绿
    def iter_no(name):
        return Path(name).stem.split("-", 1)[0]

    art_by_iter = {iter_no(name): (name, art) for name, art in artifacts}
    latest = artifacts[-1] if artifacts else None
    verify_fresh = state is not None and state.get("status") in ("VERIFYING", "COMPLETE")
    for name, doc in verifications:
        entry = art_by_iter.get(iter_no(name))
        if entry is None:
            errs.add(name, "$.gates",
                     f"R6: 缺少同迭代 {iter_no(name)}-artifact.json,无法比对门禁"
                     "(verification 与 artifact 各比各的,不跨迭代)")
            continue
        gates, _details = compute_gates(entry[1], residuals)
        # R8 — PASS 必须四门禁全绿;未过的 REVISE/REPLAN/BLOCKED 是合法评审
        if doc.get("verdict") == "PASS" and not all(gates.values()):
            failed = [k for k, v in gates.items() if not v]
            errs.add(name, "$.verdict",
                     f"R8: verdict=PASS 但门禁未全绿({failed})——应判 REVISE 并修复,不得 PASS")
        check_finding_trace(doc, entry[1], name, errs)
        check_redlines(doc, name, errs)
        claimed = doc.get("gates")
        if not isinstance(claimed, dict):
            continue
        if not verify_fresh:
            continue
        for key, computed in gates.items():
            if isinstance(claimed.get(key), bool) and claimed[key] != computed:
                errs.add(name, f"$.gates.{key}",
                         f"R6: 声称 {claimed[key]},artifact 算出 {computed}——门禁布尔必须来自脚本计算,不接受人工填写")

    if errs:
        print(f"校验失败,{len(errs)} 个问题:")
        for e in errs.items:
            print(f"  - {e}")
        return 1
    print(f"OK: {pev_dir} 全部产物通过 schema 与语义规则校验")
    if verifications and state is not None and not verify_fresh:
        print(f"注: state.status={state.get('status')} —— 盘上 verification 视为上一轮历史产物,"
              "跳过 R6 门禁布尔比对(REVISE 中间态;进入 VERIFYING/COMPLETE 后恢复比对)")
    if latest is not None:
        gates, details = compute_gates(latest[1], residuals)
        gate_ok = all(gates.values())
        print(f"门禁(脚本计算,最新迭代):dependency_acyclic={gates['dependency_acyclic']} "
              f"unique_owners={gates['unique_owners']} upstream_mapped={gates['upstream_mapped']} "
              f"findings_disposed={gates['findings_disposed']} "
              f"PASS 前置(全绿):{'通过' if gate_ok else '未通过'}")
        for d in details:
            print(f"  未过明细: {d}")
        if residuals:
            print("残留清单(交 Verifier 逐条处置,非门禁):")
            for r in residuals:
                print(f"  - {r}")
        else:
            print("残留清单:无")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
