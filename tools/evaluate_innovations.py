"""Measure fault detection and held-out challenges using real GHDL, without APIs."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from zhidian.catalog import TASKS
from zhidian.mutations import mutation_cases
from zhidian.provider import load_env
from zhidian.simulator import simulate
from zhidian.storage import now

SEED = 20261019


def compact(result):
    first = next((row for row in result["checks"] if not row["passed"]), None)
    return {key: result[key] for key in ("compiled", "completed", "passed", "total", "failed", "source_hash", "testbench_hash", "seed")} | {"first_failure": first}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_env(ROOT / ".env")
    directory = ROOT / "data" / "innovation-evaluation" / time.strftime("%Y%m%d-%H%M%S")
    directory.mkdir(parents=True, exist_ok=False)
    references, mutations = [], []
    for task_id, task in TASKS.items():
        result = simulate(task_id, task["solution"], "challenge", directory / (task_id + "-reference"), seed=SEED)
        references.append({"task_id": task_id, **compact(result)})
        print(f"reference/{task_id}: {result['total']-result['failed']}/{result['total']}", flush=True)
    for case in mutation_cases():
        row = {key: case[key] for key in ("id", "task_id", "name")}
        for suite in ("smoke", "full", "challenge"):
            result = simulate(case["task_id"], case["source"], suite, directory / (case["id"] + "-" + suite), seed=SEED if suite == "challenge" else None)
            row[suite] = compact(result)
        mutations.append(row)
        print(case["id"] + ": " + ", ".join(suite + "=" + ("survived" if row[suite]["passed"] else "detected" if row[suite]["compiled"] and row[suite]["completed"] else "invalid") for suite in ("smoke", "full", "challenge")), flush=True)
    valid = [row for row in mutations if all(row[suite]["compiled"] and row[suite]["completed"] for suite in ("smoke", "full", "challenge"))]
    scores = {suite: {"detected": sum(not row[suite]["passed"] for row in valid), "valid_mutants": len(valid)} for suite in ("smoke", "full", "challenge")}
    summary = {"created": now(), "seed": SEED, "scope": "15 个受控功能故障与 11 个参考电路的工程实验；不是模型修复率、教学效果或形式化证明。", "references": references, "mutations": mutations, "scores": scores}
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    (directory / "results.json").write_text(text, encoding="utf-8")
    (ROOT / "docs/创新实验结果.json").write_text(text, encoding="utf-8")
    md = ["# 创新实验：盲测复核与测试集故障检出", "", summary["scope"], "", f"时间：{summary['created']}；重放种子：`{SEED}`。全部结果来自实际 GHDL，不调用云模型。", "", f"11 个正确参考实现的追加验证：{sum(row['passed'] for row in references)}/11 通过。", "", "| 测试集 | 检出的有效故障 |", "| --- | --- |"]
    for suite, label in (("smoke", "基础检查"), ("full", "公开完整测试"), ("challenge", "追加随机 / 顺序验证")):
        md.append(f"| {label} | {scores[suite]['detected']}/{scores[suite]['valid_mutants']} |")
    md.extend(["", "编译或运行中断的变异体单独归为无效，不作为成功检出计入分数。", "", "| 故障 | 基础检查 | 公开完整测试 | 追加验证 |", "| --- | --- | --- | --- |"])
    for row in mutations:
        statuses = ["漏检" if row[suite]["passed"] else "检出" if row[suite]["compiled"] and row[suite]["completed"] else "无效" for suite in ("smoke", "full", "challenge")]
        md.append("| " + row["name"] + " | " + " | ".join(statuses) + " |")
    md.extend(["", "## 为什么需要额外验证", "", "故意构造的 FIR 特判版在输入超出 [-12,12] 时输出 0。它迎合现有公开随机样本范围，仍违反整数 FIR 规格。新测试加入合法的较大输入与新随机序列，检查公开测试通过是否只是范围特判。", "", "候选代码提交后才生成两组 32 位种子，写入报告用于重放。表决器、LUT、ROM 的有限输入已经穷举，所以追加验证只重排输入顺序，不宣称引入新的真值表输入。随机复核增强工程证据，仍不保证任意输入都正确。", ""])
    (ROOT / "docs/创新实验结果.md").write_text("\n".join(md), encoding="utf-8")
    success = len(valid) == len(mutations) and all(row["passed"] for row in references) and scores["challenge"]["detected"] == len(valid)
    print(json.dumps({"scores": scores, "reference_passed": sum(row["passed"] for row in references), "valid_mutants": len(valid), "success": success}, ensure_ascii=False), flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
