#!/usr/bin/env python3
"""database-schema-design PEV 产物校验器(双端通用,仅依赖 Python 标准库)。

用法:
    python3 validate.py <PEV_DIR>      # PEV_DIR 为本 skill 工作目录,如 .pev/prd-2026-09-20/db/

按文件名后缀路由到 schemas/ 下对应 schema:
    state.json                    -> state.schema.json
    iterations/*-plan.json        -> plan.schema.json
    iterations/*-artifact.json    -> artifact.schema.json
    iterations/*-verification.json-> verification.schema.json

除 JSON Schema 子集(type/enum/required/properties/items/minItems/
minimum/maximum)外,强制以下语义规则——这些是状态机的硬约束,靠肉眼最容易漏:
    R1  Evidence 条目 type=FACT/DECISION 时 evidence 必须是非空字符串
        (FACT 证据=上游产物 §x / .pev/<轮次>/ 家族产物 / 代码与 DDL 路径;
        DECISION 证据=拍板/精修锚点)。INFERENCE 同样必须带非空推理依据;
        三者缺证据 → 报错。HYPOTHESIS/UNKNOWN 允许 evidence 为 null。
    R2  artifact.status ∈ {replan_required, blocked} 时,replan_reason 必填
    R3  state.status=WAITING_FOR_INPUT 时,resume_to 必填;
        其他 status 下 resume_to 必须不存在
    R4  state.status=WAITING_FOR_UPSTREAM 时,upstream_gaps 必须非空;
        其他 status 下 upstream_gaps 必须为空
    R5  实体守恒与结构(db_schemas kind,全部对照 upstream_snapshot;一个
        项目可一库或多库):
        - 库 id 全局唯一;目标数据库(target_stores)个个有设计;
        - covered_entities 每条 ∈ 上游快照任一模块的 owns_data——越界即报错;
        - access_patterns ≥1 且 id 库内唯一;
        - tables id 库内唯一,name/purpose 非空,entity 引用本库
          covered_entities;关系型每表 pk/columns/constraints 非空,mongodb
          每集合 document_shape/validator 非空;
        - indexes 的 table 引用本库表 id、serves 引用本库 access_patterns id
          (无依据索引不许入库);denormalization 的 serves 同理;
        - evolution 非空(strategy+compat_rules);
        - 每库 environment.dialect_version 与 scale 非空(方言显式);
        - data_flow_commitments.interaction 引用快照交互 id,且本库承接实体
          的归属模块是该交互的参与方(from/to)。
    R6  门禁布尔照抄脚本:评审落点 state.status ∈ {VERIFYING, COMPLETE} 时,
        verification.gates 五值与脚本计算逐位比对,不一致整份打回
    R7  覆盖对账:承接的实体必须逐条进 upstream_items(分母造假直接报错);
        承接的交互 id 必须进 upstream_items;声明的条目必须落在快照内;
        upstream_mapping 引用合法;每条 upstream_item 被映射 ≥1 次;
        每个目标库至少有一条落点。
    R8  诚实门:self_challenge 7 维全齐且处置合法(accepted_risk 必须带理由);
        tradeoffs 全部 cost 非空;db_review kind 的 review_findings 同理
        (7 维全齐、非空 finding 带 severity+锚点、空 finding 标 NONE)。
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
    R13 红线库:redlines 须逐条处置(整块缺省、漏掉库中红线、id 重复即报错);
        红线 id 必须在红线库中;适用红线(applies=true)未通过(passed=false)时
        不得判 PASS——红线独立于评分。
    R14 verdict=PASS 的硬前提(缺一报错):
        - store_reviews 覆盖全部目标库且逐个 verdict=PASS;
        - cross_review.verdict=pass;
        - 五个门禁全绿。
        store_reviews[].store_id 必须引用设计过的库 id。
    R15 state.status ∈ {VERIFYING, COMPLETE} 时,state.cross 必须存在
        (整体停在 VERIFYING 直到 Cross 通过;cross 缺失无法证明 Cross 状态)
    R16 state↔产物对账(两边不许各说各话):
        - mode=review 时 stores 必须置空,mode=design 时必须非空;
          mode=review ↔ upstream_kind=schema_doc;
          mode=design 时 upstream_kind ∈ {module_design, architecture,
          module_doc, schema_request};
        - state.status ∈ {VERIFYING, COMPLETE} 时:design_status 全部 done;
          最新 artifact 的 deliverable_kind 与 mode 对应,db_schemas 的
          target_stores 与 state.stores[] 一致;
        - COMPLETE 收口:cross.status=passed 且逐库 review_status=pass;
        - 存在最新 verification 时:state 的 review_status/cross.status 与
          verification 的 store_reviews.verdict/cross_review.verdict 按
          映射一致(pass↔PASS、revise↔REVISE、passed↔pass、revise_required↔revise)。

五个门禁的布尔(db_schemas kind):
    stores_complete            —— 目标数据库个个有设计,且每库有 ≥1 表、
                                  ≥1 承接实体、≥1 access pattern
    entities_within_upstream   —— R5 守恒与引用检查(实体归属/实体/表/索引/
                                  denorm/数据流引用)
    upstream_mapped            —— R7 对账过且 upstream_items 非空
    findings_disposed          —— R8 过 + 表结构形状(关系型 pk/columns/constraints,
                                  mongodb document_shape/validator)+ evolution 非空
    cross_consistent           —— R5 数据流承接检查全部通过

通过时汇总输出:最新迭代的五门禁结论,以及交 Verifier 逐条处置的残留清单
(承接实体归属模块参与且声明了幂等/一致性、却无任何 schema 承接的快照交互)。

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

# 对抗 7 维(与 rubrics/db-review.md 一致)
ADVERSARIAL_DIMS = ("failure_modes", "consistency", "concurrency",
                    "boundary_erosion", "misuse_potential", "compatibility",
                    "simpler_alternative")

GATE_KEYS = ("stores_complete", "entities_within_upstream",
             "upstream_mapped", "findings_disposed", "cross_consistent")

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
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        errs.add(path.name, "$", f"无法读取/解析 JSON(须 UTF-8): {e}")
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
    snap = (body.get("input_summary") or {}).get("upstream_snapshot")
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


def snap_entity_owners(body):
    """实体文本 → 归属模块 id(实体可来自多个模块,守恒以此为基准)。"""
    out = {}
    for mid, m in snap_modules(body).items():
        for e in as_list(m.get("owns_data")):
            if isinstance(e, str):
                out[e] = mid
    return out


def designed_stores(body):
    return [c for c in as_list(body.get("stores")) if isinstance(c, dict)]


def check_conformance(body, file, errs, residuals):
    """R5 — 实体守恒与结构:全部对照 upstream_snapshot(一库或多库均可)。"""
    snap_i = snap_interactions(body)
    ent_owners = snap_entity_owners(body)
    target = [t for t in as_list((body.get("input_summary") or {}).get("target_stores"))
              if isinstance(t, str)]

    designed_ids = {c.get("id") for c in designed_stores(body)
                    if isinstance(c.get("id"), str)}
    id_list = [c.get("id") for c in designed_stores(body)]
    dup_sids = sorted({i for i in id_list if isinstance(i, str) and id_list.count(i) > 1})
    if dup_sids:
        errs.add(file, "$.artifact.stores",
                 f"R5: 库 id 重复 {dup_sids}——id 是评审与对账的定位键,全局唯一")
    for t in target:
        if t not in designed_ids:
            errs.add(file, "$.artifact.input_summary.target_stores",
                     f"R5: 目标数据库 {t!r} 没有对应设计——目标数据库一个都不能少")
    extra_faces = sorted(d for d in designed_ids if d not in set(target))
    if extra_faces:
        errs.add(file, "$.artifact.stores",
                 f"R5: 设计了目标外的数据库 {extra_faces}——目标库集在 INIT 定齐,"
                 "增库须先记 DECISION 并同步 state.stores 与 target_stores")

    committed_any = set()
    all_store_owners = set()
    for c in designed_stores(body):
        cid = c.get("id")
        kind = c.get("kind")
        base = f"$.artifact.stores[{cid}]"

        # 实体守恒:承接实体 ∈ 上游任一模块的 owns_data
        ents = [x for x in as_list(c.get("covered_entities")) if isinstance(x, str)]
        extra = sorted(e for e in ents if e not in ent_owners)
        if extra:
            errs.add(file, f"{base}.covered_entities",
                     f"R5: 承接了上游声明外的实体 {extra}——要存新数据是上游层缺口,"
                     "走三选一,不在 schema 层私自扩边")
        if not ents:
            errs.add(file, f"{base}.covered_entities",
                     "R5: 数据库必须承接 ≥1 条上游数据实体——零承接的库是画的不是设计的")
        store_owners = {ent_owners[e] for e in ents if e in ent_owners}
        all_store_owners |= store_owners

        # 环境门槛:方言与规模显式
        env = c.get("environment")
        if not isinstance(env, dict) or not nonempty_str(env.get("dialect_version")):
            errs.add(file, f"{base}.environment.dialect_version",
                     "R5: 库必须显式声明 dialect_version——「通用 SQL」不存在,特性差异决定设计")
        if not isinstance(env, dict) or not nonempty_str(env.get("scale")):
            errs.add(file, f"{base}.environment.scale",
                     "R5: 库必须显式声明 scale(行数量级/增长/读写比)——规模决定索引与分区策略")

        # access patterns(索引与 denorm 的依据分母)
        aps = [a for a in as_list(c.get("access_patterns")) if isinstance(a, dict)]
        ap_ids = [a.get("id") for a in aps if isinstance(a.get("id"), str)]
        if not aps:
            errs.add(file, f"{base}.access_patterns",
                     "R5: 库必须声明 ≥1 条 access pattern——schema 为 access pattern 服务,无依据即无设计")
        dup_ap = sorted({a for a in ap_ids if ap_ids.count(a) > 1})
        if dup_ap:
            errs.add(file, f"{base}.access_patterns", f"R5: access pattern id 重复 {dup_ap}")

        # 表结构
        tables = [t for t in as_list(c.get("tables")) if isinstance(t, dict)]
        tids = [t.get("id") for t in tables if isinstance(t.get("id"), str)]
        dup = sorted({t for t in tids if tids.count(t) > 1})
        if dup:
            errs.add(file, f"{base}.tables", f"R5: 表 id 重复 {dup}")
        for i, t in enumerate(tables):
            for field in ("name", "purpose"):
                if not nonempty_str(t.get(field)):
                    label = {"name": "表名", "purpose": "目的陈述"}[field]
                    errs.add(file, f"{base}.tables[{i}].{field}",
                             f"R5: 表 {t.get('id')!r} 的 {field} 为空——表必须有{label}")
            if t.get("entity") not in ents:
                errs.add(file, f"{base}.tables[{i}].entity",
                         f"R5: 表 {t.get('id')!r} 的 entity {t.get('entity')!r} 不在本库 covered_entities 中(可用: {sorted(ents)})——写不出实体背书的表该删")
            if kind == "mongodb":
                if not nonempty_str(t.get("document_shape")):
                    errs.add(file, f"{base}.tables[{i}].document_shape",
                             "R5: MongoDB 集合必须写 document_shape(文档字段结构 + embed/reference 决策)——列不出文档形状的集合是空话")
                if not nonempty_str(t.get("validator")):
                    errs.add(file, f"{base}.tables[{i}].validator",
                             "R5: MongoDB 集合必须写 validator($jsonSchema + validationLevel)——schema-less 不等于无约束")
            else:
                if not nonempty_str(t.get("pk")):
                    errs.add(file, f"{base}.tables[{i}].pk",
                             "R5: 表必须有主键策略(含 WHY)——主键决定聚簇与分布")
                if not nonempty_str(t.get("columns")):
                    errs.add(file, f"{base}.tables[{i}].columns",
                             "R5: 表的 columns 必须非空——没有列级定义的 schema 是空话")
                if not nonempty_str(t.get("constraints")):
                    errs.add(file, f"{base}.tables[{i}].constraints",
                             "R5: 表的 constraints 必须非空——完整性约束要进数据库(FK/UNIQUE/CHECK/NOT NULL 与 ON DELETE)")

        # 索引与 denorm 依据
        for i, ix in enumerate(as_list(c.get("indexes"))):
            if not isinstance(ix, dict):
                continue
            if ix.get("table") not in tids:
                errs.add(file, f"{base}.indexes[{i}].table",
                         f"R5: 索引 {ix.get('id')!r} 的 table {ix.get('table')!r} 不在本库表 id 中(可用: {sorted(tid for tid in tids if isinstance(tid, str))})")
            if ix.get("serves") not in ap_ids:
                errs.add(file, f"{base}.indexes[{i}].serves",
                         f"R5: 索引 {ix.get('id')!r} 的 serves {ix.get('serves')!r} 不在本库 access_patterns 中(可用: {sorted(ap_ids)})——无依据索引不许入库")
        for i, dn in enumerate(as_list(c.get("denormalization"))):
            if not isinstance(dn, dict):
                continue
            if dn.get("serves") not in ap_ids:
                errs.add(file, f"{base}.denormalization[{i}].serves",
                         f"R5: denorm {dn.get('what')!r} 的 serves {dn.get('serves')!r} 不在本库 access_patterns 中——无对应查询的 denorm 是纯负债")

        # 演进策略
        evo = c.get("evolution")
        if not isinstance(evo, dict) or not nonempty_str(evo.get("strategy")) or not nonempty_str(evo.get("compat_rules")):
            errs.add(file, f"{base}.evolution",
                     "R5: evolution 必须非空且落到 strategy + 兼容规则——没有演进交代的 schema 是定时炸弹")

        # 数据流承接
        for i, ic in enumerate(as_list(c.get("data_flow_commitments"))):
            if not isinstance(ic, dict):
                continue
            iid = ic.get("interaction")
            it = snap_i.get(iid)
            if it is None:
                errs.add(file, f"{base}.data_flow_commitments[{i}].interaction",
                         f"R5: 承接的交互 {iid!r} 不在上游快照交互中(可用: {sorted(snap_i)})")
                continue
            if not (store_owners & {it.get("from"), it.get("to")}):
                errs.add(file, f"{base}.data_flow_commitments[{i}].interaction",
                         f"R5: 本库承接实体归属模块 {sorted(store_owners)} 都不是交互 {iid}"
                         f"({it.get('from')}→{it.get('to')})的参与方——不能替别人认领")
            committed_any.add(iid)

    # 残留:承接实体归属模块参与且声明了幂等/一致性、却无任何 schema 承接的快照交互(交 Verifier 审)
    for iid, it in sorted(snap_i.items()):
        parties = {it.get("from"), it.get("to")} & all_store_owners
        if not parties:
            continue
        demands_persistence = nonempty_str(it.get("idempotency")) or nonempty_str(it.get("consistency"))
        if demands_persistence and iid not in committed_any:
            residuals.append(
                f"上游声明交互 {iid}({it.get('from')}→{it.get('to')})带幂等/一致性要求,"
                f"参与方 {sorted(parties)} 的实体已落库,但无任何 schema 承接该交互"
                "(如 outbox/去重唯一键;交 Verifier 处置)")


def check_mapping(body, file, errs):
    """R7 — 分母完备(承接的实体/交互逐条进 upstream_items)+ 映射双向对账。"""
    summary = body.get("input_summary") or {}
    items = [u for u in as_list(summary.get("upstream_items")) if isinstance(u, dict)]
    item_ids = {u.get("id") for u in items if isinstance(u.get("id"), str)}
    item_texts = {u.get("item") for u in items if isinstance(u.get("item"), str)}

    snap_m = snap_modules(body)
    snap_i = snap_interactions(body)
    all_owns = set()
    for arch in snap_m.values():
        all_owns |= {e for e in as_list(arch.get("owns_data")) if isinstance(e, str)}

    # 声明的条目必须落在快照内(实体按文本、交互按 id)
    for u in items:
        uid, text = u.get("id"), u.get("item")
        if isinstance(uid, str) and uid in snap_i:
            continue  # 交互条目,以 id 对账
        if isinstance(text, str) and text in all_owns:
            continue  # 实体条目,以文本对账
        errs.add(file, "$.artifact.input_summary.upstream_items",
                 f"R7: 条目 {uid!r}({text!r})不在上游快照(实体文本/交互 id)中——不能凭空造分母")

    # 承接的实体与交互必须逐条进分母
    for c in designed_stores(body):
        cid = c.get("id")
        for ent in as_list(c.get("covered_entities")):
            if isinstance(ent, str) and ent not in item_texts:
                errs.add(file, "$.artifact.input_summary.upstream_items",
                         f"R7: 库 {cid} 承接实体 {ent!r} 但 upstream_items 未声明——分母不全,覆盖检查失效")
        for ic in as_list(c.get("data_flow_commitments")):
            if isinstance(ic, dict) and ic.get("interaction") not in item_ids:
                errs.add(file, "$.artifact.input_summary.upstream_items",
                         f"R7: 库 {cid} 承接交互 {ic.get('interaction')!r} 但 upstream_items 未声明——分母不全,覆盖检查失效")

    designed_ids = {c.get("id") for c in designed_stores(body)
                    if isinstance(c.get("id"), str)}
    mapped = set()
    landed = set()
    for i, mp in enumerate(as_list(body.get("upstream_mapping"))):
        if not isinstance(mp, dict):
            continue
        u, m = mp.get("upstream_item"), mp.get("store_id")
        if u not in item_ids:
            errs.add(file, f"$.artifact.upstream_mapping[{i}].upstream_item",
                     f"R7: 引用了未声明的上游条目 {u!r}")
        if designed_ids and m not in designed_ids:
            errs.add(file, f"$.artifact.upstream_mapping[{i}].store_id",
                     f"R7: 落点 {m!r} 不是设计过的库 id")
        mapped.add(u)
        landed.add(m)

    missing = sorted(i for i in item_ids if i not in mapped)
    if missing:
        errs.add(file, "$.artifact.upstream_mapping",
                 f"R7: 上游条目 {missing} 声明了却无落点——要么补映射,要么从 upstream_items 删除(并交 Verifier 审删除理由)")
    target = [t for t in as_list(summary.get("target_stores")) if isinstance(t, str)]
    for t in target:
        if t in designed_ids and t not in landed:
            errs.add(file, "$.artifact.upstream_mapping",
                     f"R7: 目标数据库 {t} 没有任何落点条目——承接对账没有记录")


def check_self_challenge(body, file, errs):
    """R8 — 每库 7 维全齐、处置合法、accepted_risk 有理由。"""
    for c in designed_stores(body):
        cid = c.get("id")
        entries = [e for e in as_list(c.get("self_challenge")) if isinstance(e, dict)]
        covered = {e.get("dimension") for e in entries if isinstance(e.get("dimension"), str)}
        missing = [d for d in ADVERSARIAL_DIMS if d not in covered]
        if missing:
            errs.add(file, f"$.artifact.stores[{cid}].self_challenge",
                     f"R8: 库 {cid} 自查缺少维度 {missing}——7 维必须逐维占位,无发现也要写空 finding 证明扫过")
        for i, e in enumerate(entries):
            finding, disp = e.get("finding"), e.get("disposition")
            empty = not nonempty_str(finding)
            if empty and disp != "none":
                errs.add(file, f"$.artifact.stores[{cid}].self_challenge[{i}]",
                         "R8: finding 为空时 disposition 只能是 none")
            if not empty and disp not in ("fixed", "accepted_risk"):
                errs.add(file, f"$.artifact.stores[{cid}].self_challenge[{i}]",
                         "R8: 有发现必须处置(fixed / accepted_risk),不许悬空")
            if disp == "accepted_risk" and not nonempty_str(e.get("rationale")):
                errs.add(file, f"$.artifact.stores[{cid}].self_challenge[{i}].rationale",
                         "R8: 接受风险必须写理由——没有理由的接受是遗忘,不是决策")


def check_tradeoff_cost(body, file, errs):
    for c in designed_stores(body):
        cid = c.get("id")
        for i, t in enumerate(as_list(c.get("tradeoffs"))):
            if isinstance(t, dict) and not nonempty_str(t.get("cost")):
                errs.add(file, f"$.artifact.stores[{cid}].tradeoffs[{i}].cost",
                         "R8: 取舍缺代价——不说放弃什么的取舍不是取舍")


def check_review_findings(body, file, errs):
    """R8 诚实门(db_review)—— 7 维全齐、非空 finding 带 severity+锚点、空 finding 标 NONE。"""
    findings = [f for f in as_list(body.get("review_findings")) if isinstance(f, dict)]
    covered = {f.get("dimension") for f in findings if isinstance(f.get("dimension"), str)}
    missing = [d for d in ADVERSARIAL_DIMS if d not in covered]
    if missing:
        errs.add(file, "$.artifact.review_findings",
                 f"R8: 评审缺少维度 {missing}——7 维必须逐维占位,无发现也要写空 finding 证明扫过")
    for i, f in enumerate(findings):
        empty = not nonempty_str(f.get("finding"))
        if empty and f.get("severity") != "NONE":
            errs.add(file, f"$.artifact.review_findings[{i}].severity",
                     "R8: finding 为空时 severity 只能 NONE")
        if not empty:
            if f.get("severity") == "NONE":
                errs.add(file, f"$.artifact.review_findings[{i}].severity",
                         "R8: 非空 finding 不得标 NONE(有发现就应给 LOW/MEDIUM/HIGH/BLOCKING)")
            if not nonempty_str(f.get("evidence_anchor")):
                errs.add(file, f"$.artifact.review_findings[{i}].evidence_anchor",
                         "R8: 非空 finding 必须带 evidence_anchor(被评审 schema 的 §位置/表 id/列名)——锚不到位置的发现只是意见")


# ---------- 门禁计算(无副作用版本,与上面检查保持同一判据) ----------

def _store_shape_ok(kind, t):
    """表级结构形状按 kind 分支:关系型要求 pk/columns/constraints,MongoDB 要求 document_shape/validator。"""
    if kind == "mongodb":
        return nonempty_str(t.get("document_shape")) and nonempty_str(t.get("validator"))
    return (nonempty_str(t.get("pk")) and nonempty_str(t.get("columns"))
            and nonempty_str(t.get("constraints")))


def _structure_ok(body):
    str_ids = [i for i in (c.get("id") for c in designed_stores(body))
               if isinstance(i, str)]
    if len(str_ids) != len(set(str_ids)):
        return False
    ent_owners = snap_entity_owners(body)
    for c in designed_stores(body):
        ents = [x for x in as_list(c.get("covered_entities")) if isinstance(x, str)]
        if not ents or any(e not in ent_owners for e in ents):
            return False
        env = c.get("environment")
        if not (isinstance(env, dict) and nonempty_str(env.get("dialect_version"))
                and nonempty_str(env.get("scale"))):
            return False
        aps = [a for a in as_list(c.get("access_patterns")) if isinstance(a, dict)]
        ap_ids = [a.get("id") for a in aps if isinstance(a.get("id"), str)]
        if not aps or len(ap_ids) != len(set(ap_ids)):
            return False
        tables = [t for t in as_list(c.get("tables")) if isinstance(t, dict)]
        tids = [t.get("id") for t in tables]
        if len(tids) != len(set(tids)):
            return False
        for t in tables:
            if not (nonempty_str(t.get("name")) and nonempty_str(t.get("purpose"))
                    and _store_shape_ok(c.get("kind"), t)):
                return False
            if t.get("entity") not in ents:
                return False
        for ix in as_list(c.get("indexes")):
            if not isinstance(ix, dict):
                return False
            if ix.get("table") not in tids or ix.get("serves") not in ap_ids:
                return False
        for dn in as_list(c.get("denormalization")):
            if not isinstance(dn, dict):
                return False
            if dn.get("serves") not in ap_ids:
                return False
        evo = c.get("evolution")
        if not (isinstance(evo, dict) and nonempty_str(evo.get("strategy"))
                and nonempty_str(evo.get("compat_rules"))):
            return False
    return True


def _cross_ok(body):
    ent_owners = snap_entity_owners(body)
    snap_i = snap_interactions(body)
    for c in designed_stores(body):
        ents = [x for x in as_list(c.get("covered_entities")) if isinstance(x, str)]
        store_owners = {ent_owners[e] for e in ents if e in ent_owners}
        for ic in as_list(c.get("data_flow_commitments")):
            if not isinstance(ic, dict):
                return False
            it = snap_i.get(ic.get("interaction"))
            if it is None or not (store_owners & {it.get("from"), it.get("to")}):
                return False
    return True


def _stores_complete_ok(body):
    target = [t for t in as_list((body.get("input_summary") or {}).get("target_stores"))
              if isinstance(t, str)]
    by_id = {c.get("id"): c for c in designed_stores(body) if isinstance(c.get("id"), str)}
    for t in target:
        c = by_id.get(t)
        if c is None:
            return False
        if not as_list(c.get("tables")):
            return False
        if not as_list(c.get("covered_entities")):
            return False
        if not as_list(c.get("access_patterns")):
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
    snap_i = snap_interactions(body)
    all_owns = set()
    for arch in snap_m.values():
        all_owns |= {e for e in as_list(arch.get("owns_data")) if isinstance(e, str)}
    for u in items:
        uid, text = u.get("id"), u.get("item")
        if not ((isinstance(uid, str) and uid in snap_i)
                or (isinstance(text, str) and text in all_owns)):
            return False
    for c in designed_stores(body):
        ents = {x for x in as_list(c.get("covered_entities")) if isinstance(x, str)}
        if any(ent not in item_texts for ent in ents):
            return False
        for ic in as_list(c.get("data_flow_commitments")):
            if isinstance(ic, dict) and ic.get("interaction") not in item_ids:
                return False
    designed_ids = {c.get("id") for c in designed_stores(body)
                    if isinstance(c.get("id"), str)}
    mapped, landed = set(), set()
    for mp in as_list(body.get("upstream_mapping")):
        if not isinstance(mp, dict):
            return False
        if mp.get("upstream_item") not in item_ids:
            return False
        if designed_ids and mp.get("store_id") not in designed_ids:
            return False
        mapped.add(mp.get("upstream_item"))
        landed.add(mp.get("store_id"))
    if not item_ids <= mapped:
        return False
    for t in [t for t in as_list(summary.get("target_stores")) if isinstance(t, str)]:
        if t in designed_ids and t not in landed:
            return False
    return True


def _honesty_ok(body):
    for c in designed_stores(body):
        entries = [e for e in as_list(c.get("self_challenge")) if isinstance(e, dict)]
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
               for t in as_list(c.get("tradeoffs"))):
            return False
        evo = c.get("evolution")
        if not (isinstance(evo, dict) and nonempty_str(evo.get("strategy"))
                and nonempty_str(evo.get("compat_rules"))):
            return False
        for t in as_list(c.get("tables")):
            if isinstance(t, dict) and not _store_shape_ok(c.get("kind"), t):
                return False
    return True


def _review_findings_ok(body):
    findings = [f for f in as_list(body.get("review_findings")) if isinstance(f, dict)]
    covered = {f.get("dimension") for f in findings}
    if any(d not in covered for d in ADVERSARIAL_DIMS):
        return False
    for f in findings:
        empty = not nonempty_str(f.get("finding"))
        if empty:
            if f.get("severity") != "NONE":
                return False
        else:
            if f.get("severity") == "NONE" or not nonempty_str(f.get("evidence_anchor")):
                return False
    return True


def compute_gates(art, residuals):
    """按 deliverable_kind 算五个门禁,返回 ({五布尔}, 明细)。"""
    body = body_of(art)
    kind = kind_of(art)
    details = []

    if kind == "db_review":
        honest = _review_findings_ok(body)
        if not honest:
            details.append("诚实:review_findings 7 维全齐/非空 finding 带 severity+锚点 检查未过")
        return ({"stores_complete": True, "entities_within_upstream": True,
                 "upstream_mapped": True, "findings_disposed": honest,
                 "cross_consistent": True}, details)

    if kind != "db_schemas":
        return ({k: False for k in GATE_KEYS}, [f"未知 deliverable_kind {kind!r}"])

    complete = _stores_complete_ok(body)
    if not complete:
        details.append("目标库:设计齐全/表/承接实体/access patterns 检查未过")
    conform = _structure_ok(body)
    if not conform:
        details.append("实体守恒:实体归属/表/索引依据/演进 检查未过")
    mapped = _mapping_ok(body)
    if not mapped:
        details.append("覆盖:upstream_items 分母与映射对账未过")
    honest = _honesty_ok(body)
    if not honest:
        details.append("诚实:自查 7 维/取舍代价/列与演进 检查未过")
    cross = _cross_ok(body)
    if not cross:
        details.append("数据流:承接声明与参与方检查未过")

    return ({"stores_complete": complete, "entities_within_upstream": conform,
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
                    "FACT": "上游产物 §x / .pev/<轮次>/ 家族产物 / 代码与 DDL 路径",
                    "DECISION": "拍板/精修锚点,如 01-artifact decisions#d2",
                    "INFERENCE": "推理依据:引用了哪些上游 FACT/数据",
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
            errs.add("state.json", "$.upstream_gaps", "R4: status=WAITING_FOR_UPSTREAM 时必须携带非空 upstream_gaps(回上游的缺口清单)")
        if status != "WAITING_FOR_UPSTREAM" and isinstance(gaps, list) and len(gaps) > 0:
            errs.add("state.json", "$.upstream_gaps", "R4: 仅 WAITING_FOR_UPSTREAM 状态允许携带非空 upstream_gaps,上游更新恢复后应清空")

        # R17 — COMPLETE 与用户确认记录互相锁定(consolidate T2-2):
        # PASS 渲染后等用户确认期间停在 VERIFYING;未确认的 COMPLETE 不得让下游开始
        conf = state.get("user_confirmation")
        has_conf = isinstance(conf, dict) and isinstance(conf.get("date"), str) and conf.get("date").strip()
        if status == "COMPLETE" and not has_conf:
            errs.add("state.json", "$.user_confirmation",
                     "R17: status=COMPLETE 但缺少用户确认记录 user_confirmation(date)——PASS 渲染后须等用户确认,未确认前停在 VERIFYING")
        if status != "COMPLETE" and conf is not None:
            errs.add("state.json", "$.user_confirmation",
                     "R17: user_confirmation 仅在 status=COMPLETE 时允许存在;确认即置 COMPLETE,等待确认期间停在 VERIFYING")

        if status in ("VERIFYING", "COMPLETE") and not isinstance(state.get("cross"), dict):
            errs.add("state.json", "$.cross",
                     "R15: status=VERIFYING/COMPLETE 时必须携带 cross(Cross 跨库一致性评审状态)")


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
    except (OSError, UnicodeError) as exc:
        errs.add("", f"{base}.source.path", f"R11: 证据来源不可读或非 UTF-8:{exc}")
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
                     "R12: finding 必须携带非空 affected_upstream_items(否则 REVISE 无法定位卡住的上游条目)")
        for uid in affected:
            if not isinstance(uid, str) or not uid.strip():
                errs.add(name, f"{base}.affected_upstream_items", "R12: 受影响上游条目 id 非法")
            elif valid_ids and uid not in valid_ids:
                errs.add(name, f"{base}.affected_upstream_items",
                         f"R12: 引用未声明的上游条目 {uid!r}(声明过的: {sorted(valid_ids)})")


def check_cross_findings(doc, designed_ids, name, errs):
    """cross_review.findings 的 affected_stores 必须回指设计过的库。"""
    cross = doc.get("cross_review")
    if not isinstance(cross, dict):
        return
    for i, f in enumerate(as_list(cross.get("findings"))):
        if not isinstance(f, dict):
            continue
        base = f"$.cross_review.findings[{i}]"
        mods = as_list(f.get("affected_stores"))
        if not mods:
            errs.add(name, base, "R12: Cross 发现必须携带非空 affected_stores")
        for mid in mods:
            if designed_ids and mid not in designed_ids:
                errs.add(name, f"{base}.affected_stores",
                         f"R12: Cross 发现引用未设计过的库 {mid!r}(设计过的: {sorted(designed_ids)})")


def load_redline_library():
    path = REDLINES_DIR / "db-redlines.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return as_list(data.get("redlines"))


def check_redlines(doc, name, errs):
    """R13 — 红线库:红线 id 必须在库中;适用红线未通过不得判 PASS(红线独立于评分)。"""
    redlines = as_list(doc.get("redlines"))
    if not redlines:
        errs.add(name, "$.redlines",
                 "R13: redlines 整块缺省——红线须对照红线库逐条处置,不得不写")
        return
    library = load_redline_library()
    known = {r.get("id") for r in library} if library is not None else None
    seen_ids = [r.get("id") for r in redlines
                if isinstance(r, dict) and nonempty_str(r.get("id"))]
    dup_rids = sorted({i for i in seen_ids if seen_ids.count(i) > 1})
    if dup_rids:
        errs.add(name, "$.redlines",
                 f"R13: 红线 id 重复 {dup_rids}——逐条处置,一条记录一条红线")
    if known is not None:
        missing_red = sorted(known - set(seen_ids))
        if missing_red:
            errs.add(name, "$.redlines",
                     f"R13: 红线库中的 {missing_red} 未逐条处置——每条红线都要写 "
                     "applies/details,不适用也要写明为什么不适用")
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


def check_store_reviews(doc, target_ids, designed_ids, name, errs):
    """R14 — store_reviews 覆盖与引用合法。"""
    reviews = [r for r in as_list(doc.get("store_reviews")) if isinstance(r, dict)]
    reviewed = {r.get("store_id") for r in reviews}
    for i, r in enumerate(reviews):
        if r.get("store_id") not in designed_ids:
            errs.add(name, f"$.store_reviews[{i}].store_id",
                     f"R14: 评审了未设计过的库 {r.get('store_id')!r}(设计过的: {sorted(designed_ids)})")
    missing = sorted(set(target_ids) - reviewed)
    if missing:
        errs.add(name, "$.store_reviews",
                 f"R14: 目标数据库 {missing} 未被逐库评审——一个都不能少")


def check_state_alignment(state, latest_art, latest_verif, errs):
    """R16 — state 与产物对账:mode/stores/kind/target/评审状态两边不许各说各话。"""
    if not state:
        return
    mode = state.get("mode")
    stores = [c for c in as_list(state.get("stores")) if isinstance(c, dict)]

    if mode == "review" and stores:
        errs.add("state.json", "$.stores",
                 "R16: review 模式 stores 必须置空(评审对象是已有 schema 文档,不设计库)")
    if mode == "design" and not stores:
        errs.add("state.json", "$.stores",
                 "R16: design 模式必须登记 ≥1 个目标数据库(INIT 时一次定齐)")
    kind = state.get("upstream_kind")
    if mode == "review" and kind != "schema_doc":
        errs.add("state.json", "$.upstream_kind",
                 "R16: review 模式的被评审对象是已有 schema/DDL 文档,upstream_kind 应为 schema_doc")
    if mode == "design" and kind == "schema_doc":
        errs.add("state.json", "$.upstream_kind",
                 "R16: design 模式不消费 schema_doc(那是 review 场景的输入),"
                 "上游应为 module_design/architecture/module_doc/schema_request")

    status = state.get("status")
    if status == "COMPLETE":
        cross = state.get("cross")
        if not (isinstance(cross, dict) and cross.get("status") == "passed"):
            errs.add("state.json", "$.cross.status",
                     "R16: status=COMPLETE 但 cross.status 未记 passed——Cross 通过才允许 COMPLETE")
        not_pass = [c.get("id") for c in stores if c.get("review_status") != "pass"]
        if not_pass:
            errs.add("state.json", "$.stores",
                     f"R16: status=COMPLETE 但库 {not_pass} 的 review_status 不是 pass——逐库全过才允许 COMPLETE")

    if status not in ("VERIFYING", "COMPLETE"):
        return
    not_done = [c.get("id") for c in stores if c.get("design_status") != "done"]
    if not_done:
        errs.add("state.json", "$.stores",
                 f"R16: status={status} 但库 {not_done} 的 design_status 未全部 done——设计未完成不得进入评审")
    if latest_art is not None:
        aname, art = latest_art
        expect_kind = "db_review" if mode == "review" else "db_schemas"
        if kind_of(art) != expect_kind:
            errs.add(aname, "$.artifact.deliverable_kind",
                     f"R16: state.mode={mode!r} 对应 deliverable_kind={expect_kind!r},"
                     f"最新产物却是 {kind_of(art)!r}——两边各说各话")
        if mode == "design":
            target = {t for t in as_list((body_of(art).get("input_summary") or {})
                                         .get("target_stores")) if isinstance(t, str)}
            state_ids = {c.get("id") for c in stores if isinstance(c.get("id"), str)}
            if target != state_ids:
                errs.add(aname, "$.artifact.input_summary.target_stores",
                         f"R16: artifact 目标数据库 {sorted(target)} 与 state.stores "
                         f"{sorted(state_ids)} 不一致——面集/深度变动须同步两边并记 DECISION")
    if latest_verif is None:
        return
    _vname, vdoc = latest_verif
    reviews = {r.get("store_id"): r.get("verdict")
               for r in as_list(vdoc.get("store_reviews")) if isinstance(r, dict)}
    for c in stores:
        cid, rs = c.get("id"), c.get("review_status")
        v = reviews.get(cid)
        if v is None:
            continue
        if rs == "pending":
            errs.add("state.json", f"$.stores[{cid}].review_status",
                     f"R16: 最新评审已给库 {cid!r} 判 {v!r},state.review_status 仍是 pending——两边须同步")
        elif (rs == "pass") != (v == "PASS"):
            errs.add("state.json", f"$.stores[{cid}].review_status",
                     f"R16: 库 {cid!r} 的 state.review_status={rs!r} 与评审 verdict={v!r} 矛盾——state 与 verification 不许各说各话")
    cross = state.get("cross")
    cr = vdoc.get("cross_review")
    if isinstance(cross, dict) and isinstance(cr, dict):
        cs, cv = cross.get("status"), cr.get("verdict")
        if cs == "not_started" and cv in ("pass", "revise"):
            errs.add("state.json", "$.cross.status",
                     f"R16: cross_review 已判 {cv!r},state.cross.status 仍是 not_started——两边须同步")
        elif cs == "passed" and cv != "pass":
            errs.add("state.json", "$.cross.status",
                     "R16: state.cross.status=passed 与 cross_review.verdict 矛盾——两边不许各说各话")
        elif cs == "revise_required" and cv != "revise":
            errs.add("state.json", "$.cross.status",
                     "R16: state.cross.status=revise_required 与 cross_review.verdict 矛盾——两边不许各说各话")


def main(argv):
    if len(argv) < 2:
        print("用法: python3 validate.py <PEV_DIR>   # 如 .pev/prd-2026-09-20/db/")
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
        if kind == "db_schemas":
            check_conformance(body, name, errs, residuals)
            check_mapping(body, name, errs)
            check_self_challenge(body, name, errs)
            check_tradeoff_cost(body, name, errs)
        elif kind == "db_review":
            check_review_findings(body, name, errs)
        else:
            errs.add(name, "$.artifact.deliverable_kind",
                     f"未知 deliverable_kind {kind!r}")

    # R6/R14 — 门禁照抄;PASS 必须全绿 + 逐库全过 + Cross 通过
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
        target_ids = {t for t in as_list((body.get("input_summary") or {}).get("target_stores"))
                      if isinstance(t, str)}
        designed_ids = {c.get("id") for c in designed_stores(body)
                        if isinstance(c.get("id"), str)}

        check_store_reviews(doc, target_ids, designed_ids, name, errs)
        check_cross_findings(doc, designed_ids, name, errs)

        if doc.get("verdict") == "PASS":
            failed_gates = [k for k, v in gates.items() if not v]
            if failed_gates:
                errs.add(name, "$.verdict",
                         f"R14: verdict=PASS 但门禁未全绿({failed_gates})——应判 REVISE 并修复,不得 PASS")
            bad_reviews = [r.get("store_id") for r in as_list(doc.get("store_reviews"))
                           if isinstance(r, dict) and r.get("verdict") != "PASS"]
            if bad_reviews:
                errs.add(name, "$.store_reviews",
                         f"R14: verdict=PASS 但库 {bad_reviews} 评审为 REVISE——整体 PASS 要求逐库全过")
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

    # R16 — state 与产物对账(最新迭代为准)
    check_state_alignment(state, latest,
                          verifications[-1] if verifications else None, errs)

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
