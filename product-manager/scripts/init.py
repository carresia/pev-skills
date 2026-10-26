#!/usr/bin/env python3
"""初始化与恢复定位:创建轮次目录与 state.json,或扫描汇报全部轮次。

用法:
    python3 init.py --objective <草稿绝对路径> --workspace <含 .pev/ 的目录>
        [--carry-from <旧轮目录名>]
    python3 init.py --locate --workspace <含 .pev/ 的目录>

建轮即入阶段(design §5.1,事件面合并):goal 齐全 → PLANNING、iteration=1;
goal 缺失 → WAITING_FOR_INPUT + resume_to="PLANNING"、iteration=1(消除
iter=0 死角)。init 不追加 transitions 条目(建轮写入即初值);同日已有同
目标的活跃轮次 → 幂等报告现状不重建;同日新目标 → 目录名追加 -2、-3。
target_metric 缺失与 baseline 为 null 是 schema 合法状态,仅 warnings 提示。

--carry-from(换轮携账本,design §4.1):旧轮须为终态(COMPLETE/STOPPED/
SUPERSEDED;活轮该 resume/reopen,不给携账本);把旧轮八字段语义投影
(objective 除外——新草稿的目标覆盖之)携入新轮初值,evidence 按 id 原样
携入,后续更正走同 id 整条替换;新轮 state 写 carried_from 单向记录。

--locate 汇报:最新可自动定位轮次(pm_root)+ 全部轮次清单(目录名/status/
iteration/是否终态)+ 悬挂轮警告(非终态且非被选中轮,只读)+ 命名不匹配
目录(含 pm/state.json 但名字不合 prd-<date>[-N];不参与自动选择,须用户
点名);全部不匹配时明确报"无可自动定位轮次"。
"""

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    PROJECTION_INCLUDE, Reporter, SKILL_ROOT, load_state, read_json, run,
    write_json_atomic,
)

ACTIVE_STATUSES = {"INIT", "PLANNING", "EXECUTING", "VERIFYING",
                   "WAITING_FOR_INPUT"}
TERMINAL_STATUSES = {"COMPLETE", "STOPPED", "SUPERSEDED"}
ROUND_NAME_RE = re.compile(r"prd-(\d{4}-\d{2}-\d{2})(?:-(\d+))?$")


def next_free_round(pev_dir, base):
    """base 同名不含 state.json 即复用(重建沿用原名);否则追加 -2、-3。"""
    candidate = pev_dir / base
    seq = 1
    while (candidate / "pm" / "state.json").is_file():
        seq += 1
        candidate = pev_dir / f"{base}-{seq}"
    return candidate, seq


def active_round_with_same_goal(pev_dir, base, goal):
    """同日已有活跃轮次且 objective.goal 相同 → 幂等重建。

    活跃 = ACTIVE_STATUSES;终态轮(COMPLETE/STOPPED/SUPERSEDED)不算活跃
    (同目标重开须新建轮次;SUPERSEDED 后的继任轮可经 --carry-from 携账本)。
    """
    candidate = pev_dir / base
    seq = 1
    while candidate.is_dir():
        state_path = candidate / "pm" / "state.json"
        if state_path.is_file():
            state = read_json(state_path)
            if (isinstance(state, dict)
                    and state.get("status") in ACTIVE_STATUSES
                    and str((state.get("objective") or {}).get("goal", "")).strip()
                    == goal):
                return candidate
        seq += 1
        candidate = pev_dir / f"{base}-{seq}"
    return None


def round_sort_key(name):
    """prd-YYYY-MM-DD[-N] 的排序键:日期优先,序号按数值(避免 -10 早于 -9)。

    不匹配命名 → ("", -1):不参与自动选择(见 do_locate),但会入汇报清单。
    """
    m = ROUND_NAME_RE.match(name)
    if m is None:
        return ("", -1)
    return (m.group(1), int(m.group(2) or 0))


