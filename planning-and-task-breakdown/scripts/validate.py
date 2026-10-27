#!/usr/bin/env python3
"""planning-and-task-breakdown PEV 产物校验器(双端通用,仅依赖 Python 标准库)。

用法:
    python3 validate.py <PEV_DIR>      # PEV_DIR 为本 skill 工作目录,如 .pev/prd-2026-09-20/tasks/

按文件名后缀路由到 schemas/ 下对应 schema:
    state.json                    -> state.schema.json
    iterations/*-plan.json        -> plan.schema.json
    iterations/*-artifact.json    -> artifact.schema.json
    iterations/*-verification.json-> verification.schema.json

除 JSON Schema 子集(type/enum/required/properties/items/minItems/
minimum/maximum)外,强制以下语义规则——这些是状态机与任务清单的硬约束,靠肉眼最容易漏:
    R1  Evidence 条目 type=FACT 或 DECISION 时,evidence 必须是非空字符串
        (FACT 证据=上游产物 §x / 代码库路径;DECISION 证据=精修/拍板锚点)
    R2  artifact.status ∈ {replan_required, blocked} 时,replan_reason 必填
    R3  state.status=WAITING_FOR_INPUT 时,resume_to 必填;
        其他 status 下 resume_to 必须不存在
    R4  state.status=WAITING_FOR_UPSTREAM 时,upstream_gaps 必须非空;
        其他 status 下 upstream_gaps 必须为空
    R5  任务结构纪律:任务 id 与 inventory id 全局唯一;规模档位与文件数一致
        (XS=1 · S=1-2 · M=3-5 · L=6-8),超 8 文件必拆;验收标准 1-5 条
        (超过是任务过大信号);inventory 项 in_scope=false 时 note 必须非空
    R6  引用与依赖图:implements 引用的工作项存在;dependencies 引用的任务存在;
        依赖图无环(含自依赖);文档顺序不得违反拓扑序(前置任务必须排在后面任务之前);
        parallel_group 同组任务之间不得存在任何依赖路径(直接或传递)
    R7  verification.coverage.upstream_coverage_pct 必须等于**同迭代** artifact 直接算出
        的值(verification N ↔ artifact N,REVISE 轮的历史产物各比各的,不跨迭代聚合;
        同迭代 artifact 缺失时报错)。数字比对仅在 state.status ∈ {VERIFYING, COMPLETE}
        (评审落点)强制:其余状态(REVISE 轮"artifact 已改、旧 verification 未覆盖"的
        中间态)盘上 verification 视为上一轮历史产物,跳过比对并打印说明,回到评审落点
        即恢复比对
    R8  verdict=PASS 的 verification,其同迭代 artifact 算出的门禁必须达标
        (upstream_coverage_pct = 100)。范围内工作项漏了任务落点还判 PASS 是无效评审;
        REVISE/REPLAN/BLOCKED 不受限(覆盖未过正是打回理由)
    R9  多个迭代 artifact 并存时,相邻迭代的 inventory(工作项 id 集 + 各项
        in_scope/kind/anchor 取值)必须一致;有变更必须在新迭代 Evidence Ledger 里
        有 DECISION 背书(claim/锚点提及 inventory 或所涉工作项 id)。防止"漏拆任务
        就改分母"或"溯源锚点悄悄弱化"绕过覆盖门禁;title/note 措辞变化不查
    R10 state.plans / state.artifacts 登记册(文件名,不存内容副本)与
        iterations/ 目录双向一致

通过时汇总输出:最新迭代覆盖率与门禁结论、未覆盖工作项清单(范围内无任务落点者)、
L 档任务清单(交 Verifier 重点审是否还可拆)、并行组概览。

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

# 规模档位与文件数区间。超上限 8 一律拦截(XL 不存在,必拆)。
SIZE_FILE_RANGE = {"XS": (1, 1), "S": (1, 2), "M": (3, 5), "L": (6, 8)}
MAX_FILES = 8
MAX_AC = 5  # 验收标准条数上限,超过是任务过大信号
PCT_TOLERANCE = 0.05  # 允许 0.05 的舍入差(百分比四舍五入到一位小数)
GATE_COVERAGE = 100.0  # R8:范围内工作项覆盖门禁

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


def load_json(path, errs):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        errs.add(path.name, "$", f"无法读取/解析 JSON(须为 UTF-8): {e}")
        return None


def iter_tasks(art):
    """按文档顺序遍历 artifact 里的每个任务,产出 (task, json 路径)。"""
    body = art.get("artifact")
    if not isinstance(body, dict):
        return
    for pi, phase in enumerate(body.get("phases", [])):
        if not isinstance(phase, dict):
            continue
        for ti, task in enumerate(phase.get("tasks", [])):
            if isinstance(task, dict):
                yield task, f"$.artifact.phases[{pi}].tasks[{ti}]"


def task_ids(art):
    """文档顺序的任务 id 列表(含重复,供 R5 查重)。"""
    return [t.get("id") for t, _ in iter_tasks(art)]


def check_structure(art, file, errs):
    """R5 — 任务结构纪律:id 唯一、规模与文件数一致、验收标准条数、范围外登记。"""
    body = art.get("artifact")
    if not isinstance(body, dict):
        return

    # inventory id 唯一 + in_scope=false 须有理由
    inv = body.get("inventory")
    if isinstance(inv, list):
        ids = [i.get("id") for i in inv if isinstance(i, dict)]
        dup = sorted({i for i in ids if isinstance(i, str) and ids.count(i) > 1})
        if dup:
            errs.add(file, "$.artifact.inventory", f"R5: 工作项 id 重复 {dup}")
        for idx, item in enumerate(inv):
            if not isinstance(item, dict):
                continue
            if item.get("in_scope") is False:
                note = item.get("note")
                if not isinstance(note, str) or not note.strip():
                    errs.add(file, f"$.artifact.inventory[{idx}].note",
                             "R5: in_scope=false 的工作项必须在 note 写明理由(为什么范围外、后续怎么接)——范围收缩必须留痕")

    # 任务 id 唯一
    tids = task_ids(art)
    dup = sorted({t for t in tids if isinstance(t, str) and tids.count(t) > 1})
    if dup:
        errs.add(file, "$.artifact.phases", f"R5: 任务 id 重复 {dup}")

    # 规模档位 × 文件数;验收标准条数
    for task, path in iter_tasks(art):
        size = task.get("size")
        files = task.get("files_touched")
        if size in SIZE_FILE_RANGE and isinstance(files, list):
            lo, hi = SIZE_FILE_RANGE[size]
            n = len(files)
            if n > MAX_FILES:
                errs.add(file, f"{path}.files_touched",
                         f"R5: 预计改动 {n} 个文件,超过上限 {MAX_FILES}——任务过大,必须拆(XL 不存在)")
            elif not (lo <= n <= hi):
                errs.add(file, f"{path}.size",
                         f"R5: 规模档位 {size} 对应 {lo}-{hi} 个文件,实际声明 {n} 个——档位与文件数不一致")
        ac = task.get("acceptance_criteria")
        if isinstance(ac, list) and len(ac) > MAX_AC:
            errs.add(file, f"{path}.acceptance_criteria",
                     f"R5: 验收标准 {len(ac)} 条,超过上限 {MAX_AC}——条数爆表是任务过大信号,应拆")


def check_references(art, file, errs):
    """R6 — 引用与依赖图:悬空引用、环、文档序拓扑一致、并行组无内部依赖路径。"""
    body = art.get("artifact")
    if not isinstance(body, dict):
        return
    inv_ids = {i.get("id") for i in body.get("inventory", []) if isinstance(i, dict)}

    ordered = [t for t, _ in iter_tasks(art)]
    pos = {}
    for idx, t in enumerate(ordered):
        tid = t.get("id")
        if isinstance(tid, str) and tid not in pos:
            pos[tid] = idx

    # 悬空引用 + 文档序
    for t, path in iter_tasks(art):
        for r in t.get("implements", []) or []:
            if r not in inv_ids:
                errs.add(file, f"{path}.implements",
                         f"R6: 引用的工作项 {r!r} 不在 inventory 中(纯工程支撑任务也须登记 engineering_item,不留无落点任务)")
        for d in t.get("dependencies", []) or []:
            if d not in pos:
                errs.add(file, f"{path}.dependencies", f"R6: 依赖的任务 {d!r} 不存在(悬空引用)")
            elif pos.get(d, -1) > pos.get(t.get("id"), -1) or (d == t.get("id")):
                if d == t.get("id"):
                    errs.add(file, f"{path}.dependencies", f"R6: 任务 {d!r} 依赖自己")
                else:
                    errs.add(file, f"{path}.dependencies",
                             f"R6: 前置任务 {d!r} 排在本任务之后——文档顺序违反拓扑序,前置必须排前")

    # 环检测(Kahn)
    if pos:
        indeg = {tid: 0 for tid in pos}
        adj = {tid: [] for tid in pos}  # 前置 -> 后继
        for t, _p in iter_tasks(art):
            tid = t.get("id")
            if tid not in pos:
                continue
            for d in t.get("dependencies", []) or []:
                if d in pos and d != tid:
                    adj[d].append(tid)
                    indeg[tid] += 1
        queue = [tid for tid, deg in indeg.items() if deg == 0]
        seen = 0
        while queue:
            node = queue.pop()
            seen += 1
            for nxt in adj[node]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    queue.append(nxt)
        if seen < len(pos):
            in_cycle = sorted(tid for tid, deg in indeg.items() if deg > 0)
            errs.add(file, "$.artifact.phases", f"R6: 依赖图存在环,涉及 {in_cycle}——标出并拆/重挂,不硬排顺序")

    # 并行组:同组任务之间不得存在任何依赖路径(直接或传递)
    groups = {}
    for t, _p in iter_tasks(art):
        g = t.get("parallel_group")
        if isinstance(g, str) and g:
            groups.setdefault(g, []).append(t.get("id"))

    def prerequisites(tid):
        """tid 的全部传递前置(含直接)。"""
        seen = set()
        stack = []
        for t, _p in iter_tasks(art):
            if t.get("id") == tid:
                stack.extend(d for d in (t.get("dependencies") or []) if d in pos)
                break
        while stack:
            d = stack.pop()
            if d in seen:
                continue
            seen.add(d)
            for t, _p in iter_tasks(art):
                if t.get("id") == d:
                    stack.extend(x for x in (t.get("dependencies") or []) if x in pos)
                    break
        return seen

    reach_cache = {}
    for g, members in groups.items():
        for i, a in enumerate(members):
            if a not in reach_cache:
                reach_cache[a] = prerequisites(a)
            for b in members[i + 1:]:
                if b not in reach_cache:
                    reach_cache[b] = prerequisites(b)
                if a in reach_cache[b] or b in reach_cache[a]:
                    errs.add(file, "$.artifact.phases",
                             f"R6: 并行组 {g!r} 内 {a} 与 {b} 存在依赖路径——有依赖就不能同组,退回重划并行边界")


def compute_coverage(art):
    """R7/R8 — 从 artifact 直接算覆盖率:范围内工作项条条有任务落点。

    分母 = inventory 中 in_scope 非 False 的项(缺省视为 true);分子 = 至少被一个
    任务的 implements 引用的项。分母为 0 记 100(无范围即无缺口)。
    """
    body = art.get("artifact")
    if not isinstance(body, dict):
        return None
    inv = body.get("inventory")
    if not isinstance(inv, list):
        return None
    in_scope = [i.get("id") for i in inv
                if isinstance(i, dict) and i.get("in_scope") is not False and isinstance(i.get("id"), str)]
    implemented = set()
    for t, _p in iter_tasks(art):
        for r in t.get("implements", []) or []:
            if isinstance(r, str):
                implemented.add(r)
    if not in_scope:
        return 100.0
    return round(sum(1 for i in in_scope if i in implemented) / len(in_scope) * 100, 1)


def uncovered_items(art):
    """范围内但无任务落点的工作项 id 清单。"""
    body = art.get("artifact")
    if not isinstance(body, dict):
        return []
    implemented = set()
    for t, _p in iter_tasks(art):
        for r in t.get("implements", []) or []:
            if isinstance(r, str):
                implemented.add(r)
    return [i.get("id") for i in body.get("inventory", [])
            if isinstance(i, dict) and i.get("in_scope") is not False
            and isinstance(i.get("id"), str) and i.get("id") not in implemented]


def check_inventory_stability(artifacts, errs):
    """R9 — inventory 迭代间只许有 DECISION 背书的变更(防挪分母、防锚点弱化)。

    比较相邻迭代 artifact 的 inventory 结构(工作项 id 集 + 各项 in_scope/kind/anchor
    取值);有变化时,新迭代 Evidence Ledger 必须存在 type=DECISION 的条目且其 claim/锚点
    提及 inventory 或被改变的工作项 id。title/note 措辞变化不影响分母,不查。
    """
    if len(artifacts) < 2:
        return

    def structure(art):
        body = art.get("artifact")
        if not isinstance(body, dict):
            return None
        inv = body.get("inventory")
        if not isinstance(inv, list):
            return None
        return {i.get("id"): (i.get("in_scope") is not False, i.get("kind"), i.get("anchor"))
                for i in inv if isinstance(i, dict) and isinstance(i.get("id"), str)}

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
            and ("inventory" in e["claim"]
                 or any(c in e["claim"] for c in changed)
                 or (isinstance(e.get("evidence"), str) and "inventory" in e["evidence"]))
            for e in ledger
        )
        if not backed:
            errs.add(name, "$.artifact.inventory",
                     f"R9: 工作项登记在 {prev_name} → {name} 间变更(涉及 {changed})但无 DECISION 背书——"
                     "改分母必须留痕:在新迭代 Evidence Ledger 加 type=DECISION 条目,claim 提及 inventory 或所涉工作项 id")


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
                    errs.add("", f"{path}[{i}]", "R1: type=FACT/DECISION 的条目必须有非空 evidence(FACT=上游产物§x/代码库路径,DECISION=精修/拍板锚点);无证据请标 HYPOTHESIS/UNKNOWN")

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
        print("用法: python3 validate.py <PEV_DIR>   # 如 .pev/prd-2026-09-20/tasks/")
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

    # R5/R6 — 任务结构与依赖图
    for name, art in artifacts:
        check_structure(art, name, errs)
        check_references(art, name, errs)

    # R9 — inventory 跨迭代一致性(变更须有 DECISION 背书)
    check_inventory_stability(artifacts, errs)

    # R7 — 覆盖率数字必须等于同迭代 artifact 算出的值(不跨迭代聚合)
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
                     f"R7: 缺少同迭代 {iter_no(name)}-artifact.json,无法比对覆盖率"
                     "(verification 与 artifact 各比各的,不跨迭代)")
            continue
        pct = compute_coverage(entry[1])
        # R8 — PASS 必须过门禁;门禁未过的 REVISE/REPLAN/BLOCKED 是合法评审
        if pct is not None and doc.get("verdict") == "PASS" and pct < GATE_COVERAGE - PCT_TOLERANCE:
            errs.add(name, "$.verdict",
                     f"R8: verdict=PASS 但门禁未达标(upstream_coverage_pct={pct} 需={GATE_COVERAGE:g})——"
                     "范围内工作项还有漏拆,应判 REVISE 并补任务,不得 PASS")
        coverage = doc.get("coverage")
        if not isinstance(coverage, dict) or pct is None:
            continue
        if not verify_fresh:
            continue
        claimed = coverage.get("upstream_coverage_pct")
        if isinstance(claimed, (int, float)) and not isinstance(claimed, bool) and abs(claimed - pct) > PCT_TOLERANCE:
            errs.add(name, "$.coverage.upstream_coverage_pct",
                     f"R7: 声称 {claimed},artifact 算出 {pct}——门禁数字必须来自脚本计算,不接受人工填写")

    if errs:
        print(f"校验失败,{len(errs)} 个问题:")
        for e in errs.items:
            print(f"  - {e}")
        return 1
    print(f"OK: {pev_dir} 全部产物通过 schema 与语义规则校验")
    if verifications and state is not None and not verify_fresh:
        print(f"注: state.status={state.get('status')} —— 盘上 verification 视为上一轮历史产物,"
              "跳过 R7 覆盖率数字比对(REVISE 中间态;进入 VERIFYING/COMPLETE 后恢复比对)")
    if latest is not None:
        pct = compute_coverage(latest[1])
        if pct is not None:
            gate_ok = pct >= GATE_COVERAGE - PCT_TOLERANCE
            print(f"覆盖率(脚本计算,最新迭代):upstream_coverage_pct={pct} 门禁(=100):{'通过' if gate_ok else '未通过'}")
            gaps = uncovered_items(latest[1])
            if gaps:
                print(f"未覆盖工作项(范围内但无任务落点,交 Verifier 处置):{', '.join(str(g) for g in gaps)}")
            else:
                print("未覆盖工作项:无")
        l_sized = [t.get("id") for t, _p in iter_tasks(latest[1]) if t.get("size") == "L"]
        if l_sized:
            print(f"L 档任务(交 Verifier 重点审是否还可拆):{', '.join(str(x) for x in l_sized)}")
        groups = {}
        for t, _p in iter_tasks(latest[1]):
            g = t.get("parallel_group")
            if isinstance(g, str) and g:
                groups.setdefault(g, []).append(t.get("id"))
        if groups:
            detail = ";".join(f"{g}[{','.join(str(x) for x in m)}]" for g, m in sorted(groups.items()))
            print(f"并行组:{detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
