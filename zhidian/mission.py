"""Observable goals and plans. Only tool evidence determines repair success."""
from __future__ import annotations

GOALS = {"teach": "解释本次证据", "coach": "老师带练：提示与理解检查", "repair": "自主修复并独立验证"}
ACTION_TOOLS = {"inspect_contract", "run_simulation", "read_waveform", "read_learning_memory", "propose_patch", "inspect_attempt", "recommend_practice"}
MAX_ATTEMPTS = 3


def new_mission(goal: str) -> dict:
    if not isinstance(goal, str) or goal not in GOALS:
        raise ValueError("请选择解释证据、老师带练或自主修复目标。")
    actions = [("inspect_contract", "确认固定规格与完成条件"), ("read_waveform", "根据实际反例选择检查方向")]
    actions += [("propose_patch", "提交候选并按失败反馈调整")] if goal == "repair" else [("recommend_practice", "根据练习记录安排理解检查")]
    return {"goal": goal, "title": GOALS[goal], "status": "running", "plan_revision": 0,
            "plan_origin": "默认计划；模型可调整", "plan": [{"tool": tool, "purpose": purpose, "observations": 0} for tool, purpose in actions],
            "plan_history": [], "attempt_count": 0, "max_attempts": MAX_ATTEMPTS, "latest_attempt": "baseline", "practice": None,
            "acceptance": "原始完整测试已通过，或候选通过公开完整测试与两组追加验证" if goal == "repair" else "依据工具证据带练，并安排一道理解检查；不推断学生已掌握",
            "stop_reason": None, "requests": [], "observed_tools": {}}


def update_plan(mission: dict, steps) -> dict:
    if not isinstance(steps, list) or not 2 <= len(steps) <= 6:
        raise ValueError("行动计划需要 2–6 步。")
    checked = []
    for step in steps:
        if not isinstance(step, dict) or step.get("tool") not in ACTION_TOOLS:
            raise ValueError("计划只能选择当前开放的取证、修改和练习工具。")
        purpose = step.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 200:
            raise ValueError("每步说明须为 1–200 字的简短行动目的。")
        checked.append({"tool": step["tool"], "purpose": purpose.strip(), "observations": mission.get("observed_tools", {}).get(step["tool"], 0)})
    mission["plan_history"].append({"revision": mission["plan_revision"], "steps": mission["plan"]})
    mission.update(plan=checked, plan_origin="模型制定 / 调整", plan_revision=mission["plan_revision"]+1)
    return {"revision": mission["plan_revision"], "steps": checked, "note": "计划不是执行证据；只有工具实际返回后才记录取证次数。"}


def observe(mission: dict, tool: str) -> None:
    counts = mission.setdefault("observed_tools", {})
    counts[tool] = counts.get(tool, 0)+1
    for step in mission["plan"]:
        if step["tool"] == tool:
            step["observations"] = counts[tool]


def repair_achieved(job: dict) -> bool:
    baseline = job.get("result") or {}
    return bool((baseline.get("passed") and baseline.get("suite") == "full") or (job.get("candidate") or {}).get("verified"))


def finish_mission(job: dict) -> None:
    mission = job.get("agent")
    if not mission:
        return
    if mission["goal"] == "repair" and repair_achieved(job):
        mission.update(status="achieved", stop_reason="固定完成条件已由实际仿真满足；原始编辑器未覆盖。")
    elif job.get("model_error"):
        mission.update(status="incomplete", stop_reason=job["model_error"])
    elif mission["goal"] == "repair":
        mission.update(status="budget_exhausted", stop_reason="本轮有界执行已结束，未取得通过全部验证的修复；不能声称修好。")
    elif mission["goal"] == "coach":
        practice = mission.get("practice")
        status = "practice_checked" if practice and practice.get("submission") else "needs_practice" if practice else "incomplete"
        mission.update(status=status, stop_reason="已生成带练任务，等待你作答。" if status == "needs_practice" else "已记录本次作答；不等于掌握证明。" if status == "practice_checked" else "本次未安排理解检查，带练尚未完成。")
    else:
        mission.update(status="completed", stop_reason="教学解释已返回；功能是否通过以仿真为准。")
