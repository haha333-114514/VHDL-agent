"""Run one real, bounded free-router experiment against a local Zhidian server."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from zhidian.catalog import TASKS


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Consume free API quota for one counter-agent validation")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--goal", choices=("teach", "coach", "repair"), default="teach")
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    with urlopen(base + "/api/health", timeout=10) as response:
        health = json.load(response)
    provider = health["provider"]
    if not (provider["configured"] and provider["base"] == "https://openrouter.ai/api/v1" and provider["model"] == "openrouter/free" and provider["protocol"] == "chat_completions"):
        raise SystemExit("Validation requires a configured OpenRouter free preset; no request was sent.")
    body = {"task_id": "counter", "source": TASKS["counter"]["starter"], "mode": "model", "question": "请调用 inspect_contract 读取约束，再调用 read_waveform 查看第13个失败检查点附近的波形。根据工具证据解释复位优先级错误，调用 propose_patch 验证最小修改的完整源码，最后用中文给出教学说明。"}
    body["goal"] = args.goal
    if args.goal == "coach":
        body["question"] = "请像老师一样带练：制定简短行动计划，读取当前题的学习记忆和失败证据，先给一个观察提示，用 recommend_practice 安排一道理解检查，不要透露练习题的正确答案，也不要直接给完整修复代码。尽量在 4–5 次工具调用内完成。"
    elif args.goal == "repair":
        body["question"] = "请自主规划并修复当前电路。根据失败证据验证候选；如果失败，读取该候选版本反例后再修改。固定完成条件满足后归纳，不覆盖我的原始源码。"
    request = Request(base + "/api/run", data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "X-Zhidian-Token": health["csrf"]}, method="POST")
    with urlopen(request, timeout=10) as response:
        run_id = json.load(response)["id"]
    print("Started real free-router experiment:", run_id, flush=True)
    deadline, last = time.monotonic() + 400, None
    while time.monotonic() < deadline:
        with urlopen(base + "/api/runs/" + run_id, timeout=10) as response:
            job = json.load(response)
        progress = [(event["title"], event["state"]) for event in job["events"]]
        if progress != last:
            print("Progress:", progress[-1] if progress else job["status"], flush=True)
            last = progress
        if job["status"] != "running":
            result, candidate = job.get("result") or {}, job.get("candidate") or {}
            summary = {"run_id": run_id, "status": job["status"], "model": job.get("model"), "model_error": job.get("model_error"), "error": job.get("error"), "baseline": {key: result.get(key) for key in ("total", "failed", "passed")}, "candidate": {"verified": candidate.get("verified"), "total": (candidate.get("result") or {}).get("total"), "failed": (candidate.get("result") or {}).get("failed"), "challenges": [{key: row.get(key) for key in ("seed", "total", "failed", "passed", "testbench_hash")} for row in candidate.get("challenges", [])]}, "events": progress, "report_url": base + "/api/runs/" + run_id + "/report"}
            summary["goal"] = args.goal
            summary["agent"] = job.get("agent")
            summary["attempts"] = [{"id": row["id"], "verified": row["verified"], "source_hash": row["result"]["source_hash"], "failed": row["result"]["failed"]} for row in job.get("attempts", [])]
            output = ROOT / "data" / ("free-api-validation.json" if args.goal == "teach" else f"free-api-{args.goal}-validation.json")
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
            target_met = (job.get("agent") or {}).get("status") in {"needs_practice", "practice_checked"} if args.goal == "coach" else candidate.get("verified") and len(candidate.get("challenges", [])) == 2
            return 0 if job.get("model") and not job.get("model_error") and target_met else 1
        time.sleep(1)
    raise SystemExit("Validation timed out; check the local experiment record before retrying.")


if __name__ == "__main__":
    raise SystemExit(main())