def do_locate(workspace, rep):
    """汇报全部轮次;自动选择排序最大的合法命名轮次(design §5.2)。"""
    pev_dir = workspace / ".pev"
    rounds = []  # (目录名, sort_key, state dict or None)
    if pev_dir.is_dir():
        for d in sorted(pev_dir.iterdir()):
            state_path = d / "pm" / "state.json"
            if d.is_dir() and state_path.is_file():
                rounds.append((d.name, round_sort_key(d.name),
                               read_json(state_path)))
    matched = [r for r in rounds if r[1][0] != ""]
    unmatched = [r for r in rounds if r[1][0] == ""]

    def brief(name, state):
        if not isinstance(state, dict):
            return f"{name} state.json 不可解析"
        status = state.get("status")
        terminal = "是" if status in TERMINAL_STATUSES else "否"
        return (f"{name} status={status} iteration={state.get('iteration')} "
                f"终态={terminal}")

    if not matched:
        if rounds:
            rep.warn("无可自动定位轮次:以下目录含 pm/state.json 但命名不合 "
                     "prd-<date>[-N],不参与自动选择,由用户点名")
            for name, _, state in unmatched:
                rep.warn(f"命名不匹配:{brief(name, state)}")
        else:
            rep.warn("没有任何轮次含 pm/state.json,无可恢复的 PM 状态;按 INIT 开始")
        rep.next.append({"kind": "draft", "target": "objective",
                         "notes": "起草 objective 后运行 init.py --objective"})
        return rep.emit()

    best = max(matched, key=lambda r: r[1])
    for name, _, state in sorted(rounds, key=lambda r: r[1]):
        rep.warn(f"轮次清单:{brief(name, state)}")
    for name, _, state in matched:
        if name == best[0]:
            continue
        if isinstance(state, dict) and state.get("status") not in TERMINAL_STATUSES:
            rep.warn(f"悬挂轮:{brief(name, state)};非终态且非被选中的最新轮,"
                     "只读发现,不自动处置(存量现场口径)")
    for name, _, state in unmatched:
        rep.warn(f"命名不匹配:{brief(name, state)};不参与自动选择,须用户点名")
    rep.pm_root = str(pev_dir / best[0] / "pm")
    load_state(Path(rep.pm_root), rep)
    return rep.emit()


