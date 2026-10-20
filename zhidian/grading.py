"""Trusted check manifests and per-run log framing for simulation grading."""
from __future__ import annotations

import re

BINARY_HELPER = """function bits_defined(v : std_logic_vector) return boolean is
begin
  for i in v'range loop
    if v(i) /= '0' and v(i) /= '1' then return false; end if;
  end loop;
  return true;
end;"""


def expected_checks(task_id: str, suite: str, seed=None) -> list[dict]:
    # Kept lazy so the VHDL generators can share BINARY_HELPER without a cycle.
    from .catalog import vectors
    checks = []
    clocked = task_id in {"counter", "sequence", "fir", "ram", "pipeline", "serial_mul"}
    for index, row in enumerate(vectors(task_id, suite, seed)):
        if task_id == "counter" and suite != "smoke" and index > 0:
            checks.append({"index": len(checks)+1, "time_ns": index*10+2, "case": "sync", "expected": row["pre_expected"], "inputs": "before rising edge"})
        checks.append({"index": len(checks)+1, "time_ns": index*10+6 if clocked else (index+1)*10, "case": row["case"], "expected": row["expected"], "inputs": row["input"]})
    return checks


def grade_log(log: str, tag: str, manifest: list[dict], exit_code: int) -> dict:
    prefix = re.escape(tag)
    pattern = rf"ZD_CHECK\|{prefix}\|(\d+)\|(\d+)\|([^|\r\n]+)\|(-?\d+)\|(-?\d+)\|([^\r\n]+)"
    invalid_list = [int(value) for value in re.findall(rf"ZD_INVALID\|{prefix}\|(\d+)", log)]
    invalid = set(invalid_list)
    checks = []
    for match in re.finditer(pattern, log):
        index, ns, kind, actual, expected, inputs = match.groups()
        number, actual, expected = int(index), int(actual), int(expected)
        valid = number not in invalid
        checks.append({"index": number, "time_ns": int(ns), "case": kind, "actual": actual if valid else None, "expected": expected, "inputs": inputs.strip(), "valid": valid, "passed": valid and actual == expected})
    failed = sum(not row["passed"] for row in checks)
    endings = re.findall(rf"ZD_DONE\|{prefix}\|(\d+)\|(\d+)", log)
    stopped_by_guard = bool(re.search(r"by --stop-(?:delta|time)", log))
    error = None
    if stopped_by_guard:
        error = "仿真由时间或 delta 上限终止，不能视为测试完成。"
    elif not manifest or len(checks) != len(manifest):
        error = f"有效检查点数 {len(checks)} 与固定规格要求的 {len(manifest)} 不符。"
    elif len(invalid_list) != len(invalid) or not invalid.issubset(set(range(1, len(manifest)+1))):
        error = "非二值输出标记无效或重复。"
    elif any(any(actual[key] != expected[key] for key in ("index", "time_ns", "case", "expected", "inputs")) for actual, expected in zip(checks, manifest)):
        error = "检查点顺序、采样时间、输入或参考值与固定规格不符。"
    elif len(endings) != 1 or tuple(map(int, endings[0])) != (len(checks), failed):
        error = "缺少唯一且计数一致的测试平台完成标记。"
    completed = exit_code == 0 and error is None
    return {"checks": checks, "total": len(checks), "failed": failed, "invalid_count": len(invalid), "expected_total": len(manifest), "integrity_error": error, "completed": completed, "passed": completed and failed == 0, "stopped_by_guard": stopped_by_guard}
