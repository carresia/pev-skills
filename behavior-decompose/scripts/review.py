#!/usr/bin/env python3
"""behavior-decompose 审查编排器(单一命令,阶段感知,只追加审查历史)。

用法:
    python3 scripts/review.py <decompose目录>

正常拆解运行只有这一个编排命令,不提供冻结输入、diff、机器检查、登记或
改状态的独立子命令。命令读取 state、当前 artifact、待处理 review 输入和
用户确认记录,只执行当前已确定的机器步骤,停在下一个需要模型或用户判断
的位置;重跑幂等。每次在 stdout 打印一个 JSON 结果,字段:
    ok / status / state_status / review / written / errors / warnings /
    next_action{actor,instruction,files} / resume{command,step}
退出码:0 = ok(含"停在等待模型/用户"的正常停点);1 = REJECTED/PAUSED 等错误。

阶段推进语义(按磁盘状态自动判定,REVISE 不是 state):
  1. artifact 已完成且没有待审输入 → 生成冻结输入与机器检查,置 VERIFYING,
     停在 Verifier 语义审查(next_action.actor=verifier);
  2. reviews/<id>/candidate.json 已写好 → 校验并提交 review,按 verdict 路由状态;
  3. 最新 review 为 PASS 且 reviews/confirmation.json 已写好 → 校验确认、
     渲染 output/catalog.md 并写 COMPLETE;
  4. REVISE/REPLAN/BLOCKED 在提交 review 时按状态机路由(EXECUTING /
     PLANNING+新迭代 / WAITING_FOR_INPUT|WAITING_FOR_SPEC)。

审查历史只追加:每次审查用唯一目录 reviews/r<NNN>/,已提交的 review 不覆盖。
state.reviews 登记册记录每个 review 的 ID、路径与 SHA-256,复算比对可检测
历史被覆盖或篡改(不能抵御同时改写全部文件的攻击者,完整防篡改依赖 git)。
"""

import hashlib
import json
import re
import subprocess
import sys
import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
SCHEMA_DIR = SKILL_ROOT / "schemas"
sys.path.insert(0, str(SCRIPT_DIR))
import validate  # 复用共享检查:schema 校验器、覆盖率、逐 story 缺口

PROTOCOL_VERSION = "2026-10-29.1"

NAMED_REQUIRED = ("artifact", "upstream", "rubric", "protocol")
VERDICTS = ("PASS", "REVISE", "REPLAN", "BLOCKED")
BLOCKING_SEVERITIES = ("BLOCKING", "HIGH")
PCT_TOLERANCE = 0.05


# ---------------------------------------------------------------- 基础工具

def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(path):
    return sha_bytes(Path(path).read_bytes())


def sha_obj(obj):
    return sha_bytes(canon(obj))


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except (OSError, ValueError) as e:
        return None, f"无法读取/解析 {path}: {e}"


def write_canonical(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canon(obj))


