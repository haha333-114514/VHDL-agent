"""Bounded GHDL runner; no shell commands are accepted from users or models."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from .catalog import TASKS, testbench
from .extended_catalog import fixture_files

MAX_SOURCE = 40000
MAX_LOG = 256000


def find_ghdl() -> str | None:
    configured = os.environ.get("GHDL_PATH", "").strip().strip('"')
    candidates = [configured, shutil.which("ghdl"), r"C:\msys64\ucrt64\bin\ghdl.exe", r"C:\ghdl\bin\ghdl.exe"]
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)


def validate_source(task_id: str, source: str) -> None:
    if task_id not in TASKS:
        raise ValueError("未知实验，请选择内置任务。")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("请先输入 VHDL 源码。")
    if len(source.encode("utf-8")) > MAX_SOURCE:
        raise ValueError("源码超过 40 KB 上限，请缩小实验。")
    # Strip comments but retain string contents: paths and foreign imports are not needed here.
    code = re.sub(r"--[^\n]*", "", source).lower()
    prohibited = [r"\bfile\b", r"\btextio\b", r"\bforeign\b", r"\bvhdl_foreign\b", r"\bstd\s*\.\s*env\b", r"\b(stop|finish)\s*[;(]", r"\b(package|configuration|context)\b", r"\bzd_\w*\b"]
    if any(re.search(pattern, code) for pattern in prohibited):
        raise ValueError("当前教学运行器仅接受单电路源码，不支持文件访问、外部绑定、包/配置声明、仿真终止调用或保留的 zd_ 标识符。")
    entities = re.findall(r"\bentity\s+(\w+)\s+is\b", code)
    if entities != [TASKS[task_id]["entity"]]:
        raise ValueError(f"请保留本题唯一的 entity {TASKS[task_id]['entity']} 及其端口。")
    libraries = re.findall(r"\blibrary\s+([^;]+);", code)
    if any(name.strip() not in {"ieee", "std"} for group in libraries for name in group.split(",")):
        raise ValueError("当前教学运行器仅开放 ieee 与 std 标准库。")


def run_command(command: list[str], folder: Path, timeout: int = 15) -> tuple[int, str]:
    """File-backed logs bound Python memory; GHDL process tree is stopped on timeout."""
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("MODEL_API_KEY", None)
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    env["PATH"] = str(Path(command[0]).parent) + os.pathsep + env.get("PATH", "")
    logpath = folder / "process.log"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with logpath.open("wb") as output:
        process = subprocess.Popen(command, cwd=folder, env=env, stdout=output, stderr=subprocess.STDOUT, creationflags=flags, start_new_session=os.name != "nt")
        start = time.monotonic()
        limited = False
        while process.poll() is None:
            wavepath = folder / "wave.vcd"
            wave_oversize = wavepath.is_file() and wavepath.stat().st_size > 8_000_000
            if time.monotonic() - start > timeout or logpath.stat().st_size > MAX_LOG or wave_oversize:
                limited = True
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
                else:
                    import signal
                    os.killpg(process.pid, signal.SIGKILL)
                process.kill()
                break
            time.sleep(0.04)
        process.wait()
    with logpath.open("rb") as stream:
        log = stream.read(MAX_LOG).decode("utf-8", errors="replace")
    if limited:
        log += "\n[知电] 执行超过时间或日志上限，已停止本次工具进程。\n"
        return -1, log
    return process.returncode, log


def simulate(task_id: str, source: str, suite: str, folder: Path, *, seed: int | None = None) -> dict:
    validate_source(task_id, source)
    ghdl = find_ghdl()
    if not ghdl:
        raise RuntimeError("未找到 GHDL。请安装后设置 GHDL_PATH，再重启应用。")
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "candidate.vhd").write_text(source, encoding="utf-8", newline="\n")
    bench = testbench(task_id, suite, seed)
    (folder / "zd_tb.vhd").write_text(bench, encoding="utf-8", newline="\n")
    fixtures = fixture_files(task_id,suite,seed)
    for name, content in fixtures.items():
        (folder / name).write_text(content, encoding="utf-8", newline="\n")
    started = time.monotonic()
    logs, commands = [], []
    result = {"suite": suite, "status": "compile_error", "compiled": False, "completed": False, "passed": False, "total": 0, "failed": 0, "checks": [], "diagnostics": [], "wave_file": None, "source_hash": hashlib.sha256(source.encode()).hexdigest()}
    result.update({"seed": seed, "testbench_hash": hashlib.sha256(bench.encode()).hexdigest(), "fixture_hashes": {name: hashlib.sha256(content.encode()).hexdigest() for name, content in fixtures.items()}})
    options = ["--std=08", "--workdir=."]
    stages = [
        ("分析电路", [ghdl, "-a", *options, "candidate.vhd"]),
        ("分析测试平台", [ghdl, "-a", *options, "zd_tb.vhd"]),
        ("展开设计", [ghdl, "-e", *options, "zd_tb"]),
        ("运行仿真", [ghdl, "-r", *options, "zd_tb", "--vcd=wave.vcd", "--stop-time=10us", "--stop-delta=1000", "--assert-level=failure", "--max-stack-alloc=1024"]),
    ]
    for name, command in stages:
        commands.append({"stage": name, "argv": ["ghdl", *command[1:]]})
        code, log = run_command(command, folder)
        logs.append(f"$ {' '.join(commands[-1]['argv'])}\n{log}")
        if name == "运行仿真":
            result["compiled"] = True
            result["status"] = "runtime_error"
            pattern = r"ZD_CHECK\|(\d+)\|(\d+)\|([^|\r\n]+)\|(-?\d+)\|(-?\d+)\|([^\r\n]+)"
            for match in re.finditer(pattern, log):
                index, ns, kind, actual, expected, inputs = match.groups()
                result["checks"].append({"index": int(index), "time_ns": int(ns), "case": kind, "actual": int(actual), "expected": int(expected), "inputs": inputs.strip(), "passed": actual == expected})
            ending = re.search(r"ZD_DONE\|(\d+)\|(\d+)", log)
            result["total"] = len(result["checks"])
            result["failed"] = sum(not row["passed"] for row in result["checks"])
            if ending and int(ending[1]) == result["total"] and int(ending[2]) == result["failed"] and code == 0:
                result["completed"] = True
                result["passed"] = result["failed"] == 0
                result["status"] = "passed" if result["passed"] else "failed"
            if (folder / "wave.vcd").is_file():
                result["wave_file"] = str(folder / "wave.vcd")
        if code != 0:
            result["status"] = "limit" if code == -1 else result["status"]
            break
    full_log = "\n".join(logs)
    for match in re.finditer(r"candidate\.vhd:(\d+):(\d+):\s*([^\r\n]+)", full_log):
        result["diagnostics"].append({"line": int(match[1]), "column": int(match[2]), "message": match[3]})
    result.update({"log": full_log, "commands": commands, "duration_ms": round((time.monotonic() - started) * 1000)})
    result["files"] = [{"label":label,"path":str(folder/name)} for name,label in [
        ("zd_tb.vhd","固定测试平台 · VHDL"), ("candidate.vhd","本次被测源码"),
        ("vectors.txt","文件输入 · 地址与参考值"), ("observed.txt","文件输出 · 地址 / 实际 / 参考")
    ] if (folder/name).is_file()]
    (folder / "simulation.log").write_text(full_log, encoding="utf-8")
    return result


def diagnose(task_id: str, source: str, result: dict) -> dict:
    task = TASKS[task_id]
    if not result["compiled"]:
        first = result["diagnostics"][0] if result["diagnostics"] else {}
        return {"title": "编译尚未通过，先处理语法或接口", "explanation": first.get("message", "查看原始工具日志，确认端口、类型和语法是否符合任务约束。"), "line": first.get("line"), "kind": "compile", "evidence": "GHDL 编译输出"}
    if not result["completed"]:
        return {"title": "仿真未完整结束，暂不能判断功能", "explanation": "运行中断、超限或发生运行时错误。已取得的部分检查点不能代表完整测试通过。请查看日志。", "line": None, "kind": "runtime", "evidence": "GHDL 运行输出"}
    if result["passed"]:
        return {"title": "当前测试集全部通过", "explanation": "接下来尝试变式问题，检查自己能否解释行为。测试通过只覆盖本题列出的输入与检查点，不代表形式化证明、器件综合或板级验证。", "line": None, "kind": "pass", "evidence": f"{result['total']} 个真实仿真检查点"}
    first = next(check for check in result["checks"] if not check["passed"])
    info = task["diagnoses"].get(first["case"])
    if info:
        title, explanation, needle = info
        line = next((i for i, row in enumerate(source.splitlines(), 1) if needle.lower() in row.lower()), None)
    else:
        title, explanation, line = "输出与任务参考值不一致", "根据首个失败检查点手算这一拍的输出，再对照状态与数据更新过程。当前证据不足以唯一确定代码根因。", None
    return {"title": title, "explanation": explanation, "line": line, "kind": first["case"], "evidence": f"检查点 {first['index']} · {first['time_ns']} ns · {first['inputs']}", "first_failure": first}
