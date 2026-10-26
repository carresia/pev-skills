#!/usr/bin/env python3
"""状态机事件转移:执行 SKILL.md 状态机表的边,原子写 state.json 并追加 transitions。

用法:
    python3 transition.py --pm-root <pm 目录绝对路径> <事件> [旗标]

事件:start-planning | need-input | plan-validated | executor-replan |
executor-blocked | artifact-validated | verdict | complete | resume |
reopen | authorized-resume | supersede。旗标:resume 的 --invalidate-plan
变体;reopen 的 --note <prd_gaps 要点>(必填);authorized-resume 的
--max-iterations <新上限>(必填);supersede 的 --note <废弃原因>(必填)。

再进入类事件的触发场景(区别在于轮次当前处于什么状态):
  resume            轮次未结束,停在 WAITING_FOR_INPUT 等用户拍板(开放问题/
                    待裁定项);用户回复后触发,回 PLANNING。回答推翻现有计划时
                    加 --invalidate-plan。
  reopen            轮次已 COMPLETE(已交付),下游 requirement-clarify 打回
                    prd_gaps;iteration+1 回 PLANNING 重规划,--note 必填。
  authorized-resume 轮次达到迭代上限被写 STOPPED;用户明确授权提高上限后
                    触发,--max-iterations 必填。
  supersede         目标、范围、优先级或交付物形态变更,废弃现轮换新轮;
                    任何状态→SUPERSEDED(不可逆终态,一切写入冻结),
                    --note 必填;继任轮由 init.py --carry-from 创建。
  (另:init.py 的同目标幂等续用不是状态机事件——同日同 goal 且轮次活跃时
  init 不重建、直接续用;终态轮同 goal 则新建 -N 轮次,不走本表。)

重跑判定(纯函数,见 design"事件身份与重跑判据"):已执行 → 退出 0 不重复
转移;新事件或首次 → 按守卫执行;其余 → 非法,列出当前状态与全部合法事件。
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Reporter, SKILL_ROOT, canonical_sha256, load_state, parse_pm_root,
    read_json, run, write_json_atomic,
)

EVENT_SOURCE = {
    "start-planning": "INIT",
    "need-input": "PLANNING",
    "plan-validated": "PLANNING",
    "executor-replan": "EXECUTING",
    "executor-blocked": "EXECUTING",
    "artifact-validated": "EXECUTING",
    "verdict": "VERIFYING",
    "complete": "VERIFYING",
    "resume": "WAITING_FOR_INPUT",
    "reopen": "COMPLETE",
    "authorized-resume": "STOPPED",
    "supersede": None,  # 任何状态可触发,见 ANY_SOURCE_EVENTS
}
RESUME_STAGES = ("PLANNING", "EXECUTING", "VERIFYING")
# 无单一源状态的事件:supersede 从任何状态(含终态)触发;
# 已处 SUPERSEDED 时的放行规则见 main 的终态冻结检查
ANY_SOURCE_EVENTS = {"supersede"}


def norm(value):
    return value if value is not None else None


def classify(state, event, param, ref):
    """重跑三分支判定;输入只有 state 与命令参数(纯函数)。"""
    transitions = state.get("transitions") or []
    status = state.get("status")
    iteration = state.get("iteration")

    def ident(t):
        return (t.get("event") == event
                and norm(t.get("param")) == norm(param)
                and norm(t.get("ref_sha256")) == norm(ref))

    if transitions:
        last = transitions[-1]
        if (ident(last) and last.get("to_iteration") == iteration
                and last.get("to") == status):
            return "done"
    if event == "resume" and status != "WAITING_FOR_INPUT":
        if any(t.get("event") == "resume" and norm(t.get("param")) == norm(param)
               for t in transitions):
            return "done"
    if status == EVENT_SOURCE.get(event):
        return "execute"
    if event in ANY_SOURCE_EVENTS and status != "SUPERSEDED":
        return "execute"
    return "illegal"


def run_gate(args):
    """守卫的"重跑校验":调用对应脚本,返回退出码。"""
    proc = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / args[0]), *args[1:]],
        capture_output=True, text=True)
    return proc.returncode


def latest_doc(pm, iteration, kind):
    path = pm / "iterations" / f"{iteration:02d}-{kind}.json"
    return read_json(path) if path.is_file() else None


def derive_next(pm, state, event, branch=None):
    """按事件表与当前状态推导下一步(结构化对象数组)。"""
    status = state.get("status")
    if event == "start-planning" or event == "reopen" \
            or event == "authorized-resume" or branch == "REPLAN" \
            or event == "executor-replan":
        return [{"kind": "draft", "target": "plan",
                 "notes": "以 agents/planner.md 起草 Plan,经 commit.py plan 提交"}]
    if event == "supersede":
        return [{"kind": "draft", "target": "objective",
                 "notes": "换轮:起草新 objective 后以 init.py --objective <草稿> "
                          "--workspace <目录> --carry-from <旧轮目录名> 创建继任轮"
                          "(旧轮已冻结,证据保全)"}]
    if event == "plan-validated":
        return [{"kind": "draft", "target": "artifact",
                 "notes": "以 agents/executor.md 起草 Artifact,经 commit.py artifact 提交"}]
    if event == "artifact-validated":
        return [{"kind": "command", "cwd": str(SKILL_ROOT),
                 "argv": ["scripts/record_provenance.py", "--pm-root",
                          str(pm)]}]
    if branch == "REVISE":
        return [{"kind": "draft", "target": "artifact",
                 "notes": "按 required_changes 修订 Artifact 后重新提交"}]
    if branch == "BLOCKED" or event == "executor-blocked" or event == "need-input":
        return [{"kind": "ask-user",
                 "items": ["缺什么 / 为什么重要 / 怎么获取"]}]
    if branch == "PASS":
        return [{"kind": "command", "cwd": str(SKILL_ROOT),
                 "argv": ["scripts/render.py", "--pm-root", str(pm)]}]
    if event == "resume":
        target = state.get("status")
        if target == "PLANNING":
            return [{"kind": "draft", "target": "plan",
                     "notes": "回到 PLANNING;Plan 失效走 resume --invalidate-plan 变体"}]
        if target == "EXECUTING":
            return [{"kind": "draft", "target": "artifact",
                     "notes": "回到 EXECUTING 继续/修订 Artifact"}]
        if target == "VERIFYING":
            return [{"kind": "command", "cwd": str(SKILL_ROOT),
                     "argv": ["scripts/record_provenance.py", "--pm-root",
                              str(pm)]}]
    return []


def make_entry(event, src, dst, it, new_it, ref, param):
    return {"event": event, "from": src, "to": dst,
            "from_iteration": it, "to_iteration": new_it,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ref_sha256": ref, "param": param}


def stop_at_limit(pm, state, rep, event, it, ref, param):
    """+1 越上限:写 STOPPED 并拒绝该转移;恢复仅经 authorized-resume。"""
    src = EVENT_SOURCE[event]
    state["status"] = "STOPPED"
    state.pop("resume_to", None)
    entry = make_entry(event, src, "STOPPED", it, it, ref,
                       {"requested": param} if param is not None
                       else "iteration+1 超上限")
    state.setdefault("transitions", []).append(entry)
    write_json_atomic(pm / "state.json", state)
    rep.status = "STOPPED"
    rep.iteration = it
    rep.written.append("state.json")
    rep.warn("iteration+1 超过 max_iterations,已写 STOPPED;"
             "须向用户报告当前最佳结论、critical_issues、evidence_gaps")
    rep.next.append({"kind": "stop",
                     "reason": "达到迭代上限;恢复仅经 authorized-resume 且记录授权"})
    return rep.emit()


def main():
    argv = sys.argv[1:]
    rep = Reporter("transition")
    invalidate = "--invalidate-plan" in argv
    note = None
    new_max = None
    event = None
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--pm-root" and i + 1 < len(argv):
            rest += argv[i:i + 2]
            i += 2
        elif a == "--invalidate-plan":
            invalidate = True
            i += 1
        elif a == "--note" and i + 1 < len(argv):
            note = argv[i + 1]
            i += 2
        elif a == "--max-iterations" and i + 1 < len(argv):
            new_max = argv[i + 1]
            i += 2
        elif event is None and not a.startswith("--"):
            event = a
            i += 1
        else:
            rep.command_error("transition", f"无法识别的参数: {a}")
            return rep.emit()

    if event is None:
        rep.command_error("transition",
                          f"缺少事件;合法事件: {sorted(EVENT_SOURCE)}")
        return rep.emit()
    param = None
    if event == "resume" and invalidate:
        param = "invalidate"
    elif invalidate:
        rep.command_error("transition", "--invalidate-plan 只用于 resume 事件")
        return rep.emit()
    if event == "reopen":
        if not (isinstance(note, str) and note.strip()):
            rep.command_error("transition",
                              "reopen 须以 --note 记录 prd_gaps 来源与要点",
                              code="E_NOTE_REQUIRED")
            return rep.emit()
        param = note.strip()
    if event == "supersede":
        if not (isinstance(note, str) and note.strip()):
            rep.command_error("transition",
                              "supersede 须以 --note 记录废弃原因(用户原话或来源摘录)",
                              code="E_NOTE_REQUIRED")
            return rep.emit()
        param = {"note": note.strip()}
    if event == "authorized-resume":
        if new_max is None or not new_max.isdigit():
            rep.command_error("transition",
                              "authorized-resume 须以 --max-iterations 记录用户授权的新上限")
            return rep.emit()
        param = int(new_max)

    command = f"transition {event}" + (" --invalidate-plan" if invalidate else "")
    rep.command = command
    pm = parse_pm_root(rest, command, rep)
    if pm is None or rep.errors:
        return rep.emit()
    state = load_state(pm, rep)
    if state is None:
        return rep.emit()
    if event not in EVENT_SOURCE:
        rep.error("state.json", "$.status",
                  f"非法事件 {event!r};当前 status={state.get('status')!r},"
                  f"合法事件: {sorted(EVENT_SOURCE)}")
        return rep.emit()
    # SUPERSEDED 不可逆终态:除 supersede 自身的幂等重跑外,一切写入冻结
    if state.get("status") == "SUPERSEDED":
        if event != "supersede":
            rep.error("state.json", "$.status",
                      "SUPERSEDED 是不可逆终态,一切写入冻结;"
                      "对废弃轮反悔=再开新轮并以 init.py --carry-from 携账本",
                      code="E_FROZEN_STATE")
            return rep.emit()
        if classify(state, "supersede", param, None) != "done":
            rep.error("state.json", "$.status",
                      "已处 SUPERSEDED;仅同 --note 的 supersede 幂等重跑放行,"
                      "不同 note 不构成新事件",
                      code="E_FROZEN_STATE")
            return rep.emit()

    it = rep.iteration
    if not isinstance(it, int):
        rep.error("state.json", "$.iteration", "iteration 缺失或非整数")
        return rep.emit()
    if event == "resume" and not invalidate:
        # 普通 resume 的身份参数 = 清除前的 resume_to;须在 classify 前取值
        param = state.get("resume_to")
    if event == "authorized-resume":
        # 用户提额先于上限检查生效;新上限必须严格大于当前值
        cur_max = state.get("max_iterations", 5)
        if not isinstance(param, int) or param <= cur_max:
            rep.error("state.json", "$.max_iterations",
                      f"authorized-resume 须提高上限:新值 {param} 须大于当前 {cur_max};"
                      "授权记录须与实际提额一致")
            return rep.emit()
        state["max_iterations"] = param

    # 事件身份的关联产物摘要(重跑判定用)
    ref = None
    if event == "verdict":
        ver = latest_doc(pm, it, "verification")
        ref = canonical_sha256(ver) if ver is not None else None
    elif event in ("plan-validated",):
        plan = latest_doc(pm, it, "plan")
        ref = canonical_sha256(plan) if plan is not None else None
    elif event in ("artifact-validated", "executor-replan", "executor-blocked",
                   "complete"):
        art = latest_doc(pm, it, "artifact")
        ref = canonical_sha256(art) if art is not None else None

    verdict_branch = classify(state, event, param, ref)
    if verdict_branch == "done":
        rep.warn("重跑判已执行,未重复转移")
        rep.next.extend(derive_next(pm, state, event))
        return rep.emit()

    status = state.get("status")
    if verdict_branch == "illegal":
        last = (state.get("transitions") or [])[-1:]
        rep.error("state.json", "$.status",
                  f"非法转移:事件 {event} 要求 status="
                  f"{EVENT_SOURCE[event]!r},当前为 {status!r};"
                  f"最近转移: {json.dumps(last, ensure_ascii=False) if last else '无'};"
                  f"全部合法事件: {sorted(EVENT_SOURCE)}")
        return rep.emit()

    branch_out = None

    # —— execute 分支:先守卫,后转移 ——
    plus_one_events = {"start-planning", "executor-replan", "reopen",
                       "authorized-resume"}
    # resume --invalidate-plan 也是 +1;其余 resume 不加
    plus_one = event in plus_one_events or (event == "resume" and invalidate)

    new_it = it + 1 if plus_one else it
    max_it = state.get("max_iterations", 5)
    if plus_one and new_it > max_it:
        return stop_at_limit(pm, state, rep, event, it, ref,
                             param if param is not None else event)

    dest = None
    if event == "start-planning":
        goal = (state.get("objective") or {}).get("goal")
        if not (isinstance(goal, str) and goal.strip()):
            rep.error("state.json", "$.objective.goal",
                      "objective.goal 缺失,先补齐目标或走 need-input 问用户")
            return rep.emit()
        dest = "PLANNING"
    elif event == "need-input":
        if f"{it:02d}-plan.json" in (state.get("plans") or []):
            rep.error("state.json", "$.plans",
                      "本轮已登记 Plan,不写占位 Plan;继续现有 Plan 或 REPLAN")
            return rep.emit()
        dest = "WAITING_FOR_INPUT"
    elif event == "plan-validated":
        plan = latest_doc(pm, it, "plan")
        if plan is None or f"{it:02d}-plan.json" not in (state.get("plans") or []):
            rep.error("state.json", "$.plans", f"本轮 Plan 未登记,无法通过校验转移")
            return rep.emit()
        if run_gate(["validate.py", "--pm-root", str(pm)]) != 0:
            rep.error("state.json", "$", "校验未通过,先修复再 plan-validated")
            return rep.emit()
        dest = "EXECUTING"
    elif event in ("executor-replan", "executor-blocked"):
        art = latest_doc(pm, it, "artifact")
        need = "replan_required" if event == "executor-replan" else "blocked"
        if art is None or art.get("status") != need:
            rep.error("state.json", "$",
                      f"{event} 要求最新 Artifact status={need!r}")
            return rep.emit()
        if run_gate(["validate.py", "--pm-root", str(pm)]) != 0:
            rep.error("state.json", "$", "校验未通过(R2 等),先修复")
            return rep.emit()
        dest = "PLANNING" if event == "executor-replan" else "WAITING_FOR_INPUT"
    elif event == "artifact-validated":
        art = latest_doc(pm, it, "artifact")
        if art is None or art.get("status") != "completed":
            rep.error("state.json", "$",
                      "artifact-validated 要求最新 Artifact status=completed")
            return rep.emit()
        if run_gate(["validate.py", "--pm-root", str(pm)]) != 0:
            rep.error("state.json", "$", "A/B/C 校验未通过,不得派发质量评审")
            return rep.emit()
        dest = "VERIFYING"
    elif event == "verdict":
        ver = latest_doc(pm, it, "verification")
        if ver is None:
            rep.error("state.json", "$", "当前轮报告未提交")
            return rep.emit()
        if "provenance" not in ver:
            rep.error("state.json", "$",
                      "报告未绑定 provenance,verdict 不可用于转移;先 --bind")
            return rep.emit()
        if run_gate(["validate.py", "--pm-root", str(pm)]) != 0:
            rep.error("state.json", "$", "校验未通过(P1 复算不一致等),verdict 作废")
            return rep.emit()
        branch = ver.get("verdict")
        branch_out = branch
        if branch == "PASS":
            dest = "VERIFYING"  # 不转移,只解锁收口
        elif branch == "REVISE":
            dest = "EXECUTING"
        elif branch == "REPLAN":
            dest = "PLANNING"
        else:
            dest = "WAITING_FOR_INPUT"
        plus_one = branch in ("REVISE", "REPLAN")
        new_it = it + 1 if plus_one else it
        if plus_one and new_it > max_it:
            return stop_at_limit(pm, state, rep, "verdict", it, ref,
                                 {"verdict": branch})
    elif event == "complete":
        ver = latest_doc(pm, it, "verification")
        if ver is None or "provenance" not in ver or ver.get("verdict") != "PASS":
            rep.error("state.json", "$",
                      "complete 守卫:当前轮须存在已绑定的 PASS")
            return rep.emit()
        if run_gate(["render.py", "--pm-root", str(pm), "--check"]) != 0:
            rep.error("state.json", "$",
                      "complete 守卫:渲染字节比对未通过,先 render.py 发布")
            return rep.emit()
        if run_gate(["validate.py", "--pm-root", str(pm)]) != 0:
            rep.error("state.json", "$", "complete 守卫:校验未通过")
            return rep.emit()
        dest = "COMPLETE"
    elif event == "resume":
        target = state.get("resume_to")
        if target not in RESUME_STAGES:
            rep.error("state.json", "$.resume_to",
                      f"resume 要求合法 resume_to,当前为 {target!r}")
            return rep.emit()
        param = target if not invalidate else param
        dest = "PLANNING" if invalidate else target
    elif event == "reopen":
        dest = "PLANNING"
    elif event == "authorized-resume":
        state["max_iterations"] = param
        dest = "PLANNING"
    elif event == "supersede":
        dest = "SUPERSEDED"  # 唯一不可逆终态:无任何恢复边,反悔=新轮+carry-from

    # —— 原子写:状态 + transitions 同一次落盘 ——
    entry = make_entry(event, status, dest, it, new_it, ref, param)
    state["status"] = dest
    if new_it != it:
        state["iteration"] = new_it
    if dest == "WAITING_FOR_INPUT":
        if event == "verdict":
            state["resume_to"] = "VERIFYING"
        elif event == "executor-blocked":
            state["resume_to"] = "EXECUTING"
        elif event == "need-input":
            state["resume_to"] = "PLANNING"
    else:
        state.pop("resume_to", None)
    state.setdefault("transitions", []).append(entry)
    write_json_atomic(pm / "state.json", state)
    rep.written.append("state.json")
    rep.status = dest
    rep.iteration = new_it

    if run_gate(["validate.py", "--pm-root", str(pm)]) != 0:
        rep.warn("转移已落盘但写后校验未通过;按 errors 恢复,必要时重跑守卫命令")
    rep.next.extend(derive_next(pm, state, event, branch_out))
    return rep.emit()


if __name__ == "__main__":
    sys.exit(run("transition", main))