def copy_frozen(src, dst):
    """冻结副本逐字节复制原文件,保证 SHA-256 与命名输入一致。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(Path(src).read_bytes())


def code_sha256():
    """检查代码指纹:validate.py + review.py 自身。变化即检查结果过期。"""
    h = hashlib.sha256()
    for name in ("validate.py", "review.py"):
        h.update(name.encode("utf-8"))
        h.update((SCRIPT_DIR / name).read_bytes())
    return h.hexdigest()


def today():
    return datetime.date.today().isoformat()


class Result:
    def __init__(self):
        self.ok = True
        self.status = "WAITING"
        self.state_status = None
        self.review = None
        self.written = []
        self.errors = []
        self.warnings = []
        self.next_action = None
        self.resume_step = None

    def fail(self, status, *errors):
        self.ok = False
        self.status = status
        self.errors.extend(errors)

    def done(self, status):
        self.status = status

    def to_dict(self, decompose):
        return {
            "ok": self.ok,
            "status": self.status,
            "state_status": self.state_status,
            "review": self.review,
            "written": self.written,
            "errors": self.errors,
            "warnings": self.warnings,
            "next_action": self.next_action,
            "resume": {
                "command": f"python3 {SCRIPT_DIR / 'review.py'} {decompose}",
                "step": self.resume_step or self.status,
            },
        }


# ------------------------------------------------------------ 输入收集与哈希

def latest_registered(state, key):
    """登记册里编号最大的文件名(R9 保证与 iterations/ 一致)。"""
    names = [n for n in state.get(key, []) if isinstance(n, str)]
    if not names:
        return None
    return max(names, key=lambda n: int(re.match(r"(\d+)", n).group(1))
               if re.match(r"(\d+)", n) else -1)


def collect_named_inputs(decompose, state, art_path):
    """收集命名输入的路径与 SHA-256;ledger 以紧凑投影内嵌(可结构化 diff)。

    返回 (named, errors)。plan 无文件时记 null(REVISE 轮复用原 Plan 属正常,
    沿用登记册里最近一个 plan;一个都没有的旧运行记 null)。
    """
    named, errors = {}, []
    art_doc, err = read_json(art_path)
    if err or not isinstance(art_doc, dict):
        errors.append(f"artifact 无法读取: {err or '不是 JSON 对象'}")
        return None, errors

    def file_input(path):
        if path is None:
            return {"path": None, "sha256": None}
        p = Path(path)
        if not p.is_file():
            return None
        return {"path": str(p), "sha256": sha_file(p)}

    plan_name = latest_registered(state, "plans")
    plan_in = file_input(decompose / "iterations" / plan_name) if plan_name else {"path": None, "sha256": None}
    upstream_in = file_input(state.get("spec_source"))
    rubric_in = file_input(SKILL_ROOT / "rubrics" / "decomposition-review.md")
    protocol_in = file_input(SKILL_ROOT / "agents" / "verifier.md")

    for key, inp in (("plan", plan_in), ("upstream", upstream_in),
                     ("rubric", rubric_in), ("protocol", protocol_in)):
        if inp is None:
            errors.append(f"命名输入 {key} 缺失或不可读"
                          + (f":{state.get('spec_source')}" if key == "upstream" else ""))
    if errors:
        return None, errors

    ledger_projection = {
        "state_evidence": state.get("evidence", []) or [],
        "artifact_evidence": art_doc.get("evidence", []) or [],
    }
    named = {
        "artifact": {"path": str(art_path), "sha256": sha_file(art_path)},
        "plan": plan_in,
        "upstream": upstream_in,
        "ledger": {"path": None, "sha256": sha_obj(ledger_projection)},
        "rubric": rubric_in,
        "protocol": protocol_in,
    }
    return named, []


def named_digest(named):
    return sha_obj({k: v["sha256"] for k, v in named.items()})


# ---------------------------------------------------------------- 机器检查

def walk_nodes(art):
    """产出 (kind, id, node, parents);artifact 结构非法时返回空。"""
    body = art.get("artifact") if isinstance(art, dict) else None
    if not isinstance(body, dict) or not isinstance(body.get("epics"), list):
        return
    for epic in body["epics"]:
        if not isinstance(epic, dict):
            continue
        yield "epic", epic.get("id"), epic, ()
        for feat in epic.get("features", []) or []:
            if not isinstance(feat, dict):
                continue
            yield "feature", feat.get("id"), feat, (epic.get("id"),)
            for story in feat.get("stories", []) or []:
                if isinstance(story, dict):
                    yield "story", story.get("id"), story, (epic.get("id"), feat.get("id"))


def check_ids(art):
    ids = []
    for kind, sid, _node, _parents in walk_nodes(art):
        ids.append((kind, sid))
    problems = []
    seen = set()
    for kind, sid in ids:
        if not isinstance(sid, str) or not sid:
            problems.append(f"存在无 id 的 {kind}")
            continue
        if sid in seen:
            problems.append(f"id 重复:{sid}")
        seen.add(sid)
    return problems


def check_refs(art):
    known = {sid for _k, sid, _n, _p in walk_nodes(art)}
    problems = []
    body = art.get("artifact", {})
    for i, dep in enumerate(body.get("dependencies", []) or []):
        if not isinstance(dep, dict):
            continue
        for endpoint in ("from", "to"):
            if dep.get(endpoint) not in known:
                problems.append(f"dependencies[{i}].{endpoint} 指向不存在的条目 {dep.get(endpoint)!r}(悬空依赖)")
    return problems


def check_cycles(art):
    body = art.get("artifact", {})
    edges = {}
    for dep in body.get("dependencies", []) or []:
        if isinstance(dep, dict) and dep.get("type") == "blocked-by":
            edges.setdefault(dep.get("from"), set()).add(dep.get("to"))
    problems = []
    state_color = {}

    def visit(node, stack):
        if state_color.get(node) == 1:
            cycle = stack[stack.index(node):] + [node]
            problems.append("依赖成环:" + " -> ".join(str(x) for x in cycle))
            return
        if state_color.get(node) == 2 or node not in edges:
            return
        state_color[node] = 1
        for nxt in edges[node]:
            visit(nxt, stack + [node])
        state_color[node] = 2

    for node in list(edges):
        visit(node, [node])
        if problems:
            break
    return problems


def run_subprocess_validate(decompose):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "validate.py"), str(decompose)],
        capture_output=True, text=True)
    detail = proc.stdout.strip().splitlines()
    return proc.returncode, detail[0] if detail else ""


def load_committed_reviews(decompose, state):
    """按登记册顺序载入已提交 review;登记册与盘上不一致时记错误。"""
    errors, reviews = [], []
    reg = state.get("reviews", [])
    if not isinstance(reg, list):
        return ["state.reviews 不是数组"], reviews
    for entry in reg:
        if not isinstance(entry, dict):
            errors.append("state.reviews 含非对象条目")
            continue
        path = decompose / entry.get("path", "")
        doc, err = read_json(path)
        if err:
            errors.append(f"登记的 review 不可读({entry.get('id')}):{err}")
            continue
        try:
            if sha_file(path) != entry.get("sha256"):
                errors.append(f"review {entry.get('id')} 的 SHA-256 与登记册不符(历史被覆盖或篡改)")
        except OSError:
            errors.append(f"review {entry.get('id')} 文件缺失:{entry.get('path')}")
            continue
        doc["_path"] = str(path)
        reviews.append(doc)
    # 反向:盘上有 review.json 但未登记
    reviews_dir = decompose / "reviews"
    if reviews_dir.is_dir():
        registered = {e.get("path") for e in reg if isinstance(e, dict)}
        for rj in sorted(reviews_dir.glob("r*/review.json")):
            if f"reviews/{rj.parent.name}/review.json" not in registered:
                errors.append(f"reviews/{rj.parent.name}/review.json 存在但未登记进 state.reviews")
    return errors, reviews


def chain_and_findings(decompose, reviews):
    """校验审查链并累积必改项。返回 (baseline_ok, chain_errors, open_findings, all_findings)。

    链:按登记册顺序,previous_review 必须指向前一个 review;每份 review 绑定
    的 input 哈希、冻结 artifact 哈希须与盘上一致。基线 = 链上最近一份
    scope=full(链首必须是 full)。findings 按 id 累积,resolutions 后写覆盖先写
    (可重新打开);open = 未解决或最新 resolutions 标记 unresolved。
    """
    errors = []
    if not reviews:
        return False, errors, [], []
    if reviews[0].get("scope") != "full":
        errors.append(f"审查链首 {reviews[0].get('id')} 不是 full——没有可信完整基线")
    prev = None
    findings = {}   # id -> finding(含 origin_review)
    resolved = {}   # id -> bool(最新一次 resolution)
    for rv in reviews:
        rid = rv.get("id")
        if prev is not None and rv.get("previous_review") != prev.get("id"):
            errors.append(f"{rid} 的 previous_review={rv.get('previous_review')!r} 与前置 {prev.get('id')} 不符(断链)")
        rdir = Path(rv["_path"]).parent
        inp, err = read_json(rdir / "input.json")
        if err:
            errors.append(f"{rid} 的冻结 input 不可读:{err}")
        else:
            if sha_file(rdir / "input.json") != rv.get("input_sha256"):
                errors.append(f"{rid} 绑定的 input 哈希与盘上 input.json 不符")
            frozen, ferr = read_json(rdir / "artifact.json")
            if ferr or sha_file(rdir / "artifact.json") != rv.get("artifact_sha256"):
                errors.append(f"{rid} 绑定的 artifact 哈希与冻结副本不符")
        for f in rv.get("findings", []) or []:
            if isinstance(f, dict) and isinstance(f.get("id"), str):
                findings[f["id"]] = dict(f, origin_review=rid)
        for r in rv.get("resolutions", []) or []:
            if isinstance(r, dict) and isinstance(r.get("finding_id"), str):
                resolved[r["finding_id"]] = bool(r.get("resolved"))
        prev = rv
    baseline_ok = reviews[0].get("scope") == "full" and not errors
    open_findings = [f for fid, f in findings.items() if not resolved.get(fid, False)]
    return baseline_ok, errors, open_findings, list(findings.values())


def machine_checks(decompose, state, art_doc):
    """逐项确定性检查。返回 (checks, all_required_pass)。"""
    checks = []

    def add(cid, required, problems=None, status=None, detail="", exit_code=None):
        if status is None:
            status = "pass" if not problems else "fail"
        entry = {"id": cid, "required": required, "status": status,
                 "detail": detail or (";".join(problems) if problems else "ok")}
        if exit_code is not None:
            entry["exit_code"] = exit_code
        checks.append(entry)

    rc, first = run_subprocess_validate(decompose)
    add("CHK-VALIDATE", True,
        problems=[] if rc == 0 else [f"validate.py 退出码 {rc}:{first}"],
        exit_code=rc)

    structural = not isinstance(art_doc.get("artifact"), dict)
    add("CHK-IDS-UNIQUE", True,
        problems=["artifact 结构不可解析"] if structural else check_ids(art_doc))
    add("CHK-REFS-RESOLVE", True,
        problems=["artifact 结构不可解析"] if structural else check_refs(art_doc))
    add("CHK-DEP-CYCLES", True,
        problems=["artifact 结构不可解析"] if structural else check_cycles(art_doc))

    reg_errors, reviews = load_committed_reviews(decompose, state)
    has_history = bool(state.get("reviews"))
    if has_history:
        _ok, chain_errors, _open, _all = chain_and_findings(decompose, reviews)
        add("CHK-REVIEW-REGISTRY", True, problems=reg_errors)
        add("CHK-CHAIN", True, problems=chain_errors)
    else:
        add("CHK-REVIEW-REGISTRY", False, status="skipped", detail="尚无已提交 review")
        add("CHK-CHAIN", False, status="skipped", detail="尚无已提交 review")
        if reg_errors:
            checks[-2]["status"] = "fail"
            checks[-2]["detail"] = ";".join(reg_errors)

    add("CHK-INPUT-CONSISTENCY", True, detail="命名输入均已读取并记录哈希")
    ok = all(c["status"] == "pass" for c in checks if c["required"])
    return checks, ok


# ------------------------------------------------------- diff 与影响闭包

def diff_stories(prev_art, cur_art):
    prev = {sid: (node, parents) for kind, sid, node, parents in walk_nodes(prev_art) if kind == "story"}
    cur = {sid: (node, parents) for kind, sid, node, parents in walk_nodes(cur_art) if kind == "story"}
    added = sorted(set(cur) - set(prev))
    removed = sorted(set(prev) - set(cur))
    changed, moved = [], []
    for sid in sorted(set(prev) & set(cur)):
        p_node, p_par = prev[sid]
        c_node, c_par = cur[sid]
        if p_par != c_par:
            moved.append({"id": sid, "from": list(p_par), "to": list(c_par)})
        fields = [k for k in set(p_node) | set(c_node)
                  if canon(p_node.get(k)) != canon(c_node.get(k))]
        if fields:
            changed.append({"id": sid, "changed_fields": sorted(fields)})
    return added, removed, changed, moved


def free_text_strings(art):
    """收集 artifact 树里的全部自由文本(标题、理由、note、blocks 等)。"""
    out = []

    def walk(node):
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(art.get("artifact", {}))
    return out


def mentions_id(texts, sid):
    pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(sid)}(?![A-Za-z0-9])")
    return any(pat.search(t) for t in texts)


def diff_and_impact(prev_art, cur_art):
    """确定性变更清单 + 影响闭包。返回 (diff, gaps)。

    稳定 ID(epic/feature/story)按 ID 比较;scenario 无稳定 ID 按索引比较并
    标记风险。自由文本只解析明确的 ID 出现;被删除 ID 仍被自由文本引用视为
    影响不确定(gap),不得记为无影响。
    """
    added, removed, changed, moved = diff_stories(prev_art, cur_art)
    p_body, c_body = prev_art.get("artifact", {}), cur_art.get("artifact", {})

    dep_diff = {"added": [], "removed": []}
    def dep_set(body):
        return {(d.get("from"), d.get("to"), d.get("type"))
                for d in body.get("dependencies", []) or [] if isinstance(d, dict)}
    p_deps, c_deps = dep_set(p_body), dep_set(c_body)
    dep_diff["added"] = sorted(list(c_deps - p_deps))
    dep_diff["removed"] = sorted(list(p_deps - c_deps))

    defaults_changed = canon(p_body.get("category_defaults")) != canon(c_body.get("category_defaults"))
    top_changed = [k for k in ("status", "decisions", "unresolved", "replan_reason")
                   if canon(prev_art.get(k)) != canon(cur_art.get(k))]

    story_index_risk = any("scenarios" in e["changed_fields"] for e in changed)

    texts = free_text_strings(cur_art)
    gaps = []
    dangling_mentions = []
    for sid in removed:
        if mentions_id(texts, sid):
            dangling_mentions.append(sid)
    if dangling_mentions:
        gaps.append(f"被删除的条目 {dangling_mentions} 仍被目录自由文本引用,影响范围不确定")

    parents = {}
    for kind, sid, _node, pars in walk_nodes(cur_art):
        parents[sid] = list(pars)
    affected = set(added) | {e["id"] for e in changed} | {e["id"] for e in moved}
    if defaults_changed:
        affected |= {sid for kind, sid, _n, _p in walk_nodes(cur_art) if kind == "story"}
    parent_closure = sorted({p for sid in affected for p in parents.get(sid, [])})
    affected_deps = [e for e in dep_diff["added"] + dep_diff["removed"]
                     if any(ep in affected or ep in removed for ep in e[:2])]
    context_mentions = sorted(sid for sid in affected if mentions_id(texts, sid))

    diff = {
        "artifact_sha256": {"before": sha_obj(prev_art), "after": sha_obj(cur_art)},
        "stories": {"added": added, "removed": removed, "changed": changed, "moved": moved},
        "dependencies": {k: [list(e) for e in v] for k, v in dep_diff.items()},
        "category_defaults_changed": defaults_changed,
        "top_level_changed": top_changed,
        "scenario_index_compare_risk": story_index_risk,
    }
    impact = {
        "affected_ids": sorted(affected),
        "parent_closure": parent_closure,
        "affected_dependencies": [list(e) for e in affected_deps],
        "free_text_mentions_of_changed": context_mentions,
        "removed_ids": removed,
    }
    return diff, impact, gaps


def diff_ledger(prev_projection, cur_projection):
    def keys(proj):
        return [(e.get("claim"), e.get("type")) for e in
                (proj.get("state_evidence", []) + proj.get("artifact_evidence", []))
                if isinstance(e, dict)]
    p, c = keys(prev_projection), keys(cur_projection)
    return {"added": [list(x) for x in c if x not in p],
            "removed": [list(x) for x in p if x not in c]}


# -------------------------------------------------------------- scope 决策

def valid_full_approval(decompose, digest):
    """读取 reviews/full-approval.json;绑定 named_inputs_digest 才有效。"""
    doc, err = read_json(decompose / "reviews" / "full-approval.json")
    if err or not isinstance(doc, dict):
        return None
    if doc.get("named_inputs_digest") == digest:
        return doc
    return None


# ------------------------------------------------------------ 输入生成/复用

def build_input(decompose, state, res):
    """生成冻结输入对象。返回 (input_obj | None)。失败写 res.errors。"""
    art_name = latest_registered(state, "artifacts")
    if not art_name:
        res.fail("WAITING", "登记册没有 artifact——Executor 完成后再审查")
        return None
    art_path = decompose / "iterations" / art_name
    art_doc, err = read_json(art_path)
    if err:
        res.fail("REJECTED", f"当前 artifact 不可读:{err}")
        return None
    named, errors = collect_named_inputs(decompose, state, art_path)
    if errors:
        res.fail("REJECTED", *errors)
        return None

    reg_errors, reviews = load_committed_reviews(decompose, state)
    if reg_errors:
        res.fail("REJECTED", *reg_errors)
        return None

    digest = named_digest(named)
    scope, prev_review, diff, impact, ledger_diff = "full", None, None, None, None
    plan_diff = None
    gaps = []

    if reviews:
        prev_review = reviews[-1]
        prev_rdir = Path(prev_review["_path"]).parent
        prev_input, err = read_json(prev_rdir / "input.json")
        prev_art, aerr = read_json(prev_rdir / "artifact.json")
        if err or aerr or sha_file(prev_rdir / "input.json") != prev_review.get("input_sha256"):
            res.fail("REJECTED",
                     f"前置 review {prev_review.get('id')} 的冻结输入/副本与登记不符,无法推导增量基线")
            return None
        prev_named = prev_input.get("named_inputs", {})
        approval = valid_full_approval(decompose, digest)
        if approval:
            scope = "full"  # 用户明确批准的再次 full(批准绑定当前命名输入)
        else:
            scope = "delta"
            if named["upstream"]["sha256"] != prev_named.get("upstream", {}).get("sha256"):
                gaps.append("上游 spec 变更,且无可核验的旧版本——影响范围无法确定")
            if named["rubric"]["sha256"] != prev_named.get("rubric", {}).get("sha256") \
                    or named["protocol"]["sha256"] != prev_named.get("protocol", {}).get("sha256"):
                gaps.append("审查标准(rubric/协议)变更,旧版本不可得——影响范围无法确定")
            prev_plan = prev_named.get("plan", {})
            if named["plan"]["sha256"] and named["plan"]["sha256"] == prev_plan.get("sha256"):
                pass  # plan 未变
            elif named["plan"]["path"] == prev_plan.get("path"):
                gaps.append("同迭代 Plan 文件被改写,旧版本不可得——影响范围无法确定")
            elif named["plan"]["sha256"]:
                # 新迭代换了 Plan 文件:旧 Plan 仍在 iterations/,可核验地比对
                old_doc, oerr = read_json(prev_plan.get("path") or "")
                new_doc, nerr = read_json(named["plan"]["path"])
                if oerr or nerr:
                    gaps.append("Plan 新旧版本无法读取,影响范围无法确定")
                else:
                    plan_diff = {
                        "old": prev_plan.get("path"), "new": named["plan"]["path"],
                        "changed_keys": sorted(k for k in set(old_doc) | set(new_doc)
                                               if canon(old_doc.get(k)) != canon(new_doc.get(k))),
                    }
            if not gaps:
                diff, impact, dgaps = diff_and_impact(prev_art, art_doc)
                gaps.extend(dgaps)
                ledger_diff = diff_ledger(prev_input.get("ledger_projection", {}),
                                          json.loads(json.dumps(
                                              {"state_evidence": state.get("evidence", []) or [],
                                               "artifact_evidence": art_doc.get("evidence", []) or []})))
            if gaps:
                res.fail("PAUSED",
                         *gaps,
                         "影响范围无法界定:补充可核验材料,或由用户批准再次 full"
                         "(写 reviews/full-approval.json,绑定 named_inputs_digest="
                         f"{digest},记录决定来源)")
                return None
    else:
        legacy = any((decompose / "iterations").glob("*-verification.json"))
        if legacy:
            approval = valid_full_approval(decompose, digest)
            if not approval:
                res.fail("PAUSED",
                         "旧运行存在无法绑定冻结输入的审查记录,不能作为新协议基线;"
                         "须用户批准 full 建立可信基线(写 reviews/full-approval.json,"
                         f"绑定 named_inputs_digest={digest},记录决定来源)")
                return None

    _ok, chain_errors, open_findings, _all = chain_and_findings(decompose, reviews)
    if chain_errors:
        res.fail("REJECTED", *chain_errors)
        return None

    checks, checks_ok = machine_checks(decompose, state, art_doc)
    if not checks_ok:
        res.fail("REJECTED",
                 "机器检查存在必需项失败/跳过/缺失,不派发 Verifier:",
                 *[f"{c['id']}:{c['detail']}" for c in checks if c["required"] and c["status"] != "pass"])
        return None

    scenario_pct, critical_pct = validate.compute_coverage([("x", art_doc)])

    next_seq = (max(int(m.group(1)) for m in
                   (re.match(r"r(\d+)", e.get("id", "")) for e in state.get("reviews", [])
                    if isinstance(e, dict)) if m) + 1) if state.get("reviews") else 1
    pending_dirs = [d.name for d in (decompose / "reviews").glob("r*")
                    if d.is_dir() and (d / "input.json").exists() and not (d / "review.json").exists()] \
        if (decompose / "reviews").is_dir() else []
    if pending_dirs:
        next_seq = max(next_seq, max(int(re.match(r"r(\d+)", n).group(1)) for n in pending_dirs))

    return {
        "protocol_version": PROTOCOL_VERSION,
        "review_id": f"r{next_seq:03d}",
        "scope": scope,
        "iteration": state.get("iteration"),
        "named_inputs": named,
        "named_inputs_digest": digest,
        "ledger_projection": {
            "state_evidence": state.get("evidence", []) or [],
            "artifact_evidence": art_doc.get("evidence", []) or [],
        },
        "previous_review": prev_review.get("id") if prev_review else None,
        "diff": diff,
        "impact_closure": impact,
        "ledger_diff": ledger_diff,
        "plan_diff": plan_diff,
        "open_findings": [
            {"id": f["id"], "kind": f.get("kind"), "severity": f.get("severity"),
             "what": f.get("what"), "origin_review": f.get("origin_review")}
            for f in open_findings],
        "coverage": {"scenario_category_pct": scenario_pct, "critical_risk_pct": critical_pct},
        "checks": checks,
        "code_sha256": code_sha256(),
    }


def dispatch(decompose, state, res):
    """生成/复用待审输入并停在 Verifier 语义审查。"""
    # 修订重审开始时先撤旧投影:它属于上一次已提交审查、对应旧 artifact,
    # 留着会让 validate.py R8 在"artifact 已改、尚未重审"的中间态误报;
    # 提交新 review 时按新结论重写投影(validate.py 容忍投影缺失)
    if state.get("status") == "EXECUTING":
        art_name0 = latest_registered(state, "artifacts")
        if art_name0:
            n = int(re.match(r"(\d+)", art_name0).group(1))
            (decompose / "iterations" / f"{n:02d}-verification.json").unlink(missing_ok=True)

    pending = None
    reviews_dir = decompose / "reviews"
    if reviews_dir.is_dir():
        for d in sorted(reviews_dir.glob("r*")):
            if d.is_dir() and (d / "input.json").exists() and not (d / "review.json").exists():
                pending = d
                break

    inp = build_input(decompose, state, res)
    if inp is None:
        return
    rdir = reviews_dir / inp["review_id"]
    art_path = decompose / "iterations" / latest_registered(state, "artifacts")

    if pending is not None and pending.name == inp["review_id"]:
        old, err = read_json(pending / "input.json")
        if err is None and sha_obj(old) == sha_obj(inp):
            res.done("DISPATCHED")  # 幂等复用:输入未变
        else:
            write_canonical(rdir / "input.json", inp)   # 未提交的待审输入可重建
            copy_frozen(art_path, rdir / "artifact.json")
            res.written += [str(rdir / "input.json"), str(rdir / "artifact.json")]
            res.warnings.append("待审输入因命名输入变化已重建(未提交,不涉及历史)")
            res.done("DISPATCHED")
    else:
        write_canonical(rdir / "input.json", inp)
        copy_frozen(art_path, rdir / "artifact.json")
        res.written += [str(rdir / "input.json"), str(rdir / "artifact.json")]
        res.done("DISPATCHED")

    # 冻结副本与当前 artifact 逐字节一致(复用路径兜底)
    if sha_file(rdir / "artifact.json") != inp["named_inputs"]["artifact"]["sha256"]:
        copy_frozen(art_path, rdir / "artifact.json")

    if state.get("status") == "EXECUTING":
        state["status"] = "VERIFYING"
        write_canonical(decompose / "state.json", state)
        res.written.append(str(decompose / "state.json"))

    res.state_status = state["status"]
    res.review = {"id": inp["review_id"], "scope": inp["scope"],
                  "path": f"reviews/{inp['review_id']}/input.json"}
    upstream = inp["named_inputs"]["upstream"]["path"]
    res.next_action = {
        "actor": "verifier",
        "instruction": (
            f"独立语义审查(scope={inp['scope']}):只依据文件,写 reviews/{inp['review_id']}/candidate.json。"
            + ("首次完整审查:对照上游逐条审查完整目录。" if inp["scope"] == "full"
               else "逐项核销 open_findings、核验 diff/impact_closure 覆盖的变更及其影响闭包,未变内容不重复审查。")),
        "files": [str(rdir / "input.json"), str(rdir / "artifact.json"),
                  inp["named_inputs"]["plan"]["path"], upstream,
                  str(SKILL_ROOT / "rubrics" / "decomposition-review.md"),
                  str(SKILL_ROOT / "agents" / "verifier.md")],
    }
    res.resume_step = "await candidate.json → 重跑本命令提交"


# ------------------------------------------------------------ candidate 提交

def candidate_schema_errors(cand):
    problems = []
    if not isinstance(cand, dict):
        return ["candidate 不是 JSON 对象"]
    for key in ("verdict", "scope", "input_sha256", "scores", "coverage",
                "critical_issues", "required_changes", "resolutions"):
        if key not in cand:
            problems.append(f"candidate 缺字段 {key}")
    if problems:
        return problems
    if cand["verdict"] not in VERDICTS:
        problems.append(f"verdict 非法:{cand['verdict']!r}")
    if cand["scope"] not in ("full", "delta"):
        problems.append(f"scope 非法:{cand['scope']!r}")
    for listkey in ("critical_issues", "required_changes", "resolutions"):
        if not isinstance(cand[listkey], list):
            problems.append(f"{listkey} 不是数组")
    return problems


def render_catalog(decompose, state, art_doc, review):
    """按 templates/catalog.md 结构从 artifact 机械渲染(确定性,不自由发挥)。"""
    body = art_doc["artifact"]
    scenario_pct, critical_pct = validate.compute_coverage([("x", art_doc)])
    g_app = [c for c in body["category_defaults"].get("applicable", [])]
    g_inapp = [f"{i.get('what')}({i.get('reason')})" for i in body["category_defaults"].get("inapplicable", [])]
    L = []
    L.append(f"# 行为目录 — {state['objective']['goal']}")
    L.append("")
    L.append(f"> 上游:{state['spec_source']} · 迭代 {state['iteration']} · "
             f"Verdict {review['verdict']} · 生成于 {review.get('date', '')}")
    L.append(">")
    L.append(f"> 覆盖门禁:场景类别 {scenario_pct}%(≥90%) · P0/P1 风险类 {critical_pct}%(须 100%)")
    L.append(">")
    L.append(f"> 全局场景表态:适用 {', '.join(g_app)} · 全局豁免 {', '.join(g_inapp) or '无'}")
    L.append("")
    L.append("本目录止于产品行为。技术选型 → `architecture-design`;代码级任务 → `planning-and-task-breakdown`。")
    L.append("")
    L.append("## 残留与未决(交下游前须过目)")
    L.append("")
    L.append("> 单轮评审通过不等于零残留。下表汇总最新 review 的 warnings 与脚本「逐 story 适用未覆盖」清单,交下游时一并移交。")
    L.append("")
    L.append("| 级别 | 条目 | 处置 |")
    L.append("|---|---|---|")
    rows = 0
    for w in review.get("warnings", []) or []:
        L.append(f"| WARN | {w} | 见最新 review |")
        rows += 1
    for sid, missing in validate.per_story_gaps(art_doc):
        L.append(f"| GAP | {sid} 缺 {', '.join(missing)} | 交下游关注 |")
        rows += 1
    if not rows:
        L.append("| - | 无 | - |")
    L.append("")
    L.append("## 依赖总览")
    L.append("")
    L.append("| 项 | 依赖 | 类型 | 说明 |")
    L.append("|---|---|---|---|")
    deps = body.get("dependencies", []) or []
    if deps:
        for d in deps:
            L.append(f"| {d.get('from')} | {d.get('to')} | {d.get('type')} | {d.get('note', '')} |")
    else:
        L.append("| - | - | - | 无产品级依赖 |")
    L.append("")

    def esc(s):
        return str(s).replace("|", "\\|").replace("\n", " ")

    for epic in body.get("epics", []):
        L.append(f"## {esc(epic.get('id'))}: {esc(epic.get('title'))}")
        L.append("")
        L.append(f"**Scope**:{esc(epic.get('scope', ''))}")
        L.append(f"**Success Criteria**:{esc(epic.get('success_criteria', ''))}")
        L.append("")
        for feat in epic.get("features", []):
            L.append(f"### {esc(feat.get('id'))}: {esc(feat.get('title'))}")
            L.append("")
            L.append("| Story | 点数 | 优先级 | 溯源 |")
            L.append("|---|---|---|---|")
            for st in feat.get("stories", []):
                L.append(f"| {esc(st['id'])} {esc(st['title'])} | {st['points']} | "
                         f"{st['priority']} | {esc(st.get('trace', ''))} |")
            L.append("")
            for st in feat.get("stories", []):
                L.append(f"#### {esc(st['id'])}: {esc(st['title'])}")
                L.append("")
                L.append("**Acceptance Criteria**")
                for ac in st.get("acceptance_criteria", []):
                    L.append(f"- {ac}")
                L.append("")
                L.append("**Scenarios**")
                L.append("| 类别 | Given | When | Then | 溯源 |")
                L.append("|---|---|---|---|---|")
                for sc in st.get("scenarios", []):
                    L.append(f"| {sc['class']} | {esc(sc['given'])} | {esc(sc['when'])} | "
                             f"{esc(sc['then'])} | {esc(sc.get('trace', ''))} |")
                L.append("")
    L.append("## DECISION 汇总(用户拍板记录)")
    L.append("")
    L.append("| 决定 | 锚点 |")
    L.append("|---|---|")
    decisions = [e for e in (state.get("evidence", []) or []) + (art_doc.get("evidence", []) or [])
                 if isinstance(e, dict) and e.get("type") == "DECISION"]
    if decisions:
        for e in decisions:
            L.append(f"| {esc(e.get('claim', ''))} | {esc(e.get('evidence', ''))} |")
    else:
        L.append("| 无 | - |")
    L.append("")
    return "\n".join(L)


def write_verification_projection(decompose, state, review, art_doc):
    """把最新 review 投影为旧协议 iterations/<N>-verification.json(validate.py 兼容)。"""
    n = int(re.match(r"(\d+)", latest_registered(state, "artifacts")).group(1))
    proj = {
        "verdict": review["verdict"],
        "scores": review["scores"],
        "coverage": review["coverage"],
        "strengths": review.get("strengths", []),
        "critical_issues": [
            {"what": f.get("what"), "why": f.get("why"), "change": f.get("change")}
            for f in review.get("findings", []) if f.get("kind") == "critical"],
        "warnings": review.get("warnings", []),
        "required_changes": [
            f"{f.get('what')}(why:{f.get('why')};change:{f.get('change')})"
            for f in review.get("findings", []) if f.get("kind") == "required_change"],
        "evidence_gaps": review.get("evidence_gaps", []),
        "confidence": review.get("confidence", "medium"),
    }
    write_canonical(decompose / "iterations" / f"{n:02d}-verification.json", proj)


def route_state_for_review(decompose, state, review, art_doc):
    """按 verdict 路由状态(REVISE 不是 state)。返回 (结果标签, next_action, written)。"""
    written = []
    if review["verdict"] == "PASS":
        state["status"] = "VERIFYING"
        out = decompose / "output" / "catalog.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_catalog(decompose, state, art_doc, review), encoding="utf-8")
        written.append(str(out))
        return "AWAIT_USER_CONFIRMATION", {
            "actor": "user",
            "instruction": "渲染稿已生成(output/catalog.md)。用户确认交付后写 reviews/confirmation.json"
                           f"(date/artifact_sha256={review['artifact_sha256']}/named_inputs_digest 见 input.json),"
                           "再重跑本命令完成。",
            "files": [str(out)],
        }, written
    if review["verdict"] == "REVISE":
        state["status"] = "EXECUTING"
        return "COMMITTED", {"actor": "executor",
                             "instruction": "按 review 必改项修订目录;完成后重跑本命令进入下一轮审查。",
                             "files": []}, written
    if review["verdict"] == "REPLAN":
        state["status"] = "PLANNING"
        state["iteration"] = int(state.get("iteration", 0)) + 1
        return "COMMITTED", {"actor": "planner",
                             "instruction": f"按 review 重规划;新迭代号 {state['iteration']},产物登记进 state 后重跑本命令。",
                             "files": []}, written
    # BLOCKED
    routing = review.get("blocked_routing") or {"kind": "WAITING_FOR_INPUT"}
    if routing.get("kind") == "WAITING_FOR_SPEC":
        state["status"] = "WAITING_FOR_SPEC"
        state["spec_gaps"] = routing.get("spec_gaps") or []
    else:
        state["status"] = "WAITING_FOR_INPUT"
        state["resume_to"] = "VERIFYING"
    return "COMMITTED", {"actor": "user",
                         "instruction": "存在未决缺口,等待用户三选一(回上游/上游补充/直接拍板);处置后按 SKILL 流程恢复并重跑本命令。",
                         "files": []}, written


def commit(decompose, state, rdir, res):
    """校验 candidate 并提交 review、更新登记册、路由状态。"""
    inp, err = read_json(rdir / "input.json")
    if err:
        res.fail("REJECTED", f"待审输入不可读:{err}")
        return
    # 输入仍与盘上一致(命名输入重算);失效则作废 candidate,让下次运行重建输入
    rebuilt, _ = collect_named_inputs(decompose, state, Path(inp["named_inputs"]["artifact"]["path"]))
    if rebuilt is None or named_digest(rebuilt) != inp["named_inputs_digest"]:
        (rdir / "candidate.json").unlink(missing_ok=True)
        res.fail("REJECTED", "命名输入已变化,当前待审输入失效——candidate 已作废,重跑命令重建输入后再审")
        return
    if code_sha256() != inp.get("code_sha256"):
        res.fail("REJECTED", "检查代码指纹变化,既有机器检查结果过期——重跑命令重建输入后再审")
        return

    cand, err = read_json(rdir / "candidate.json")
    if err:
        res.fail("REJECTED", f"candidate 不可读:{err}")
        return
    problems = candidate_schema_errors(cand)
    if problems:
        res.fail("REJECTED", *problems)
        return
    if cand["scope"] != inp["scope"]:
        res.fail("REJECTED", f"candidate scope={cand['scope']} 与待审输入 scope={inp['scope']} 不符")
        return
    if cand["input_sha256"] != sha_obj(inp):
        res.fail("REJECTED", "candidate 未绑定当前待审输入哈希(须填 input.json 的 SHA-256)")
        return

    art_doc, _ = read_json(Path(inp["named_inputs"]["artifact"]["path"]))
    reg_errors, reviews = load_committed_reviews(decompose, state)
    if reg_errors:
        res.fail("REJECTED", *reg_errors)
        return
    baseline_ok, chain_errors, open_findings, all_findings = chain_and_findings(decompose, reviews)
    if chain_errors:
        res.fail("REJECTED", *chain_errors)
        return

    # 覆盖率数字必须来自脚本计算(R6/R8 同口径)
    scenario_pct, critical_pct = validate.compute_coverage([("x", art_doc)])
    cov = cand.get("coverage", {})
    for key, computed in (("scenario_category_pct", scenario_pct), ("critical_risk_pct", critical_pct)):
        claimed = cov.get(key)
        if not isinstance(claimed, (int, float)) or isinstance(claimed, bool) or abs(claimed - computed) > PCT_TOLERANCE:
            res.fail("REJECTED", f"coverage.{key} 声称 {claimed},脚本算出 {computed}——门禁数字必须来自脚本计算")
            return
    if cand["verdict"] == "PASS" and (scenario_pct < validate.GATE_SCENARIO_MIN - PCT_TOLERANCE
                                      or critical_pct < validate.GATE_CRITICAL_MIN - PCT_TOLERANCE):
        res.fail("REJECTED", f"PASS 但门禁未达标(scenario={scenario_pct} 需≥{validate.GATE_SCENARIO_MIN:g},"
                             f"critical={critical_pct} 需={validate.GATE_CRITICAL_MIN:g})——应判 REVISE")
        return

    # 发现核销:每个待审输入给出的 open finding 必须逐项表态,不得字符串相似度猜
    open_ids = {f["id"] for f in inp.get("open_findings", [])}
    res_ids = [r.get("finding_id") for r in cand["resolutions"] if isinstance(r, dict)]
    if len(res_ids) != len(set(res_ids)):
        res.fail("REJECTED", "resolutions 存在重复 finding_id")
        return
    if set(res_ids) != open_ids:
        missing = sorted(open_ids - set(res_ids))
        extra = sorted(set(res_ids) - open_ids)
        res.fail("REJECTED", f"发现核销不完整:缺 {missing or '无'}、多 {extra or '无'}——每个未关闭必改项逐项 resolved|unresolved")
        return
    for r in cand["resolutions"]:
        if not isinstance(r.get("resolved"), bool):
            res.fail("REJECTED", f"resolution {r.get('finding_id')} 缺 resolved 布尔值")
            return

    # 新发现分配稳定 ID(跨运行不回收;已用 ID 不得复用)
    used = {f["id"] for f in all_findings}
    seq = len(all_findings)
    findings = []
    for issue in cand.get("critical_issues", []):
        if not isinstance(issue, dict) or issue.get("severity") not in BLOCKING_SEVERITIES:
            continue  # 非阻塞级别不进必改账(与 verdict!=PASS 才有阻塞发现一致)
        seq += 1
        fid = f"F{seq:03d}"
        while fid in used:
            seq += 1
            fid = f"F{seq:03d}"
        findings.append({"id": fid, "kind": "critical", "severity": issue.get("severity"),
                         "what": issue.get("what"), "why": issue.get("why"),
                         "change": issue.get("change")})
    for rc in cand.get("required_changes", []):
        if not isinstance(rc, dict):
            continue
        seq += 1
        fid = f"F{seq:03d}"
        while fid in used:
            seq += 1
            fid = f"F{seq:03d}"
        findings.append({"id": fid, "kind": "required_change", "severity": rc.get("severity", "HIGH"),
                         "what": rc.get("what"), "why": rc.get("why"), "change": rc.get("change")})

    if cand["verdict"] == "PASS" and findings:
        res.fail("REJECTED", "PASS 但携带阻塞级发现/必改项——须判 REVISE 并保留发现")
        return
    if cand["verdict"] == "PASS" and any(not r.get("resolved") for r in cand["resolutions"]):
        res.fail("REJECTED", "PASS 但存在未解决(resolved=false)的必改项——须先修复或判 REVISE")
        return

    # BLOCKED 路由的前置校验(在写盘之前,避免半提交)
    blocked_routing = None
    if cand["verdict"] == "BLOCKED":
        blocked = cand.get("blocked") or {}
        if blocked.get("kind") == "WAITING_FOR_SPEC":
            blocked_routing = {"kind": "WAITING_FOR_SPEC", "spec_gaps": blocked.get("spec_gaps")}
            if not isinstance(blocked_routing["spec_gaps"], list) or not blocked_routing["spec_gaps"]:
                res.fail("REJECTED", "BLOCKED(kind=WAITING_FOR_SPEC) 必须携带非空 spec_gaps")
                return
        else:
            blocked_routing = {"kind": "WAITING_FOR_INPUT"}

    review = {
        "id": inp["review_id"],
        "scope": inp["scope"],
        "verdict": cand["verdict"],
        "input_sha256": sha_file(rdir / "input.json"),
        "artifact_sha256": inp["named_inputs"]["artifact"]["sha256"],
        "previous_review": inp.get("previous_review"),
        "findings": findings,
        "resolutions": cand["resolutions"],
        "scores": cand.get("scores", {}),
        "coverage": {"scenario_category_pct": scenario_pct, "critical_risk_pct": critical_pct},
        "strengths": cand.get("strengths", []),
        "warnings": cand.get("warnings", []),
        "evidence_gaps": cand.get("evidence_gaps", []),
        "confidence": cand.get("confidence", "medium"),
        "blocked_routing": blocked_routing,
        "date": today(),
    }

    # 先写投影使 validate.py 口径一致,再复算机器检查;失败则移除投影
    n = int(re.match(r"(\d+)", latest_registered(state, "artifacts")).group(1))
    write_verification_projection(decompose, state, review, art_doc)
    checks, checks_ok = machine_checks(decompose, state, art_doc)
    if not checks_ok:
        (decompose / "iterations" / f"{n:02d}-verification.json").unlink(missing_ok=True)
        res.fail("REJECTED", "提交时机器检查失败:",
                 *[f"{c['id']}:{c['detail']}" for c in checks if c["required"] and c["status"] != "pass"])
        return

    write_canonical(rdir / "review.json", review)
    (rdir / "candidate.json").unlink(missing_ok=True)
    rel = f"reviews/{review['id']}/review.json"
    state.setdefault("reviews", []).append(
        {"id": review["id"], "path": rel, "sha256": sha_file(rdir / "review.json")})

    label, next_action, written = route_state_for_review(decompose, state, review, art_doc)
    write_canonical(decompose / "state.json", state)
    res.done(label)
    res.next_action = next_action
    res.written += written + [str(rdir / "review.json"), str(decompose / "state.json")]
    res.review = {"id": review["id"], "scope": review["scope"], "verdict": review["verdict"], "path": rel}
    res.state_status = state["status"]
    res.resume_step = "review 已提交,状态已路由"


# ---------------------------------------------------------------- 完成与门禁

def try_complete(decompose, state, reviews, res):
    """最新 review 为 PASS:等待确认;confirmation.json 有效则写 COMPLETE。"""
    latest = reviews[-1]
    rdir = Path(latest["_path"]).parent
    inp, err = read_json(rdir / "input.json")
    if err:
        res.fail("REJECTED", f"最新 review 的输入不可读:{err}")
        return
    baseline_ok, chain_errors, open_findings, _ = chain_and_findings(decompose, reviews)
    if not baseline_ok or chain_errors:
        res.fail("REJECTED", "审查链无效,不能进入完成流程:", *chain_errors)
        return
    res.done("AWAIT_USER_CONFIRMATION")
    res.review = {"id": latest["id"], "scope": latest["scope"], "verdict": "PASS"}
    res.next_action = {
        "actor": "user",
        "instruction": "等待用户确认交付;确认后写 reviews/confirmation.json 再重跑本命令。",
        "files": [str(decompose / "output" / "catalog.md")],
    }
    conf, cerr = read_json(decompose / "reviews" / "confirmation.json")
    if cerr or not isinstance(conf, dict):
        return  # 尚无确认记录:停在等待
    named, _ = collect_named_inputs(decompose, state, Path(inp["named_inputs"]["artifact"]["path"]))
    if named is None:
        res.fail("REJECTED", "命名输入当前不可读,完成资格失效")
        return
    digest = named_digest(named)
    art_doc, _ = read_json(Path(inp["named_inputs"]["artifact"]["path"]))
    gates = []
    if open_findings:
        gates.append(f"必改项未全部关闭:{[f['id'] for f in open_findings]}")
    if conf.get("artifact_sha256") != latest["artifact_sha256"] \
            or named["artifact"]["sha256"] != latest["artifact_sha256"]:
        gates.append(f"确认绑定的 artifact 哈希与最新 review 不符(确认={conf.get('artifact_sha256')},"
                     f"review={latest['artifact_sha256']},当前={named['artifact']['sha256']})")
    if conf.get("named_inputs_digest") != digest or digest != inp["named_inputs_digest"]:
        gates.append("确认后命名输入发生变化,当前审查与完成资格失效——须重新审查并重新确认")
    if gates:
        res.fail("REJECTED", *gates)
        return
    # 输出渲染一致
    rendered = render_catalog(decompose, state, art_doc, latest)
    out = decompose / "output" / "catalog.md"
    if out.is_file() and out.read_text(encoding="utf-8") != rendered:
        res.fail("REJECTED", "output/catalog.md 与已审版本渲染不一致——交付前须重新审查")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.is_file():
        out.write_text(rendered, encoding="utf-8")
        res.written.append(str(out))
    state["user_confirmation"] = {"date": conf.get("date", today()),
                                  "note": conf.get("note", ""),
                                  "artifact_sha256": latest["artifact_sha256"]}
    state["status"] = "COMPLETE"
    write_canonical(decompose / "state.json", state)
    res.written.append(str(decompose / "state.json"))
    res.done("COMPLETED")
    res.state_status = "COMPLETE"
    res.next_action = {"actor": "downstream",
                       "instruction": "目录已 COMPLETE,交给下游 skill(architecture-design)。",
                       "files": [str(out)]}


# ----------------------------------------------------------------------- 主流程

def main(argv):
    if len(argv) != 2:
        print(json.dumps({"ok": False, "status": "USAGE", "errors": ["用法: python3 review.py <decompose目录>"]},
                         ensure_ascii=False))
        return 1
    decompose = Path(argv[1])
    res = Result()
    if not decompose.is_dir():
        res.fail("USAGE", f"目录不存在:{decompose}")
    else:
        state, err = read_json(decompose / "state.json")
        if err:
            res.fail("REJECTED", f"state.json 不可读:{err}")
        else:
            res.state_status = state.get("status")
            route(decompose, state, res)
    print(json.dumps(res.to_dict(decompose), ensure_ascii=False, indent=2))
    return 0 if res.ok else 1


def reconcile_interrupted_commits(decompose, state, art_doc):
    """补齐被中断的提交:盘上有 review.json 但登记册没有(任务 5.3 写边界)。

    逐个校验绑定(input 哈希、冻结 artifact 哈希、previous_review 链)后补登记;
    若被中断的是最新 review 且 artifact 未再变、state 还停在提交前,补齐状态路由。
    返回 (changed, errors)。幂等:重跑不再改动。
    """
    errors, changed = [], False
    reviews_dir = decompose / "reviews"
    if not reviews_dir.is_dir():
        return changed, errors
    registered = {e.get("path") for e in state.get("reviews", []) if isinstance(e, dict)}
    for d in sorted(reviews_dir.glob("r*")):
        rel = f"reviews/{d.name}/review.json"
        if not (d.is_dir() and (d / "review.json").is_file() and rel not in registered):
            continue
        rv, err = read_json(d / "review.json")
        if err:
            errors.append(f"中断恢复失败:{rel} 不可读:{err}")
            continue
        if sha_file(d / "input.json") != rv.get("input_sha256"):
            errors.append(f"中断恢复失败:{d.name} 的 input 哈希绑定不符")
            continue
        if not (d / "artifact.json").is_file() or sha_file(d / "artifact.json") != rv.get("artifact_sha256"):
            errors.append(f"中断恢复失败:{d.name} 的冻结 artifact 哈希绑定不符")
            continue
        reg = state.get("reviews", [])
        prev_id = reg[-1].get("id") if reg else None
        if rv.get("previous_review") != prev_id:
            errors.append(f"中断恢复失败:{d.name} 的 previous_review={rv.get('previous_review')!r}"
                          f" 与登记册末端 {prev_id!r} 不符(断链)")
            continue
        state.setdefault("reviews", []).append(
            {"id": rv.get("id"), "path": rel, "sha256": sha_file(d / "review.json")})
        changed = True
        registered.add(rel)
        # 最新一笔且 artifact 未变、state 还停在提交前:补齐路由
        art_name = latest_registered(state, "artifacts")
        cur_sha = sha_file(decompose / "iterations" / art_name) if art_name else None
        if cur_sha == rv.get("artifact_sha256") and state.get("status") == "EXECUTING":
            route_state_for_review(decompose, state, rv, art_doc)
    return changed, errors


def route(decompose, state, res):
    status = state.get("status")
    if status in ("INIT", "PLANNING"):
        res.done("WAITING")
        res.next_action = {"actor": "planner" if status == "PLANNING" else "executor",
                           "instruction": "尚未到审查阶段。" if status == "PLANNING" else "先完成 INIT/PLANNING。"}
        return
    if status in ("WAITING_FOR_INPUT", "WAITING_FOR_SPEC"):
        res.done("WAITING")
        res.next_action = {"actor": "user",
                           "instruction": f"运行挂起在 {status}"
                           + (f"(resume_to={state.get('resume_to')})" if state.get("resume_to") else "")
                           + ";用户三选一处置后按 SKILL 流程恢复。"}
        return
    if status == "COMPLETE":
        # COMPLETE 也复核登记册完整性:防"state 已 COMPLETE 但审查历史缺失/被篡改"
        reg_errors, _reviews = load_committed_reviews(decompose, state)
        if reg_errors:
            res.fail("REJECTED", "COMPLETE 状态的审查历史不一致:", *reg_errors)
            return
        res.done("WAITING")
        res.next_action = {"actor": "downstream", "instruction": "运行已 COMPLETE。"}
        return

    # EXECUTING / VERIFYING
    art_name = latest_registered(state, "artifacts")
    if not art_name:
        res.done("WAITING")
        res.next_action = {"actor": "executor", "instruction": "登记册没有 artifact,Executor 完成后再审查。"}
        return
    art_doc, err = read_json(decompose / "iterations" / art_name)
    if err:
        res.fail("REJECTED", f"当前 artifact 不可读:{err}")
        return
    if art_doc.get("status") != "completed":
        res.done("WAITING")
        res.next_action = {"actor": "executor", "instruction": f"artifact status={art_doc.get('status')},尚未完成。"}
        return

    # 中断恢复:补齐"review.json 已写、登记/路由未落"的半提交
    rec_changed, rec_errors = reconcile_interrupted_commits(decompose, state, art_doc)
    if rec_errors:
        res.fail("REJECTED", *rec_errors)
        return
    if rec_changed:
        write_canonical(decompose / "state.json", state)
        res.written.append(str(decompose / "state.json"))
        res.warnings.append("已补齐被中断的提交登记/路由(幂等恢复)")
        status = state.get("status")  # 恢复可能已推进状态
        res.state_status = status

    reg_errors, reviews = load_committed_reviews(decompose, state)
    if reg_errors:
        res.fail("REJECTED", *reg_errors)
        return

    reviews_dir = decompose / "reviews"
    pending = None
    if reviews_dir.is_dir():
        for d in sorted(reviews_dir.glob("r*")):
            if d.is_dir() and (d / "input.json").exists() and not (d / "review.json").exists():
                pending = d
                break

    if pending is not None and (pending / "candidate.json").exists():
        commit(decompose, state, pending, res)
        return

    latest = reviews[-1] if reviews else None
    if latest is not None and latest.get("verdict") == "PASS" and status == "VERIFYING" and pending is None \
            and sha_file(decompose / "iterations" / art_name) == latest.get("artifact_sha256"):
        # 命名输入(上游/Plan/标准)未再变才停在等确认;变了走重审
        l_inp, _l_err = read_json(Path(latest["_path"]).parent / "input.json")
        named_now, _ = collect_named_inputs(decompose, state, decompose / "iterations" / art_name)
        if isinstance(l_inp, dict) and named_now is not None \
                and named_digest(named_now) == l_inp.get("named_inputs_digest"):
            try_complete(decompose, state, reviews, res)
            return

    dispatch(decompose, state, res)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
