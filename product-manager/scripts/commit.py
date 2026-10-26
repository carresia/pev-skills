#!/usr/bin/env python3
"""产物提交:落盘 iterations/<N>-<type>.json、更新登记册、写后校验、阶段转移。

用法:
    python3 commit.py --pm-root <pm 目录绝对路径> plan|artifact|verification <草稿绝对路径>
    python3 commit.py --pm-root <pm 目录绝对路径> state-update <补丁绝对路径>

提交顺序固定:草稿校验 → 产物落盘(临时+改名) → 登记册 → validate(转移
硬闸) → 阶段转移;任一步后中断,重跑同一命令即收敛。事件面合并(design
§1.1):commit plan 成功即转 EXECUTING(plan-validated 边并入);commit
artifact 按 status 三分支转移(completed→VERIFYING / replan_required→
PLANNING+1·上限 / blocked→WAITING_FOR_INPUT+resume_to=EXECUTING);
transitions 日志仍按 v1 事件名记录。覆盖权限:编号=当前 iteration、当前轮
不存在绑定 PASS 的 verification、且与当前阶段匹配;编号更小一律拒绝
(历史轮只读,复用不等于可改写)。state-update 只接受八个语义路径的补丁。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Reporter, SKILL_ROOT, canonical_sha256, load_state, parse_pm_root,
    read_json, run, select_plan, write_json_atomic,
)
from transition import make_entry  # noqa: E402
from record_provenance import PROVENANCE_FIELDS, snapshot_for  # noqa: E402
import validate as validator  # noqa: E402
from render import RenderError, select_template  # noqa: E402
from render import TEMPLATES, validate_inputs  # noqa: E402

SEMANTIC_FIELDS = ("objective", "business_context", "known", "assumptions",
                   "evidence", "metrics", "hypotheses", "opportunities")
ARRAY_APPEND = ("known", "assumptions", "metrics", "hypotheses",
                "opportunities")
STAGE_OF = {"plan": "PLANNING", "artifact": "EXECUTING",
            "verification": "VERIFYING"}
SCHEMA_OF = {"plan": "plan.schema.json", "artifact": "artifact.schema.json",
             "verification": "verification.schema.json"}
ID_RE = re.compile(r"^E[1-9][0-9]*$")
EVIDENCE_TYPES = ("FACT", "INFERENCE", "HYPOTHESIS", "UNKNOWN")
CONFIDENCE = ("high", "medium", "low")
ARTIFACT_EVENT = {"completed": "artifact-validated",
                  "replan_required": "executor-replan",
                  "blocked": "executor-blocked"}


def already_transferred(state, event, ref, iteration):
    """本命令对应的阶段转移是否已随先前一次执行落盘(幂等重跑判定)。"""
    entries = state.get("transitions") or []
    if not entries:
        return False
    last = entries[-1]
    return (last.get("event") == event
            and last.get("ref_sha256") == ref
            and last.get("to_iteration") == iteration
            and last.get("to") == state.get("status"))


def transfer(pm, state, rep, event, src, dst, it, new_it, ref,
             resume_to=None):
    """写状态转移(status/iteration/resume_to/transitions)并原子落盘。"""
    entry = make_entry(event, src, dst, it, new_it, ref, None)
    state["status"] = dst
    if new_it != it:
        state["iteration"] = new_it
    if dst == "WAITING_FOR_INPUT":
        state["resume_to"] = resume_to
    else:
        state.pop("resume_to", None)
    state.setdefault("transitions", []).append(entry)
    write_json_atomic(pm / "state.json", state)
    rep.status = dst
    rep.iteration = new_it


def stop_at_limit_commit(pm, state, rep, event, src, it, ref):
    """replan 分支越上限:产物与登记册已落盘留证,写 STOPPED 拒绝该转移。"""
    state["status"] = "STOPPED"
    state.pop("resume_to", None)
    entry = make_entry(event, src, "STOPPED", it, it, ref,
                       {"requested": event})
    state.setdefault("transitions", []).append(entry)
    write_json_atomic(pm / "state.json", state)
    rep.status = "STOPPED"
    rep.iteration = it
    rep.warn("iteration+1 超过 max_iterations,已写 STOPPED;"
             "须向用户报告当前最佳结论、critical_issues、evidence_gaps")
    rep.next.append({"kind": "stop",
                     "reason": "达到迭代上限;恢复仅经 resume --raise-limit "
                               "且记录授权"})


def run_script_json(script, pm):
    """跑 scripts/ 下脚本并解析其 JSON 输出;返回 (returncode, payload)。"""
    proc = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / script),
         "--pm-root", str(pm)],
        capture_output=True, text=True)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"ok": proc.returncode == 0, "errors": [
            {"file": script, "json_path": None,
             "reason": f"输出异常: {proc.stdout[:200]}"}],
            "warnings": [], "written": []}
    return proc.returncode, payload


def commit_verification(pm, state, rep, draft, iteration, status):
    """收口折叠(design §2.3,任务 2.10):一条命令完成
    落盘 → 绑定(复算三摘要)→ 按 verdict 转移 → PASS 分支 render+validate+COMPLETE。
    verdict 从报告字段读取,不经命令参数;重跑按报告与状态的组合分支收敛。
    """
    ver_name = f"{iteration:02d}-verification.json"
    doc_name = f"iterations/{ver_name}"
    ver_path = pm / "iterations" / ver_name
    snap_path = pm / "iterations" / f"{iteration:02d}-verification-input.json"
    snap = read_json(snap_path) if snap_path.is_file() else None
    disk = read_json(ver_path) if ver_path.is_file() else None
    same_report = (isinstance(disk, dict) and snap is not None
                   and disk.get("verdict") == draft.get("verdict")
                   and disk.get("verification_input") == draft.get("verification_input")
                   and draft.get("verification_input") == snap)

    # —— 重跑收敛:状态已离开 VERIFYING 时的组合分支 ——
    if status != "VERIFYING":
        if status == "COMPLETE" and same_report \
                and "provenance" in disk and disk.get("verdict") == "PASS":
            # 已 COMPLETE:validate 干净才判已执行(内容变化重跑被 P1 拒绝,R2)
            rc, payload = run_script_json("validate.py", pm)
            for e in payload.get("errors", []):
                rep.error(e.get("file"), e.get("json_path"), e.get("reason"))
            if rc != 0 or rep.errors:
                return rep.emit()
            rep.warn("重跑判已执行,收口已完成")
            rep.next.append({"kind": "deliver",
                             "notes": "向用户交付 output/ 下最终文档"})
            return rep.emit()
        entries = state.get("transitions") or []
        last = entries[-1] if entries else None
        if (isinstance(last, dict) and last.get("event") == "verdict"
                and last.get("to_iteration") == iteration
                and last.get("to") == status
                and isinstance(disk, dict) and "provenance" in disk
                and disk.get("verdict") == draft.get("verdict")
                and disk.get("verification_input") == draft.get("verification_input")):
            rep.warn("重跑判已执行,verdict 转移已完成")
            if draft.get("verdict") == "REVISE":
                rep.next.append({"kind": "draft", "target": "artifact",
                                 "notes": "按 required_changes 修订 Artifact 后重新提交"})
            elif draft.get("verdict") == "REPLAN":
                rep.next.append({"kind": "draft", "target": "plan",
                                 "notes": "以 agents/planner.md 重新起草 Plan"})
            else:
                rep.next.append({"kind": "ask-user",
                                 "items": ["缺什么 / 为什么重要 / 怎么获取"]})
            return rep.emit()
        rep.error("state.json", "$.status",
                  f"阶段不匹配:verification 提交要求 status=VERIFYING,"
                  f"当前为 {status}")
        return rep.emit()

    # —— VERIFYING:草稿校验(schema/R5/复述) ——
    schema = json.loads((validator.SCHEMA_DIR / SCHEMA_OF["verification"])
                        .read_text(encoding="utf-8"))
    validator.validate(draft, schema, doc_name, "$", rep)
    rc = draft.get("required_changes")
    n = len(rc) if isinstance(rc, list) else 0
    if draft.get("verdict") == "PASS" and n > 0:
        rep.error(doc_name, "$.required_changes", "R5: PASS 时 required_changes 必须为空")
    if draft.get("verdict") == "REVISE" and n == 0:
        rep.error(doc_name, "$.required_changes", "R5: REVISE 时 required_changes 必须非空")
    if snap is None:
        rep.error(doc_name, "$.verification_input",
                  "快照不存在,先运行 record_provenance.py 再派发与提交报告")
    elif draft.get("verification_input") != snap:
        rep.error(doc_name, "$.verification_input",
                  "报告复述与快照不一致,不可提交;核对输入是否在派发后变更")
    # 绑定 PASS 覆盖守卫:同号覆盖仅允许"当轮无绑定 PASS"(design §2.3)
    if (isinstance(disk, dict) and "provenance" in disk
            and disk.get("verdict") == "PASS" and not same_report):
        rep.error(doc_name, "$",
                  "当前轮已存在绑定 PASS 的 verification,覆盖提交被拒绝;"
                  "收口重跑用同一报告;重新验证须换轮")
    if rep.errors:
        return rep.emit()

    # —— 绑定与落盘(报告带 provenance 一次原子写) ——
    if same_report and "provenance" in disk:
        report = disk  # 已绑定未转移/已渲染未 COMPLETE:续走,不重写
    else:
        sel = select_plan(pm, state, iteration)
        if sel is None:
            rep.error("state.json", "$.plans", "找不到有效 Plan,无法绑定")
            return rep.emit()
        plan_doc = read_json(sel[1])
        plan_name = sel[1].relative_to(pm).as_posix()
        art_name = f"{iteration:02d}-artifact.json"
        artifact_doc = read_json(pm / "iterations" / art_name)
        if plan_doc is None or artifact_doc is None:
            rep.error("state.json", "$", "当轮 Plan/Artifact 缺失或不可解析,无法绑定")
            return rep.emit()
        current = snapshot_for(state, plan_doc, plan_name, artifact_doc,
                               iteration)
        for key, conflict_file in (
                ("artifact_sha256", f"iterations/{art_name}"),
                ("plan_sha256", plan_name),
                ("state_projection_sha256", "state.json")):
            if current[key] != snap[key]:
                rep.error(conflict_file, "$",
                          "输入在派发后变更,provenance 复算不一致,该报告作废;"
                          "恢复:重跑 record_provenance.py 原位重写快照并重新派发 Verifier")
                return rep.emit()
        report = dict(draft)
        report["provenance"] = {k: snap[k] for k in PROVENANCE_FIELDS}
        write_json_atomic(ver_path, report)
        rep.written.append(doc_name)

    verdict = report.get("verdict")
    ref = canonical_sha256(report)

    if verdict == "PASS":
        # —— PASS 收口:validate 硬闸(P1 复算)→ render 发布 → 写 COMPLETE ——
        rc, payload = run_script_json("validate.py", pm)
        for e in payload.get("errors", []):
            rep.error(e.get("file"), e.get("json_path"), e.get("reason"))
        if rc != 0 or rep.errors:
            return rep.emit()
        rc, payload = run_script_json("render.py", pm)
        for e in payload.get("errors", []):
            rep.error(e.get("file"), e.get("json_path"), e.get("reason"))
        if rc != 0 or rep.errors:
            return rep.emit()
        rep.written.extend(payload.get("written", []))
        art = read_json(pm / "iterations" / f"{iteration:02d}-artifact.json")
        state.setdefault("transitions", []).append(
            make_entry("verdict", "VERIFYING", "VERIFYING",
                       iteration, iteration, ref, None))
        state.setdefault("transitions", []).append(
            make_entry("complete", "VERIFYING", "COMPLETE",
                       iteration, iteration,
                       canonical_sha256(art) if art is not None else None,
                       None))
        state["status"] = "COMPLETE"
        state.pop("resume_to", None)
        write_json_atomic(pm / "state.json", state)
        rep.status = "COMPLETE"
        rep.iteration = iteration
        rep.next.append({"kind": "deliver",
                         "notes": "向用户交付 output/ 下最终文档"})
        return rep.emit()

    # —— REVISE / REPLAN / BLOCKED:按 verdict 自动转移 ——
    plus_one = verdict in ("REVISE", "REPLAN")
    new_it = iteration + 1 if plus_one else iteration
    if plus_one and new_it > state.get("max_iterations", 5):
        state["status"] = "STOPPED"
        state.pop("resume_to", None)
        state.setdefault("transitions", []).append(
            make_entry("verdict", "VERIFYING", "STOPPED", iteration,
                       iteration, ref, {"verdict": verdict}))
        write_json_atomic(pm / "state.json", state)
        rep.status = "STOPPED"
        rep.iteration = iteration
        rep.warn(f"verdict={verdict} 的 iteration+1 超过 max_iterations,"
                 "已写 STOPPED;须向用户报告当前最佳结论、critical_issues、"
                 "evidence_gaps")
        rep.next.append({"kind": "stop",
                         "reason": "达到迭代上限;恢复仅经 resume --raise-limit "
                                   "且记录授权"})
        return rep.emit()
    dst = {"REVISE": "EXECUTING", "REPLAN": "PLANNING"}.get(
        verdict, "WAITING_FOR_INPUT")
    transfer(pm, state, rep, "verdict", "VERIFYING", dst,
             iteration, new_it, ref,
             resume_to="VERIFYING" if dst == "WAITING_FOR_INPUT" else None)
    if verdict == "REVISE":
        rep.next.append({"kind": "draft", "target": "artifact",
                         "notes": "按 required_changes 修订 Artifact 后重新提交"})
    elif verdict == "REPLAN":
        rep.next.append({"kind": "draft", "target": "plan",
                         "notes": "以 agents/planner.md 重新起草 Plan,经 commit.py plan 提交"})
    else:
        rep.next.append({"kind": "ask-user",
                         "items": ["缺什么 / 为什么重要 / 怎么获取"]})
    return rep.emit()


def post_validate(pm, rep):
    """写后校验:失败不回滚已落盘产物,恢复动作是重跑同一 commit 命令。"""
    proc = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "validate.py"),
         "--pm-root", str(pm)],
        capture_output=True, text=True)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        rep.error("validate.py", None,
                  f"写后校验输出异常: {proc.stdout[:200]}")
        return
    for e in payload.get("errors", []):
        rep.error(e.get("file"), e.get("json_path"), e.get("reason"))
    for w in payload.get("warnings", []):
        rep.warn(w)
    if not payload.get("ok"):
        rep.warn("写后校验失败;若为登记册不一致,恢复动作是重跑同一 commit 命令")


def bound_pass_exists(pm, iteration):
    ver_path = pm / "iterations" / f"{iteration:02d}-verification.json"
    ver = read_json(ver_path) if ver_path.is_file() else None
    return (isinstance(ver, dict) and "provenance" in ver
            and ver.get("verdict") == "PASS")


def check_ledger_entry(entry, path, rep):
    """Ledger 条目契约(C 类):id 格式、claim/type/confidence、FACT/INFERENCE 依据。"""
    if not isinstance(entry, dict):
        rep.error("state.json", path, "Ledger 条目必须是对象")
        return
    eid = entry.get("id")
    if not isinstance(eid, str) or not ID_RE.match(eid):
        rep.error("state.json", f"{path}.id",
                  f"Ledger id 须匹配 ^E[1-9][0-9]*$,实际为 {eid!r}")
    if not (isinstance(entry.get("claim"), str) and entry["claim"].strip()):
        rep.error("state.json", f"{path}.claim", "claim 须为非空字符串")
    if entry.get("type") not in EVIDENCE_TYPES:
        rep.error("state.json", f"{path}.type",
                  f"type 须 ∈ {EVIDENCE_TYPES}")
    if entry.get("confidence") not in CONFIDENCE:
        rep.error("state.json", f"{path}.confidence",
                  f"confidence 须 ∈ {CONFIDENCE}")
    if entry.get("type") in ("FACT", "INFERENCE"):
        ev = entry.get("evidence")
        if not (isinstance(ev, str) and ev.strip()):
            rep.error("state.json", f"{path}.evidence",
                      "FACT/INFERENCE 须有非空 evidence 出处")


def apply_state_update(state, patch, rep):
    """把补丁合并进 state(数组追加、evidence 同 id 整条替换、对象整体替换)。"""
    for key in patch:
        if key not in SEMANTIC_FIELDS:
            rep.error("$", f"$.{key}",
                      f"补丁只接受语义字段 {SEMANTIC_FIELDS},生命周期字段与登记册一律拒绝")
            return False
    if "objective" in patch:
        obj = patch["objective"]
        if not isinstance(obj, dict):
            rep.error("$", "$.objective", "objective 补丁须为完整对象")
            return False
        goal = obj.get("goal")
        if not (isinstance(goal, str) and goal.strip()):
            rep.error("$", "$.objective.goal", "替换后 objective.goal 须非空")
            return False
    for key in ("objective", "business_context"):
        if key in patch:
            state[key] = patch[key]
    for key in ARRAY_APPEND:
        if key in patch:
            if not isinstance(patch[key], list):
                rep.error("$", f"$.{key}", f"{key} 补丁须为数组(按原顺序追加)")
                return False
            state.setdefault(key, []).extend(patch[key])
    if "evidence" in patch:
        if not isinstance(patch["evidence"], list):
            rep.error("$", "$.evidence", "evidence 补丁须为数组")
            return False
        seen = set()
        ledger = state.setdefault("evidence", [])
        index = {e.get("id"): i for i, e in enumerate(ledger)
                 if isinstance(e, dict)}
        for i, entry in enumerate(patch["evidence"]):
            check_ledger_entry(entry, f"$.evidence[{i}]", rep)
            eid = entry.get("id") if isinstance(entry, dict) else None
            if eid in seen:
                rep.error("$", f"$.evidence[{i}].id",
                          f"补丁内 id {eid!r} 重复")
                return False
            seen.add(eid)
            if eid in index:
                ledger[index[eid]] = entry
            else:
                ledger.append(entry)
                index[eid] = len(ledger) - 1
    return not rep.errors


def check_artifact_b_c(artifact_doc, plan_doc, plan_name, state,
                       artifact_name, rep):
    """B 类(模板必填集,豁免生效)与 C 类(final_deliverable 可解析、evidence_ref 可解析)。"""
    try:
        name = select_template(plan_doc.get("final_deliverable", ""))
    except RenderError as e:
        rep.error(plan_name, "$.final_deliverable", f"C: {e}")
        return
    spec = TEMPLATES[name]
    body = artifact_doc.get("artifact")
    waived_names = set()
    for i, w in enumerate(artifact_doc.get("waived_fields") or []):
        if isinstance(w, dict) and isinstance(w.get("field"), str):
            waived_names.add(w["field"])
    try:
        validate_inputs(body, spec, waived_names, artifact_name, "$.artifact")
    except RenderError as e:
        rep.error(artifact_name, e.json_path, f"B: {e}")
    # 列表项结构中引用 state.evidence 的模板:证据行字段齐备
    ev_spec = spec["state_loops"].get("evidence")
    if ev_spec:
        for i, e in enumerate(state.get("evidence", [])):
            check_ledger_entry(e, f"$.evidence[{i}]", rep)
    ids = {e.get("id") for e in state.get("evidence", [])
           if isinstance(e, dict)}
    if name == "product-opportunity":
        for i, opp in enumerate(body.get("opportunities", [])
                                if isinstance(body, dict) else []):
            ref = opp.get("evidence_ref") if isinstance(opp, dict) else None
            if isinstance(ref, str) and ref.strip() and ref not in ids:
                rep.error(artifact_name, f"$.artifact.opportunities[{i}].evidence_ref",
                          f"C: evidence_ref {ref!r} 不在 Ledger 现存 id 中")


def main():
    argv = sys.argv[1:]
    rep = Reporter("commit")
    rest = []
    sub = None
    draft_path = None
    i = 0
    while i < len(argv):
        if argv[i] == "--pm-root" and i + 1 < len(argv):
            rest += argv[i:i + 2]
            i += 2
        elif sub is None:
            sub = argv[i]
            i += 1
        elif draft_path is None:
            draft_path = argv[i]
            i += 1
        else:
            rep.command_error("commit", f"过多参数: {argv[i]}")
            return rep.emit()
    if sub not in ("plan", "artifact", "verification", "state-update"):
        rep.command_error("commit",
                          "子命令须为 plan|artifact|verification|state-update")
        return rep.emit()
    pm = parse_pm_root(rest, "commit", rep)
    if pm is None or rep.errors:
        return rep.emit()
    if draft_path is None:
        rep.command_error("commit", "缺少草稿绝对路径参数")
        return rep.emit()
    state = load_state(pm, rep)
    if state is None:
        return rep.emit()
    iteration = rep.iteration
    if not isinstance(iteration, int) or iteration < 1:
        rep.error("state.json", "$.iteration",
                  f"iteration 须为正整数才能提交产物,实际为 {iteration!r};"
                  "init 建轮即 iteration=1,请核对轮次状态")
        return rep.emit()
    status = rep.status

    draft = read_json(Path(draft_path).expanduser().resolve())
    if draft is None:
        rep.command_error("commit", f"草稿无法读取/解析: {draft_path}")
        return rep.emit()

    # SUPERSEDED 不可逆终态:一切写入(含 state-update)冻结
    if status == "SUPERSEDED":
        rep.error("state.json", "$.status",
                  "SUPERSEDED 是不可逆终态,本轮一切写入冻结;"
                  "继任轮经 init.py --carry-from 创建",
                  code="E_FROZEN_STATE")
        return rep.emit()

    # 收口折叠(任务 2.10):verification 一步完成落盘/绑定/按 verdict 转移/
    # PASS 分支 render+validate+COMPLETE(verdict 从报告字段读取)
    if sub == "verification":
        return commit_verification(pm, state, rep, draft, iteration, status)

    if sub == "state-update":
        if status in ("COMPLETE", "STOPPED"):
            rep.error("state.json", "$.status",
                      f"{status} 为终点,语义字段冻结;继续工作须新建轮次或获授权恢复",
                      code="E_FROZEN_STATE")
            return rep.emit()
        if not isinstance(draft, dict) or not draft:
            rep.error("$", "$", "补丁须为非空单层 JSON 对象")
            return rep.emit()
        merged = json.loads(json.dumps(state, ensure_ascii=False))
        if not apply_state_update(merged, draft, rep):
            return rep.emit()
        schema = json.loads((validator.SCHEMA_DIR / "state.schema.json")
                            .read_text(encoding="utf-8"))
        validator.validate(merged, schema, "state.json", "$", rep)
        if rep.errors:
            return rep.emit()
        write_json_atomic(pm / "state.json", merged)
        rep.written.append("state.json")
        if merged.get("status") == "WAITING_FOR_INPUT":
            rep.next.append({"kind": "command", "cwd": str(SKILL_ROOT),
                             "argv": ["scripts/transition.py", "--pm-root",
                                      str(pm), "resume"]})
            rep.next.append({"kind": "command", "cwd": str(SKILL_ROOT),
                             "argv": ["scripts/transition.py", "--pm-root",
                                      str(pm), "resume", "--invalidate-plan"]})
            rep.next.append({"kind": "ask-user",
                             "items": ["向用户确认答复是否使当前 Plan 失效,选定 resume 变体"]})
        post_validate(pm, rep)
        return rep.emit()

    # plan / artifact / verification
    if bound_pass_exists(pm, iteration):
        rep.error(f"iterations/{iteration:02d}-{sub}.json", "$",
                  "当前轮已存在绑定 PASS 的 verification,一切覆盖提交被拒绝;"
                  "修订须新建轮次")
        return rep.emit()
    stage = STAGE_OF[sub]
    if status != stage:
        # 事件面合并后的幂等重跑:转移已随本命令落盘 → 判已执行退出 0
        rerun_event = ("plan-validated" if sub == "plan"
                       else ARTIFACT_EVENT.get(draft.get("status")))
        if rerun_event and already_transferred(
                state, rerun_event, canonical_sha256(draft), iteration):
            rerun_name = f"{iteration:02d}-{sub}.json"
            reg = state.setdefault(sub + "s", [])
            if rerun_name not in reg:  # 收敛:修复被回滚的登记册
                reg.append(rerun_name)
                write_json_atomic(pm / "state.json", state)
            rep.warn("重跑判已执行,未重复转移")
            if sub == "plan":
                rep.next.append({"kind": "draft", "target": "artifact",
                                 "notes": "以 agents/executor.md 起草 Artifact,"
                                          "经 commit.py artifact 提交"})
            elif draft.get("status") == "completed":
                rep.next.append({"kind": "command", "cwd": str(SKILL_ROOT),
                                 "argv": ["scripts/record_provenance.py",
                                          "--pm-root", str(pm)]})
            elif draft.get("status") == "replan_required":
                rep.next.append({"kind": "draft", "target": "plan",
                                 "notes": "按 replan_reason 重新规划,"
                                          "经 commit.py plan 提交"})
            else:
                rep.next.append({"kind": "ask-user",
                                 "items": ["缺什么 / 为什么重要 / 怎么获取"]})
            return rep.emit()
        rep.error("state.json", "$.status",
                  f"阶段不匹配:{sub} 提交要求 status={stage},当前为 {status}")
        return rep.emit()

    name = f"{iteration:02d}-{sub}.json"
    doc_name = f"iterations/{name}"
    schema = json.loads((validator.SCHEMA_DIR / SCHEMA_OF[sub])
                        .read_text(encoding="utf-8"))
    validator.validate(draft, schema, doc_name, "$", rep)

    if sub == "artifact" and draft.get("status") in ("replan_required",
                                                     "blocked"):
        reason = draft.get("replan_reason")
        if not isinstance(reason, dict) or not reason:
            rep.error(doc_name, "$.replan_reason",
                      "R2: status 为 replan_required/blocked 时必须填写 replan_reason")
    if sub == "artifact" and draft.get("status") == "completed":
        sel = select_plan(pm, state, iteration)
        if sel is None:
            rep.error("state.json", "$.plans", "找不到有效 Plan,B 类无从判定")
        else:
            plan_doc = read_json(sel[1])
            if plan_doc is None:
                rep.error(sel[1].name, "$", "有效 Plan 无法解析")
            else:
                check_artifact_b_c(draft, plan_doc, sel[1].name, state,
                                   doc_name, rep)
    if rep.errors:
        return rep.emit()

    # 产物落盘 → 登记册(同一次 state 原子写) → 写后校验(转移硬闸) → 阶段转移
    write_json_atomic(pm / "iterations" / name, draft)
    rep.written.append(doc_name)
    if sub in ("plan", "artifact"):
        reg_key = sub + "s"
        reg = state.setdefault(reg_key, [])
        if name not in reg:
            reg.append(name)
        write_json_atomic(pm / "state.json", state)
    post_validate(pm, rep)
    if rep.errors:
        return rep.emit()

    # 事件面合并(任务 2.9):阶段推进随提交自动发生,日志按 v1 事件名记录
    ref = canonical_sha256(draft)
    if sub == "plan":
        transfer(pm, state, rep, "plan-validated", "PLANNING", "EXECUTING",
                 iteration, iteration, ref)
        rep.next.append({"kind": "draft", "target": "artifact",
                         "notes": "以 agents/executor.md 起草 Artifact,"
                                  "经 commit.py artifact 提交"})
    elif sub == "artifact":
        art_status = draft.get("status")
        if art_status == "completed":
            transfer(pm, state, rep, "artifact-validated", "EXECUTING",
                     "VERIFYING", iteration, iteration, ref)
            rep.next.append({"kind": "command", "cwd": str(SKILL_ROOT),
                             "argv": ["scripts/record_provenance.py",
                                      "--pm-root", str(pm)]})
        elif art_status == "replan_required":
            new_it = iteration + 1
            if new_it > state.get("max_iterations", 5):
                stop_at_limit_commit(pm, state, rep, "executor-replan",
                                     "EXECUTING", iteration, ref)
                return rep.emit()
            transfer(pm, state, rep, "executor-replan", "EXECUTING",
                     "PLANNING", iteration, new_it, ref)
            rep.next.append({"kind": "draft", "target": "plan",
                             "notes": "按 replan_reason 重新规划,"
                                      "经 commit.py plan 提交"})
        else:  # blocked
            transfer(pm, state, rep, "executor-blocked", "EXECUTING",
                     "WAITING_FOR_INPUT", iteration, iteration, ref,
                     resume_to="EXECUTING")
            rep.next.append({"kind": "ask-user",
                             "items": ["缺什么 / 为什么重要 / 怎么获取"]})
    return rep.emit()


if __name__ == "__main__":
    sys.exit(run("commit", main))
