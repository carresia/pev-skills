#!/usr/bin/env python3
"""初始化与恢复定位:创建轮次目录与 state.json,或扫描最新可恢复轮次。

用法:
    python3 init.py --objective <草稿绝对路径> --workspace <含 .pev/ 的目录>
    python3 init.py --locate --workspace <含 .pev/ 的目录>

objective 缺 goal(字段不存在、为 null 或空白串)时置 WAITING_FOR_INPUT +
resume_to="PLANNING";target_metric 缺失与 baseline 为 null 是 schema 合法
状态,仅 warnings 提示。同日已有同目标的活跃轮次 → 幂等报告现状不重建;
同日新目标 → 目录名追加 -2、-3。
"""

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Reporter, SKILL_ROOT, load_state, read_json, run, write_json_atomic,
)


def transition_next(pm_dir, event, *extra):
    """构造指向 transition.py 的下一条 command 类 next。"""
    return {"kind": "command", "cwd": str(SKILL_ROOT),
            "argv": ["scripts/transition.py", "--pm-root", str(pm_dir),
                     event, *extra]}


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

    活跃 = status ∈ {INIT, PLANNING, EXECUTING, VERIFYING, WAITING_FOR_INPUT};
    COMPLETE/STOPPED 是终点,不算活跃(同目标重开须新建轮次)。
    """
    active = {"INIT", "PLANNING", "EXECUTING", "VERIFYING", "WAITING_FOR_INPUT"}
    candidate = pev_dir / base
    seq = 1
    while candidate.is_dir():
        state_path = candidate / "pm" / "state.json"
        if state_path.is_file():
            state = read_json(state_path)
            if (isinstance(state, dict)
                    and state.get("status") in active
                    and str((state.get("objective") or {}).get("goal", "")).strip()
                    == goal):
                return candidate
        seq += 1
        candidate = pev_dir / f"{base}-{seq}"
    return None


def round_sort_key(name):
    """prd-YYYY-MM-DD[-N] 的排序键:日期优先,序号按数值(避免 -10 早于 -9)。"""
    m = re.match(r"prd-(\d{4}-\d{2}-\d{2})(?:-(\d+))?$", name)
    if m is None:
        return ("", -1)
    return (m.group(1), int(m.group(2) or 0))


def do_locate(workspace, rep):
    pev_dir = workspace / ".pev"
    best = None  # (轮次目录名, pm 目录)
    if pev_dir.is_dir():
        for state_path in pev_dir.glob("prd-*/pm/state.json"):
            round_name = state_path.parent.parent.name
            if best is None or round_sort_key(round_name) > round_sort_key(best[0]):
                best = (round_name, state_path.parent)
    if best is None:
        rep.warn("没有任何轮次含 pm/state.json,无可恢复的 PM 状态;按 INIT 开始")
        rep.next.append({"kind": "draft", "target": "objective",
                         "notes": "起草 objective 后运行 init.py --objective"})
        return rep.emit()
    rep.pm_root = str(best[1])
    load_state(best[1], rep)
    return rep.emit()


def main():
    argv = sys.argv[1:]
    do_bind_locate = "--locate" in argv
    command = "init --locate" if do_bind_locate else "init"
    rep = Reporter(command)
    rest = [a for a in argv if a != "--locate"]

    workspace = None
    objective_path = None
    i = 0
    while i < len(rest):
        if rest[i] == "--workspace" and i + 1 < len(rest):
            workspace = Path(rest[i + 1]).expanduser().resolve()
            i += 2
        elif rest[i] == "--objective" and i + 1 < len(rest):
            objective_path = Path(rest[i + 1]).expanduser().resolve()
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
        if state is not None and rep.status == "INIT":
            rep.next.append(transition_next(same / "pm", "start-planning"))
        elif state is not None and rep.status == "WAITING_FOR_INPUT":
            rep.next.append({
                "kind": "ask-user",
                "items": ["按 WAITING 恢复协议向用户确认缺失项"],
            })
        # 其余活动状态:只读汇报,续接以最近一次产物与 validate 结果为准
        return rep.emit()
    round_dir, _ = next_free_round(pev_dir, base)
    pm_dir = round_dir / "pm"
    pm_dir.mkdir(parents=True, exist_ok=True)
    (pm_dir / "iterations").mkdir(exist_ok=True)
    rep.pm_root = str(pm_dir)

    state = {
        "objective": objective,
        "status": "WAITING_FOR_INPUT" if goal_missing else "INIT",
        "iteration": 0,
        "max_iterations": 5,
    }
    if goal_missing:
        state["resume_to"] = "PLANNING"
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
        rep.next.append(transition_next(pm_dir, "start-planning"))
    return rep.emit()


if __name__ == "__main__":
    sys.exit(run("init", main))
