#!/usr/bin/env python3
"""来源记录:派发 Verifier 前写被验证输入快照(输入冻结命令)。

用法:
    python3 record_provenance.py --pm-root <pm 目录绝对路径>

快照:iterations/<N>-verification-input.json(原子写,幂等重跑);派发后、
绑定前输入变更 → 原位重写快照重新派发;当轮已有绑定 PASS 时快照只读。
绑定(--bind)已随收口折叠并入 commit.py 的 verification 子命令
(任务 2.10):报告提交即复算三摘要并写 provenance,不经模型转述。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Reporter, SKILL_ROOT, canonical_sha256, load_state, parse_pm_root,
    read_json, run, select_plan, state_projection, write_json_atomic,
)

PROVENANCE_FIELDS = ("algorithm", "plan_path", "artifact_sha256",
                     "plan_sha256", "state_projection_sha256")


def snapshot_for(state, plan_doc, plan_name, artifact_doc, iteration):
    return {
        "algorithm": "sha256-v1",
        "iteration": iteration,
        "plan_path": plan_name,
        "artifact_sha256": canonical_sha256(artifact_doc),
        "plan_sha256": canonical_sha256(plan_doc),
        "state_projection_sha256": canonical_sha256(state_projection(state)),
    }


def main():
    argv = sys.argv[1:]
    command = "record_provenance"
    rep = Reporter(command)

    pm = parse_pm_root(argv, command, rep)
    if pm is None or rep.errors:
        return rep.emit()
    state = load_state(pm, rep)
    if state is None:
        return rep.emit()
    iteration = rep.iteration
    if not isinstance(iteration, int) or iteration < 1:
        rep.error("state.json", "$.iteration",
                  f"iteration 须为正整数才能定位本轮产物,实际为 {iteration!r}")
        return rep.emit()

    sel = select_plan(pm, state, iteration)
    if sel is None:
        rep.error("state.json", "$.plans",
                  f"找不到编号不超过 {iteration} 的已登记 Plan 文件")
        return rep.emit()
    plan_path = sel[1]
    plan_name = plan_path.relative_to(pm).as_posix()
    plan_doc = read_json(plan_path)
    if plan_doc is None:
        rep.error(plan_name, "$", "无法读取/解析有效 Plan")
        return rep.emit()

    art_name = f"{iteration:02d}-artifact.json"
    registry = state.get("artifacts")
    if not isinstance(registry, list) or art_name not in registry:
        rep.error("state.json", "$.artifacts",
                  f"当前轮 {art_name} 未登记,无法记录来源")
        return rep.emit()
    artifact_doc = read_json(pm / "iterations" / art_name)
    if artifact_doc is None:
        rep.error(f"iterations/{art_name}", "$", "无法读取/解析当轮 Artifact")
        return rep.emit()

    snap = snapshot_for(state, plan_doc, plan_name, artifact_doc, iteration)
    snap_name = f"{iteration:02d}-verification-input.json"
    snap_path = pm / "iterations" / snap_name
    ver_name = f"{iteration:02d}-verification.json"
    ver_path = pm / "iterations" / ver_name

    existing = read_json(snap_path) if snap_path.is_file() else None
    if existing != snap:
        if ver_path.is_file():
            ver = read_json(ver_path)
            if isinstance(ver, dict) and "provenance" in ver:
                rep.error(snap_name, "$",
                          "当前轮已有绑定 PASS,快照与同编号产物只读;修订须新建轮次")
                return rep.emit()
        write_json_atomic(snap_path, snap)
        rep.written.append(f"iterations/{snap_name}")
    rep.next.append({
        "kind": "dispatch-verifier",
        "snapshot": f"iterations/{snap_name}",
        "artifact": f"iterations/{art_name}",
        "plan": plan_name,
    })
    return rep.emit()


if __name__ == "__main__":
    sys.exit(run("record_provenance", main))
