"""rc 流程脚本共享的协议与工具(仅标准库;改编自 product-manager/scripts/_common.py)。

"模型—脚本交接协议"(change harden-rc-pev-closeout design.md):stdout 永远是
单行紧凑 JSON,字段 ok/command/rc_root/skill_root/status/iteration/written/
deleted/errors/warnings/next;退出码 0=成功、1=失败;全部预期错误与运行时
异常都转换为同一 JSON 结构。

命令面原则(design.md"状态操作与脚本职责"):命令只设在模型必须拿主意的地方;
下一步已确定的步骤并入同一命令自动做完;岔路由产物文件字段表达。
"""

import json
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent

# design.md"来源绑定":state 投影纳入路径(必要语义输入;生命周期字段一律排除:
# status/iteration/max_iterations/plans/artifacts/resume_to/prd_gaps/transitions)
PROJECTION_INCLUDE = ("objective", "prd_source", "evidence")

# rc 文件编号惯例:<N> = 写入时 state.iteration + 1(SKILL.md"运行目录"节)
def file_no(iteration):
    return int(iteration) + 1


REASON_MAX = 500


def trunc(reason):
    reason = str(reason)
    if len(reason) > REASON_MAX:
        return reason[:REASON_MAX] + "…(截断)"
    return reason


def canonical_sha256(obj):
    """规范化序列化的 SHA-256:键排序、UTF-8、紧凑分隔符。"""
    import hashlib
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def state_projection(state):
    """按 design 的纳入路径取 state 投影。"""
    return {k: state[k] for k in PROJECTION_INCLUDE if k in state}


class Reporter:
    """收集本次执行的 written/deleted/errors/warnings 并按协议输出。"""

    def __init__(self, command):
        self.command = command
        self.rc_root = None
        self.status = None
        self.iteration = None
        self.written = []
        self.deleted = []
        self.errors = []
        self.warnings = []
        self.next = []

    def error(self, file, json_path, reason, code=None):
        entry = {"file": file, "json_path": json_path, "reason": trunc(reason)}
        if code:
            entry["code"] = code
        self.errors.append(entry)

    def command_error(self, command_name, reason, code=None):
        """命令级错误:file 固定为命令名,json_path 为 null。"""
        self.error(command_name, None, reason, code=code)

    def warn(self, text):
        self.warnings.append(trunc(text))

    def emit(self):
        payload = {
            "ok": not self.errors,
            "command": self.command,
            "rc_root": self.rc_root,
            "skill_root": str(SKILL_ROOT),
            "status": self.status,
            "iteration": self.iteration,
            "written": self.written,
            "deleted": self.deleted,
            "errors": self.errors,
            "warnings": self.warnings,
            "next": self.next,
        }
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        return 0 if payload["ok"] else 1


def run(command, main_impl):
    """入口包装:未捕获异常转换为统一 JSON,不向 stdout 输出裸 traceback。"""
    try:
        return main_impl()
    except Exception as e:  # noqa: BLE001 — 协议要求兜底
        reporter = Reporter(command)
        reporter.command_error(command, f"internal error: {type(e).__name__}")
        print(f"debug: {e}", file=sys.stderr)
        return reporter.emit()


def parse_rc_root(argv, command, reporter):
    """解析 --rc-root <路径>;失败时记命令级错误并返回 None。"""
    args = list(argv)
    rc_root = None
    while args:
        if args[0] == "--rc-root":
            if len(args) < 2:
                reporter.command_error(command, "--rc-root 缺少路径参数")
                return None
            rc_root = args[1]
            args = args[2:]
        else:
            reporter.command_error(command, f"无法识别的参数: {args[0]}")
            return None
    if rc_root is None:
        reporter.command_error(command, "缺少 --rc-root <rc 目录绝对路径>")
        return None
    path = Path(rc_root).expanduser().resolve()
    reporter.rc_root = str(path)
    return path


def load_state(rc_root, reporter):
    """读取 state.json;失败记错误并返回 None,status/iteration 保持 null。"""
    path = rc_root / "state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        reporter.error("state.json", "$", f"无法读取/解析 state.json: {e}")
        return None
    if not isinstance(state, dict):
        reporter.error("state.json", "$", "state.json 顶层必须是对象")
        return None
    reporter.status = state.get("status")
    iteration = state.get("iteration")
    reporter.iteration = iteration if isinstance(iteration, int) else None
    return state


def read_json(path):
    """读取 JSON 文件;失败返回 None,由调用方决定如何报错。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json_atomic(path, obj):
    """临时文件+改名原子写;统一 UTF-8、缩进 2、末尾换行。"""
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def select_plan(rc_root, state, iteration):
    """编号不超过 iteration+1 的最新已登记 Plan(REVISE 复用旧 Plan)。

    rc 编号惯例:<N> = iteration+1,故登记名 01-plan.json 对应 iteration 0。
    返回 (编号, 路径) 或 None。
    """
    registry = state.get("plans")
    best = None
    limit = file_no(iteration)
    for name in registry if isinstance(registry, list) else []:
        if not isinstance(name, str) or not name.endswith("-plan.json"):
            continue
        stem = name[: -len("-plan.json")]
        if not stem.isdigit():
            continue
        n = int(stem)
        if n <= limit and (rc_root / "iterations" / name).is_file():
            if best is None or n > best[0]:
                best = (n, rc_root / "iterations" / name)
    return best


def append_transition(state, event, src, dst, iteration, new_iteration, ref, param):
    """事件账本条目(审计记录,不单独证明交付正确;design.md"最小数据契约")。"""
    import time
    entry = {"event": event, "from": src, "to": dst,
             "from_iteration": iteration, "to_iteration": new_iteration,
             "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "ref_sha256": ref, "param": param}
    state.setdefault("transitions", []).append(entry)


def post_validate(rc_root, rep):
    """写后校验:失败不回滚已落盘产物,恢复动作是重跑同一 commit 命令。"""
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / "validate.py"),
         "--rc-root", str(rc_root)],
        capture_output=True, text=True)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        rep.error("validate.py", None, f"写后校验输出异常: {proc.stdout[:200]}")
        return
    for e in payload.get("errors", []):
        rep.error(e.get("file"), e.get("json_path"), e.get("reason"))
    for w in payload.get("warnings", []):
        rep.warn(w)
    if not payload.get("ok"):
        rep.warn("写后校验失败;若为登记册不一致,恢复动作是重跑同一 commit 命令")
