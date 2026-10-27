#!/usr/bin/env python3
"""初始化与恢复定位:创建轮次 rc/ 目录与 state.json,或只读汇报各轮现状。

用法:
    python3 init.py --workspace <含 .pev/ 的目录> --prd-source <PRD 路径> \
        --objective <草稿绝对路径> [--round <轮次名>] [--restart]
    python3 init.py --locate --workspace <含 .pev/ 的目录>

轮次解析:--round 显式点名优先;否则 prd_source 位于 .pev/<轮次>/ 下时跟随该
轮次;外部 PRD 新开 prd-<今日>[-2,-3]。同日同目标活跃轮 → 幂等续用不重建
(design.md:init 目录已存在时返回现状,不静默覆盖)。COMPLETE 轮不可重复
INIT:修订走 reopen,重来走 --restart(归档 rc.bak-<日期> 后在本轮重建)。

--locate 只读汇报:各轮 status/iteration + 悬挂轮提示,不阻塞任何目标。
"""

import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Reporter, read_json, run, write_json_atomic,
)

ACTIVE_STATUSES = {"INIT", "PLANNING", "EXECUTING", "VERIFYING",
                   "WAITING_FOR_INPUT", "WAITING_FOR_PRD"}
ROUND_NAME_RE = re.compile(r"prd-(\d{4}-\d{2}-\d{2})(?:-(\d+))?$")


def round_sort_key(name):
    """prd-YYYY-MM-DD[-N] 排序键:日期优先,序号按数值;不匹配排最后。"""
    m = ROUND_NAME_RE.match(name)
    if m is None:
        return ("", -1)
    return (m.group(1), int(m.group(2) or 0))


def resolve_round(pev_dir, prd_source, explicit):
    """返回 (轮次目录, 是否新建)。"""
    if explicit:
        return pev_dir / explicit, not (pev_dir / explicit / "rc").is_dir()
    try:
        rel = prd_source.resolve().relative_to(pev_dir.resolve())
    except ValueError:
        rel = None
    if rel is not None and len(rel.parts) >= 1 and rel.parts[0] != ".pev":
        candidate = pev_dir / rel.parts[0]
        if candidate.is_dir():
            return candidate, not candidate.joinpath("rc").is_dir()
    base = f"prd-{time.strftime('%Y-%m-%d')}"
    candidate = pev_dir / base
    seq = 1
    while candidate.joinpath("rc", "state.json").is_file():
        seq += 1
        candidate = pev_dir / f"{base}-{seq}"
    return candidate, True


def active_same_goal(rc_dir, goal):
    state = read_json(rc_dir / "state.json")
    return (isinstance(state, dict)
            and state.get("status") in ACTIVE_STATUSES
            and str((state.get("objective") or {}).get("goal", "")).strip() == goal)


def do_locate(workspace, rep):
    """只读汇报全部含 rc/state.json 的轮次;自动指向排序最新的一个。"""
    pev_dir = workspace / ".pev"
    rounds = []
    if pev_dir.is_dir():
        for d in sorted(pev_dir.iterdir()):
            state_path = d / "rc" / "state.json"
            if d.is_dir() and state_path.is_file():
                rounds.append((d.name, round_sort_key(d.name),
                               read_json(state_path)))
    if not rounds:
        rep.warn("没有任何轮次含 rc/state.json,无可恢复的澄清状态;按 INIT 开始")
        return rep.emit()
    for name, _, state in sorted(rounds, key=lambda r: r[1]):
        if isinstance(state, dict):
            rep.warn(f"轮次清单:{name} status={state.get('status')} "
                     f"iteration={state.get('iteration')}")
        else:
            rep.warn(f"轮次清单:{name} state.json 不可解析")
    best = max(rounds, key=lambda r: r[1])
    rc_dir = pev_dir / best[0] / "rc"
    rep.rc_root = str(rc_dir)
    state = load_round_state(rc_dir, rep)
    for name, _, state in rounds:
        if name != best[0] and isinstance(state, dict) \
                and state.get("status") not in ("COMPLETE",):
            rep.warn(f"悬挂轮:{name} 非终态且非最新轮,只读发现,不自动处置")
    return rep.emit()


def load_round_state(rc_dir, rep):
    state = read_json(rc_dir / "state.json")
    if isinstance(state, dict):
        rep.status = state.get("status")
        it = state.get("iteration")
        rep.iteration = it if isinstance(it, int) else None
    return state


