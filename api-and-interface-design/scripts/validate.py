#!/usr/bin/env python3
"""api-and-interface-design PEV 产物校验器(双端通用,仅依赖 Python 标准库)。

用法:
    python3 validate.py <PEV_DIR>      # PEV_DIR 为本 skill 工作目录,如 .pev/prd-2026-09-20/api/

按文件名后缀路由到 schemas/ 下对应 schema:
    state.json                    -> state.schema.json
    iterations/*-plan.json        -> plan.schema.json
    iterations/*-artifact.json    -> artifact.schema.json
    iterations/*-verification.json-> verification.schema.json

除 JSON Schema 子集(type/enum/required/properties/items/minItems/
minimum/maximum)外,强制以下语义规则——这些是状态机的硬约束,靠肉眼最容易漏:
    R1  Evidence 条目 type=FACT/DECISION 时 evidence 必须是非空字符串
        (FACT 证据=上游产物 §x / .pev/<轮次>/ 家族产物 / 代码路径;
        DECISION 证据=拍板/精修锚点)。INFERENCE 同样必须带非空推理依据;
        三者缺证据 → 报错。HYPOTHESIS/UNKNOWN 允许 evidence 为 null。
    R2  artifact.status ∈ {replan_required, blocked} 时,replan_reason 必填
    R3  state.status=WAITING_FOR_INPUT 时,resume_to 必填;
        其他 status 下 resume_to 必须不存在
    R4  state.status=WAITING_FOR_UPSTREAM 时,upstream_gaps 必须非空;
        其他 status 下 upstream_gaps 必须为空
    R5  契约守恒与结构(api_contracts kind,全部对照 upstream_snapshot):
        - 契约面 id 全局唯一;owner_module ⊆ 快照模块;目标契约面(target_contracts)个个有设计;
        - covered_capabilities ⊆ owner_module 的快照 exposes——越界即报错;
        - operations id 契约面内唯一,name/purpose 非空,capability 引用本面
          covered_capabilities;
        - detail 模式 operations 的 request/response 非空、error_model 与
          versioning 非空;brief 模式 request/response 必须为空且 error_model/
          versioning 必须省略;
        - interaction_commitments.interaction 引用快照交互 id,且 owner_module
          是该交互的参与方(from/to)。
    R6  门禁布尔照抄脚本:评审落点 state.status ∈ {VERIFYING, COMPLETE} 时,
        verification.gates 五值与脚本计算逐位比对,不一致整份打回
    R7  覆盖对账:承接的能力必须逐条进 upstream_items(分母造假直接报错);
        承接的交互 id 必须进 upstream_items;声明的条目必须落在快照内;
        upstream_mapping 引用合法;每条 upstream_item 被映射 ≥1 次;
        每个目标契约面至少有一条落点。
    R8  诚实门:self_challenge 7 维全齐且处置合法(accepted_risk 必须带理由);
        tradeoffs 全部 cost 非空;api_review kind 的 review_findings 同理
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
        - contract_reviews 覆盖全部目标契约面且逐个 verdict=PASS;
        - cross_review.verdict=pass;
        - 五个门禁全绿。
        contract_reviews[].contract_id 必须引用设计过的契约面 id。
    R15 state.status ∈ {VERIFYING, COMPLETE} 时,state.cross 必须存在
        (整体停在 VERIFYING 直到 Cross 通过;cross 缺失无法证明 Cross 状态)
    R16 state↔产物对账(两边不许各说各话):
        - mode=review 时 contracts 必须置空,mode=design 时必须非空;
          mode=review ↔ upstream_kind=contract_doc;
        - state.status ∈ {VERIFYING, COMPLETE} 时:design_status 全部 done;
          最新 artifact 的 deliverable_kind 与 mode 对应,api_contracts 的
          target_contracts 与 state.contracts[] 一致;
        - COMPLETE 收口:cross.status=passed 且逐契约面 review_status=pass;
        - 存在最新 verification 时:state 的 review_status/cross.status 与
          verification 的 contract_reviews.verdict/cross_review.verdict 按
          映射一致(pass↔PASS、revise↔REVISE、passed↔pass、revise_required↔revise)。

五个门禁的布尔(api_contracts kind):
    contracts_complete         —— 目标契约面个个有设计,且每面有 ≥1 操作、
                                  ≥1 承接能力
    capabilities_within_upstream —— R5 守恒与引用检查(owner/能力/操作/交互引用)
    upstream_mapped            —— R7 对账过且 upstream_items 非空
    findings_disposed          —— R8 过 + detail 的 error_model/versioning 非空/
                                  brief 的二者省略
    cross_consistent           —— R5 交互承接检查全部通过

通过时汇总输出:最新迭代的五门禁结论,以及交 Verifier 逐条处置的残留清单
(owner 模块参与却无任何契约承接的快照交互)。

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

# 对抗 7 维(与 rubrics/api-review.md 一致)
ADVERSARIAL_DIMS = ("failure_modes", "consistency", "concurrency",
                    "boundary_erosion", "misuse_potential", "compatibility",
                    "simpler_alternative")

GATE_KEYS = ("contracts_complete", "capabilities_within_upstream",
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


def designed_contracts(body):
    return [c for c in as_list(body.get("contracts")) if isinstance(c, dict)]


def check_conformance(body, file, errs, residuals):
    """R5 — 契约守恒与结构:全部对照 upstream_snapshot。"""
    snap_m = snap_modules(body)
    snap_i = snap_interactions(body)
    target = [t for t in as_list((body.get("input_summary") or {}).get("target_contracts"))
              if isinstance(t, str)]

    designed_ids = {c.get("id") for c in designed_contracts(body)
                    if isinstance(c.get("id"), str)}
    id_list = [c.get("id") for c in designed_contracts(body)]
    dup_cids = sorted({i for i in id_list if isinstance(i, str) and id_list.count(i) > 1})
    if dup_cids:
        errs.add(file, "$.artifact.contracts",
                 f"R5: 契约面 id 重复 {dup_cids}——id 是评审与对账的定位键,全局唯一")
    for t in target:
        if t not in designed_ids:
            errs.add(file, "$.artifact.input_summary.target_contracts",
                     f"R5: 目标契约面 {t!r} 没有对应设计——目标契约面一个都不能少")
    extra_faces = sorted(d for d in designed_ids if d not in set(target))
    if extra_faces:
        errs.add(file, "$.artifact.contracts",
                 f"R5: 设计了目标外的契约面 {extra_faces}——目标面集在 INIT 定齐,"
                 "增面须先记 DECISION 并同步 state.contracts 与 target_contracts")

    committed_any = set()
    for c in designed_contracts(body):
        cid = c.get("id")
        base = f"$.artifact.contracts[{cid}]"
        owner = c.get("owner_module")
        arch = snap_m.get(owner)
        if arch is None:
            errs.add(file, f"{base}.owner_module",
                     f"R5: 契约面 {cid!r} 的 owner_module {owner!r} 不是上游快照声明的模块——契约无权新造模块")
            continue

        # 能力守恒
        arch_exposes = {e for e in as_list(arch.get("exposes")) if isinstance(e, str)}
        caps = [x for x in as_list(c.get("covered_capabilities")) if isinstance(x, str)]
        extra = sorted(set(caps) - arch_exposes)
        if extra:
            errs.add(file, f"{base}.covered_capabilities",
                     f"R5: 承接了上游声明外的能力 {extra}——需要新能力是上游层缺口,"
                     "走三选一,不在契约层私自扩边")
        if not caps:
            errs.add(file, f"{base}.covered_capabilities",
                     "R5: 契约面必须承接 ≥1 条上游能力——零承接的契约面是画的不是设计的")

        # 操作结构
        depth = c.get("depth")
        ops = [o for o in as_list(c.get("operations")) if isinstance(o, dict)]
        oids = [o.get("id") for o in ops if isinstance(o.get("id"), str)]
        dup = sorted({o for o in oids if oids.count(o) > 1})
        if dup:
            errs.add(file, f"{base}.operations", f"R5: 操作 id 重复 {dup}")
        for i, o in enumerate(ops):
            for field in ("name", "purpose"):
                if not nonempty_str(o.get(field)):
                    errs.add(file, f"{base}.operations[{i}].{field}",
                             f"R5: 操作 {o.get('id')!r} 的 {field} 为空——操作必须有{'名称' if field == 'name' else '目的陈述'}")
            if o.get("capability") not in caps:
                errs.add(file, f"{base}.operations[{i}].capability",
                         f"R5: 操作 {o.get('id')!r} 的 capability {o.get('capability')!r} 不在本面 covered_capabilities 中(可用: {sorted(caps)})")
            req, resp = o.get("request"), o.get("response")
            if depth == "detail" and (not nonempty_str(req) or not nonempty_str(resp)):
                errs.add(file, f"{base}.operations[{i}]",
                         "R5: detail 模式操作的 request/response 必须非空——完整契约没有载荷定义就是空话")
            if depth == "brief" and (nonempty_str(req) or nonempty_str(resp)):
                errs.add(file, f"{base}.operations[{i}]",
                         "R5: brief 模式操作不得携带 request/response——要完整 schema 请提升该面为 detail")

        # 错误模型与版本策略按深度
        em, ver = c.get("error_model"), c.get("versioning")
        if depth == "detail":
            if not isinstance(em, dict) or not nonempty_str(em.get("strategy")) or not as_list(em.get("codes")):
                errs.add(file, f"{base}.error_model",
                         "R5: detail 模式 error_model 必须非空且落到 strategy + code 表——统一错误处理不能停在口号")
            if not isinstance(ver, dict) or not nonempty_str(ver.get("strategy")) or not nonempty_str(ver.get("compat_rules")):
                errs.add(file, f"{base}.versioning",
                         "R5: detail 模式 versioning 必须写清策略与兼容规则——没有兼容交代的对外契约是定时炸弹")
        elif depth == "brief":
            if "error_model" in c:
                errs.add(file, f"{base}.error_model",
                         "R5: brief 模式必须省略 error_model——要完整错误语义请提升该面为 detail")
            if "versioning" in c:
                errs.add(file, f"{base}.versioning",
                         "R5: brief 模式必须省略 versioning——要版本策略请提升该面为 detail")

        # 交互承接
        for i, ic in enumerate(as_list(c.get("interaction_commitments"))):
            if not isinstance(ic, dict):
                continue
            iid = ic.get("interaction")
            it = snap_i.get(iid)
            if it is None:
                errs.add(file, f"{base}.interaction_commitments[{i}].interaction",
                         f"R5: 承接的交互 {iid!r} 不在上游快照交互中(可用: {sorted(snap_i)})")
                continue
            if owner not in (it.get("from"), it.get("to")):
                errs.add(file, f"{base}.interaction_commitments[{i}].interaction",
                         f"R5: 模块 {owner} 不是交互 {iid}({it.get('from')}→{it.get('to')})的参与方——不能替别人认领")
            committed_any.add(iid)

    # 残留:owner 参与却无任何契约承接的快照交互(交 Verifier 审是否越界省略)
    owners = {c.get("owner_module") for c in designed_contracts(body)
              if isinstance(c.get("owner_module"), str)}
    for iid, it in sorted(snap_i.items()):
        parties = {it.get("from"), it.get("to")} & owners
        if parties and iid not in committed_any:
            residuals.append(
                f"上游声明交互 {iid}({it.get('from')}→{it.get('to')})的参与方 "
                f"{sorted(parties)} 有契约面,但无任何契约承接该交互(交 Verifier 处置)")


def check_mapping(body, file, errs):
    """R7 — 分母完备(承接的能力/交互逐条进 upstream_items)+ 映射双向对账。"""
    summary = body.get("input_summary") or {}
    items = [u for u in as_list(summary.get("upstream_items")) if isinstance(u, dict)]
    item_ids = {u.get("id") for u in items if isinstance(u.get("id"), str)}
    item_texts = {u.get("item") for u in items if isinstance(u.get("item"), str)}

    snap_m = snap_modules(body)
    snap_i = snap_interactions(body)
    all_exposes = set()
    for arch in snap_m.values():
        all_exposes |= {e for e in as_list(arch.get("exposes")) if isinstance(e, str)}

    # 声明的条目必须落在快照内(能力按文本、交互按 id)
    for u in items:
        uid, text = u.get("id"), u.get("item")
        if isinstance(uid, str) and uid in snap_i:
            continue  # 交互条目,以 id 对账
        if isinstance(text, str) and text in all_exposes:
            continue  # 能力条目,以文本对账
        errs.add(file, "$.artifact.input_summary.upstream_items",
                 f"R7: 条目 {uid!r}({text!r})不在上游快照(能力文本/交互 id)中——不能凭空造分母")

    # 承接的能力与交互必须逐条进分母
    for c in designed_contracts(body):
        cid = c.get("id")
        for cap in as_list(c.get("covered_capabilities")):
            if isinstance(cap, str) and cap not in item_texts:
                errs.add(file, "$.artifact.input_summary.upstream_items",
                         f"R7: 契约面 {cid} 承接能力 {cap!r} 但 upstream_items 未声明——分母不全,覆盖检查失效")
        for ic in as_list(c.get("interaction_commitments")):
            if isinstance(ic, dict) and ic.get("interaction") not in item_ids:
                errs.add(file, "$.artifact.input_summary.upstream_items",
                         f"R7: 契约面 {cid} 承接交互 {ic.get('interaction')!r} 但 upstream_items 未声明——分母不全,覆盖检查失效")

    designed_ids = {c.get("id") for c in designed_contracts(body)
                    if isinstance(c.get("id"), str)}
    mapped = set()
    landed = set()
    for i, mp in enumerate(as_list(body.get("upstream_mapping"))):
        if not isinstance(mp, dict):
            continue
        u, m = mp.get("upstream_item"), mp.get("contract_id")
        if u not in item_ids:
            errs.add(file, f"$.artifact.upstream_mapping[{i}].upstream_item",
                     f"R7: 引用了未声明的上游条目 {u!r}")
        if designed_ids and m not in designed_ids:
            errs.add(file, f"$.artifact.upstream_mapping[{i}].contract_id",
                     f"R7: 落点 {m!r} 不是设计过的契约面 id")
        mapped.add(u)
        landed.add(m)

    missing = sorted(i for i in item_ids if i not in mapped)
    if missing:
        errs.add(file, "$.artifact.upstream_mapping",
                 f"R7: 上游条目 {missing} 声明了却无落点——要么补映射,要么从 upstream_items 删除(并交 Verifier 审删除理由)")
    target = [t for t in as_list(summary.get("target_contracts")) if isinstance(t, str)]
    for t in target:
        if t in designed_ids and t not in landed:
            errs.add(file, "$.artifact.upstream_mapping",
                     f"R7: 目标契约面 {t} 没有任何落点条目——承接对账没有记录")


def check_self_challenge(body, file, errs):
    """R8 — 每契约面 7 维全齐、处置合法、accepted_risk 有理由。"""
    for c in designed_contracts(body):
        cid = c.get("id")
        entries = [e for e in as_list(c.get("self_challenge")) if isinstance(e, dict)]
        covered = {e.get("dimension") for e in entries if isinstance(e.get("dimension"), str)}
        missing = [d for d in ADVERSARIAL_DIMS if d not in covered]
        if missing:
            errs.add(file, f"$.artifact.contracts[{cid}].self_challenge",
                     f"R8: 契约面 {cid} 自查缺少维度 {missing}——7 维必须逐维占位,无发现也要写空 finding 证明扫过")
        for i, e in enumerate(entries):
            finding, disp = e.get("finding"), e.get("disposition")
            empty = not nonempty_str(finding)
            if empty and disp != "none":
                errs.add(file, f"$.artifact.contracts[{cid}].self_challenge[{i}]",
                         "R8: finding 为空时 disposition 只能是 none")
            if not empty and disp not in ("fixed", "accepted_risk"):
                errs.add(file, f"$.artifact.contracts[{cid}].self_challenge[{i}]",
                         "R8: 有发现必须处置(fixed / accepted_risk),不许悬空")
            if disp == "accepted_risk" and not nonempty_str(e.get("rationale")):
                errs.add(file, f"$.artifact.contracts[{cid}].self_challenge[{i}].rationale",
                         "R8: 接受风险必须写理由——没有理由的接受是遗忘,不是决策")


def check_tradeoff_cost(body, file, errs):
    for c in designed_contracts(body):
        cid = c.get("id")
        for i, t in enumerate(as_list(c.get("tradeoffs"))):
            if isinstance(t, dict) and not nonempty_str(t.get("cost")):
                errs.add(file, f"$.artifact.contracts[{cid}].tradeoffs[{i}].cost",
                         "R8: 取舍缺代价——不说放弃什么的取舍不是取舍")


def check_review_findings(body, file, errs):
    """R8 诚实门(api_review)—— 7 维全齐、非空 finding 带 severity+锚点、空 finding 标 NONE。"""
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
                         "R8: 非空 finding 必须带 evidence_anchor(被评审契约的 §位置/端点 id)——锚不到位置的发现只是意见")


# ---------- 门禁计算(无副作用版本,与上面检查保持同一判据) ----------

def _structure_ok(body):
    str_ids = [i for i in (c.get("id") for c in designed_contracts(body))
               if isinstance(i, str)]
    if len(str_ids) != len(set(str_ids)):
        return False
    snap_m = snap_modules(body)
    for c in designed_contracts(body):
        arch = snap_m.get(c.get("owner_module"))
        if arch is None:
            return False
        arch_exposes = {e for e in as_list(arch.get("exposes")) if isinstance(e, str)}
        caps = [x for x in as_list(c.get("covered_capabilities")) if isinstance(x, str)]
        if not caps or not arch_exposes >= set(caps):
            return False
        ops = [o for o in as_list(c.get("operations")) if isinstance(o, dict)]
        oids = [o.get("id") for o in ops]
        if len(oids) != len(set(oids)):
            return False
        depth = c.get("depth")
        for o in ops:
            if not nonempty_str(o.get("name")) or not nonempty_str(o.get("purpose")):
                return False
            if o.get("capability") not in caps:
                return False
            req_ok = nonempty_str(o.get("request")) and nonempty_str(o.get("response"))
            if depth == "detail" and not req_ok:
                return False
            if depth == "brief" and (nonempty_str(o.get("request")) or nonempty_str(o.get("response"))):
                return False
        em, ver = c.get("error_model"), c.get("versioning")
        if depth == "detail":
            if not (isinstance(em, dict) and nonempty_str(em.get("strategy"))
                    and as_list(em.get("codes"))):
                return False
            if not (isinstance(ver, dict) and nonempty_str(ver.get("strategy"))
                    and nonempty_str(ver.get("compat_rules"))):
                return False
        elif depth == "brief":
            if "error_model" in c or "versioning" in c:
                return False
    return True


def _cross_ok(body):
    snap_i = snap_interactions(body)
    for c in designed_contracts(body):
        owner = c.get("owner_module")
        for ic in as_list(c.get("interaction_commitments")):
            if not isinstance(ic, dict):
                return False
            it = snap_i.get(ic.get("interaction"))
            if it is None or owner not in (it.get("from"), it.get("to")):
                return False
    return True


def _contracts_complete_ok(body):
    target = [t for t in as_list((body.get("input_summary") or {}).get("target_contracts"))
              if isinstance(t, str)]
    by_id = {c.get("id"): c for c in designed_contracts(body) if isinstance(c.get("id"), str)}
    for t in target:
        c = by_id.get(t)
        if c is None:
            return False
        if not as_list(c.get("operations")):
            return False
        if not as_list(c.get("covered_capabilities")):
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
    all_exposes = set()
    for arch in snap_m.values():
        all_exposes |= {e for e in as_list(arch.get("exposes")) if isinstance(e, str)}
    for u in items:
        uid, text = u.get("id"), u.get("item")
        if not ((isinstance(uid, str) and uid in snap_i)
                or (isinstance(text, str) and text in all_exposes)):
            return False
    for c in designed_contracts(body):
        caps = {x for x in as_list(c.get("covered_capabilities")) if isinstance(x, str)}
        if any(cap not in item_texts for cap in caps):
            return False
        for ic in as_list(c.get("interaction_commitments")):
            if isinstance(ic, dict) and ic.get("interaction") not in item_ids:
                return False
    designed_ids = {c.get("id") for c in designed_contracts(body)
                    if isinstance(c.get("id"), str)}
    mapped, landed = set(), set()
    for mp in as_list(body.get("upstream_mapping")):
        if not isinstance(mp, dict):
            return False
        if mp.get("upstream_item") not in item_ids:
            return False
        if designed_ids and mp.get("contract_id") not in designed_ids:
            return False
        mapped.add(mp.get("upstream_item"))
        landed.add(mp.get("contract_id"))
    if not item_ids <= mapped:
        return False
    for t in [t for t in as_list(summary.get("target_contracts")) if isinstance(t, str)]:
        if t in designed_ids and t not in landed:
            return False
    return True


def _honesty_ok(body):
    for c in designed_contracts(body):
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
        depth = c.get("depth")
        em, ver = c.get("error_model"), c.get("versioning")
        if depth == "detail":
            if not (isinstance(em, dict) and as_list(em.get("codes"))):
                return False
            if not (isinstance(ver, dict) and nonempty_str(ver.get("compat_rules"))):
                return False
        if depth == "brief" and ("error_model" in c or "versioning" in c):
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

    if kind == "api_review":
        honest = _review_findings_ok(body)
        if not honest:
            details.append("诚实:review_findings 7 维全齐/非空 finding 带 severity+锚点 检查未过")
        return ({"contracts_complete": True, "capabilities_within_upstream": True,
                 "upstream_mapped": True, "findings_disposed": honest,
                 "cross_consistent": True}, details)

    if kind != "api_contracts":
        return ({k: False for k in GATE_KEYS}, [f"未知 deliverable_kind {kind!r}"])

    complete = _contracts_complete_ok(body)
    if not complete:
        details.append("目标契约面:设计齐全/操作/承接能力 检查未过")
    conform = _structure_ok(body)
    if not conform:
        details.append("契约守恒:owner/能力/操作/错误模型/版本 检查未过")
    mapped = _mapping_ok(body)
    if not mapped:
        details.append("覆盖:upstream_items 分母与映射对账未过")
    honest = _honesty_ok(body)
    if not honest:
        details.append("诚实:自查 7 维/取舍代价/错误模型与版本按深度 检查未过")
    cross = _cross_ok(body)
    if not cross:
        details.append("交互:承接声明与参与方检查未过")

    return ({"contracts_complete": complete, "capabilities_within_upstream": conform,
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
                    "FACT": "上游产物 §x / .pev/<轮次>/ 家族产物 / 代码路径",
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

        if status in ("VERIFYING", "COMPLETE") and not isinstance(state.get("cross"), dict):
            errs.add("state.json", "$.cross",
                     "R15: status=VERIFYING/COMPLETE 时必须携带 cross(Cross 跨契约一致性评审状态)")


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
    """cross_review.findings 的 affected_contracts 必须回指设计过的契约面。"""
    cross = doc.get("cross_review")
    if not isinstance(cross, dict):
        return
    for i, f in enumerate(as_list(cross.get("findings"))):
        if not isinstance(f, dict):
            continue
        base = f"$.cross_review.findings[{i}]"
        mods = as_list(f.get("affected_contracts"))
        if not mods:
            errs.add(name, base, "R12: Cross 发现必须携带非空 affected_contracts")
        for mid in mods:
            if designed_ids and mid not in designed_ids:
                errs.add(name, f"{base}.affected_contracts",
                         f"R12: Cross 发现引用未设计过的契约面 {mid!r}(设计过的: {sorted(designed_ids)})")


def load_redline_library():
    path = REDLINES_DIR / "api-redlines.json"
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


def check_contract_reviews(doc, target_ids, designed_ids, name, errs):
    """R14 — contract_reviews 覆盖与引用合法。"""
    reviews = [r for r in as_list(doc.get("contract_reviews")) if isinstance(r, dict)]
    reviewed = {r.get("contract_id") for r in reviews}
    for i, r in enumerate(reviews):
        if r.get("contract_id") not in designed_ids:
            errs.add(name, f"$.contract_reviews[{i}].contract_id",
                     f"R14: 评审了未设计过的契约面 {r.get('contract_id')!r}(设计过的: {sorted(designed_ids)})")
    missing = sorted(set(target_ids) - reviewed)
    if missing:
        errs.add(name, "$.contract_reviews",
                 f"R14: 目标契约面 {missing} 未被逐契约面评审——一个都不能少")


def check_state_alignment(state, latest_art, latest_verif, errs):
    """R16 — state 与产物对账:mode/contracts/kind/target/评审状态两边不许各说各话。"""
    if not state:
        return
    mode = state.get("mode")
    contracts = [c for c in as_list(state.get("contracts")) if isinstance(c, dict)]

    if mode == "review" and contracts:
        errs.add("state.json", "$.contracts",
                 "R16: review 模式 contracts 必须置空(评审对象是已有契约文档,不设计契约面)")
    if mode == "design" and not contracts:
        errs.add("state.json", "$.contracts",
                 "R16: design 模式必须登记 ≥1 个目标契约面(INIT 时一次定齐)")
    kind = state.get("upstream_kind")
    if mode == "review" and kind != "contract_doc":
        errs.add("state.json", "$.upstream_kind",
                 "R16: review 模式的被评审对象是已有契约文档,upstream_kind 应为 contract_doc")
    if mode == "design" and kind == "contract_doc":
        errs.add("state.json", "$.upstream_kind",
                 "R16: design 模式不消费 contract_doc(那是 review 场景的输入),"
                 "上游应为 module_design/architecture/module_doc")

    status = state.get("status")
    if status == "COMPLETE":
        cross = state.get("cross")
        if not (isinstance(cross, dict) and cross.get("status") == "passed"):
            errs.add("state.json", "$.cross.status",
                     "R16: status=COMPLETE 但 cross.status 未记 passed——Cross 通过才允许 COMPLETE")
        not_pass = [c.get("id") for c in contracts if c.get("review_status") != "pass"]
        if not_pass:
            errs.add("state.json", "$.contracts",
                     f"R16: status=COMPLETE 但契约面 {not_pass} 的 review_status 不是 pass——逐契约面全过才允许 COMPLETE")

    if status not in ("VERIFYING", "COMPLETE"):
        return
    not_done = [c.get("id") for c in contracts if c.get("design_status") != "done"]
    if not_done:
        errs.add("state.json", "$.contracts",
                 f"R16: status={status} 但契约面 {not_done} 的 design_status 未全部 done——设计未完成不得进入评审")
    if latest_art is not None:
        aname, art = latest_art
        expect_kind = "api_review" if mode == "review" else "api_contracts"
        if kind_of(art) != expect_kind:
            errs.add(aname, "$.artifact.deliverable_kind",
                     f"R16: state.mode={mode!r} 对应 deliverable_kind={expect_kind!r},"
                     f"最新产物却是 {kind_of(art)!r}——两边各说各话")
        if mode == "design":
            target = {t for t in as_list((body_of(art).get("input_summary") or {})
                                         .get("target_contracts")) if isinstance(t, str)}
            state_ids = {c.get("id") for c in contracts if isinstance(c.get("id"), str)}
            if target != state_ids:
                errs.add(aname, "$.artifact.input_summary.target_contracts",
                         f"R16: artifact 目标契约面 {sorted(target)} 与 state.contracts "
                         f"{sorted(state_ids)} 不一致——面集/深度变动须同步两边并记 DECISION")
    if latest_verif is None:
        return
    _vname, vdoc = latest_verif
    reviews = {r.get("contract_id"): r.get("verdict")
               for r in as_list(vdoc.get("contract_reviews")) if isinstance(r, dict)}
    for c in contracts:
        cid, rs = c.get("id"), c.get("review_status")
        v = reviews.get(cid)
        if v is None:
            continue
        if rs == "pending":
            errs.add("state.json", f"$.contracts[{cid}].review_status",
                     f"R16: 最新评审已给契约面 {cid!r} 判 {v!r},state.review_status 仍是 pending——两边须同步")
        elif (rs == "pass") != (v == "PASS"):
            errs.add("state.json", f"$.contracts[{cid}].review_status",
                     f"R16: 契约面 {cid!r} 的 state.review_status={rs!r} 与评审 verdict={v!r} 矛盾——state 与 verification 不许各说各话")
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
        print("用法: python3 validate.py <PEV_DIR>   # 如 .pev/prd-2026-09-20/api/")
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
        if kind == "api_contracts":
            check_conformance(body, name, errs, residuals)
            check_mapping(body, name, errs)
            check_self_challenge(body, name, errs)
            check_tradeoff_cost(body, name, errs)
        elif kind == "api_review":
            check_review_findings(body, name, errs)
        else:
            errs.add(name, "$.artifact.deliverable_kind",
                     f"未知 deliverable_kind {kind!r}")

    # R6/R14 — 门禁照抄;PASS 必须全绿 + 逐契约面全过 + Cross 通过
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
        target_ids = {t for t in as_list((body.get("input_summary") or {}).get("target_contracts"))
                      if isinstance(t, str)}
        designed_ids = {c.get("id") for c in designed_contracts(body)
                        if isinstance(c.get("id"), str)}

        check_contract_reviews(doc, target_ids, designed_ids, name, errs)
        check_cross_findings(doc, designed_ids, name, errs)

        if doc.get("verdict") == "PASS":
            failed_gates = [k for k, v in gates.items() if not v]
            if failed_gates:
                errs.add(name, "$.verdict",
                         f"R14: verdict=PASS 但门禁未全绿({failed_gates})——应判 REVISE 并修复,不得 PASS")
            bad_reviews = [r.get("contract_id") for r in as_list(doc.get("contract_reviews"))
                           if isinstance(r, dict) and r.get("verdict") != "PASS"]
            if bad_reviews:
                errs.add(name, "$.contract_reviews",
                         f"R14: verdict=PASS 但契约面 {bad_reviews} 评审为 REVISE——整体 PASS 要求逐契约面全过")
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
