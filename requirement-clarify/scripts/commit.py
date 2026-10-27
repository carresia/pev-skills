#!/usr/bin/env python3
"""产物提交:落盘、登记、按草稿字段分叉;PASS 验证在同一命令内自动收口。

用法:
    python3 commit.py --rc-root <rc 目录绝对路径> plan|artifact|verification <草稿绝对路径>
    python3 commit.py --rc-root <rc 目录绝对路径> state-update <补丁绝对路径>

提交顺序固定:草稿校验 → 产物落盘(临时+改名) → 登记册 → 状态推进+事件入账
(同一次原子写) → 写后校验;任一步后中断,重跑同一命令即收敛。
岔路用草稿字段表达,模型不敲第二条命令(design.md 原则③):
    artifact.status      completed|replan_required|blocked
    verification.verdict PASS|REVISE|REPLAN|BLOCKED
    state-update 补丁    invalidate_plan|back_to_prd|prd_refreshed
verdict=PASS 时同一命令内自动完成:绑定复算 → 确定性渲染 → 逐字节校验 →
iteration 上限检查 → 原子写 COMPLETE;任一步失败整体失败,旧发布文件保持原状。

覆盖权限:当前轮不存在已绑定 PASS 时允许同编号重提交(幂等收敛);
已绑定 PASS 后一切覆盖拒绝,修订走 reopen。COMPLETE 后一切写入冻结。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Reporter, append_transition, canonical_sha256, file_no,
    load_state, parse_rc_root, post_validate, read_json, run,
    write_json_atomic,
)
import validate as validator  # noqa: E402
from provenance import ProvenanceError, bind_report, write_snapshot  # noqa: E402
from render_lib import RenderError, render_spec, validate_body  # noqa: E402

SEMANTIC_KEYS = {"evidence", "answers", "decisions", "prd_gaps",
                 "back_to_prd", "invalidate_plan", "prd_refreshed"}
STAGE_OF = {"plan": ("INIT", "PLANNING"), "artifact": ("EXECUTING",),
            "verification": ("VERIFYING",)}
SCHEMA_OF = {"plan": "plan.schema.json", "artifact": "artifact.schema.json",
             "verification": "verification.schema.json"}


def doc_path(iteration, kind):
    return f"iterations/{file_no(iteration):02d}-{kind}.json"


def bound_pass_exists(rc_root, iteration):
    ver = read_json(rc_root / "iterations"
                    / f"{file_no(iteration):02d}-verification.json")
    return (isinstance(ver, dict) and "provenance" in ver
            and ver.get("verdict") == "PASS")


def check_ledger_entry(entry, path, rep):
    """Ledger 条目契约(R1):type 合法;FACT/DECISION 须有非空 evidence。"""
    if not isinstance(entry, dict):
        rep.error("state.json", path, "Ledger 条目必须是对象")
        return
    if entry.get("type") not in ("FACT", "INFERENCE", "HYPOTHESIS",
                                 "UNKNOWN", "DECISION"):
        rep.error("state.json", f"{path}.type",
                  f"type 须为 FACT/INFERENCE/HYPOTHESIS/UNKNOWN/DECISION,"
                  f"实际为 {entry.get('type')!r}")
    if entry.get("type") in ("FACT", "DECISION"):
        ev = entry.get("evidence")
        if not (isinstance(ev, str) and ev.strip()):
            rep.error("state.json", f"{path}.evidence",
                      "R1: type=FACT/DECISION 的条目必须有非空 evidence"
                      "(FACT=PRD§x/.pev/<轮次>/pm/ 产物/代码文件,"
                      "DECISION=澄清记录锚点)")


def check_value_first(plan_doc, doc_name, errs):
    """R5(核心不变量#1「价值先行」)的草稿级检查,先于落盘拒绝。"""
    seq = [s.get("action") for s in plan_doc.get("plan", [])
           if isinstance(s, dict) and s.get("action") in validator.ACTION_ORDER]
    order = validator.ACTION_ORDER
    for i in range(1, len(seq)):
        if order[seq[i]] < order[seq[i - 1]]:
            errs.add(doc_name, f"$.plan[{i}].action",
                     f"R5: 违反「价值先行」——{seq[i]} 排在 {seq[i - 1]} 之后;"
                     "顺序必须是 interrogate_value → interrogate_ambiguity → draft")
            return
    if "interrogate_ambiguity" in seq:
        i = seq.index("interrogate_ambiguity")
        if "interrogate_value" not in seq[:i]:
            errs.add(doc_name, f"$.plan[{i}].action",
                     "R5: 违反「价值先行」——首个 Plan 必须先 interrogate_value "
                     "再 interrogate_ambiguity")


def check_verdict_content(ver, doc_name, errs):
    """R7:verdict 必须与内容一致,否则下游拿到空指令。"""
    verdict = ver.get("verdict")
    rc = ver.get("required_changes")
    n = len(rc) if isinstance(rc, list) else 0
    if verdict == "PASS" and n > 0:
        errs.add(doc_name, "$.required_changes", "R7: PASS 时 required_changes 必须为空")
    if verdict == "REVISE" and n == 0:
        errs.add(doc_name, "$.required_changes",
                 "R7: REVISE 时 required_changes 必须非空——Executor 按它修订")
    if verdict == "REPLAN" and not (ver.get("critical_issues")
                                    or ver.get("evidence_gaps")):
        errs.add(doc_name, "$.critical_issues",
                 "R7: REPLAN 时 critical_issues 或 evidence_gaps 必须非空")


def iteration_limit_guard(state, rep, next_it, action):
    """+1 越上限:拒绝该转移,状态不变;恢复须向用户报告并获授权调整上限。"""
    max_it = state.get("max_iterations", 5)
    if next_it <= max_it:
        return False
    rep.error("state.json", "$.iteration",
              f"{action} 将使 iteration={next_it} 超过 max_iterations={max_it};"
              "已达迭代上限:向用户报告当前最佳结论、critical_issues 与未闭环问题,"
              "不得宣称完成;用户明确授权后可调高 max_iterations 再继续",
              code="E_ITERATION_LIMIT")
    rep.next.append({"kind": "stop",
                     "reason": "达到迭代上限;已拒绝本次推进,状态未改变"})
    return True


def latest_artifact_path(rc_root, state):
    """登记册中编号最大的、盘上存在的 Artifact;无则 None。"""
    best = None
    for name in state.get("artifacts") or []:
        if not (isinstance(name, str) and name.endswith("-artifact.json")):
            continue
        stem = name[:-len("-artifact.json")]
        if not stem.isdigit():
            continue
        path = rc_root / "iterations" / name
        if path.is_file() and (best is None or int(stem) > best[0]):
            best = (int(stem), path)
    return best[1] if best else None


def merge_user_input(rc_root, state, patch, rep):
    """把答复效果合并进 state 与最新 Artifact(确定性双写,取代模型手工同步)。"""
    for key in patch:
        if key not in SEMANTIC_KEYS:
            rep.error("$", f"$.{key}",
                      f"补丁只接受 {sorted(SEMANTIC_KEYS)};生命周期字段一律拒绝")
            return False
    if "evidence" in patch:
        if not isinstance(patch["evidence"], list):
            rep.error("$", "$.evidence", "evidence 补丁须为数组")
            return False
        ledger = state.setdefault("evidence", [])
        for i, entry in enumerate(patch["evidence"]):
            check_ledger_entry(entry, f"$.evidence[{i}]", rep)
        if rep.errors:
            return False
        ledger.extend(patch["evidence"])
    artifact_writes = {k: patch[k] for k in ("answers", "decisions")
                       if k in patch}
    if artifact_writes:
        path = latest_artifact_path(rc_root, state)
        if path is None:
            rep.error("$", "$.answers",
                      "当前轮没有已登记 Artifact,无处并入 answers/decisions;"
                      "blocked 前应先提交 blocked Artifact")
            return False
        art = read_json(path)
        if art is None:
            rep.error(path.name, "$", "无法读取/解析当前 Artifact")
            return False
        for key, items in artifact_writes.items():
            if not isinstance(items, list):
                rep.error("$", f"$.{key}", f"{key} 补丁须为数组")
                return False
            art.setdefault(key, []).extend(items)
        write_json_atomic(path, art)
        rep.written.append(f"iterations/{path.name}")
    return not rep.errors


def advance_and_write(rc_root, state, rep, event, dest, new_it, ref, param=None,
                      resume_to=None):
    """状态推进 + 事件入账,同一次原子写(design:中断后不存在半程账本)。"""
    src = state.get("status")
    entry_it = state.get("iteration")
    append_transition(state, event, src, dest, entry_it, new_it, ref, param)
    state["status"] = dest
    if new_it != entry_it:
        state["iteration"] = new_it
    if resume_to is not None:
        state["resume_to"] = resume_to
    else:
        state.pop("resume_to", None)
    write_json_atomic(rc_root / "state.json", state)
    rep.written.append("state.json")
    rep.status = dest
    rep.iteration = new_it


def closeout_pass(rc_root, state, rep, was_bound):
    """PASS 收口链:绑定复算 → 渲染 → 逐字节校验 → 上限 → 原子 COMPLETE。"""
    iteration = rep.iteration
    art_name = f"{file_no(iteration):02d}-artifact.json"
    # 1) 绑定复算(输入漂移即作废;provenance 写进报告文件)
    try:
        ver, ver_written = bind_report(rc_root, state, iteration, rep)
    except ProvenanceError as e:
        rep.error(e.file, e.json_path, str(e))
        return rep.emit()
    if ver_written:
        rep.written.append(ver_written)
    # 2) 确定性渲染(内存中完成,失败不触碰发布物)
    art = read_json(rc_root / "iterations" / art_name)
    try:
        text = render_spec(art.get("artifact"), state, f"{art_name}")
    except RenderError as e:
        rep.error(f"iterations/{art_name}", getattr(e, "json_path", None), str(e))
        return rep.emit()
    expected = text.encode("utf-8")
    spec_path = rc_root / "output" / "spec.md"
    # 3) 逐字节校验:本轮已绑定过 PASS 而盘上发布物不一致 → 手改,拒绝
    if was_bound and spec_path.is_file() \
            and spec_path.read_bytes() != expected:
        rep.error("output/spec.md", None,
                  "已绑定 PASS 后发布物与来源渲染不一致(手工修改),"
                  "拒绝覆盖;恢复:撤销手改后重跑同一命令")
        return rep.emit()
    # 4) iteration 上限(R8 同源检查,先于发布)
    if iteration > state.get("max_iterations", 5):
        rep.error("state.json", "$.iteration",
                  f"iteration={iteration} 超过 max_iterations="
                  f"{state.get('max_iterations', 5)},不得宣称完成")
        return rep.emit()
    # 4.5) 交付副本冲突检查(T1-6):登记 deliver_to 时,变更目录已有
    # 不同内容的 spec.md(其他轮次或手工写入)→ 整体失败,两处都不写
    deliver_to = state.get("deliver_to")
    deliver_path = None
    if isinstance(deliver_to, str) and deliver_to:
        # rc → <轮次> → .pev → workspace;deliver_to 相对 workspace
        deliver_path = rc_root.parent.parent.parent / deliver_to / "spec.md"
        try:
            occupied = deliver_path.read_bytes()
        except OSError:
            occupied = None
        if occupied is not None and occupied != expected:
            rep.error(f"{deliver_to}/spec.md", None,
                      f"交付目标已被其他内容占用({deliver_path}),"
                      "拒绝覆盖;确认归属后人工处理目标文件再重跑")
            return rep.emit()
    # 5) 原子发布 → 6) 原子 COMPLETE(状态+事件同一次落盘)
    try:
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = spec_path.parent / ".render.tmp"
        tmp.write_bytes(expected)
        tmp.replace(spec_path)
    except OSError as e:
        rep.error("output/spec.md", None, f"写入失败,旧文件保持原状: {e}")
        return rep.emit()
    rep.written.append("output/spec.md")
    if deliver_path is not None:
        try:
            deliver_path.parent.mkdir(parents=True, exist_ok=True)
            dtmp = deliver_path.parent / ".render.tmp"
            dtmp.write_bytes(expected)
            dtmp.replace(deliver_path)
        except OSError as e:
            rep.error(f"{deliver_to}/spec.md", None,
                      f"交付写入失败: {e};原发布物 output/spec.md 已更新")
            return rep.emit()
        rep.written.append(f"{deliver_to}/spec.md")
    final_ver = read_json(rc_root / "iterations"
                          / f"{file_no(iteration):02d}-verification.json")
    advance_and_write(rc_root, state, rep, event="complete", dest="COMPLETE",
                      new_it=iteration, ref=canonical_sha256(final_ver),
                      param={"verdict": "PASS"})
    post_validate(rc_root, rep)
    rep.next.append({"kind": "stop",
                     "reason": "已发布 output/spec.md 并完成;交付下游 behavior-decompose"})
    return rep.emit()


def main():
    argv = sys.argv[1:]
    rep = Reporter("commit")
    sub = None
    draft_path = None
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--rc-root" and i + 1 < len(argv):
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
    rc_root = parse_rc_root(rest, "commit", rep)
    if rc_root is None or rep.errors:
        return rep.emit()
    if draft_path is None:
        rep.command_error("commit", "缺少草稿绝对路径参数")
        return rep.emit()
    state = load_state(rc_root, rep)
    if state is None:
        return rep.emit()
    iteration = rep.iteration
    if not isinstance(iteration, int) or iteration < 0:
        rep.error("state.json", "$.iteration",
                  f"iteration 缺失或非整数: {iteration!r}")
        return rep.emit()
    status = rep.status

    draft = read_json(Path(draft_path).expanduser().resolve())
    if draft is None:
        rep.command_error("commit", f"草稿无法读取/解析: {draft_path}")
        return rep.emit()

    # COMPLETE 是终点:一切写入冻结(verification 的 done 重跑在下方先行判定)
    if status == "COMPLETE" and sub != "verification":
        rep.error("state.json", "$.status",
                  "COMPLETE 为终点,一切写入冻结;修订走 reopen --note",
                  code="E_FROZEN_STATE")
        return rep.emit()

    if sub == "state-update":
        return do_state_update(rc_root, state, draft, rep)
    return do_commit(rc_root, state, draft, rep, sub)


def do_state_update(rc_root, state, patch, rep):
    status = rep.status
    if status not in ("WAITING_FOR_INPUT", "WAITING_FOR_PRD"):
        rep.error("state.json", "$.status",
                  f"state-update 用于恢复停靠态(WAITING_FOR_INPUT/"
                  f"WAITING_FOR_PRD),当前为 {status!r}")
        return rep.emit()
    if not isinstance(patch, dict) or not patch:
        rep.error("$", "$", "补丁须为非空 JSON 对象")
        return rep.emit()
    if not merge_user_input(rc_root, state, patch, rep):
        return rep.emit()

    def emit_next(dest):
        if dest == "PLANNING":
            rep.next.append({"kind": "draft", "target": "plan",
                             "notes": "以 agents/planner.md 重规划受影响批次,"
                                      "经 commit.py plan 提交"})
        elif dest == "EXECUTING":
            rep.next.append({"kind": "draft", "target": "artifact",
                             "notes": "回到 EXECUTING 继续/修订 Artifact,"
                                      "经 commit.py artifact 提交"})
        elif dest == "VERIFYING":
            rep.next.append({"kind": "dispatch-verifier",
                             "snapshot": f"iterations/"
                                         f"{file_no(rep.iteration):02d}-verification-input.json"})
        else:
            rep.next.append({"kind": "stop",
                             "reason": "已记 prd_gaps;等待 PRD 更新,"
                                       "届时以 state-update prd_refreshed 恢复"})

    iteration = rep.iteration
    if patch.get("prd_refreshed"):
        if status != "WAITING_FOR_PRD":
            rep.error("state.json", "$.status",
                      "prd_refreshed 仅用于 WAITING_FOR_PRD")
            return rep.emit()
        if iteration_limit_guard(state, rep, iteration + 1, "PRD 更新恢复"):
            return rep.emit()
        state["prd_gaps"] = []
        advance_and_write(rc_root, state, rep, "state-update", "PLANNING",
                          iteration + 1, None, {"branch": "prd-refresh"})
    elif patch.get("back_to_prd"):
        if status != "WAITING_FOR_INPUT":
            rep.error("state.json", "$.status",
                      "back_to_prd 仅用于 WAITING_FOR_INPUT")
            return rep.emit()
        gaps = patch.get("prd_gaps")
        if not isinstance(gaps, list) or not gaps:
            rep.error("$", "$.prd_gaps",
                      "R4: back_to_prd 须携带非空 prd_gaps(question+prd_anchor)")
            return rep.emit()
        state["prd_gaps"] = gaps
        advance_and_write(rc_root, state, rep, "state-update",
                          "WAITING_FOR_PRD", iteration, None,
                          {"branch": "back-to-prd"})
    elif patch.get("invalidate_plan"):
        if status != "WAITING_FOR_INPUT":
            rep.error("state.json", "$.status",
                      "invalidate_plan 仅用于 WAITING_FOR_INPUT")
            return rep.emit()
        if iteration_limit_guard(state, rep, iteration + 1, "重规划"):
            return rep.emit()
        advance_and_write(rc_root, state, rep, "state-update", "PLANNING",
                          iteration + 1, None, {"branch": "invalidate"})
    else:
        target = state.get("resume_to")
        if target not in ("PLANNING", "EXECUTING", "VERIFYING"):
            rep.error("state.json", "$.resume_to",
                      f"恢复要求合法 resume_to,当前为 {target!r}")
            return rep.emit()
        advance_and_write(rc_root, state, rep, "state-update", target,
                          iteration, None, {"branch": "resume"})
        if target == "VERIFYING":
            # 答复并入了 Artifact/State,旧快照已过期:自动重冻结再派发
            try:
                _, snap_written = write_snapshot(rc_root, state, iteration)
            except ProvenanceError as e:
                rep.error(e.file, e.json_path, str(e))
                return rep.emit()
            if snap_written:
                rep.written.append(snap_written)
    post_validate(rc_root, rep)
    emit_next(rep.status)
    return rep.emit()


def do_commit(rc_root, state, draft, rep, sub):
    iteration = rep.iteration
    status = rep.status
    name = doc_path(iteration, sub)
    disk_doc_path = rc_root / "iterations" / f"{file_no(iteration):02d}-{sub}.json"

    # PASS 收口的 done 判定先于冻结检查:收口完成后重跑同一命令 = 幂等成功
    if sub == "verification" and status == "COMPLETE":
        ver = read_json(disk_doc_path)
        last = (state.get("transitions") or [None])[-1]
        if (isinstance(ver, dict) and isinstance(last, dict)
                and last.get("event") == "complete"
                and last.get("ref_sha256") == canonical_sha256(ver)):
            rep.warn("重跑判已完成,未重复转移")
            rep.next.append({"kind": "stop",
                             "reason": "本轮已收口;交付下游 behavior-decompose"})
            return rep.emit()

    # 阶段守卫
    stage = STAGE_OF[sub]
    if status not in stage:
        rep.error("state.json", "$.status",
                  f"阶段不匹配:{sub} 提交要求 status ∈ {stage},当前为 {status}")
        return rep.emit()

    # 绑定 PASS 后的覆盖权限:同内容重跑放行(幂等),内容变更拒绝
    was_bound = False
    if sub == "verification" and disk_doc_path.is_file():
        prev = read_json(disk_doc_path)
        if isinstance(prev, dict) and "provenance" in prev:
            prev_unbound = {k: v for k, v in prev.items() if k != "provenance"}
            if prev_unbound != draft:
                rep.error(name, "$",
                          "当前轮已有绑定 PASS 的验证报告,且本次草稿与已提交内容"
                          "不一致,覆盖被拒绝;修订走 reopen --note",
                          code="E_BOUND_PASS")
                return rep.emit()
            was_bound = True
    if sub in ("plan", "artifact") and bound_pass_exists(rc_root, iteration):
        rep.error(name, "$",
                  "当前轮已存在绑定 PASS 的验证,一切覆盖提交被拒绝;修订走 reopen")
        return rep.emit()

    # 草稿校验(schema + 草稿级语义规则),先于落盘拒绝
    errs = validator.Errors()
    schema = json.loads((validator.SCHEMA_DIR / SCHEMA_OF[sub])
                        .read_text(encoding="utf-8"))
    validator.validate(draft, schema, name, "$", errs)
    if sub == "plan":
        check_value_first(draft, name, errs)
    if sub == "artifact" and draft.get("status") in ("replan_required",
                                                     "blocked"):
        reason = draft.get("replan_reason")
        if not isinstance(reason, dict) or not any(
                isinstance(v, str) and v.strip() for v in reason.values()):
            errs.add(name, "$.replan_reason",
                     "R2: status 为 replan_required/blocked 时 replan_reason "
                     "必须至少填写一个非空字段")
    if sub == "artifact" and draft.get("status") == "completed":
        try:
            validate_body(draft.get("artifact"), f"{file_no(iteration):02d}-artifact.json")
        except RenderError as e:
            errs.add(name, getattr(e, "json_path", None), str(e))
    if sub == "verification":
        check_verdict_content(draft, name, errs)
        snap_name = f"iterations/{file_no(iteration):02d}-verification-input.json"
        snap = read_json(rc_root / "iterations"
                         / f"{file_no(iteration):02d}-verification-input.json")
        if snap is None:
            errs.add(name, "$.verification_input",
                     "快照不存在,先经 commit artifact(completed)冻结验证输入")
        elif draft.get("verification_input") != snap:
            errs.add(name, "$.verification_input",
                     "报告复述与盘上快照不一致(错轮或输入漂移),不可提交")
    # Errors.add(file, path, message) 以空格拼接;这里转为协议 errors
    for item in errs.items:
        file_part, _, rest_msg = item.partition(" ")
        json_part, _, reason = rest_msg.partition(": ")
        rep.error(file_part, json_part or None, reason or rest_msg)
    if rep.errors:
        return rep.emit()

    # 产物落盘;已绑定报告的同内容重跑不重写文件(provenance 保留)
    if not (sub == "verification" and was_bound):
        write_json_atomic(disk_doc_path, draft)
        rep.written.append(name)

    if sub == "plan":
        reg = state.setdefault("plans", [])
        if disk_doc_path.name not in reg:
            reg.append(disk_doc_path.name)
        advance_and_write(rc_root, state, rep, event="plan", dest="EXECUTING",
                          new_it=iteration, ref=canonical_sha256(draft))
        post_validate(rc_root, rep)
        rep.next.append({"kind": "draft", "target": "artifact",
                         "notes": "以 agents/executor.md 按当前 Plan 批次执行,"
                                  "经 commit.py artifact 提交"})
        return rep.emit()

    if sub == "artifact":
        reg = state.setdefault("artifacts", [])
        if disk_doc_path.name not in reg:
            reg.append(disk_doc_path.name)
        branch = draft.get("status")
        # 答复与决定确定性并入 Ledger(取代模型手工双写)
        for key in ("evidence",):
            entries = draft.get(key) or []
            ledger = state.setdefault("evidence", [])
            known = {json.dumps(e, sort_keys=True, ensure_ascii=False)
                     for e in ledger if isinstance(e, dict)}
            for e in entries:
                if isinstance(e, dict) \
                        and json.dumps(e, sort_keys=True, ensure_ascii=False) not in known:
                    ledger.append(e)
        if branch == "completed":
            try:
                _, snap_written = write_snapshot(rc_root, state, iteration)
            except ProvenanceError as e:
                rep.error(e.file, e.json_path, str(e))
                return rep.emit()
            if snap_written:
                rep.written.append(snap_written)
            advance_and_write(rc_root, state, rep, event="artifact",
                              dest="VERIFYING", new_it=iteration,
                              ref=canonical_sha256(draft))
            post_validate(rc_root, rep)
            rep.next.append({"kind": "dispatch-verifier",
                             "snapshot": f"iterations/"
                                         f"{file_no(iteration):02d}-verification-input.json",
                             "artifact": name})
            return rep.emit()
        if branch == "replan_required":
            if iteration_limit_guard(state, rep, iteration + 1, "重规划"):
                return rep.emit()
            advance_and_write(rc_root, state, rep, event="artifact",
                              dest="PLANNING", new_it=iteration + 1,
                              ref=canonical_sha256(draft))
            post_validate(rc_root, rep)
            rep.next.append({"kind": "draft", "target": "plan",
                             "notes": "以 agents/planner.md 吸收 replan_reason 重规划"})
            return rep.emit()
        # blocked
        advance_and_write(rc_root, state, rep, event="artifact",
                          dest="WAITING_FOR_INPUT", new_it=iteration,
                          ref=canonical_sha256(draft), resume_to="EXECUTING")
        post_validate(rc_root, rep)
        rep.next.append({"kind": "ask-user",
                         "items": ["逐问呈现:问题 / 为什么重要 / 推荐答案 / 三选一"]})
        return rep.emit()

    # verification
    verdict = draft.get("verdict")
    if verdict == "PASS":
        return closeout_pass(rc_root, state, rep, was_bound)
    if verdict == "REVISE":
        if iteration_limit_guard(state, rep, iteration + 1, "修订"):
            return rep.emit()
        advance_and_write(rc_root, state, rep, event="verification",
                          dest="EXECUTING", new_it=iteration + 1,
                          ref=canonical_sha256(draft),
                          param={"verdict": verdict})
        post_validate(rc_root, rep)
        rep.next.append({"kind": "draft", "target": "artifact",
                         "notes": "按 required_changes 修订 Artifact 后重新提交"})
        return rep.emit()
    if verdict == "REPLAN":
        if iteration_limit_guard(state, rep, iteration + 1, "重规划"):
            return rep.emit()
        advance_and_write(rc_root, state, rep, event="verification",
                          dest="PLANNING", new_it=iteration + 1,
                          ref=canonical_sha256(draft),
                          param={"verdict": verdict})
        post_validate(rc_root, rep)
        rep.next.append({"kind": "draft", "target": "plan",
                         "notes": "以 agents/planner.md 吸收 critical_issues/"
                                  "evidence_gaps 重规划"})
        return rep.emit()
    # BLOCKED
    advance_and_write(rc_root, state, rep, event="verification",
                      dest="WAITING_FOR_INPUT", new_it=iteration,
                      ref=canonical_sha256(draft), resume_to="VERIFYING")
    post_validate(rc_root, rep)
    rep.next.append({"kind": "ask-user",
                     "items": ["逐问呈现 Verifier 的未决问题:"
                               "问题 / 为什么重要 / 推荐答案 / 三选一"]})
    return rep.emit()


if __name__ == "__main__":
    sys.exit(run("commit", main))