def main():
    argv = sys.argv[1:]
    do_bind_locate = "--locate" in argv
    command = "init --locate" if do_bind_locate else "init"
    rep = Reporter(command)
    rest = [a for a in argv if a != "--locate"]

    workspace = None
    objective_path = None
    carry_from = None
    i = 0
    while i < len(rest):
        if rest[i] == "--workspace" and i + 1 < len(rest):
            workspace = Path(rest[i + 1]).expanduser().resolve()
            i += 2
        elif rest[i] == "--objective" and i + 1 < len(rest):
            objective_path = Path(rest[i + 1]).expanduser().resolve()
            i += 2
        elif rest[i] == "--carry-from" and i + 1 < len(rest):
            carry_from = rest[i + 1]
            i += 2
        else:
            rep.command_error(command, f"无法识别的参数: {rest[i]}")
            return rep.emit()
    if workspace is None:
        rep.command_error(command, "缺少 --workspace <含 .pev/ 的目录>")
        return rep.emit()
    if not workspace.is_dir():
        rep.command_error(command, f"workspace 目录不存在: {workspace}")
        return rep.emit()

    if do_bind_locate:
        return do_locate(workspace, rep)

    if objective_path is None:
        rep.command_error(command, "缺少 --objective <草稿绝对路径>")
        return rep.emit()
    objective = read_json(objective_path)
    if not isinstance(objective, dict):
        rep.command_error(command,
                          f"objective 草稿无法解析为对象: {objective_path}")
        return rep.emit()

    goal = objective.get("goal")
    goal_missing = (goal is None or (isinstance(goal, str) and not goal.strip()))

    pev_dir = workspace / ".pev"
    base = f"prd-{time.strftime('%Y-%m-%d')}"
    same = active_round_with_same_goal(pev_dir, base,
                                       str(goal or "").strip())
    if same is not None:
        rep.pm_root = str(same / "pm")
        state = load_state(same / "pm", rep)
        rep.warn("同日已存在同目标的活跃轮次,不重建;按当前状态继续")
        if carry_from is not None:
            rep.warn("--carry-from 未生效:幂等续用既有活跃轮,不携账本")
        if state is not None and rep.status == "INIT":
            # 存量 INIT 轮(本 change 前创建):start-planning 已并入 init,无推进命令
            rep.warn("存量 INIT 轮无阶段推进命令;继续工作:supersede 换轮后 "
                     "init --carry-from,或人工确认废弃")
            rep.next.append({"kind": "ask-user",
                             "items": ["存量 INIT 轮处置:换轮(supersede + "
                                       "carry-from)或确认废弃"]})
        elif state is not None and rep.status == "PLANNING":
            rep.next.append({"kind": "draft", "target": "plan",
                             "notes": "以 agents/planner.md 起草 Plan,"
                                      "经 commit.py plan 提交"})
        elif state is not None and rep.status == "WAITING_FOR_INPUT":
            rep.next.append({
                "kind": "ask-user",
                "items": ["按 WAITING 恢复协议向用户确认缺失项"],
            })
        # 其余活动状态:只读汇报,续接以最近一次产物与 validate 结果为准
        return rep.emit()
    # --carry-from:源须为终态轮;活轮该 resume/reopen,不给携账本(design §4.1)
    carry_state = None
    if carry_from is not None:
        src_state_path = pev_dir / carry_from / "pm" / "state.json"
        carry_state = read_json(src_state_path) if src_state_path.is_file() else None
        if not isinstance(carry_state, dict):
            rep.command_error(command,
                              f"--carry-from 源不存在或不可解析: {src_state_path}")
            return rep.emit()
        if carry_state.get("status") not in TERMINAL_STATUSES:
            rep.command_error(
                command,
                f"carry 源 {carry_from} 为活跃轮(status={carry_state.get('status')});"
                "活轮该 resume/reopen,不给携账本;换轮先 transition.py supersede",
                code="E_CARRY_SOURCE_ACTIVE")
            return rep.emit()

    round_dir, _ = next_free_round(pev_dir, base)
    pm_dir = round_dir / "pm"
    pm_dir.mkdir(parents=True, exist_ok=True)
    (pm_dir / "iterations").mkdir(exist_ok=True)
    rep.pm_root = str(pm_dir)

    # 建轮即 PLANNING(WAITING 变体同 iteration=1,消除 iter=0 死角);
    # init 不追加 transitions 条目(建轮写入即初值,design §5.1)
    state = {
        "objective": objective,
        "status": "WAITING_FOR_INPUT" if goal_missing else "PLANNING",
        "iteration": 1,
        "max_iterations": 5,
    }
    if goal_missing:
        state["resume_to"] = "PLANNING"
    if carry_state is not None:
        # 携旧轮八字段语义投影;objective 以新草稿为准(换轮即目标变更)
        for key in PROJECTION_INCLUDE:
            if key != "objective" and key in carry_state:
                state[key] = json.loads(json.dumps(carry_state[key],
                                                   ensure_ascii=False))
        state["carried_from"] = carry_from
        rep.warn(f"已从 {carry_from} 携带语义投影(evidence "
                 f"{len(state.get('evidence') or [])} 条按 id 原样携入;"
                 "objective 以新草稿为准)")
    for optional in ("target_metric", "baseline"):
        if objective.get(optional) in (None, ""):
            rep.warn(f"objective.{optional} 缺失(未知为 null,schema 合法;"
                     "是否足以开工由 Planner 判断)")
    write_json_atomic(pm_dir / "state.json", state)
    rep.written.append("state.json")

    if goal_missing:
        rep.next.append({
            "kind": "ask-user",
            "items": ["objective.goal 缺失:缺什么 / 为什么重要 / 怎么获取"],
        })
    else:
        rep.next.append({"kind": "draft", "target": "plan",
                         "notes": "以 agents/planner.md 起草 Plan,"
                                  "经 commit.py plan 提交"})
    return rep.emit()


if __name__ == "__main__":
    sys.exit(run("init", main))
