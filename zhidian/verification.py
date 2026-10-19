"""Verify a proposed patch on public tests and two fresh reproducible challenges."""
from pathlib import Path
import secrets

from .simulator import simulate

EXHAUSTIVE_TASKS = {"majority", "lut", "file_rom"}


def verify_candidate(task_id: str, source: str, folder: Path, *, seeds=None) -> dict:
    result = simulate(task_id, source, "full", folder / "public")
    challenges = []
    if result["passed"]:
        # Generated after receiving the candidate, never chosen by the model.
        seeds = list(seeds) if seeds is not None else [secrets.randbits(32), secrets.randbits(32)]
        if len(seeds) != 2 or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds):
            raise ValueError("候选验证需要两组有效的 32 位随机种子。")
        for index, seed in enumerate(seeds):
            challenges.append(simulate(task_id, source, "challenge", folder / f"challenge-{index+1}", seed=seed))
    verified = result["passed"] and len(challenges) == 2 and all(row["passed"] for row in challenges)
    return {"result": result, "challenges": challenges, "verified": verified, "challenge_kind": "exhaustive_reorder" if task_id in EXHAUSTIVE_TASKS else "fresh_random_sequences"}
