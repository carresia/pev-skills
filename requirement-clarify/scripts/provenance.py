"""来源快照与绑定复算库(改编自 product-manager/scripts/record_provenance.py)。

快照:iterations/<N>-verification-input.json,由 commit.py artifact(completed)
自动生成,冻结被验证输入;绑定:commit.py verification(PASS)提交时按盘上
文件复算三摘要,与快照一致才把 provenance 写进报告。
本模块是库,由 commit.py 内部调用,不是模型命令。
"""

from _common import canonical_sha256, read_json, select_plan, state_projection

PROVENANCE_FIELDS = ("algorithm", "plan_path", "artifact_sha256",
                     "plan_sha256", "state_projection_sha256")


class ProvenanceError(Exception):
    def __init__(self, reason, file, json_path=None):
        super().__init__(reason)
        self.file = file
        self.json_path = json_path


def snapshot_for(state, plan_doc, plan_name, artifact_doc, iteration):
    """按 design"来源绑定"计算快照;生命周期字段不进入摘要。"""
    from _common import file_no
    return {
        "algorithm": "rc-sha256-v1",
        "iteration": file_no(iteration),
        "plan_path": plan_name,
        "artifact_sha256": canonical_sha256(artifact_doc),
        "plan_sha256": canonical_sha256(plan_doc),
        "state_projection_sha256": canonical_sha256(state_projection(state)),
    }


def load_inputs(rc_root, state, iteration):
    """定位并读取当前轮的有效 Plan 与 Artifact;缺任一即 ProvenanceError。"""
    sel = select_plan(rc_root, state, iteration)
    if sel is None:
        raise ProvenanceError(
            f"找不到编号不超过 {iteration + 1} 的已登记 Plan 文件",
            "state.json", "$.plans")
    plan_path = sel[1]
    plan_name = plan_path.relative_to(rc_root).as_posix()
    plan_doc = read_json(plan_path)
    if plan_doc is None:
        raise ProvenanceError("无法读取/解析有效 Plan", plan_name, "$")

    art_name = f"{iteration + 1:02d}-artifact.json"
    registry = state.get("artifacts")
    if not isinstance(registry, list) or art_name not in registry:
        raise ProvenanceError(f"当前轮 {art_name} 未登记,无法记录来源",
                              "state.json", "$.artifacts")
    artifact_doc = read_json(rc_root / "iterations" / art_name)
    if artifact_doc is None:
        raise ProvenanceError("无法读取/解析当轮 Artifact",
                              f"iterations/{art_name}", "$")
    return plan_name, plan_doc, art_name, artifact_doc


def write_snapshot(rc_root, state, iteration):
    """计算并原子写快照(幂等:内容不变则不重写);返回快照对象。"""
    plan_name, plan_doc, _, artifact_doc = load_inputs(rc_root, state, iteration)
    snap = snapshot_for(state, plan_doc, plan_name, artifact_doc, iteration)
    snap_name = f"{iteration + 1:02d}-verification-input.json"
    snap_path = rc_root / "iterations" / snap_name
    existing = read_json(snap_path) if snap_path.is_file() else None
    if existing != snap:
        from _common import write_json_atomic
        write_json_atomic(snap_path, snap)
        return snap, f"iterations/{snap_name}"
    return snap, None


def bind_report(rc_root, state, iteration, rep):
    """复算三摘要并核对报告复述;一致才把 provenance 原子写进报告文件。

    失败抛 ProvenanceError;成功返回 (报告文档, 写入相对路径或 None)。
    """
    plan_name, plan_doc, art_name, artifact_doc = load_inputs(rc_root, state,
                                                              iteration)
    ver_name = f"iterations/{iteration + 1:02d}-verification.json"
    ver_path = rc_root / "iterations" / f"{iteration + 1:02d}-verification.json"
    ver = read_json(ver_path)
    if ver is None:
        raise ProvenanceError("当轮报告未落盘,无法绑定", ver_name, "$")

    snap_name = f"{iteration + 1:02d}-verification-input.json"
    snapshot = read_json(rc_root / "iterations" / snap_name)
    if snapshot is None:
        raise ProvenanceError("快照不存在,先经 commit artifact 生成快照",
                              f"iterations/{snap_name}", "$")
    if ver.get("verification_input") != snapshot:
        raise ProvenanceError("报告未复述快照标识或与快照不一致,不可绑定;"
                              "须重新验证", ver_name, "$.verification_input")

    current = snapshot_for(state, plan_doc, plan_name, artifact_doc, iteration)
    for key, conflict_file in (
            ("artifact_sha256", f"iterations/{art_name}"),
            ("plan_sha256", plan_name),
            ("state_projection_sha256", "state.json")):
        if current[key] != snapshot[key]:
            raise ProvenanceError(
                "输入在派发后变更,绑定复算不一致,该报告作废;"
                "恢复:重跑 commit artifact 原位重写快照并重新验证",
                conflict_file, "$")

    provenance = {k: snapshot[k] for k in PROVENANCE_FIELDS}
    written = None
    if ver.get("provenance") != provenance:
        ver["provenance"] = provenance
        from _common import write_json_atomic
        write_json_atomic(ver_path, ver)
        written = ver_name
    return ver, written
