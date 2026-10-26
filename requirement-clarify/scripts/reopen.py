#!/usr/bin/env python3
"""重开:已收口轮的修订入口。iteration+1,旧 PASS 失去当前交付资格。

用法:
    python3 reopen.py --rc-root <rc 目录绝对路径> --note <修订要点(必填)>

适用来源:COMPLETE(用户要求修订),或 VERIFYING(当前轮已绑定 PASS 但内容
需要变更)。其他活跃状态不存在需要作废的 PASS,继续正常流程即可,不走 reopen。
历史报告不删除;同 --note 重跑幂等(不重复递增)。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    Reporter, append_transition, canonical_sha256, load_state, parse_rc_root,
    post_validate, read_json, run, write_json_atomic,
)
from commit import bound_pass_exists, iteration_limit_guard  # noqa: E402


def main():
    argv = sys.argv[1:]
    rep = Reporter("reopen")
    note = None
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--rc-root" and i + 1 < len(argv):
            rest += argv[i:i + 2]
            i += 2
        elif argv[i] == "--note" and i + 1 < len(argv):
            note = argv[i + 1]
            i += 2
        else:
            rep.command_error("reopen", f"无法识别的参数: {argv[i]}")
            return rep.emit()
    rc_root = parse_rc_root(rest, "reopen", rep)
    if rc_root is None or rep.errors:
        return rep.emit()
    if not (isinstance(note, str) and note.strip()):
        rep.command_error("reopen", "reopen 须以 --note 记录修订要点(用户原话或来源摘录)",
                          code="E_NOTE_REQUIRED")
        return rep.emit()
    note = note.strip()
    state = load_state(rc_root, rep)
    if state is None:
        return rep.emit()
    status = rep.status
    iteration = rep.iteration

    # 同 note 重跑幂等:上一次 reopen 已生效则不重复递增(先于来源守卫)
    last = (state.get("transitions") or [None])[-1]
    if (isinstance(last, dict) and last.get("event") == "reopen"
            and last.get("param") == note
            and last.get("to_iteration") == iteration
            and last.get("to") == status):
        rep.warn("重跑判已执行,未重复递增 iteration")
        rep.next.append({"kind": "draft", "target": "artifact",
                         "notes": "继续追加/修订 Artifact,经 commit.py artifact 提交"})
        return rep.emit()

    if status not in ("COMPLETE", "VERIFYING"):
        rep.error("state.json", "$.status",
                  f"reopen 适用于 COMPLETE/VERIFYING(存在需作废的 PASS),"
                  f"当前为 {status!r};活跃轮继续正常流程即可")
        return rep.emit()
    if status == "VERIFYING" and not bound_pass_exists(rc_root, iteration):
        rep.error("state.json", "$.status",
                  "VERIFYING 但当前轮无绑定 PASS,无需 reopen;继续正常流程")
        return rep.emit()

    if iteration_limit_guard(state, rep, iteration + 1, "reopen"):
        return rep.emit()
    ref = None
    ver = read_json(rc_root / "iterations"
                    / f"{iteration + 1:02d}-verification.json")
    if ver is not None:
        ref = canonical_sha256(ver)
    append_transition(state, "reopen", status, "EXECUTING", iteration,
                      iteration + 1, ref, note)
    state["status"] = "EXECUTING"
    state["iteration"] = iteration + 1
    state.pop("resume_to", None)
    write_json_atomic(rc_root / "state.json", state)
    rep.written.append("state.json")
    rep.status = "EXECUTING"
    rep.iteration = iteration + 1
    post_validate(rc_root, rep)
    rep.next.append({"kind": "draft", "target": "artifact",
                     "notes": "在原目录追加证据或修订 Artifact,重新提交验证;"
                              "旧 PASS 已失效"})
    return rep.emit()


if __name__ == "__main__":
    sys.exit(run("reopen", main))
