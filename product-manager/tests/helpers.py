"""测试共享工具:构造最小合法 pm 目录、运行 skill 脚本。

仅依赖标准库。所有夹具都是合成数据,与任何真实 PM 工作目录无关。
用法(在 skill 根目录): python3 -m unittest discover -s tests -t . -v
"""

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent

# design.md"输入绑定与来源证明":state 投影的显式纳入/排除路径(七条生命周期路径排除)
PROJECTION_INCLUDE = (
    "objective", "business_context", "known", "assumptions",
    "evidence", "metrics", "hypotheses", "opportunities",
)


def canonical_sha256(obj):
    """规范化序列化的 SHA-256:键排序、UTF-8、紧凑分隔符(design.md 同一规则)。"""
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def state_projection(state):
    """按 design 的纳入路径取 state 投影(排除集字段不参与摘要)。"""
    return {k: state[k] for k in PROJECTION_INCLUDE if k in state}


def run_script(script_name, *args):
    """运行 scripts/ 下的脚本,返回 CompletedProcess(stdout/stderr 为文本)。"""
    return subprocess.run(
        [sys.executable, str(SKILL_ROOT / "scripts" / script_name), *args],
        capture_output=True, text=True,
    )


def run_validate(pm_dir):
    return run_script("validate.py", str(pm_dir))


def out_json(proc):
    """把脚本 stdout 解析为 JSON(模型—脚本交接协议:stdout 永远是单行紧凑 JSON)。"""
    return json.loads(proc.stdout)


def min_evidence(i=1, type_="FACT", claim=None, evidence="data.csv", confidence="high"):
    """一条合法 Ledger 条目;FACT/INFERENCE 必须带非空 evidence(R1)。"""
    return {
        "id": f"E{i}", "claim": claim or f"合成论断{i}", "type": type_,
        "evidence": evidence, "confidence": confidence,
    }


def min_state(**over):
    """最小合法 state;默认 INIT、无产物(design:INIT 无产物是合法中间态)。"""
    state = {
        "objective": {"goal": "把新用户次周留存率从 20% 提升到 25%",
                      "target_metric": "次周留存率", "baseline": 0.20},
        "status": "INIT",
        "iteration": 0,
        "max_iterations": 5,
    }
    state.update(over)
    return state


PRD_BODY = {
    "title": "合成 PRD:消息推送优化",
    "background": "留存数据显示新用户次周流失集中在首周内。",
    "goal": "通过首周引导推送把次周留存率从 20% 提升到 25%",
    "primary_metric": "次周留存率",
    "solution": "首周第 1/3/5 天推送个性化引导",
    "solution_rationale": "流失时点集中在第 2-4 天,引导推送对应补齐",
    "in_scope": ["首周推送文案", "频控策略"],
    "out_of_scope": ["推送通道改造"],
    "launch_plan": "灰度 10% 一周后全量",
    "acceptance": "次周留存率相对对照组提升不低于 3 个百分点",
    "user_stories": [
        {"user": "新注册用户", "action": "收到首周引导推送",
         "value": "更快完成关键动作"},
    ],
    "validation_metrics": [
        {"name": "次周留存率", "definition": "注册后第 7-14 天活跃占比",
         "purpose": "验证目标达成", "source": "现有埋点"},
    ],
}


def min_artifact(status="completed", **over):
    """最小合法 Artifact;completed 正文满足 PRD 模板 B 类必填集。"""
    art = {"status": status, "artifact": dict(PRD_BODY)}
    if status in ("replan_required", "blocked"):
        art["replan_reason"] = {"problem": "关键输入缺失", "why_invalid": "无法继续",
                                "new_information": "用户补充", "recommended": "等待补数"}
    art.update(over)
    return art


def min_decision_artifact(**over):
    """decision.md 夹具:{{roi}} 是正文标量,证据行来自 state.evidence。"""
    art = {"status": "completed", "artifact": {
        "title": "合成决策:推送 vs 引导页改版",
        "conclusion": "首周推送的预期收益更高",
        "confidence": "high",
        "recommendation": "先做首周推送,两周后复测",
        "roi": "预计 ROI 1.8(口径:留存增益折算)",
        "solutions": [
            {"name": "首周推送", "benefit": "留存 +3pp", "benefit_confidence": "high",
             "cost": "2 人周", "risks": ["频控打扰", "退订率上升"]},
            {"name": "引导页改版", "benefit": "留存 +1pp", "benefit_confidence": "medium",
             "cost": "3 人周", "risks": []},
        ],
    }}
    art.update(over)
    return art


