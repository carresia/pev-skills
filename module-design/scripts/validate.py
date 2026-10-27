#!/usr/bin/env python3
"""module-design PEV 产物校验器(双端通用,仅依赖 Python 标准库)。

用法:
    python3 validate.py <PEV_DIR>      # PEV_DIR 为本 skill 工作目录,如 .pev/prd-2026-09-20/module/

按文件名后缀路由到 schemas/ 下对应 schema:
    state.json                    -> state.schema.json
    iterations/*-plan.json        -> plan.schema.json
    iterations/*-artifact.json    -> artifact.schema.json
    iterations/*-verification.json-> verification.schema.json

除 JSON Schema 子集(type/enum/required/properties/items/minItems/
minimum/maximum)外,强制以下语义规则——这些是状态机的硬约束,靠肉眼最容易漏:
    R1  Evidence 条目 type=FACT/DECISION 时 evidence 必须是非空字符串
        (FACT 证据=架构产物 §x / .pev/<轮次>/ 家族产物 / 代码路径;
        DECISION 证据=拍板/精修锚点)。INFERENCE 同样必须带非空推理依据;
        三者缺证据 → 报错。HYPOTHESIS/UNKNOWN 允许 evidence 为 null。
    R2  artifact.status ∈ {replan_required, blocked} 时,replan_reason 必填
    R3  state.status=WAITING_FOR_INPUT 时,resume_to 必填;
        其他 status 下 resume_to 必须不存在
    R4  state.status=WAITING_FOR_UPSTREAM 时,upstream_gaps 必须非空;
        其他 status 下 upstream_gaps 必须为空
    R5  边界守恒与结构(module_designs kind,全部对照 architecture_snapshot):
        - 设计模块 id ⊆ 快照模块 id;目标模块(target_modules)个个有设计;
        - depends_on ⊆ 快照声明;owned_data_handling.data ⊆ 快照 owns_data;
          exposes_realization.expose ⊆ 快照 exposes——越界即报错;
        - 组件 id 模块内唯一,responsibility 与 hides 非空(复述式凑数交 Verifier);
        - exposes_realization.component_id / fmea.component_id 引用存在的组件;
        - interaction_commitments.interaction 引用快照交互 id,且本模块是该
          交互的参与方(from/to);
        - detail 模式 fmea 非空且 dfx 五项 x 全覆盖;brief 模式 fmea 必须为空
          且 dfx ≥1。
    R6  门禁布尔照抄脚本:评审落点 state.status ∈ {VERIFYING, COMPLETE} 时,
        verification.gates 五值与脚本计算逐位比对,不一致整份打回
    R7  覆盖对账:upstream_items 必须覆盖每个目标模块的全部快照 exposes
        (逐条精确匹配,分母造假直接报错);upstream_mapping 引用合法;
        每条 upstream_item 被映射 ≥1 次;每个目标模块至少有一条落点。
    R8  诚实门:self_challenge 7 维全齐且处置合法(accepted_risk 必须带理由);
        tradeoffs 全部 cost 非空。
    R9  state.plans / state.artifacts 登记册(文件名,不存内容副本)与
        iterations/ 目录双向一致
    R10 completed 的 artifact 不得残留占位/未关闭措辞(TODO/TBD/FIXME、
        [待确认]、待定 等);未关闭语义应走 status=blocked + unresolved。
    R11 证据可解析与回读新鲜度:DECISION 证据若引用 decisions#<id>,锚点必须
        真实存在于某个 artifact 的 decisions;evidence 带 source{path,excerpt,
        digest} 时回读来源文件校验 excerpt 命中与摘要一致。
    R12 verification.findings 的反向追溯:每条 finding 必须带非空
        affected_upstream_items,且每个 id 回指同迭代 artifact 声明过的
        upstream_items。
    R13 红线库:verification.redlines 的红线 id 必须在红线库中;适用红线
        (applies=true)未通过(passed=false)时不得判 PASS——红线独立于评分。
    R14 verdict=PASS 的硬前提(缺一报错):
        - module_reviews 覆盖全部目标模块且逐个 verdict=PASS;
        - cross_review.verdict=pass;
        - 五个门禁全绿。
        module_reviews[].module_id 必须引用设计过的模块 id。

五个门禁的布尔(module_designs kind):
    modules_complete         —— 目标模块个个有设计,且每模块有 ≥1 组件、
                                ≥1 核心流程、≥1 DFX 条目
    deps_within_architecture —— R5 守恒与引用检查(依赖/数据/暴露/组件/交互引用)
    upstream_mapped          —— R7 对账过且 upstream_items 非空
    findings_disposed        —— R8 过 + detail 的 fmea 非空/brief 的 fmea 为空
    cross_consistent         —— R5 交互承接检查全部通过

通过时汇总输出:最新迭代的五门禁结论,以及交 Verifier 逐条处置的残留清单
(快照声明了 owns_data 却无 owned_data_handling 条目的数据)。

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

# 对抗 7 维(与 rubrics/module-review.md 一致)
ADVERSARIAL_DIMS = ("failure_modes", "consistency", "concurrency",
                    "boundary_erosion", "hidden_coupling", "testability",
                    "simpler_alternative")

# DFX 五项(detail 模式全覆盖)
DFX_KINDS = ("reliability", "testability", "maintainability",
             "observability", "security")

GATE_KEYS = ("modules_complete", "deps_within_architecture", "upstream_mapped",
             "findings_disposed", "cross_consistent")

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


def snapshot_of(body):
    snap = (body.get("input_summary") or {}).get("architecture_snapshot")
    return snap if isinstance(snap, dict) else {}


def snap_modules(body):
    out = {}
    for m in as_list(snapshot_of(body).get("modules")):
        if isinstance(m, dict) and isinstance(m.get("id"), str):
            out[m["id"]] = m
    return out


def snap_interactions(body):
    out = {}
    for it in as_list(snapshot_of(body).get("interactions")):
        if isinstance(it, dict) and isinstance(it.get("id"), str):
            out[it["id"]] = it
    return out


def designed_modules(body):
    return [m for m in as_list(body.get("modules")) if isinstance(m, dict)]


def component_ids(m):
    return {c.get("id") for c in as_list(m.get("internal_components"))
            if isinstance(c, dict) and isinstance(c.get("id"), str)}


def check_conformance(body, file, errs, residuals):
    """R5 — 边界守恒与结构:全部对照 architecture_snapshot。"""
    snap_m = snap_modules(body)
    snap_i = snap_interactions(body)
    target = [t for t in as_list((body.get("input_summary") or {}).get("target_modules"))
              if isinstance(t, str)]

    for t in target:
        if t not in snap_m:
            errs.add(file, "$.artifact.input_summary.target_modules",
                     f"R5: 目标模块 {t!r} 不在架构快照中——目标只能取自架构声明的模块")

    for m in designed_modules(body):
        mid = m.get("id")
        base = f"$.artifact.modules[{mid}]"
        arch = snap_m.get(mid)
        if arch is None:
            errs.add(file, f"{base}.id",
                     f"R5: 模块 {mid!r} 不是架构快照声明的模块——模块设计无权新造模块")
            continue

        # 依赖守恒
        arch_deps = {d for d in as_list(arch.get("depends_on")) if isinstance(d, str)}
        extra = sorted({d for d in as_list(m.get("depends_on"))
                        if isinstance(d, str)} - arch_deps)
        if extra:
            errs.add(file, f"{base}.depends_on",
                     f"R5: 新增架构声明外的依赖 {extra}——需要新依赖是架构层缺口,"
                     "走三选一,不在模块层私自扩边")

        # 组件结构
        comps = [c for c in as_list(m.get("internal_components")) if isinstance(c, dict)]
        cids = [c.get("id") for c in comps if isinstance(c.get("id"), str)]
        dup = sorted({c for c in cids if cids.count(c) > 1})
        if dup:
            errs.add(file, f"{base}.internal_components", f"R5: 组件 id 重复 {dup}")
        cset = component_ids(m)
        for i, c in enumerate(comps):
            for field in ("responsibility", "hides"):
                if not nonempty_str(c.get(field)):
                    errs.add(file, f"{base}.internal_components[{i}].{field}",
                             f"R5: 组件 {c.get('id')!r} 的 {field} 为空——"
                             + ("复述职责不算 hides,写它隐藏的设计决策" if field == "hides" else "组件必须有职责陈述"))

        # exposes 落点守恒
        arch_exposes = {e for e in as_list(arch.get("exposes")) if isinstance(e, str)}
        for i, er in enumerate(as_list(m.get("exposes_realization"))):
            if not isinstance(er, dict):
                continue
            if er.get("expose") not in arch_exposes:
                errs.add(file, f"{base}.exposes_realization[{i}].expose",
                         f"R5: 落点声明的暴露能力 {er.get('expose')!r} 不在架构快照 exposes 中")
            if er.get("component_id") not in cset:
                errs.add(file, f"{base}.exposes_realization[{i}].component_id",
                         f"R5: 实现组件 {er.get('component_id')!r} 不存在(可用: {sorted(cset)})")

        # 自有数据守恒
        arch_data = {d for d in as_list(arch.get("owns_data")) if isinstance(d, str)}
        handled = set()
        for i, od in enumerate(as_list(m.get("owned_data_handling"))):
            if not isinstance(od, dict):
                continue
            if od.get("data") not in arch_data:
                errs.add(file, f"{base}.owned_data_handling[{i}].data",
                         f"R5: 数据 {od.get('data')!r} 不是架构声明本模块拥有的——所有权是架构决定")
            handled.add(od.get("data"))
        for d in sorted(arch_data - handled):
            residuals.append(f"模块 {mid} 架构声明拥有数据 {d!r} 但无内部处理描述(交 Verifier 处置)")

        # 交互承接
        for i, ic in enumerate(as_list(m.get("interaction_commitments"))):
            if not isinstance(ic, dict):
                continue
            iid = ic.get("interaction")
            it = snap_i.get(iid)
            if it is None:
                errs.add(file, f"{base}.interaction_commitments[{i}].interaction",
                         f"R5: 承接的交互 {iid!r} 不在架构快照交互中(可用: {sorted(snap_i)})")
                continue
            if mid not in (it.get("from"), it.get("to")):
                errs.add(file, f"{base}.interaction_commitments[{i}].interaction",
                         f"R5: 模块 {mid} 不是交互 {iid}({it.get('from')}→{it.get('to')})的参与方——不能替别人认领")

        # FMEA 与 DFX 按深度
        fmea = [f for f in as_list(m.get("fmea")) if isinstance(f, dict)]
        mode = m.get("design_mode")
        if mode == "detail" and not fmea:
            errs.add(file, f"{base}.fmea",
                     "R5: detail 模式 FMEA 必须非空——可靠性设计没有失效分析就是空话")
        if mode == "brief" and fmea:
            errs.add(file, f"{base}.fmea",
                     "R5: brief 模式不得携带 FMEA——要 FMEA 请提升该模块为 detail")
        for i, f in enumerate(fmea):
            if f.get("component_id") not in cset:
                errs.add(file, f"{base}.fmea[{i}].component_id",
                         f"R5: FMEA 组件 {f.get('component_id')!r} 不存在(可用: {sorted(cset)})")
        xs = {d.get("x") for d in as_list(m.get("dfx")) if isinstance(d, dict)}
        if mode == "detail":
            missing = [x for x in DFX_KINDS if x not in xs]
            if missing:
                errs.add(file, f"{base}.dfx",
                         f"R5: detail 模式 DFX 五项须全覆盖,缺 {missing}")
        elif mode == "brief" and not xs:
            errs.add(file, f"{base}.dfx", "R5: brief 模式至少要有 1 条关键 DFX 点")


def check_mapping(body, file, errs):
    """R7 — 分母完备(快照 exposes 逐条进 upstream_items)+ 映射双向对账。"""
    summary = body.get("input_summary") or {}
    items = [u for u in as_list(summary.get("upstream_items")) if isinstance(u, dict)]
    item_ids = {u.get("id") for u in items if isinstance(u.get("id"), str)}
    item_texts = {u.get("item") for u in items if isinstance(u.get("item"), str)}

    snap_m = snap_modules(body)
    target = [t for t in as_list(summary.get("target_modules")) if isinstance(t, str)]
    for t in target:
        arch = snap_m.get(t)
        if not arch:
            continue  # 已在 R5 报过
        for e in as_list(arch.get("exposes")):
            if isinstance(e, str) and e not in item_texts:
                errs.add(file, "$.artifact.input_summary.upstream_items",
                         f"R7: 快照声明模块 {t} 暴露 {e!r} 但 upstream_items 未声明——分母不全,覆盖检查失效")

    designed_ids = {m.get("id") for m in designed_modules(body)
                    if isinstance(m.get("id"), str)}
    mapped = set()
    landed = set()
    for i, mp in enumerate(as_list(body.get("upstream_mapping"))):
        if not isinstance(mp, dict):
            continue
        u, m = mp.get("upstream_item"), mp.get("module_id")
        if u not in item_ids:
            errs.add(file, f"$.artifact.upstream_mapping[{i}].upstream_item",
                     f"R7: 引用了未声明的上游条目 {u!r}")
        if designed_ids and m not in designed_ids:
            errs.add(file, f"$.artifact.upstream_mapping[{i}].module_id",
                     f"R7: 落点 {m!r} 不是设计过的模块 id")
        mapped.add(u)
        landed.add(m)

    missing = sorted(i for i in item_ids if i not in mapped)
    if missing:
        errs.add(file, "$.artifact.upstream_mapping",
                 f"R7: 上游条目 {missing} 声明了却无落点——要么补映射,要么从 upstream_items 删除(并交 Verifier 审删除理由)")
    for t in target:
        if t in designed_ids and t not in landed:
            errs.add(file, "$.artifact.upstream_mapping",
                     f"R7: 目标模块 {t} 没有任何落点条目——职责承接没有对账记录")


def check_self_challenge(body, file, errs):
    """R8 — 每模块 7 维全齐、处置合法、accepted_risk 有理由。"""
    for m in designed_modules(body):
        mid = m.get("id")
        entries = [e for e in as_list(m.get("self_challenge")) if isinstance(e, dict)]
        covered = {e.get("dimension") for e in entries if isinstance(e.get("dimension"), str)}
        missing = [d for d in ADVERSARIAL_DIMS if d not in covered]
        if missing:
            errs.add(file, f"$.artifact.modules[{mid}].self_challenge",
                     f"R8: 模块 {mid} 自查缺少维度 {missing}——7 维必须逐维占位,无发现也要写空 finding 证明扫过")
        for i, e in enumerate(entries):
            finding, disp = e.get("finding"), e.get("disposition")
            empty = not nonempty_str(finding)
            if empty and disp != "none":
                errs.add(file, f"$.artifact.modules[{mid}].self_challenge[{i}]",
                         "R8: finding 为空时 disposition 只能是 none")
            if not empty and disp not in ("fixed", "accepted_risk"):
                errs.add(file, f"$.artifact.modules[{mid}].self_challenge[{i}]",
                         "R8: 有发现必须处置(fixed / accepted_risk),不许悬空")
            if disp == "accepted_risk" and not nonempty_str(e.get("rationale")):
                errs.add(file, f"$.artifact.modules[{mid}].self_challenge[{i}].rationale",
                         "R8: 接受风险必须写理由——没有理由的接受是遗忘,不是决策")


def check_tradeoff_cost(body, file, errs):
    for m in designed_modules(body):
        mid = m.get("id")
        for i, t in enumerate(as_list(m.get("tradeoffs"))):
            if isinstance(t, dict) and not nonempty_str(t.get("cost")):
                errs.add(file, f"$.artifact.modules[{mid}].tradeoffs[{i}].cost",
                         "R8: 取舍缺代价——不说放弃什么的取舍不是取舍")


# ---------- 门禁计算(无副作用版本,与上面检查保持同一判据) ----------

def _structure_ok(body):
    snap_m = snap_modules(body)
    snap_i = snap_interactions(body)
    for m in designed_modules(body):
        mid = m.get("id")
        arch = snap_m.get(mid)
        if arch is None:
            return False
        arch_deps = {d for d in as_list(arch.get("depends_on")) if isinstance(d, str)}
        if not arch_deps >= {d for d in as_list(m.get("depends_on")) if isinstance(d, str)}:
            return False
        cset = component_ids(m)
        comps = [c for c in as_list(m.get("internal_components")) if isinstance(c, dict)]
        cids = [c.get("id") for c in comps]
        if len(cids) != len(cset):
            return False
        if any(not nonempty_str(c.get("responsibility")) or not nonempty_str(c.get("hides"))
               for c in comps):
            return False
        arch_exposes = {e for e in as_list(arch.get("exposes")) if isinstance(e, str)}
        for er in as_list(m.get("exposes_realization")):
            if not isinstance(er, dict):
                return False
            if er.get("expose") not in arch_exposes or er.get("component_id") not in cset:
                return False
        arch_data = {d for d in as_list(arch.get("owns_data")) if isinstance(d, str)}
        for od in as_list(m.get("owned_data_handling")):
            if isinstance(od, dict) and od.get("data") not in arch_data:
                return False
    return True


def _cross_ok(body):
    snap_i = snap_interactions(body)
    for m in designed_modules(body):
        mid = m.get("id")
        for ic in as_list(m.get("interaction_commitments")):
            if not isinstance(ic, dict):
                return False
            it = snap_i.get(ic.get("interaction"))
            if it is None or mid not in (it.get("from"), it.get("to")):
                return False
    return True


def _modules_complete_ok(body):
    snap_m = snap_modules(body)
    target = [t for t in as_list((body.get("input_summary") or {}).get("target_modules"))
              if isinstance(t, str)]
    by_id = {m.get("id"): m for m in designed_modules(body) if isinstance(m.get("id"), str)}
    for t in target:
        m = by_id.get(t)
        if m is None:
            return False
        if not as_list(m.get("internal_components")):
            return False
        if not as_list(m.get("core_flows")):
            return False
        if not as_list(m.get("dfx")):
            return False
    return True


def _mapping_ok(body):
    summary = body.get("input_summary") or {}
    items = [u for u in as_list(summary.get("upstream_items")) if isinstance(u, dict)]
    item_ids = {u.get("id") for u in items if isinstance(u.get("id"), str)}
    item_texts = {u.get("item") for u in items if isinstance(u.get("item"), str)}
    if not item_ids:
        return False
    snap_m = snap_modules(body)
    for t in [t for t in as_list(summary.get("target_modules")) if isinstance(t, str)]:
        arch = snap_m.get(t)
        if arch and any(isinstance(e, str) and e not in item_texts
                        for e in as_list(arch.get("exposes"))):
            return False
    designed_ids = {m.get("id") for m in designed_modules(body)
                    if isinstance(m.get("id"), str)}
    mapped, landed = set(), set()
    for mp in as_list(body.get("upstream_mapping")):
        if not isinstance(mp, dict):
            return False
        if mp.get("upstream_item") not in item_ids:
            return False
        if designed_ids and mp.get("module_id") not in designed_ids:
            return False
        mapped.add(mp.get("upstream_item"))
        landed.add(mp.get("module_id"))
    if not item_ids <= mapped:
        return False
    for t in [t for t in as_list(summary.get("target_modules")) if isinstance(t, str)]:
        if t in designed_ids and t not in landed:
            return False
    return True


def _honesty_ok(body):
    for m in designed_modules(body):
        entries = [e for e in as_list(m.get("self_challenge")) if isinstance(e, dict)]
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
        if any(isinstance(t, dict) and not nonempty_str(t.get("cost"))
               for t in as_list(m.get("tradeoffs"))):
            return False
        fmea = as_list(m.get("fmea"))
        if m.get("design_mode") == "detail" and not fmea:
            return False
        if m.get("design_mode") == "brief" and fmea:
            return False
    return True


def compute_gates(art, residuals):
    """按 deliverable_kind 算五个门禁,返回 ({五布尔}, 明细)。"""
    body = body_of(art)
    kind = kind_of(art)
    details = []

    if kind != "module_designs":
        return ({k: False for k in GATE_KEYS}, [f"未知 deliverable_kind {kind!r}"])

    complete = _modules_complete_ok(body)
    if not complete:
        details.append("目标模块:设计齐全/组件/流程/DFX 检查未过")
    conform = _structure_ok(body)
    if not conform:
        details.append("边界守恒:依赖/数据/暴露/组件 检查未过")
    mapped = _mapping_ok(body)
    if not mapped:
        details.append("覆盖:upstream_items 分母与映射对账未过")
    honest = _honesty_ok(body)
    if not honest:
        details.append("诚实:自查 7 维/取舍代价/FMEA 按深度 检查未过")
    cross = _cross_ok(body)
    if not cross:
        details.append("交互:承接声明与参与方检查未过")

    return ({"modules_complete": complete, "deps_within_architecture": conform,
             "upstream_mapped": mapped, "findings_disposed": honest,
             "cross_consistent": cross}, details)


# ---------- R1-R4 / R9-R13(与家族同构) ----------

def semantic_rules(state, artifacts, errs):
    """R1-R4:schema 表达不了(或没表达)的状态机硬约束。"""
    ledgers = [("state.json $.evidence", state.get("evidence", []))] if state else []
    for name, art in artifacts:
        ledgers.append((f"{name} $.evidence", art.get("evidence", [])))
    for path, entries in ledgers:
        for i, e in enumerate(entries):
            if isinstance(e, dict) and e.get("type") in ("FACT", "DECISION", "INFERENCE"):
                ev = e.get("evidence")
                hint = {
                    "FACT": "架构产物 §x / .pev/<轮次>/ 家族产物 / 代码路径",
                    "DECISION": "拍板/精修锚点,如 01-artifact decisions#d2",
                    "INFERENCE": "推理依据:引用了哪些架构 FACT/数据",
                }[e["type"]]
                if not isinstance(ev, str) or not ev.strip():
                    errs.add("", f"{path}[{i}]",
                             f"R1: type={e['type']} 的条目必须有非空 evidence({hint});"
                             "无证据请标 HYPOTHESIS/UNKNOWN")

    for name, art in artifacts:
        if art.get("status") in ("replan_required", "blocked"):
            reason = art.get("replan_reason")
            if not isinstance(reason, dict) or not reason:
                errs.add(name, "$.replan_reason", "R2: status 为 replan_required/blocked 时必须填写 replan_reason")

    if state:
        status = state.get("status")
        resume = state.get("resume_to")
        if status == "WAITING_FOR_INPUT" and resume not in RESUME_STAGES:
            errs.add("state.json", "$.resume_to", "R3: status=WAITING_FOR_INPUT 时必须写 resume_to(PLANNING/EXECUTING/VERIFYING)")
        if status != "WAITING_FOR_INPUT" and resume is not None:
            errs.add("state.json", "$.resume_to", "R3: 仅 WAITING_FOR_INPUT 状态允许携带 resume_to,恢复后应清除")

        gaps = state.get("upstream_gaps")
        if status == "WAITING_FOR_UPSTREAM" and (not isinstance(gaps, list) or len(gaps) == 0):
            errs.add("state.json", "$.upstream_gaps", "R4: status=WAITING_FOR_UPSTREAM 时必须携带非空 upstream_gaps(回架构的缺口清单)")
        if status != "WAITING_FOR_UPSTREAM" and isinstance(gaps, list) and len(gaps) > 0:
            errs.add("state.json", "$.upstream_gaps", "R4: 仅 WAITING_FOR_UPSTREAM 状态允许携带非空 upstream_gaps,架构更新恢复后应清空")

        # R15 — COMPLETE 与用户确认记录互相锁定(consolidate T2-2):
        # PASS 渲染后等用户确认期间停在 VERIFYING;未确认的 COMPLETE 不得让下游开始
        conf = state.get("user_confirmation")
        has_conf = isinstance(conf, dict) and isinstance(conf.get("date"), str) and conf.get("date").strip()
        if status == "COMPLETE" and not has_conf:
            errs.add("state.json", "$.user_confirmation",
                     "R15: status=COMPLETE 但缺少用户确认记录 user_confirmation(date)——PASS 渲染后须等用户确认,未确认前停在 VERIFYING")
        if status != "COMPLETE" and conf is not None:
            errs.add("state.json", "$.user_confirmation",
                     "R15: user_confirmation 仅在 status=COMPLETE 时允许存在;确认即置 COMPLETE,等待确认期间停在 VERIFYING")


def normalize_text(value):
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def sha256_hex(value):
    return "sha256:" + hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def find_project_root(pev_dir):
    current = Path(pev_dir).resolve()
    for candidate in [current, *current.parents]:
        if candidate.name == ".pev":
            return candidate.parent
    return None


def iter_string_paths(value, prefix="$"):
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


def upstream_item_ids_of(art):
    body = body_of(art)
    items = as_list((body.get("input_summary") or {}).get("upstream_items"))
    return {u.get("id") for u in items if isinstance(u, dict) and isinstance(u.get("id"), str)}


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
                     "R12: finding 必须携带非空 affected_upstream_items(否则 REVISE 无法定位卡住的模块条目)")
        for uid in affected:
            if not isinstance(uid, str) or not uid.strip():
                errs.add(name, f"{base}.affected_upstream_items", "R12: 受影响上游条目 id 非法")
            elif valid_ids and uid not in valid_ids:
                errs.add(name, f"{base}.affected_upstream_items",
                         f"R12: 引用未声明的上游条目 {uid!r}(声明过的: {sorted(valid_ids)})")


def check_cross_findings(doc, designed_ids, name, errs):
    """cross_review.findings 的 affected_modules 必须回指设计过的模块。"""
    cross = doc.get("cross_review")
    if not isinstance(cross, dict):
        return
    for i, f in enumerate(as_list(cross.get("findings"))):
        if not isinstance(f, dict):
            continue
        base = f"$.cross_review.findings[{i}]"
        mods = as_list(f.get("affected_modules"))
        if not mods:
            errs.add(name, base, "R12: Cross 发现必须携带非空 affected_modules")
        for mid in mods:
            if designed_ids and mid not in designed_ids:
                errs.add(name, f"{base}.affected_modules",
                         f"R12: Cross 发现引用未设计过的模块 {mid!r}(设计过的: {sorted(designed_ids)})")


def load_redline_library():
    """库缺失、不可解析或 redlines 非非空数组 → 一律 None(调用方必须拒绝)。"""
    path = REDLINES_DIR / "module-redlines.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    redlines = data.get("redlines") if isinstance(data, dict) else None
    if not isinstance(redlines, list) or not redlines:
        return None
    return redlines


def check_redlines(doc, name, errs):
    """R13 — 红线全覆盖:报告必须逐条说明库中每条红线是否适用及依据。

    库缺失/损坏、报告缺红线部分、漏写库中任一条:一律拒绝,红线检查不可
    静默跳过(consolidate T2-1)。条目级:适用红线未通过不得判 PASS
    (红线独立于评分)。
    """
    library = load_redline_library()
    if library is None:
        errs.add("redlines/module-redlines.json", "$",
                 "R13: 红线库缺失或内容损坏,无法核对红线覆盖;修复库文件后重跑校验")
        return
    known = {r.get("id") for r in library if isinstance(r, dict)}
    raw = doc.get("redlines")
    if not as_list(raw):
        errs.add(name, "$.redlines",
                 "R13: 报告缺少红线部分——每条库中红线必须逐条说明是否适用及依据")
        return
    redlines = [r for r in as_list(raw) if isinstance(r, dict)]
    covered = {r.get("id") for r in redlines}
    for rid in sorted(known - covered, key=str):
        errs.add(name, "$.redlines",
                 f"R13: 库中红线 {rid!r} 未在报告中说明(漏写)")
    verdict = doc.get("verdict")
    for i, r in enumerate(redlines):
        base = f"$.redlines[{i}]"
        rid = r.get("id")
        if not nonempty_str(rid):
            errs.add(name, base, "R13: 红线缺少 id")
            continue
        if rid not in known:
            errs.add(name, f"{base}.id", f"R13: 红线 {rid!r} 不在红线库中(可用: {sorted(known, key=str)})")
        if not nonempty_str(r.get("details")):
            errs.add(name, f"{base}.details", "R13: 红线必须写 details(为什么适用/不适用、结论依据)")
        if r.get("applies") is True:
            passed = r.get("passed")
            if not isinstance(passed, bool):
                errs.add(name, f"{base}.passed", "R13: 适用红线(applies=true)必须显式写 passed 布尔")
            elif passed is False and verdict == "PASS":
                errs.add(name, f"{base}.passed",
                         f"R13: 适用红线 {rid} 未通过却判 verdict=PASS——红线独立于评分,任一适用红线不过不得 PASS")


def check_module_reviews(doc, target_ids, designed_ids, name, errs):
    """R14 — module_reviews 覆盖与引用合法。"""
    reviews = [r for r in as_list(doc.get("module_reviews")) if isinstance(r, dict)]
    reviewed = {r.get("module_id") for r in reviews}
    for i, r in enumerate(reviews):
        if r.get("module_id") not in designed_ids:
            errs.add(name, f"$.module_reviews[{i}].module_id",
                     f"R14: 评审了未设计过的模块 {r.get('module_id')!r}(设计过的: {sorted(designed_ids)})")
    missing = sorted(set(target_ids) - reviewed)
    if missing:
        errs.add(name, "$.module_reviews",
                 f"R14: 目标模块 {missing} 未被逐模块评审——一个都不能少")


def main(argv):
    if len(argv) < 2:
        print("用法: python3 validate.py <PEV_DIR>   # 如 .pev/prd-2026-09-20/module/")
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

    # R5/R7/R8 — 守恒/覆盖/诚实:错误进 errs,门禁布尔留给对账
    residuals = []
    for name, art in artifacts:
        check_no_placeholders(art, name, errs)
        body, kind = body_of(art), kind_of(art)
        if kind == "module_designs":
            check_conformance(body, name, errs, residuals)
            check_mapping(body, name, errs)
            check_self_challenge(body, name, errs)
            check_tradeoff_cost(body, name, errs)
        else:
            errs.add(name, "$.artifact.deliverable_kind",
                     f"未知 deliverable_kind {kind!r}")

    # R6/R14 — 门禁照抄;PASS 必须全绿 + 逐模块全过 + Cross 通过
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
        art = entry[1]
        gates, _details = compute_gates(art, residuals)
        body = body_of(art)
        target_ids = {t for t in as_list((body.get("input_summary") or {}).get("target_modules"))
                      if isinstance(t, str)}
        designed_ids = {m.get("id") for m in designed_modules(body)
                        if isinstance(m.get("id"), str)}

        check_module_reviews(doc, target_ids, designed_ids, name, errs)
        check_cross_findings(doc, designed_ids, name, errs)

        if doc.get("verdict") == "PASS":
            failed_gates = [k for k, v in gates.items() if not v]
            if failed_gates:
                errs.add(name, "$.verdict",
                         f"R14: verdict=PASS 但门禁未全绿({failed_gates})——应判 REVISE 并修复,不得 PASS")
            bad_reviews = [r.get("module_id") for r in as_list(doc.get("module_reviews"))
                           if isinstance(r, dict) and r.get("verdict") != "PASS"]
            if bad_reviews:
                errs.add(name, "$.module_reviews",
                         f"R14: verdict=PASS 但模块 {bad_reviews} 评审为 REVISE——整体 PASS 要求逐模块全过")
            cross = doc.get("cross_review")
            if not (isinstance(cross, dict) and cross.get("verdict") == "pass"):
                errs.add(name, "$.cross_review.verdict",
                         "R14: verdict=PASS 但 cross_review.verdict≠pass——Cross 未通过不得整体 PASS")
        check_finding_trace(doc, art, name, errs)
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
        keys = " ".join(f"{k}={gates[k]}" for k in GATE_KEYS)
        print(f"门禁(脚本计算,最新迭代):{keys} PASS 前置(全绿):{'通过' if gate_ok else '未通过'}")
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
