"""Local SQLite learning records. Code runs and quiz performance stay separate."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3

from .catalog import TASKS


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "learning.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, created TEXT NOT NULL, task_id TEXT NOT NULL,
                  mode TEXT NOT NULL, status TEXT NOT NULL, total INTEGER NOT NULL,
                  failed INTEGER NOT NULL, concept TEXT NOT NULL, reference_run INTEGER NOT NULL,
                  summary TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quizzes (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL,
                  quiz_id TEXT NOT NULL, task_id TEXT NOT NULL, concept TEXT NOT NULL,
                  choice INTEGER NOT NULL, correct INTEGER NOT NULL
                );
            """)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def save_run(self, run: dict) -> None:
        result = run["result"]
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)", (
                run["id"], run["created"], run["task_id"], run["mode"], result["status"],
                result["total"], result["failed"], TASKS[run["task_id"]]["concept"],
                int(run.get("reference_run", False)), json.dumps({"title": run["diagnosis"]["title"], "duration_ms": run.get("duration_ms", 0)}, ensure_ascii=False),
            ))

    def history(self, limit: int = 30) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY created DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), "summary": json.loads(row["summary"]), "task_title": TASKS[row["task_id"]]["title"]} for row in rows]

    def save_quiz(self, quiz_id: str, quiz: dict, choice: int) -> dict:
        correct = choice == quiz["answer"]
        with self.connect() as db:
            db.execute("INSERT INTO quizzes (created,quiz_id,task_id,concept,choice,correct) VALUES (?,?,?,?,?,?)", (now(), quiz_id, quiz["task_id"], quiz["concept"], choice, int(correct)))
        return {"correct": correct, "answer": quiz["answer"], "explanation": quiz["explanation"]}

    def profile(self) -> dict:
        with self.connect() as db:
            run_count = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            student_passed = db.execute("SELECT COUNT(*) FROM runs WHERE status='passed' AND reference_run=0").fetchone()[0]
            quiz_count, quiz_correct = db.execute("SELECT COUNT(*), COALESCE(SUM(correct),0) FROM quizzes").fetchone()
            concepts = []
            for task in TASKS.values():
                runs = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN status='passed' AND reference_run=0 THEN 1 ELSE 0 END),0) AS passed FROM runs WHERE task_id=?", (task["id"],)).fetchone()
                quizzes = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(correct),0) AS correct FROM quizzes WHERE task_id=?", (task["id"],)).fetchone()
                latest = db.execute("SELECT correct FROM quizzes WHERE task_id=? ORDER BY id DESC LIMIT 1", (task["id"],)).fetchone()
                state = "待探索" if not runs["n"] and not quizzes["n"] else "建议复习" if latest and not latest["correct"] else "已练习" if quizzes["correct"] else "待检验理解"
                concepts.append({"task_id": task["id"], "name": task["concept_name"], "runs": runs["n"], "passed_runs": runs["passed"], "quiz_count": quizzes["n"], "quiz_correct": quizzes["correct"], "state": state})
        return {"run_count": run_count, "passed_runs": student_passed, "quiz_count": quiz_count, "quiz_correct": quiz_correct, "concepts": concepts, "note": "仿真通过记录代码表现；答题记录当前练习表现。二者均不等同于已掌握知识。"}
