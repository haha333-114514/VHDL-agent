"""Replay finite grading edge cases with real GHDL; never calls a cloud API."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from zhidian.catalog import TASKS
from zhidian.simulator import simulate


def grading_cases():
    counter = TASKS["counter"]["solution"]
    return [
        {"id": "unknown_zero", "task_id": "counter", "expected_pass": False,
         "source": counter.replace("q <= count;", "q <= (others => 'X') when count = 0 else count;")},
        {"id": "forged_completion", "task_id": "counter", "expected_pass": False,
         "source": """library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity counter4 is
  port (clk, reset, en : in std_logic; q : out unsigned(3 downto 0));
end entity;
architecture rtl of counter4 is
  signal toggle : std_logic := '0';
begin
  toggle <= not toggle;
  q <= (others => '0');
  process begin
    report "Z" & "D_DONE|0|0";
    wait;
  end process;
end architecture;
"""},
        {"id": "correct_uninitialized_counter", "task_id": "counter", "expected_pass": True,
         "source": counter.replace(" := (others => '0')", "")},
    ]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="current")
    args = parser.parse_args()
    folder = ROOT / "data/grading-audit" / (time.strftime("%Y%m%d-%H%M%S") + "-" + args.label)
    folder.mkdir(parents=True, exist_ok=False)
    rows = []
    for case in grading_cases():
        result = simulate(case["task_id"], case["source"], "full", folder / case["id"])
        row = {"id": case["id"], "expected_pass": case["expected_pass"], "matches_expectation": result["passed"] == case["expected_pass"], **{key: result.get(key) for key in ("compiled", "completed", "passed", "status", "total", "failed", "invalid_count", "expected_total", "integrity_error", "source_hash", "testbench_hash")}}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = {"label": args.label, "scope": "有限评分边界案例；不代表任意 VHDL 的隔离或安全证明。", "cases": rows}
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "data" / ("grading-audit-" + args.label + ".json")).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(row["matches_expectation"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
