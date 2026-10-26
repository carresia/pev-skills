#!/usr/bin/env python3
"""来源记录:派发 Verifier 前写被验证输入快照;--bind 复算一致才写 provenance。

用法:
    python3 record_provenance.py --pm-root <pm 目录绝对路径>          # 计算三摘要,写快照
    python3 record_provenance.py --pm-root <pm 目录绝对路径> --bind   # 复算一致才绑定 provenance

快照:iterations/<N>-verification-input.json(原子写,幂等重跑)。
绑定要求:报告已复述快照标识(verification_input 与快照逐字段一致),
且按当前文件复算三摘要与快照一致;任一不符则该 verdict 不可用于交付。
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
    do_bind = "--bind" in argv
    command = "record_provenance --bind" if do_bind else "record_provenance"
    rep = Reporter(command)

    pm = parse_pm_root([a for a in argv if a != "--bind"], command, rep)
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

    if not do_bind:
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

    # --bind
    if not snap_path.is_file():
        rep.error(snap_name, "$",
                  "快照不存在,先运行 record_provenance.py 生成快照再派发")
        return rep.emit()
    snapshot = read_json(snap_path)
    if snapshot is None:
        rep.error(snap_name, "$", "无法读取/解析快照文件")
        return rep.emit()
    if not ver_path.is_file():
        rep.error(ver_name, "$", "当轮报告未提交,无法绑定")
        return rep.emit()
    ver = read_json(ver_path)
    if ver is None:
        rep.error(ver_name, "$", "无法读取/解析当轮报告")
        return rep.emit()

    if ver.get("verification_input") != snapshot:
        rep.error(ver_name, "$.verification_input",
                  "报告未复述快照标识或与快照不一致,不可绑定;须重新验证")
        return rep.emit()

    current = snapshot_for(state, plan_doc, plan_name, artifact_doc, iteration)
    for key, conflict_file in (
            ("artifact_sha256", f"iterations/{art_name}"),
            ("plan_sha256", plan_name),
            ("state_projection_sha256", "state.json")):
        if current[key] != snapshot[key]:
            rep.error(conflict_file, "$",
                      "输入在派发后变更,provenance 复算不一致,该报告作废;"
                      "恢复:重跑 record_provenance.py 原位重写快照并重新派发 Verifier"
                      "（当前轮已有绑定 PASS 时须新建轮次）")
            return rep.emit()

    provenance = {k: snapshot[k] for k in PROVENANCE_FIELDS}
    if ver.get("provenance") != provenance:
        ver["provenance"] = provenance
        write_json_atomic(ver_path, ver)
        rep.written.append(f"iterations/{ver_name}")
    rep.next.append({
        "kind": "command",
        "cwd": str(SKILL_ROOT),
        "argv": ["scripts/transition.py", "--pm-root", str(pm), "verdict"],
    })
    return rep.emit()


if __name__ == "__main__":
    sys.exit(run("record_provenance", main))
