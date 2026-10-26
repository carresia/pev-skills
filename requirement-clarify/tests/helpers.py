"""测试共享工具:构造最小合法 rc 工作目录、运行 skill 脚本。

仅依赖标准库。所有夹具都是合成数据,与任何真实 rc 工作目录无关。
用法(在 skill 根目录): python3 -m unittest discover -s tests -t . -v

rc 与 PM 的关键差异(夹具据此构造,勿混用):
- 文件编号 <N> = 写入时 state.iteration + 1(初始 iteration=0,首轮 01);
- rc Evidence Ledger 条目无 id 字段(claim/type/evidence/confidence);
- 命令参数为 --workspace(init)或 --rc-root(其余),输出同 PM 单行 JSON 协议。
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent

# design.md"来源绑定":state 投影的显式纳入路径(生命周期字段一律排除)
PROJECTION_INCLUDE = ("objective", "prd_source", "evidence")

PROTO_KEYS = {"ok", "command", "rc_root", "skill_root", "status", "iteration",
              "written", "deleted", "errors", "warnings", "next"}


def canonical_sha256(obj):
    """规范化序列化的 SHA-256:键排序、UTF-8、紧凑分隔符(与 scripts/_common.py 同一规则)。"""
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def state_projection(state):
    """按 design 的纳入路径取 state 投影(生命周期字段不参与摘要)。"""
    return {k: state[k] for k in PROJECTION_INCLUDE if k in state}


def run_script(script_name, *args):
    """运行 scripts/ 下的脚本,返回 CompletedProcess(stdout/stderr 为文本)。"""
    return subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / script_name), *args],
        capture_output=True, text=True,
    )


def out_json(proc):
    """把脚本 stdout 解析为 JSON(模型—脚本交接协议:stdout 永远是单行紧凑 JSON)。"""
    return json.loads(proc.stdout)


def assert_protocol(payload):
    """协议形状断言:全部必需键在场且容器字段类型正确。"""
    missing = PROTO_KEYS - set(payload)
    assert not missing, f"协议缺字段: {sorted(missing)}"
    for key in ("written", "deleted", "errors", "warnings", "next"):
        assert isinstance(payload[key], list), f"{key} 须为数组"


def min_state(**over):
    """最小合法 rc state;默认 INIT、iteration=0(首轮文件为 01)。"""
    state = {
        "objective": {"goal": "把登录验证码改造成滑块,降低登录失败率"},
        "prd_source": "docs/prd.md",
        "status": "INIT",
        "iteration": 0,
        "max_iterations": 5,
    }
    state.update(over)
    return state


def min_ledger(i=1, type_="FACT", claim=None, evidence="PRD §2", confidence="high"):
    """一条合法 rc Ledger 条目;FACT/DECISION 必须带非空 evidence(R1)。"""
    return {"claim": claim or f"合成论断{i}", "type": type_,
            "evidence": evidence, "confidence": confidence}


def min_plan(**over):
    """最小合法 Plan;action 顺序满足 R5(价值先行)。"""
    plan = {
        "goal": "把登录验证码改造成滑块,降低登录失败率",
        "understanding": "验证码失败率高,疑与图形码可读性相关。",
        "known": ["登录失败率 8%"], "unknown": ["失败根因分布"], "assumptions": [],
        "plan": [
            {"id": "P1", "objective": "质疑需求价值并确认成功标准",
             "action": "interrogate_value", "inputs": ["PRD §2"],
             "expected_output": "价值问题答案", "success_criteria": "目标可量化"},
            {"id": "P2", "objective": "逐章扫清落地模糊地带",
             "action": "interrogate_ambiguity", "inputs": ["PRD §4-§6"],
             "expected_output": "模糊点答案", "success_criteria": "无未决问题"},
            {"id": "P3", "objective": "聚合 Spec 正文",
             "action": "draft", "inputs": ["全部答案"],
             "expected_output": "Spec 结构化正文", "success_criteria": "模板必填齐备"},
        ],
        "final_deliverable": "templates/spec.md",
        "stop_conditions": ["证据不足以支撑结论时停止"],
    }
    plan.update(over)
    return plan


def min_spec_body(**over):
    """最小合法 Spec 正文(templates/spec.md 的全部必填占位)。"""
    body = {
        "title": "滑块验证码改造工程 Spec",
        "background_summary": "登录失败集中在验证码环节",
        "objective_summary": "降低验证码导致的登录失败率",
        "scope_summary": "登录页验证码组件及风控联动",
        "eng_scope_addenda": "新增滑块组件前端埋点",
        "prd_ref_user_stories": "PRD §5 用户故事 1-3",
        "behavior_detail": "滑块失败 3 次后降级短信验证(来源: 澄清决定)",
        "rules": [{"rule": "滑块失败 3 次锁定 10 分钟", "source": "PRD §4"}],
        "permissions": [{"rule": "风控服务可读设备指纹", "source": "PRD §5"}],
        "exceptions": [{"case": "滑块组件加载失败", "handling": "降级短信验证",
                        "source": "澄清决定"}],
        "nfrs": [{"requirement": "滑块加载 P95 < 500ms", "source": "PRD §6"}],
        "data_metrics": [{"name": "滑块通过率", "definition": "通过次数/展示次数",
                          "status": "需新增埋点", "code_evidence": "无滑块埋点",
                          "work_item": "前端补滑块通过/失败埋点"}],
        "acceptance": [{"criteria": "验证码失败率下降至 2% 以下"}],
        "tracking_acceptance": "§8 表中「需新增」各项全部落地并可在报表查到",
        "always": "验证失败后保留用户输入",
        "ask_first": "需要接入外部风控时",
        "never": "不存储明文短信验证码",
        "open_questions": [],
    }
    body.update(over)
    return body


def min_artifact(status="completed", **over):
    """最小合法 Artifact;completed 正文满足 spec 模板必填集。"""
    art = {"status": status, "evidence": [], "artifact": min_spec_body()}
    if status in ("replan_required", "blocked"):
        art["replan_reason"] = {"problem": "关键输入缺失", "why_invalid": "无法继续",
                                "new_information": "用户补充", "recommended": "等待补数"}
    art.update(over)
    return art


def snapshot_for(state, plan_doc, plan_name, artifact_doc, file_no):
    """按 design 规则计算验证输入快照(测试侧实现,与 scripts/provenance.py 同一规则)。"""
    return {
        "algorithm": "rc-sha256-v1",
        "iteration": file_no,
        "plan_path": plan_name,
        "artifact_sha256": canonical_sha256(artifact_doc),
        "plan_sha256": canonical_sha256(plan_doc),
        "state_projection_sha256": canonical_sha256(state_projection(state)),
    }


def min_verification(verdict="PASS", snap=None, **over):
    """最小合法验证报告;snap 给定时复述快照(verification_input 逐字段一致)。"""
    ver = {
        "verdict": verdict,
        "strengths": ["全部答案有来源"],
        "critical_issues": [],
        "warnings": [],
        "required_changes": [],
        "evidence_gaps": [],
        "confidence": "high",
    }
    if verdict == "REVISE" and not over.get("required_changes"):
        ver["required_changes"] = ["补齐 §4 规则的来源标注"]
    if verdict == "REPLAN" and not over.get("critical_issues"):
        ver["critical_issues"] = [{"what": "范围失准", "why": "PRD §5 变更",
                                   "change": "重规划问题批次"}]
    if snap is not None:
        ver["verification_input"] = snap
    ver.update(over)
    return ver


class RcDir:
    """在临时目录里组装 .pev/<轮次>/rc/ 工作目录。"""

    def __init__(self, round_name="prd-2026-01-01"):
        self.workspace = Path(tempfile.mkdtemp(prefix="rc-test-"))
        self.round_name = round_name
        self.round = self.workspace / ".pev" / round_name
        self.root = self.round / "rc"
        self.iter_dir = self.root / "iterations"
        self.iter_dir.mkdir(parents=True)
        self.state = min_state()
        self.flush_state()

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        self._state = value
        self._plans = [x for x in value.get("plans", []) if isinstance(x, str)]
        self._artifacts = [x for x in value.get("artifacts", []) if isinstance(x, str)]

    def file_no(self):
        """当前轮文件编号 = iteration + 1(rc 编号惯例)。"""
        return int(self.state.get("iteration", 0)) + 1

    def _iter_path(self, n, kind):
        return self.iter_dir / f"{n:02d}-{kind}.json"

    def write_doc(self, n, kind, doc, register=True):
        """写 iterations/<NN>-<kind>.json;plan/artifact 自动登记(与 commit 行为一致)。"""
        path = self._iter_path(n, kind)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        base = kind.split("-")[0]
        if register and base in ("plan", "artifact"):
            reg = {"plan": self._plans, "artifact": self._artifacts}[base]
            if path.name not in reg:
                reg.append(path.name)
            self.flush_state()
        return path

    def write_raw(self, rel, text):
        """原样写文件(用于截断 JSON、手改 Markdown 等反例)。"""
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_prd(self, text="# 合成 PRD\n\n§2 目标:降低登录失败率\n"):
        """在轮次 pm/ 下放一份 PRD,返回其绝对路径(prd_source 合法取值)。"""
        prd = self.round / "pm" / "output" / "prd.md"
        prd.parent.mkdir(parents=True, exist_ok=True)
        prd.write_text(text, encoding="utf-8")
        return prd.resolve()

    def flush_state(self):
        self.state.setdefault("plans", [])
        self.state.setdefault("artifacts", [])
        self.state["plans"] = list(self._plans)
        self.state["artifacts"] = list(self._artifacts)
        (self.root / "state.json").write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    def write_draft(self, name, obj):
        """把草稿写到 rc 外的临时位置(草稿是模型侧文件,不属于 rc 目录)。"""
        path = self.workspace / "drafts" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return path

    def advance_to(self, status):
        """推进到目标状态的正常链前缀:PLANNING→EXECUTING→VERIFYING。"""
        if status in ("PLANNING", "EXECUTING", "VERIFYING"):
            plan = min_plan()
            self.write_doc(1, "plan", plan)
        if status in ("EXECUTING", "VERIFYING"):
            self.state["status"] = "EXECUTING"
            self.flush_state()
            art = min_artifact()
            self.write_doc(1, "artifact", art)
            snap = snapshot_for(self.state, plan, "iterations/01-plan.json",
                                art, 1)
            self.write_doc(1, "verification-input", snap, register=False)
        if status == "VERIFYING":
            self.state["status"] = "VERIFYING"
            self.flush_state()

    def spec_path(self):
        return self.root / "output" / "spec.md"

    def cleanup(self):
        shutil.rmtree(self.workspace, ignore_errors=True)
