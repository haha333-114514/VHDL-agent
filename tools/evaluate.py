"""Run the fixed teaching regression set and save honest engineering evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from zhidian.catalog import TASKS
from zhidian.simulator import diagnose, simulate
from zhidian.storage import now
from zhidian.provider import load_env


def main():
    load_env(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "evaluation")
    args = parser.parse_args()
    directory = args.output / time.strftime("%Y%m%d-%H%M%S")
    directory.mkdir(parents=True, exist_ok=False)
    rows = []
    for task_id, task in TASKS.items():
        for variant in ("starter", "solution"):
            result = simulate(task_id, task[variant], "full", directory / f"{task_id}-{variant}")
            expected = variant == "solution"
            row = {"task_id": task_id, "title": task["title"], "variant": variant, "status": result["status"], "checks": result["total"], "failed": result["failed"], "expected_behavior": result["completed"] and result["passed"] == expected, "diagnosis": diagnose(task_id, task[variant], result)["title"], "duration_ms": result["duration_ms"], "source_hash": result["source_hash"]}
            rows.append(row)
            print(f"{task_id}/{variant}: {result['status']}, {result['total']-result['failed']}/{result['total']}", flush=True)
    summary = {"created": now(), "scope": f"{len(TASKS)} 组固定教学电路的工程回归；不代表模型泛化、自动修复成功率或教学效果评测。", "cases": len(rows), "expected_behavior_cases": sum(row["expected_behavior"] for row in rows), "results": rows}
    (directory / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# 知电固定教学集回归结果", "", summary["scope"], "", f"时间：{summary['created']}", "", "| 任务 | 版本 | 结果 | 通过检查点 | 是否符合预期 |", "| --- | --- | --- | --- | --- |"]
    for row in rows:
        md.append(f"| {row['title']} | {row['variant']} | {row['status']} | {row['checks']-row['failed']}/{row['checks']} | {row['expected_behavior']} |")
    (directory / "results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(str(directory.resolve()), flush=True)
    return 0 if all(row["expected_behavior"] for row in rows) else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