def main():
    argv = sys.argv[1:]
    do_locate_mode = "--locate" in argv
    do_restart = "--restart" in argv
    command = "init --locate" if do_locate_mode else "init"
    rep = Reporter(command)
    rest = [a for a in argv if a not in ("--locate", "--restart")]

    workspace = None
    prd_source = None
    objective_path = None
    explicit_round = None
    deliver_to = None
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--workspace" and i + 1 < len(rest):
            workspace = Path(rest[i + 1]).expanduser().resolve()
            i += 2
        elif a == "--prd-source" and i + 1 < len(rest):
            prd_source = Path(rest[i + 1]).expanduser().resolve()
            i += 2
        elif a == "--objective" and i + 1 < len(rest):
            objective_path = Path(rest[i + 1]).expanduser().resolve()
            i += 2
        elif a == "--round" and i + 1 < len(rest):
            explicit_round = rest[i + 1]
            i += 2
        elif a == "--deliver-to" and i + 1 < len(rest):
            deliver_to = rest[i + 1]
            i += 2
        else:
            rep.command_error(command, f"无法识别的参数: {a}")
            return rep.emit()
    if workspace is None:
        rep.command_error(command, "缺少 --workspace <含 .pev/ 的目录>")
        return rep.emit()
    if not workspace.is_dir():
        rep.command_error(command, f"workspace 目录不存在: {workspace}")
        return rep.emit()

    if do_locate_mode:
        return do_locate(workspace, rep)

    # 交付登记(T1-6):spec.md 额外交付到变更目录;存相对 workspace 的
    # POSIX 路径。目录须已存在(变更由 openspec new change 先行创建)。
    deliver_rel = None
    if deliver_to is not None:
        p = Path(deliver_to).expanduser()
        if p.is_absolute():
            try:
                p = p.resolve().relative_to(workspace)
            except ValueError:
                rep.command_error(command,
                                  f"--deliver-to 须在 workspace 内: {deliver_to}")
                return rep.emit()
        deliver_rel = p.as_posix()
        if not (workspace / deliver_rel).is_dir():
            rep.command_error(command,
                              f"--deliver-to 目录不存在(先创建变更): {deliver_rel}")
            return rep.emit()

    if prd_source is None:
        rep.command_error(command, "缺少 --prd-source <PRD 路径>")
        return rep.emit()
    if not prd_source.is_file():
        rep.command_error(command, f"prd_source 文件不存在: {prd_source}")
        return rep.emit()
    if objective_path is None:
        rep.command_error(command, "缺少 --objective <草稿绝对路径>")
        return rep.emit()
    objective = read_json(objective_path)
    if not isinstance(objective, dict):
        rep.command_error(command,
                          f"objective 草稿无法解析为对象: {objective_path}")
        return rep.emit()
    goal = str(objective.get("goal") or "").strip()

    pev_dir = workspace / ".pev"
    round_dir, _ = resolve_round(pev_dir, prd_source, explicit_round)
    rc_dir = round_dir / "rc"

    if rc_dir.joinpath("state.json").is_file() and not do_restart:
        existing = read_json(rc_dir / "state.json")
        if isinstance(existing, dict) \
                and existing.get("status") in ACTIVE_STATUSES:
            if goal and active_same_goal(rc_dir, goal):
                rep.rc_root = str(rc_dir)
                load_round_state(rc_dir, rep)
                rep.warn("同目标活跃轮已存在,不重建;按当前状态继续")
                return rep.emit()
            rep.command_error(
                command,
                f"{rc_dir} 已有活跃澄清轮(status={existing.get('status')!r});"
                "续用请勿重复 INIT,重开用 --restart,修订收口轮用 reopen",
                code="E_ROUND_ACTIVE")
            return rep.emit()
        if isinstance(existing, dict) and existing.get("status") == "COMPLETE":
            rep.command_error(
                command,
                f"{rc_dir} 已收口(COMPLETE);修订走 reopen --note,重来走 --restart",
                code="E_ROUND_COMPLETE")
            return rep.emit()

    if do_restart and rc_dir.is_dir():
        stamp = time.strftime("%Y-%m-%d")
        archive = round_dir / f"rc.bak-{stamp}"
        seq = 1
        while archive.exists():
            seq += 1
            archive = round_dir / f"rc.bak-{stamp}-{seq}"
        shutil.move(str(rc_dir), str(archive))
        rep.warnings.append(f"已归档旧 rc/ 至 {archive.name}")

    rc_dir.mkdir(parents=True, exist_ok=True)
    (rc_dir / "iterations").mkdir(exist_ok=True)
    rep.rc_root = str(rc_dir)

    goal_missing = not goal
    state = {
        "objective": objective,
        "prd_source": str(prd_source),
        "status": "WAITING_FOR_INPUT" if goal_missing else "INIT",
        "iteration": 0,
        "max_iterations": 5,
    }
    if deliver_rel is not None:
        state["deliver_to"] = deliver_rel
    if goal_missing:
        state["resume_to"] = "PLANNING"
    write_json_atomic(rc_dir / "state.json", state)
    rep.written.append("state.json")
    rep.status = state["status"]
    rep.iteration = 0

    if goal_missing:
        rep.next.append({
            "kind": "ask-user",
            "items": ["objective.goal 缺失:澄清目标是什么 / 为什么重要 / 一次问齐"],
        })
    else:
        rep.next.append({
            "kind": "draft", "target": "plan",
            "notes": "以 agents/planner.md 起草 Plan,经 commit.py plan 提交",
        })
    return rep.emit()


if __name__ == "__main__":
    sys.exit(run("init", main))