def min_opportunity_artifact(**over):
    """product-opportunity.md 夹具:evidence_ref 引用 state.evidence 现存 id。"""
    art = {"status": "completed", "artifact": {
        "title": "合成机会:新用户激活",
        "goal": "提升新用户激活率",
        "metric": "激活率", "baseline": "20%", "target": "25%",
        "problem": "新用户首周无关键动作",
        "root_cause": "缺少引导触点",
        "recommendation": "优先做首周推送引导",
        "opportunities": [
            {"name": "首周推送引导", "priority": "P0", "impact": "激活率 +3pp",
             "evidence_ref": "E1", "confidence": "high"},
        ],
    }}
    art.update(over)
    return art


def min_plan(**over):
    plan = {
        "goal": "把新用户次周留存率从 20% 提升到 25%",
        "understanding": "流失集中在首周,疑与引导缺失相关。",
        "known": ["次周留存率 20%"], "unknown": ["流失根因"], "assumptions": [],
        "plan": [{"id": "P1", "objective": "定位流失根因并起草方案",
                  "action": "draft", "inputs": ["state.evidence"],
                  "expected_output": "Artifact", "success_criteria": "B/C 类通过"}],
        "final_deliverable": "PRD",
        "stop_conditions": ["证据不足以支撑结论时停止"],
    }
    plan.update(over)
    return plan


def min_verification(verdict="PASS", **over):
    ver = {
        "verdict": verdict,
        "strengths": ["证据链完整"],
        "critical_issues": [],
        "warnings": [],
        "required_changes": [],
        "evidence_gaps": [],
        "confidence": "high",
    }
    if verdict == "REVISE" and not over.get("required_changes"):
        ver["required_changes"] = ["补齐 secondary_metrics 口径定义"]
    ver.update(over)
    return ver


def min_provenance(pm_dir, iteration=1, plan=None, artifact=None, state=None,
                   plan_name=None, artifact_name=None):
    """按 design 规则计算并返回 provenance 对象(绑定语义的测试侧实现)。"""
    plan = plan if plan is not None else min_plan()
    artifact = artifact if artifact is not None else min_artifact()
    state = state if state is not None else min_state()
    return {
        "algorithm": "sha256-v1",
        "plan_path": plan_name or f"iterations/{iteration:02d}-plan.json",
        "artifact_sha256": canonical_sha256(artifact),
        "plan_sha256": canonical_sha256(plan),
        "state_projection_sha256": canonical_sha256(state_projection(state)),
    }


class PmDir:
    """在临时目录里组装一个 pm/ 工作目录;登记册自动保持与文件一致(R4)。"""

    def __init__(self, state=None):
        self.root = Path(tempfile.mkdtemp(prefix="nana-test-"))
        self.iter_dir = self.root / "iterations"
        self.iter_dir.mkdir()
        self.state = state if state is not None else min_state()
        self.flush_state()

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        # 替换 state 时重新播种登记册,避免 flush_state 覆盖手工预设的登记项
        self._state = value
        self._plans = [x for x in value.get("plans", []) if isinstance(x, str)]
        self._artifacts = [x for x in value.get("artifacts", []) if isinstance(x, str)]

    def _iter_path(self, n, kind):
        return self.iter_dir / f"{n:02d}-{kind}.json"

    def write_doc(self, n, kind, doc, register=True):
        """写 iterations/<NN>-<kind>.json;kind 可带后缀如 verification-input。"""
        path = self.iter_dir / f"{n:02d}-{kind}.json"
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

    def flush_state(self):
        self.state.setdefault("plans", [])
        self.state.setdefault("artifacts", [])
        self.state["plans"] = list(self._plans)
        self.state["artifacts"] = list(self._artifacts)
        (self.root / "state.json").write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    def cleanup(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)
