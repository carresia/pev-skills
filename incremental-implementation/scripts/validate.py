#!/usr/bin/env python3
"""incremental-implementation PEV 产物校验器(双端通用,仅依赖 Python 标准库)。

用法:
    python3 validate.py <PEV_DIR>      # PEV_DIR 为本 skill 工作目录,如 .pev/prd-2026-10-07/impl/

按文件名后缀路由到 schemas/ 下对应 schema:
    state.json                     -> state.schema.json
    iterations/*-plan.json         -> plan.schema.json
    iterations/*-artifact.json     -> artifact.schema.json
    iterations/*-verification.json -> verification.schema.json

上游对账源:同轮 tasks/ 目录(planning-and-task-breakdown 的结构化产物
iterations/*-artifact.json,取最大编号)存在时,task_registry 的任务 id 集合
必须与其一致(转录对账);tasks/ 不存在(外部清单场景)时跳过该项,
分母以 task_registry 自身为准。

除 JSON Schema 子集(type/enum/required/properties/items/minItems/
minimum/maximum)外,强制以下语义规则——这些是状态机与实施记录的硬约束,
靠肉眼最容易漏:
    R1  Evidence 条目 type=FACT 或 DECISION 时,evidence 必须是非空字符串
        (FACT 证据=任务清单/设计产物 §x / 命令输出 / commit;DECISION 证据=拍板锚点)
    R2  artifact.status ∈ {replan_required, blocked} 时,replan_reason 必填
    R3  state.status=WAITING_FOR_INPUT 时,resume_to 必填;
        其他 status 下 resume_to 必须不存在
    R4  state.status=WAITING_FOR_UPSTREAM 时,upstream_gaps 必须非空;
        其他 status 下 upstream_gaps 必须为空
    R5  实施记录结构纪律:registry/record id 唯一;record.id 必须在 registry 中;
        deferred 任务 note 必填;done 任务——vcs=git 时 commits 非空、tests 至少一条
        result=pass 且 evidence 非空、acceptance_results 与 registry 验收集合
        完全一致且全部 met=true;failed/deferred 任务 note 必填;
        baseline.checks 任一 fail 即拦截(基线未过不许开工)
    R6  引用与范围纪律:record 的 files_changed ⊆ 该任务 registry.files_touched ∪
        deviations[].path(范围纪律,逐文件核对);deviations[].why 必须非空;
        上游 tasks/ 存在时 registry 任务 id 集合必须与上游一致(转录不得增删)
    R7  verification.coverage 的 task_execution_pct 与 scope_violations 必须等于
        **同迭代** artifact 直接算出的值(verification N ↔ artifact N;数字比对仅在
        state.status ∈ {VERIFYING, COMPLETE} 时强制,REVISE 中间态跳过并打印说明)
    R8  verdict=PASS 的 verification,其同迭代 artifact 算出的门禁必须达标
        (task_execution_pct = 100 且 scope_violations = 0)。任务没做完、范围
        跑偏了还判 PASS 是无效评审;REVISE/REPLAN/BLOCKED 不受限
    R9  多个迭代 artifact 并存时,相邻迭代的 task_registry(任务 id 集 + 各项
        deferred/files_touched/acceptance_criteria 取值)必须一致;有变更必须在新
        迭代 Evidence Ledger 里有 DECISION 背书(claim/锚点提及 registry 或所涉
        任务 id)。防止"漏做任务就改分母"或"悄悄放宽声明范围";title/note/trace
        措辞变化不查
    R10 state.plans / state.artifacts 登记册(文件名,不存内容副本)与
        iterations/ 目录双向一致

通过时汇总输出:最新迭代执行覆盖率与门禁结论、范围违规模清单、失败/延后任务
清单(交 Verifier 处置)、偏离声明概览(Verifier 重点审)。

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

PCT_TOLERANCE = 0.05  # 允许 0.05 的舍入差(百分比四舍五入到一位小数)
GATE_COVERAGE = 100.0  # R8:任务执行覆盖门禁
GATE_VIOLATIONS = 0  # R8:范围违规门禁

TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
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


def load_json(path, errs, label=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        errs.add(label or path.name, "$", f"无法读取/解析 JSON(须为 UTF-8): {e}")
        return None


def registry_index(art):
    """artifact.task_registry → {id: entry};无结构返回空 dict。"""
    body = art.get("artifact")
    if not isinstance(body, dict):
        return {}
    inv = body.get("task_registry")
    if not isinstance(inv, list):
        return {}
    return {e.get("id"): e for e in inv if isinstance(e, dict) and isinstance(e.get("id"), str)}


def iter_records(art):
    """遍历 artifact.task_records,产出 (record, json 路径)。"""
    body = art.get("artifact")
    if not isinstance(body, dict):
        return
    for i, rec in enumerate(body.get("task_records", []) or []):
        if isinstance(rec, dict):
            yield rec, f"$.artifact.task_records[{i}]"


def check_structure(art, file, errs, vcs):
    """R5 — 实施记录结构纪律。"""
    body = art.get("artifact")
    if not isinstance(body, dict):
        return

    # 基线检查任一 fail 即拦截:分不清是你改坏的还是本来就坏
    baseline = body.get("baseline")
    if isinstance(baseline, dict):
        for i, chk in enumerate(baseline.get("checks", []) or []):
            if isinstance(chk, dict) and chk.get("result") == "fail":
                errs.add(file, f"$.artifact.baseline.checks[{i}]",
                         "R5: 基线检查未过({})——基线挂了不许开工:先修复基线,或经用户拍板调整"
                         "基线检查口径(记 DECISION)后重记 baseline".format(chk.get("what")))

    # registry id 唯一 + deferred 须有理由(查重用原始列表,dict 会吞重复)
    reg = registry_index(art)
    raw_ids = [e.get("id") for e in (body.get("task_registry") or []) if isinstance(e, dict)]
    dup = sorted({i for i in raw_ids if isinstance(i, str) and raw_ids.count(i) > 1})
    if dup:
        errs.add(file, "$.artifact.task_registry", f"R5: 任务 id 重复 {dup}")
    for tid, entry in reg.items():
        if entry.get("deferred") is True:
            note = entry.get("note")
            if not isinstance(note, str) or not note.strip():
                errs.add(file, f"$.artifact.task_registry[{tid}].note",
                         "R5: deferred=true 的任务必须在 note 写明理由(为什么延后、后续怎么接)——范围收缩必须留痕")

    # record id 唯一 + 悬空引用
    rec_ids = [r.get("id") for r, _ in iter_records(art)]
    dup = sorted({r for r in rec_ids if isinstance(r, str) and rec_ids.count(r) > 1})
    if dup:
        errs.add(file, "$.artifact.task_records", f"R5: 执行记录 id 重复 {dup}")
    for rec, path in iter_records(art):
        rid = rec.get("id")
        if isinstance(rid, str) and rid not in reg:
            errs.add(file, f"{path}.id",
                     f"R5: 执行记录 {rid!r} 不在 task_registry 中——只执行登记过的任务,改清单走三选一")

    # done / failed / deferred 的证据纪律
    for rec, path in iter_records(art):
        rid, status = rec.get("id"), rec.get("status")
        note = rec.get("note")
        if status == "done":
            if vcs == "git":
                commits = rec.get("commits")
                if not isinstance(commits, list) or not commits:
                    errs.add(file, f"{path}.commits",
                             "R5: done 任务(vcs=git)必须有 commit 证据——没有落盘提交的任务不可回滚、不可审计")
            tests = rec.get("tests") or []
            if not any(isinstance(t, dict) and t.get("result") == "pass"
                       and isinstance(t.get("evidence"), str) and t.get("evidence").strip()
                       for t in tests):
                errs.add(file, f"{path}.tests",
                         "R5: done 任务必须至少一条 result=pass 且 evidence 非空的验证记录——\"全绿\"两个字不算证据")
            entry = reg.get(rid)
            if isinstance(entry, dict):
                expected = {c for c in (entry.get("acceptance_criteria") or []) if isinstance(c, str)}
                got = {a.get("criterion") for a in (rec.get("acceptance_results") or [])
                       if isinstance(a, dict) and isinstance(a.get("criterion"), str)}
                if expected != got:
                    errs.add(file, f"{path}.acceptance_results",
                             f"R5: 验收对照与 registry 验收标准集合不一致(缺 {sorted(expected - got)} 多 {sorted(got - expected)})——逐条对照,不许漏不许换")
                for i, a in enumerate(rec.get("acceptance_results") or []):
                    if isinstance(a, dict) and a.get("met") is not True:
                        errs.add(file, f"{path}.acceptance_results[{i}]",
                                 "R5: done 任务的验收条目必须全部 met=true——有未满足项就不是 done,改 status=failed 并写 note")
                    if isinstance(a, dict) and not (isinstance(a.get("evidence"), str) and a.get("evidence").strip()):
                        errs.add(file, f"{path}.acceptance_results[{i}].evidence",
                                 "R5: 验收对照必须带 evidence(测试输出/命令结果/commit)——空对照等于没对照")
        elif status in ("failed", "deferred"):
            if not isinstance(note, str) or not note.strip():
                errs.add(file, f"{path}.note",
                         f"R5: status={status} 的任务必须在 note 写明原因与下一步")


def scope_violation_files(art):
    """R6/R8 — 实际改动落在声明范围与偏离声明之外的文件清单。"""
    body = art.get("artifact")
    if not isinstance(body, dict):
        return []
    reg = registry_index(art)
    out = []
    for rec, _p in iter_records(art):
        rid = rec.get("id")
        entry = reg.get(rid)
        if not isinstance(entry, dict):
            continue
        allowed = {f for f in (entry.get("files_touched") or []) if isinstance(f, str)}
        for d in (rec.get("deviations") or []):
            if isinstance(d, dict) and isinstance(d.get("path"), str):
                allowed.add(d["path"])
        for f in (rec.get("files_changed") or []):
            if isinstance(f, str) and f not in allowed:
                out.append((rid, f))
    return out


def check_references(art, file, errs, upstream_ids):
    """R6 — 范围纪律与上游转录对账。"""
    body = art.get("artifact")
    if not isinstance(body, dict):
        return

    # deviations[].why 非空
    for rec, path in iter_records(art):
        for i, d in enumerate(rec.get("deviations") or []):
            if isinstance(d, dict):
                why = d.get("why")
                if not isinstance(why, str) or not why.strip():
                    errs.add(file, f"{path}.deviations[{i}].why",
                             "R6: 范围偏离必须写明 why——没有理由的越界就是范围失控")

    # 范围纪律:逐文件核对
    for rid, f in scope_violation_files(art):
        errs.add(file, "$.artifact.task_records",
                 f"R6: 任务 {rid} 实际改动 {f} 不在声明文件清单与偏离声明内——范围纪律:要么补 deviations(写 why),"
                 "要么这文件不该动(回滚);上游 files_touched 失实则走三选一回 planning-and-task-breakdown")

    # 上游转录对账:registry 任务 id 集合 == 上游任务 id 集合
    if upstream_ids is not None:
        reg_ids = set(registry_index(art))
        if reg_ids != upstream_ids:
            errs.add(file, "$.artifact.task_registry",
                     f"R6: task_registry 与上游 tasks/ 任务集不一致(缺 {sorted(upstream_ids - reg_ids)} "
                     f"多 {sorted(reg_ids - upstream_ids)})——转录不得增删任务;要改清单走上游 skill")


def compute_coverage(art):
    """R7/R8 — 从 artifact 直接算执行覆盖率。

    分母 = registry 中 deferred 非 true 的任务;分子 = 有 done 记录的任务。
    分母为 0 记 100(无应做任务即无缺口)。
    """
    body = art.get("artifact")
    if not isinstance(body, dict):
        return None
    reg = registry_index(art)
    due = [tid for tid, e in reg.items() if e.get("deferred") is not True]
    done = {r.get("id") for r, _p in iter_records(art) if r.get("status") == "done"}
    if not due:
        return 100.0
    return round(sum(1 for t in due if t in done) / len(due) * 100, 1)


def check_registry_stability(artifacts, errs):
    """R9 — task_registry 迭代间只许有 DECISION 背书的变更(防挪分母、防放宽范围)。

    比较相邻迭代 artifact 的 registry 结构(任务 id 集 + 各项 deferred/
    files_touched/acceptance_criteria 取值);有变化时,新迭代 Evidence Ledger
    必须存在 type=DECISION 的条目且其 claim/锚点提及 registry 或被改变的任务 id。
    title/note/trace 措辞变化不影响分母,不查。
    """
    if len(artifacts) < 2:
        return

    def structure(art):
        body = art.get("artifact")
        if not isinstance(body, dict):
            return None
        reg = body.get("task_registry")
        if not isinstance(reg, list):
            return None
        return {e.get("id"): (e.get("deferred") is True,
                              tuple(e.get("files_touched") or []),
                              tuple(e.get("acceptance_criteria") or []))
                for e in reg if isinstance(e, dict) and isinstance(e.get("id"), str)}

    for (prev_name, prev), (name, art) in zip(artifacts, artifacts[1:]):
        s_prev, s_new = structure(prev), structure(art)
        if s_prev is None or s_new is None or s_prev == s_new:
            continue
        changed = sorted(set(s_prev) ^ set(s_new)
                         | {k for k in set(s_prev) & set(s_new) if s_prev[k] != s_new[k]})
        ledger = art.get("evidence") if isinstance(art.get("evidence"), list) else []
        backed = any(
            isinstance(e, dict) and e.get("type") == "DECISION"
            and isinstance(e.get("claim"), str)
            and ("registry" in e["claim"]
                 or any(c in e["claim"] for c in changed)
                 or (isinstance(e.get("evidence"), str) and "registry" in e["evidence"]))
            for e in ledger
        )
        if not backed:
            errs.add(name, "$.artifact.task_registry",
                     f"R9: 任务分母在 {prev_name} → {name} 间变更(涉及 {changed})但无 DECISION 背书——"
                     "改分母必须留痕:在新迭代 Evidence Ledger 加 type=DECISION 条目,claim 提及 registry 或所涉任务 id")


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
                    errs.add("", f"{path}[{i}]",
                             "R1: type=FACT/DECISION 的条目必须有非空 evidence(FACT=清单§x/命令输出/commit,DECISION=拍板锚点);无证据请标 HYPOTHESIS/UNKNOWN")

    # R2 — replan_required/blocked 必须给理由
    for name, art in artifacts:
        if art.get("status") in ("replan_required", "blocked"):
            reason = art.get("replan_reason")
            if not isinstance(reason, dict) or not reason:
                errs.add(name, "$.replan_reason",
                         "R2: status 为 replan_required/blocked 时必须填写 replan_reason")

    # R3 — WAITING_FOR_INPUT 与 resume_to 互相锁定
    if state:
        status = state.get("status")
        resume = state.get("resume_to")
        if status == "WAITING_FOR_INPUT" and resume not in RESUME_STAGES:
            errs.add("state.json", "$.resume_to",
                     "R3: status=WAITING_FOR_INPUT 时必须写 resume_to(PLANNING/EXECUTING/VERIFYING)")
        if status != "WAITING_FOR_INPUT" and resume is not None:
            errs.add("state.json", "$.resume_to",
                     "R3: 仅 WAITING_FOR_INPUT 状态允许携带 resume_to,恢复后应清除")

    # R4 — WAITING_FOR_UPSTREAM 与 upstream_gaps 互相锁定
    if state:
        status = state.get("status")
        gaps = state.get("upstream_gaps")
        if status == "WAITING_FOR_UPSTREAM" and (not isinstance(gaps, list) or len(gaps) == 0):
            errs.add("state.json", "$.upstream_gaps",
                     "R4: status=WAITING_FOR_UPSTREAM 时必须携带非空 upstream_gaps(回上游的缺口清单)")
        if status != "WAITING_FOR_UPSTREAM" and isinstance(gaps, list) and len(gaps) > 0:
            errs.add("state.json", "$.upstream_gaps",
                     "R4: 仅 WAITING_FOR_UPSTREAM 状态允许携带非空 upstream_gaps,上游更新恢复后应清空")


def load_upstream_ids(pev_dir, errs):
    """读取同轮 tasks/ 的最新结构化 artifact,提取任务 id 集合;无 tasks/ 返回 None。"""
    tasks_iter = pev_dir.parent / "tasks" / "iterations"
    if not tasks_iter.is_dir():
        return None
    files = sorted(tasks_iter.glob("*-artifact.json"))
    if not files:
        return None
    latest = files[-1]
    doc = load_json(latest, errs, label="上游 tasks/iterations/" + latest.name)
    if doc is None:
        errs.add("上游 tasks/iterations/" + latest.name, "$",
                 "上游结构化产物不可读——无法对账转录分母;修复上游或确认 plan_source 指向")
        return None
    body = doc.get("artifact")
    ids = set()
    if isinstance(body, dict):
        for phase in body.get("phases", []) or []:
            if not isinstance(phase, dict):
                continue
            for t in phase.get("tasks", []) or []:
                if isinstance(t, dict) and isinstance(t.get("id"), str):
                    ids.add(t["id"])
    if not ids:
        errs.add("上游 tasks/iterations/" + latest.name, "$",
                 "上游结构化产物里提取不到任务 id——确认它是 planning-and-task-breakdown 的产物")
    return ids


def main(argv):
    if len(argv) < 2:
        print("用法: python3 validate.py <PEV_DIR>   # 如 .pev/prd-2026-10-07/impl/")
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

    upstream_ids = load_upstream_ids(pev_dir, errs)
    vcs = state.get("vcs", "git") if isinstance(state, dict) else "git"

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

    # R10 — 登记册与 iterations/ 目录双向一致(文件名对账,不存内容副本)
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
                         f"R10: 文件存在于 iterations/ 但未登记进 state.{key}")
            for fname in sorted(reg_set - found[key]):
                errs.add("state.json", f"$.{key}",
                         f"R10: 登记的 {fname} 在 iterations/ 中不存在")

    # R5/R6 — 实施记录结构与范围纪律
    # 上游转录对账(R6)只对最新 artifact 做:上游 REPLAN 后,历史迭代的 registry
    # 与新上游不一致是合法中间态——当时转录对当时上游;分母变更另有 R9 把关。
    for idx, (name, art) in enumerate(artifacts):
        check_structure(art, name, errs, vcs)
        check_references(art, name, errs, upstream_ids if idx == len(artifacts) - 1 else None)

    # R9 — registry 跨迭代一致性(变更须有 DECISION 背书)
    check_registry_stability(artifacts, errs)

    # R7 — 门禁数字必须等于同迭代 artifact 算出的值(不跨迭代聚合)
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
                     f"R7: 缺少同迭代 {iter_no(name)}-artifact.json,无法比对门禁数字"
                     "(verification 与 artifact 各比各的,不跨迭代)")
            continue
        pct = compute_coverage(entry[1])
        vio = len(scope_violation_files(entry[1]))
        # R8 — PASS 必须双门禁达标;未达标的 REVISE/REPLAN/BLOCKED 是合法评审
        if pct is not None and doc.get("verdict") == "PASS" and (
                pct < GATE_COVERAGE - PCT_TOLERANCE or vio > GATE_VIOLATIONS):
            errs.add(name, "$.verdict",
                     f"R8: verdict=PASS 但门禁未达标(task_execution_pct={pct} 需={GATE_COVERAGE:g};"
                     f"scope_violations={vio} 需={GATE_VIOLATIONS})——任务没做完或范围跑偏,应判 REVISE,不得 PASS")
        coverage = doc.get("coverage")
        if not isinstance(coverage, dict) or pct is None:
            continue
        if not verify_fresh:
            continue
        claimed_pct = coverage.get("task_execution_pct")
        if isinstance(claimed_pct, (int, float)) and not isinstance(claimed_pct, bool) \
                and abs(claimed_pct - pct) > PCT_TOLERANCE:
            errs.add(name, "$.coverage.task_execution_pct",
                     f"R7: 声称 {claimed_pct},artifact 算出 {pct}——门禁数字必须来自脚本计算,不接受人工填写")
        claimed_vio = coverage.get("scope_violations")
        if isinstance(claimed_vio, int) and not isinstance(claimed_vio, bool) and claimed_vio != vio:
            errs.add(name, "$.coverage.scope_violations",
                     f"R7: 声称 {claimed_vio},artifact 算出 {vio}——门禁数字必须来自脚本计算,不接受人工填写")

    if errs:
        print(f"校验失败,{len(errs)} 个问题:")
        for e in errs.items:
            print(f"  - {e}")
        return 1
    print(f"OK: {pev_dir} 全部产物通过 schema 与语义规则校验")
    if upstream_ids is not None:
        print(f"上游对账:tasks/ 最新结构化产物任务 {len(upstream_ids)} 条,registry 转录一致")
    else:
        print("上游对账:未发现同轮 tasks/(外部清单场景),分母以 task_registry 为准")
    if verifications and state is not None and not verify_fresh:
        print(f"注: state.status={state.get('status')} —— 盘上 verification 视为上一轮历史产物,"
              "跳过 R7 门禁数字比对(REVISE 中间态;进入 VERIFYING/COMPLETE 后恢复比对)")
    if latest is not None:
        pct = compute_coverage(latest[1])
        if pct is not None:
            gate_ok = pct >= GATE_COVERAGE - PCT_TOLERANCE
            print(f"执行覆盖率(脚本计算,最新迭代):task_execution_pct={pct} 门禁(=100):{'通过' if gate_ok else '未通过'}")
        violations = scope_violation_files(latest[1])
        print(f"范围违规(脚本计算,最新迭代):scope_violations={len(violations)} 门禁(=0):{'通过' if not violations else '未通过'}")
        for rid, f in violations:
            print(f"  - 任务 {rid} 违规文件:{f}")
        body = latest[1].get("artifact", {})
        not_done = [(r.get("id"), r.get("status")) for r, _p in iter_records(latest[1])
                    if r.get("status") != "done"]
        if not_done:
            print(f"失败/延后任务(交 Verifier 处置):{', '.join(f'{i}({s})' for i, s in not_done)}")
        else:
            print("失败/延后任务:无")
        dev_count = sum(len(r.get("deviations") or []) for r, _p in iter_records(latest[1]))
        deferred = [tid for tid, e in registry_index(latest[1]).items() if e.get("deferred") is True]
        if dev_count:
            print(f"偏离声明共 {dev_count} 条(Verifier 逐条审 why 是否成立)")
        if deferred:
            print(f"延后任务:{', '.join(deferred)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
