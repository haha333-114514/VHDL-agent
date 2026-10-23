"""Controlled model decisions + real GHDL: evaluate the teaching/repair workflow.

This does NOT measure a cloud model's autonomous repair or learning gains.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from zhidian.catalog import TASKS, QUIZZES
from zhidian.mutations import range_overfit_fir
from zhidian.provider import run_agent
from zhidian.service import Service


def call(name, **args):
    return {"type": "function_call", "name": name, "arguments": json.dumps(args, ensure_ascii=False), "call_id": uuid.uuid4().hex}


def response(*tools, text=None):
    output = list(tools)
    if text is not None:
        output.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
    return {"output": output, "model": "scripted-offline-decisions"}


CASES = ("failed_then_fixed", "blind_test_feedback", "premature_success", "duplicate_patch", "candidate_budget", "best_version_retained", "wrong_answer_review", "correct_answer_check", "interruption_checkpoint")


def run_case(case: str, directory: Path) -> dict:
    if case not in CASES:
        raise ValueError("Unknown controlled experiment")
    directory.mkdir(parents=True, exist_ok=False)
    service = Service(directory)
    service.config.update({"base": "http://127.0.0.1:1", "model": "offline-controlled", "key": ""})
    task_id = "fir" if case == "blind_test_feedback" else "counter"
    good = TASKS[task_id]["solution"]
    wrong = range_overfit_fir() if task_id == "fir" else good.replace("count + 1", "count + 2")
    goal = "coach" if case in {"wrong_answer_review", "correct_answer_check"} else "teach" if case == "best_version_retained" else "repair"
    if case == "wrong_answer_review":
        service.store.save_quiz("counter_priority", QUIZZES["counter_priority"], 0)
    plan = response(call("update_plan", steps=[{"tool": "inspect_attempt", "purpose": "读取版本与实际反例"}, {"tool": "propose_patch", "purpose": "按反例修正并验证"}]))
    bad_patch = lambda source=wrong: response(call("propose_patch", source=source, explanation="受控错误候选，用于测试失败反馈闭环。"))
    fix = response(call("propose_patch", source=good, explanation="受控正确实现，用于验证工作流，不代表模型生成能力。"))
    finish = response(text="请根据实际工具结果复查；通过仅限于当前测试范围。")
    checkpoint_seen = []
    if case in {"failed_then_fixed", "blind_test_feedback", "interruption_checkpoint"}:
        script = [plan, bad_patch(), response(call("inspect_attempt", attempt_id="patch-1"), call("read_waveform", attempt_id="patch-1", center_index=1)), fix, finish]
    elif case == "premature_success":
        script = [response(text="未使用工具却声称已经修好。"), fix, finish]
    elif case == "duplicate_patch":
        script = [bad_patch(), bad_patch(), fix, finish]
    elif case == "candidate_budget":
        script = [bad_patch(wrong+f"\n-- distinct candidate {i}\n") for i in range(3)] + [fix, finish]
    elif case == "best_version_retained":
        script = [fix, bad_patch(), finish]
    else:
        script = [response(call("read_learning_memory")), response(call("recommend_practice", quiz_id=None, reason="先预测控制信号同时有效时的行为，再用反馈检验本次理解。")), finish]
    replies = iter(script)
    request_count, tool_results = 0, []
    def transport(config, messages, schemas):
        nonlocal request_count
        request_count += 1
        tool_results[:] = [json.loads(row["output"]) for row in messages if row.get("type") == "function_call_output"]
        if case == "interruption_checkpoint" and request_count == 3:
            run_id = next(iter(service.jobs))
            restored = Service(directory).get(run_id)
            assert restored["status"] == "error" and restored["agent"]["status"] == "interrupted"
            assert len(restored["attempts"]) == 1 and not restored["attempts"][0]["verified"]
            checkpoint_seen.append(True)
        return next(replies)
    def agent(config, context, dispatch, event):
        return run_agent(config, context, dispatch, event, request_fn=transport)
    with patch("zhidian.service.run_agent", side_effect=agent):
        run = service.start({"task_id": task_id, "source": TASKS[task_id]["starter"], "mode": "model", "goal": goal})
        with service.lock:
            service.jobs[run["id"]]["evaluation"] = {"model_decisions": "scripted_offline", "simulation": "real_GHDL", "note": "受控演示：模型决策由测试脚本提供；仿真为真实 GHDL。"}
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            job = service.get(run["id"])
            if job["status"] != "running":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("Controlled experiment timed out")
    assert job["status"] == "complete", job.get("error")
    assert job["model_error"] is None, job["model_error"]
    assert job["source"] == TASKS[task_id]["starter"]
    if goal == "coach":
        practice = job["agent"]["practice"]
        assert job["agent"]["status"] == "needs_practice"
        assert practice["quiz"]["id"] == "counter_priority"
        assert "answer" not in practice["quiz"] and "explanation" not in practice["quiz"]
        answer = 0 if case == "wrong_answer_review" else 1
        graded = service.answer_practice(run["id"], practice["quiz"]["id"], answer)
        assert graded["correct"] == (case == "correct_answer_check")
        job = Service(directory).get(run["id"])
        assert job["agent"]["status"] == "practice_checked"
        assert job["agent"]["practice"]["submission"]["correct"] == graded["correct"]
    elif case == "candidate_budget":
        assert len(job["attempts"]) == 3 and not job["candidate"]["verified"]
        assert job["agent"]["status"] == "budget_exhausted"
        assert any("3 个候选上限" in str(row.get("error")) for row in tool_results)
    else:
        assert job["candidate"]["verified"]
        if goal == "repair":
            assert job["agent"]["status"] == "achieved"
        if case in {"failed_then_fixed", "blind_test_feedback", "interruption_checkpoint", "duplicate_patch"}:
            assert len(job["attempts"]) == 2 and not job["attempts"][0]["verified"]
        if case == "blind_test_feedback":
            assert job["attempts"][0]["result"]["passed"] and all(not row["passed"] for row in job["attempts"][0]["challenges"])
        if case == "best_version_retained":
            assert job["candidate"]["id"] == "patch-1" and not job["attempts"][-1]["verified"]
        if case == "duplicate_patch":
            assert any("已运行" in str(row.get("error")) for row in tool_results)
        if case == "premature_success":
            assert any(row["key"] == "mission-continue" for row in job["events"])
            assert "未使用工具" not in job["model"]["text"]
        if case == "interruption_checkpoint":
            assert checkpoint_seen
    summary = {"case": case, "passed": True, "run_id": job["id"], "goal": goal, "mission_status": job["agent"]["status"], "requests": request_count,
               "model_decisions": "scripted_offline", "simulator": "real_GHDL", "attempts": [{"id": row["id"], "source_hash": row["result"]["source_hash"], "public_passed": row["result"]["passed"], "verified": row["verified"], "checks": row["result"]["total"], "failed": row["result"]["failed"], "challenge_checks": [r["total"] for r in row["challenges"]]} for row in job["attempts"]],
               "practice_checked": bool((job["agent"].get("practice") or {}).get("submission")), "original_source_preserved": True}
    (directory/"experiment.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES)
    args = parser.parse_args()
    directory = ROOT / "data/teacher-agent-evaluation" / time.strftime("%Y%m%d-%H%M%S")
    results = []
    for case in [args.case] if args.case else CASES:
        row = run_case(case, directory/case)
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = {"date": time.strftime("%Y-%m-%d"), "scope": "受控离线模型决策 + 真实 GHDL；不是云模型自主修复率或学生学习效果。", "results": results}
    (directory/"results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Evidence:", directory, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
