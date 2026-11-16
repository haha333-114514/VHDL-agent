"""Application orchestration, evidence traces and reproducible Markdown reports."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from pathlib import Path
import threading
import time
import traceback
import uuid

from .catalog import TASKS, QUIZZES, public_task
from .mission import ACTION_TOOLS, finish_mission, new_mission, observe, repair_achieved, update_plan
from .provider import Configuration, run_agent
from .simulator import diagnose, simulate, validate_source
from .storage import Store, now
from .verification import compare_checks, verify_candidate


SUITES = {"smoke": "基础检查", "boundary": "边界补测", "full": "完整测试"}


class Service:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.store = Store(self.directory)
        self.config = Configuration()
        self.jobs: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.capacity = threading.BoundedSemaphore(1)

    def event(self, run_id: str, key: str, title: str, detail: str, state: str = "done") -> None:
        with self.lock:
            job = self.jobs[run_id]
            item = next((row for row in job["events"] if row["key"] == key and row["state"] == "running"), None)
            data = {"key": key, "title": title, "detail": detail, "state": state, "at": now()}
            if item is None:
                job["events"].append(data)
            else:
                item.update(data)

    def start(self, values: dict) -> dict:
        task_id = values.get("task_id")
        source = values.get("source", "")
        validate_source(task_id, source)
        mode = values.get("mode", "local")
        if mode not in {"local", "model"}:
            raise ValueError("请选择本地证据诊断或模型智能体。")
        question = values.get("question", "")
        if not isinstance(question, str) or len(question) > 4000:
            raise ValueError("补充问题最多 4000 个字符。")
        reference = values.get("action") == "reference"
        if reference:
            mode = "local"
        mission = new_mission(values.get("goal", "teach")) if mode == "model" else None
        config = self.config.snapshot()
        if mode == "model" and not self.config.public()["configured"]:
            raise ValueError("模型尚未配置。先在模型设置中填写免费服务密钥，或使用本地证据诊断。")
        if not self.capacity.acquire(blocking=False):
            raise ValueError("当前已有实验运行中，请等待完成。")
        run_id = uuid.uuid4().hex
        job = {"id": run_id, "created": now(), "task_id": task_id, "source": TASKS[task_id]["solution"] if reference else source, "original_source": source if reference else None, "mode": mode, "question": question.strip(), "reference_run": reference, "status": "running", "events": [], "result": None, "smoke": None, "diagnosis": None, "candidate": None, "model": None, "model_error": None, "error": None}
        job.update(agent=mission, attempts=[])
        with self.lock:
            self.jobs[run_id] = job
            # Bound memory while keeping every completed run on disk.
            old = [key for key, value in self.jobs.items() if value["status"] != "running"]
            for key in old[:-20]:
                self.jobs.pop(key, None)
        threading.Thread(target=self.execute, args=(run_id, config), daemon=True).start()
        return {"id": run_id, "status": "running"}

    @staticmethod
    def compact(result: dict) -> dict:
        return {"status": result["status"], "compiled": result["compiled"], "completed": result["completed"], "total": result["total"], "failed": result["failed"], "expected_total": result.get("expected_total"), "invalid_count": result.get("invalid_count", 0), "integrity_error": result.get("integrity_error"), "source_hash": result["source_hash"], "first_failures": [row for row in result["checks"] if not row["passed"]][:8], "diagnostics": result["diagnostics"][:8], "log_tail": result["log"][-2500:]}

    def checkpoint(self, job: dict) -> None:
        with self.lock:
            directory = self.directory / "runs" / job["id"]
            checkpoint = directory / "run.json"
            temporary = directory / "run.json.tmp"
            temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            for attempt in range(6):
                try:
                    temporary.replace(checkpoint)
                    return
                except PermissionError as exc:
                    # Open file handles on Windows can briefly prevent atomic replacement.
                    if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 5:
                        raise
                    time.sleep(0.02 * 2 ** attempt)

    @staticmethod
    def artifact_url(directory: Path, path: str) -> str:
        artifact = Path(path).resolve()
        if not artifact.is_relative_to(directory):
            # A saved snapshot can retain absolute paths from before a project move.
            for parent in artifact.parents:
                if parent.name == directory.name and parent.parent.name == "runs":
                    artifact = (directory / artifact.relative_to(parent)).resolve()
                    break
        relative = artifact.relative_to(directory).as_posix()
        return f"/api/runs/{directory.name}/artifact/{relative}"

    @staticmethod
    def attempt(job: dict, attempt_id=None) -> dict:
        if attempt_id is None or attempt_id == "baseline":
            return {"id": "baseline", "source": job["source"], "result": job["result"], "verified": False, "challenges": []}
        if attempt_id == "latest":
            return job["attempts"][-1] if job["attempts"] else Service.attempt(job)
        if not isinstance(attempt_id, str):
            raise ValueError("版本编号须为 baseline、latest 或已存在的 patch 编号。")
        found = next((row for row in job["attempts"] if row["id"] == attempt_id), None)
        if found is None:
            raise ValueError("未找到该版本，请使用 baseline、latest 或已返回的 patch 编号。")
        return found

    def recommend_practice(self, job: dict, args: dict) -> dict:
        reason = args.get("reason", "")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 400:
            raise ValueError("练习目的须为 1–400 字。")
        available = self.quizzes(job["task_id"])
        choices = {row["id"]: row for row in available}
        selected = args.get("quiz_id")
        if selected is None:
            memory = self.store.task_memory(job["task_id"])
            recent = {}
            for row in memory["recent_quizzes"]:
                recent.setdefault(row["quiz_id"], row)
            wrong = next((key for key, row in recent.items() if not row["correct"] and key in choices), None)
            selected = wrong or next((key for key in choices if key not in recent), available[0]["id"])
            basis = "近期答错，先复习" if wrong else "优先未做题，其次做变式复习"
        else:
            basis = "模型在当前任务题库中选择"
        if not isinstance(selected, str) or selected not in choices:
            raise ValueError("只能推荐当前任务中已有的理解题。可用题号：" + ", ".join(choices) + "；也可将 quiz_id 设为 null，由工具按记忆选择。")
        practice = {"quiz": choices[selected], "reason": reason.strip(), "basis": basis, "submission": None}
        job["agent"]["practice"] = practice
        return practice

    def answer_practice(self, run_id: str, quiz_id: str, choice: int) -> dict:
        # Validate identity before using it in a filesystem path.
        snapshot = self.get(run_id)
        with self.lock:
            job = self.jobs.get(run_id)
            if job is None:
                job = json.loads((self.directory / "runs" / run_id / "run.json").read_text(encoding="utf-8"))
                if snapshot["status"] == "error" and job["status"] == "running":
                    job.update(status="error", error=snapshot["error"])
                    job["agent"].update(status="interrupted", stop_reason=snapshot["error"])
                self.jobs[run_id] = job
            mission = job.get("agent") or {}
            practice = mission.get("practice")
            if not practice or practice["quiz"]["id"] != quiz_id or QUIZZES[quiz_id]["task_id"] != job["task_id"]:
                raise ValueError("这道题不是本次智能体安排的理解检查。")
            quiz = QUIZZES[quiz_id]
            if type(choice) is not int or not 0 <= choice < len(quiz["options"]):
                raise ValueError("请选择一个有效答案。")
            result = self.store.save_quiz(quiz_id, quiz, choice)
            practice["submission"] = {"choice": choice, "correct": result["correct"], "feedback": result["explanation"], "at": now()}
            if job["status"] == "complete":
                finish_mission(job)
            self.checkpoint(job)
            if job["status"] == "complete":
                (self.directory / "runs" / run_id / "report.md").write_text(self.report(job), encoding="utf-8")
            return {**result, "agent": copy.deepcopy(mission)}

    def execute(self, run_id: str, config: dict) -> None:
        start = time.monotonic()
        job = self.jobs[run_id]
        directory = self.directory / "runs" / run_id
        directory.mkdir(parents=True)
        task_id, source = job["task_id"], job["source"]
        def event(key, title, detail, state="done"):
            self.event(run_id, key, title, detail, state)
            self.checkpoint(job)
        try:
            event("contract", "读取实验约束", "固定接口、参考模型与测试平台；本次源码单独保存。")
            if job["reference_run"]:
                event("reference", "验证教学参考实现", "这是内置教学参考版本，在新目录运行；学生原代码仍保留。")
            event("smoke", "运行基础检查", "调用 GHDL 分析、展开并仿真。", "running")
            smoke = simulate(task_id, source, "smoke", directory / "smoke")
            with self.lock:
                job["smoke"] = smoke
            event("smoke", "基础检查已完成", self.describe(smoke), "done" if smoke["passed"] else "attention")
            result = smoke
            if smoke["compiled"] and smoke["completed"]:
                event("full", "补充边界与完整测试", TASKS[task_id]["coverage"], "running")
                result = simulate(task_id, source, "full", directory / "full")
                event("full", "完整测试已完成", self.describe(result), "done" if result["passed"] else "attention")
            else:
                event("full", "功能测试暂缓", "先解决编译或运行错误，再判断电路功能。", "skipped")
            diagnostic = diagnose(task_id, source, result)
            with self.lock:
                job["result"], job["diagnosis"] = result, diagnostic
            event("wave", "整理仿真证据", f"保留 {result['total']} 个检查点、原始日志及实际生成的 VCD。" if result["checks"] else "已保存原始工具日志；当前没有完整的功能采样。")
            event("diagnosis", "生成学习建议", diagnostic["title"])
            if job["mode"] == "model" and diagnostic["kind"] == "environment":
                with self.lock:
                    job["model_error"] = "本机工具环境异常，模型请求已暂缓；修正系统时间或 GHDL 标准库后再运行。"
                event("model-environment", "模型请求暂缓", job["model_error"], "attention")
            elif job["mode"] == "model":
                self.model_step(job, config, directory, event)
            with self.lock:
                finish_mission(job)
                job["duration_ms"] = round((time.monotonic() - start) * 1000)
                job["status"] = "complete"
                for row in job["events"]:
                    if row["state"] == "running":
                        row["state"] = "attention" if job["model_error"] else "done"
                self.store.save_run(job)
                # Finish every artifact before a completed run can be observed by polling.
                self.checkpoint(job)
                (directory / "report.md").write_text(self.report(job), encoding="utf-8")
        except Exception as exc:
            logging.getLogger("zhidian").exception("Experiment %s failed", run_id)
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else f"运行器遇到 {type(exc).__name__}，请查看本机终端。"
            with self.lock:
                job["status"], job["error"] = "error", message
                if job.get("agent"):
                    job["agent"].update(status="incomplete", stop_reason=message)
            event("error", "本次实验未完成", message, "attention")
        finally:
            self.capacity.release()

    @staticmethod
    def describe(result: dict) -> str:
        if not result["compiled"]:
            return "GHDL 编译 / 展开未通过，已保留原始错误。"
        if not result["completed"]:
            return "仿真未完整结束，不能标记为测试通过。"
        return f"{result['total'] - result['failed']} / {result['total']} 个检查点通过，{result['failed']} 个不符合参考值。"

    def model_step(self, job: dict, config: dict, directory: Path, event) -> None:
        tool_index = 0
        def dispatch(name: str, args: dict) -> dict:
            nonlocal tool_index
            tool_index += 1
            key = f"tool-{tool_index}"
            allowed = ACTION_TOOLS | {"update_plan"}
            if name not in allowed:
                raise ValueError("模型请求了未开放的工具。")
            event(key, f"调用工具 · {name}", "正在取得可复查证据。", "running")
            try:
                if name == "inspect_contract":
                    output = {key: value for key, value in public_task(TASKS[job["task_id"]]).items() if key != "starter"}
                elif name == "read_learning_memory":
                    output = self.store.task_memory(job["task_id"])
                elif name == "update_plan":
                    output = update_plan(job["agent"], args.get("steps"))
                elif name == "recommend_practice":
                    output = self.recommend_practice(job, args)
                elif name == "inspect_attempt":
                    attempt = self.attempt(job, args.get("attempt_id"))
                    output = {"attempt_id": attempt["id"], "source": attempt["source"], "result": self.compact(attempt["result"]), "verified": attempt["verified"], "challenges": [self.compact(row) for row in attempt["challenges"]]}
                elif name == "read_waveform":
                    center = args.get("center_index")
                    if type(center) is not int or not 1 <= center <= 1000:
                        raise ValueError("检查点编号应为 1–1000 的整数。")
                    attempt = self.attempt(job, args.get("attempt_id"))
                    output = {"attempt_id": attempt["id"], "source_hash": attempt["result"]["source_hash"], "sampling": "测试平台沿后或组合逻辑稳定后的离散检查点；完整事件波形另存 VCD。", "checks": attempt["result"]["checks"][max(0, center-4):center+3]}
                elif name == "run_simulation":
                    suite = args.get("suite")
                    if suite not in SUITES:
                        raise ValueError("不支持的测试集。")
                    attempt = self.attempt(job, args.get("attempt_id"))
                    result = simulate(job["task_id"], attempt["source"], suite, directory / f"model-test-{tool_index}")
                    output = {"attempt_id": attempt["id"], **self.compact(result)}
                else:
                    candidate_source = args.get("source", "")
                    explanation = args.get("explanation", "")
                    if not isinstance(explanation, str) or len(explanation) > 4000:
                        raise ValueError("修改说明过长或格式无效。")
                    mission = job["agent"]
                    if mission["goal"] == "repair" and repair_achieved(job):
                        raise ValueError("修复目标已取得验证证据，请归纳结果，不再修改。")
                    if len(job["attempts"]) >= mission["max_attempts"]:
                        raise ValueError("已达到本轮 3 个候选上限，请根据证据说明未完成事项。")
                    validate_source(job["task_id"], candidate_source)
                    digest = hashlib.sha256(candidate_source.encode()).hexdigest()
                    if candidate_source == job["source"] or any(row["result"]["source_hash"] == digest for row in job["attempts"]):
                        raise ValueError("该源码已运行，请先读取反例并修改，不重复消耗仿真预算。")
                    validation = verify_candidate(job["task_id"], candidate_source, directory / f"model-patch-{tool_index}")
                    candidate = {"id": f"patch-{len(job['attempts'])+1}", "source": candidate_source, "explanation": explanation, **validation, "origin": "模型候选修改"}
                    candidate["comparison"] = compare_checks(job["result"], validation["result"])
                    with self.lock:
                        job["attempts"].append(candidate)
                        if not job["candidate"] or not job["candidate"]["verified"] or candidate["verified"]:
                            job["candidate"] = candidate
                        mission.update(attempt_count=len(job["attempts"]), latest_attempt=candidate["id"])
                        if mission["goal"] == "repair" and repair_achieved(job):
                            mission["status"] = "achieved"
                    output = {"attempt_id": candidate["id"], "comparison_to_baseline": candidate["comparison"], **self.compact(validation["result"]), "status": "passed" if validation["verified"] else "failed", "verified": validation["verified"], "public_tests_passed": validation["result"]["passed"], "challenge_kind": validation["challenge_kind"], "challenges": [{**self.compact(row), "seed": row["seed"], "testbench_hash": row["testbench_hash"]} for row in validation["challenges"]]}
                observe(job["agent"], name)
                event(key, f"工具返回 · {name}", "结果已加入模型上下文和运行记录。")
                return output
            except Exception as exc:
                detail = str(exc) if isinstance(exc, (ValueError, RuntimeError, TypeError)) else type(exc).__name__
                if config.get("key"):
                    detail = detail.replace(config["key"], "[已隐藏]")
                event(key, f"工具失败 · {name}", detail[:500] + "；不能据此声称通过。", "attention")
                raise
        if job["agent"]["goal"] == "repair" and repair_achieved(job):
            job["agent"]["status"] = "achieved"
        context = {"task": {key: value for key, value in public_task(TASKS[job["task_id"]]).items() if key != "starter"}, "student_source": job["source"], "student_question": job["question"] or "请根据证据解释问题，给我分层提示与理解检查。", "baseline": self.compact(job["result"]), "local_diagnosis": job["diagnosis"], "practice_catalog": self.quizzes(job["task_id"]), "mission": job["agent"]}
        try:
            model = run_agent(config, context, dispatch, event)
            with self.lock:
                job["model"] = model
            event("model-final", "模型教学解释已生成", f"{model['rounds']} 轮请求，{model['tool_calls']} 次模型工具调用。")
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else f"模型处理遇到 {type(exc).__name__}；本地仿真证据已保留。"
            # Stack locations help debug transports without logging credentials,
            # exception payloads, frame locals, prompts or response bodies.
            if not isinstance(exc, (ValueError, RuntimeError)):
                logging.getLogger("zhidian").error("Model loop failure (%s): %s", type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)))
            # A credential must never become part of a persisted error string.
            if config["key"]:
                message = message.replace(config["key"], "[已隐藏]")
            with self.lock:
                job["model_error"] = message
            event("model-error", "模型增强暂未完成", message, "attention")

    def get(self, run_id: str) -> dict:
        if len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise ValueError("无效的实验编号。")
        with self.lock:
            if run_id in self.jobs:
                job = copy.deepcopy(self.jobs[run_id])
            else:
                path = self.directory / "runs" / run_id / "run.json"
                if not path.is_file():
                    raise FileNotFoundError("未找到该实验记录。")
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["status"] == "running":
                    job.update(status="error", error="上次服务已中断；本次保留已取得的证据，请重新运行任务。")
                    if job.get("agent"):
                        job["agent"].update(status="interrupted", stop_reason=job["error"])
        results = [job.get("result"), job.get("smoke"), (job.get("candidate") or {}).get("result"), *(job.get("candidate") or {}).get("challenges", [])]
        for attempt in job.get("attempts", []):
            results.extend([attempt["result"], *attempt["challenges"]])
        directory = self.directory / "runs" / run_id
        for result in results:
            if result:
                wave = result.pop("wave_file", None)
                if wave:
                    result["wave_url"] = self.artifact_url(directory, wave)
                for artifact in result.get("files",[]):
                    filepath = artifact.pop("path",None)
                    if filepath:
                        artifact["url"] = self.artifact_url(directory, filepath)
        return job

    def hint(self, run_id: str, level: int) -> dict:
        job = self.get(run_id)
        if level not in {1, 2, 3}:
            raise ValueError("提示级别应为 1–3。")
        task = TASKS[job["task_id"]]
        if job["result"] and not job["result"]["compiled"]:
            hints = ["点击编译错误中的行号，检查这一行及前一行的括号、分号与类型。", "先保留原始 entity 与端口，逐项核对 GHDL 的第一条错误。后续错误可能由第一处引起。", "可载入独立验证的教学参考版本进行对照。语法通过后仍需重新运行功能测试。"]
        else:
            hints = task["hints"]
        return {"level": level, "text": hints[level-1]}

    def quizzes(self, task_id: str | None = None) -> list[dict]:
        return [{"id": key, **{k: v for k, v in quiz.items() if k not in {"answer", "explanation"}}} for key, quiz in QUIZZES.items() if task_id is None or quiz["task_id"] == task_id]

    def report(self, job: dict) -> str:
        task, result = TASKS[job["task_id"]], job["result"]
        lines = [f"# 知电实验报告：{task['title']}", "", f"- 实验编号：{job['id']}", f"- 时间：{job['created']}", f"- 模式：{'模型智能体' if job['mode']=='model' else '本地证据诊断'}", f"- 源码 SHA-256：`{result['source_hash']}`", f"- 教学参考版本：{'是' if job['reference_run'] else '否'}", "", "## 任务约束", "", *[f"- {line}" for line in task["requirements"]], "", "## 实际运行结果", "", self.describe(result), "", f"覆盖范围：{task['coverage']}", "", f"诊断：{job['diagnosis']['title']}", "", job["diagnosis"]["explanation"], "", "## 失败检查点（最多前 20 个）", "", "| 检查点 | 时间/ns | 输入 | 预期 | 实际 |", "| --- | --- | --- | --- | --- |"]
        for row in [row for row in result["checks"] if not row["passed"]][:20]:
            actual = "非 0/1 输出" if row.get("valid") is False else row["actual"]
            lines.append(f"| {row['index']} | {row['time_ns']} | {row['inputs']} | {row['expected']} | {actual} |")
        if result.get("protocol_version"):
            lines += ["", f"评分协议：v{result['protocol_version']}；检查清单要求 {result['expected_total']} 点；非二值采样 {result['invalid_count']} 点。"]
            if result.get("integrity_error"):
                lines += ["", "完整性检查：" + result["integrity_error"]]
        if job.get("agent"):
            mission = job["agent"]
            lines += ["", "## 智能体目标与行动", "", f"目标：{mission['title']}；状态：{mission['status']}。", "", mission["stop_reason"] or mission["acceptance"], "", f"计划调整 {mission['plan_revision']} 次："]
            if job.get("evaluation"):
                lines += ["", job["evaluation"]["note"]]
            lines += [f"- {step['purpose']}；工具 {step['tool']}；实际取证 {step['observations']} 次。" for step in mission["plan"]]
            if job.get("attempts"):
                lines += ["", "| 版本 | 公开检查通过 | 独立验证 | 源码 SHA-256 |", "| --- | --- | --- | --- |"]
                for attempt in job["attempts"]:
                    row = attempt["result"]
                    lines.append(f"| {attempt['id']} | {row['total']-row['failed']}/{row['total']} | {'通过' if attempt['verified'] else '未通过'} | {row['source_hash']} |")
                for attempt in job["attempts"]:
                    comparison = attempt.get("comparison", {})
                    if comparison:
                        lines += ["", f"{attempt['id']} 与原始代码的相同检查点对照：纠正 {comparison['corrected']} 点，新增不一致 {comparison['regressed']} 点。"]
                        for row in comparison["examples"]:
                            lines.append(f"- 检查点 {row['index']}，{row['time_ns']} ns，{row['inputs']}：原始 {row['before']} → 候选 {row['after']}；参考 {row['expected']}。")
            if mission.get("practice"):
                practice = mission["practice"]
                lines += ["", "### 理解检查", "", practice["reason"], "", practice["quiz"]["question"]]
                if practice.get("submission"):
                    lines += ["", "本次作答：" + ("正确" if practice["submission"]["correct"] else "建议复习"), "", practice["submission"]["feedback"]]
                else:
                    lines += ["", "尚未作答；不能据此推断已理解。"]
        if job.get("model"):
            model = job["model"]
            lines += ["", "## 模型教学解释", "", f"实际响应模型：{model['model']}；{model['rounds']} 轮请求，{model['tool_calls']} 次工具调用。", "", model["text"]]
            if model.get("requests"):
                lines += ["", "## 每轮模型与用量记录", "", "| 轮次 | 服务报告模型 | 请求编号 | 输入 / 输出 tokens | 服务报告费用 |", "| --- | --- | --- | --- | --- |"]
                for request in model["requests"]:
                    usage = request["usage"]
                    cost = usage["reported_cost"]
                    lines.append(f"| {request['round']} | {request['actual_model'] or '未报告'} | {request['response_id'] or '未报告'} | {usage['input_tokens'] if usage['input_tokens'] is not None else '未报告'} / {usage['output_tokens'] if usage['output_tokens'] is not None else '未报告'} | {cost if cost is not None else '未报告'} |")
                lines += ["", "费用单位由服务商定义；仅记录本次已返回请求的报告值。缺失值不是零，不代表账户总费用。"]
        if job.get("candidate"):
            candidate = job["candidate"]
            lines += ["", "## 候选修复验证", "", f"综合判定：{'通过' if candidate['verified'] else '尚未通过'}；原始源码未覆盖。", "", "公开测试：" + self.describe(candidate["result"])]
            for index, challenge in enumerate(candidate.get("challenges", []), 1):
                lines += ["", f"追加验证 {index}：{self.describe(challenge)}；种子 {challenge['seed']}；测试平台 SHA-256：`{challenge['testbench_hash']}`。"]
            if candidate.get("challenge_kind") == "exhaustive_reorder":
                lines += ["", "本题公开测试已穷举有限输入；追加验证重排输入顺序，不宣称出现新的真值表输入。"]
            lines += ["", "```vhdl", candidate["source"].rstrip(), "```"]
        if job.get("model_error"):
            lines += ["", "模型状态：" + job["model_error"]]
        lines += ["", "## 运行轨迹", "", *[f"- {event['title']}：{event['detail']}" for event in job["events"]], "", "## 被测源码", "", "```vhdl", job["source"].rstrip(), "```", "", "## 原始工具输出", "", "```text", result["log"].rstrip(), "```", "", "## 验证边界", "", "当前结果来自 GHDL 仿真与固定参考模型，不包含形式化证明、器件综合、布局布线、时序收敛或实际板级测试。波形图展示离散检查点，完整事件波形见同目录 VCD。答题记录与仿真通过分开保存，不将参考代码通过视作学生已掌握。", ""]
        return "\n".join(lines)
