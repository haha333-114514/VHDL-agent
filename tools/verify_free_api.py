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
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    with urlopen(base + "/api/health", timeout=10) as response:
        health = json.load(response)
    provider = health["provider"]
    if not (provider["configured"] and provider["base"] == "https://openrouter.ai/api/v1" and provider["model"] == "openrouter/free" and provider["protocol"] == "chat_completions"):
        raise SystemExit("Validation requires a configured OpenRouter free preset; no request was sent.")
    body = {"task_id": "counter", "source": TASKS["counter"]["starter"], "mode": "model", "question": "请调用 inspect_contract 读取约束，再调用 read_waveform 查看第13个失败检查点附近的波形。根据工具证据解释复位优先级错误，调用 propose_patch 验证最小修改的完整源码，最后用中文给出教学说明。"}
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
            output = ROOT / "data" / "free-api-validation.json"
            output.parent.mkdir(exist_ok=True)
            output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
            return 0 if job.get("model") and not job.get("model_error") and candidate.get("verified") and len(candidate.get("challenges", [])) == 2 else 1
        time.sleep(1)
    raise SystemExit("Validation timed out; check the local experiment record before retrying.")


if __name__ == "__main__":
    raise SystemExit(main())
