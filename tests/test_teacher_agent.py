import json
from pathlib import Path
import tempfile
import unittest

from tools.evaluate_teacher_agent import run_case
from zhidian.catalog import QUIZZES
from zhidian.mission import finish_mission, new_mission, observe, repair_achieved, update_plan
from zhidian.provider import run_agent
from zhidian.service import Service
from zhidian.simulator import find_ghdl
from zhidian.verification import compare_checks


class MissionTests(unittest.TestCase):
    def test_comparison_matches_stimulus_and_shows_both_improvements_and_regressions(self):
        a = {"index": 1, "time_ns": 6, "case": "reset", "inputs": "reset=1", "expected": 0, "actual": 4, "passed": False}
        b = {**a, "index": 2, "time_ns": 16, "actual": 0, "passed": True}
        result = compare_checks({"checks": [a, b]}, {"checks": [{**a, "actual": 0, "passed": True}, {**b, "actual": 2, "passed": False}, {**a, "inputs": "different", "actual": 0, "passed": True}]})
        self.assertEqual((result["comparable_checks"], result["corrected"], result["regressed"]), (2, 1, 1))
        self.assertEqual(result["examples"][0]["before"], 4)

    def test_plan_cannot_award_itself_repair_success(self):
        mission = new_mission("repair")
        update_plan(mission, [{"tool": "propose_patch", "purpose": "声称已修好"}, {"tool": "inspect_attempt", "purpose": "检查证据"}])
        observe(mission, "propose_patch")
        job = {"agent": mission, "result": {"passed": False}, "candidate": {"verified": False}, "model_error": None}
        finish_mission(job)
        self.assertEqual(mission["status"], "budget_exhausted")
        self.assertFalse(repair_achieved(job))

    def test_public_only_candidate_or_smoke_pass_cannot_meet_goal(self):
        for job in [{"result": {"passed": True, "suite": "smoke"}}, {"candidate": {"result": {"passed": True}, "verified": False}}]:
            self.assertFalse(repair_achieved(job))
        self.assertTrue(repair_achieved({"result": {"passed": True, "suite": "full"}}))
        self.assertTrue(repair_achieved({"candidate": {"verified": True}}))

    def test_invalid_plan_does_not_partially_replace_an_existing_plan(self):
        mission = new_mission("coach")
        original = json.dumps(mission)
        with self.assertRaises(ValueError):
            update_plan(mission, [{"tool": "read_waveform", "purpose": "读取"}, {"tool": "shell", "purpose": "执行"}])
        self.assertEqual(json.dumps(mission), original)

    def test_replan_preserves_past_observations_and_copies_input(self):
        mission = new_mission("repair")
        observe(mission, "read_waveform")
        steps = [{"tool": "inspect_attempt", "purpose": "读取失败版本"}, {"tool": "propose_patch", "purpose": "再次验证"}]
        update_plan(mission, steps)
        steps[0]["purpose"] = "external mutation"
        observe(mission, "propose_patch")
        self.assertEqual(mission["plan_history"][0]["steps"][1]["observations"], 1)
        self.assertEqual(mission["plan"][0]["purpose"], "读取失败版本")
        self.assertEqual(mission["plan"][1]["observations"], 1)

    def test_bad_goal_has_a_clear_validation_error(self):
        for goal in (None, [], {}, "shell"):
            with self.assertRaises(ValueError):
                new_mission(goal)

    def test_premature_text_uses_bounded_requests_and_never_sets_success(self):
        mission = new_mission("repair")
        count = 0
        def transport(*args):
            nonlocal count
            count += 1
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "没有证据却宣称通过。"}]}]}
        result = run_agent({"model": "offline"}, {"mission": mission}, lambda *args: self.fail("No tool requested"), lambda *args: None, request_fn=transport)
        self.assertEqual(count, 7)
        self.assertEqual(result["tool_calls"], 0)
        finish_mission({"agent": mission})
        self.assertEqual(mission["status"], "budget_exhausted")


class TeachingMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = Service(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_recent_wrong_answer_is_prioritized_without_answer_key(self):
        self.service.store.save_quiz("counter_priority", QUIZZES["counter_priority"], 0)
        job = {"task_id": "counter", "agent": new_mission("coach")}
        result = self.service.recommend_practice(job, {"quiz_id": None, "reason": "复习控制冲突"})
        self.assertEqual(result["quiz"]["id"], "counter_priority")
        self.assertNotIn("answer", result["quiz"])
        self.assertNotIn("explanation", result["quiz"])
        self.assertIsNone(result["submission"])

    def test_solved_question_yields_to_an_unanswered_variant(self):
        self.service.store.save_quiz("counter_priority", QUIZZES["counter_priority"], 0)
        self.service.store.save_quiz("counter_priority", QUIZZES["counter_priority"], 1)
        result = self.service.recommend_practice({"task_id": "counter", "agent": new_mission("coach")}, {"quiz_id": None, "reason": "用未做的变式检查迁移"})
        self.assertNotEqual(result["quiz"]["id"], "counter_priority")

    def test_memory_and_practice_stay_within_current_task(self):
        other = next((key, value) for key, value in QUIZZES.items() if value["task_id"] == "majority")
        self.service.store.save_quiz(other[0], other[1], 0)
        self.assertEqual(self.service.store.task_memory("counter")["recent_quizzes"], [])
        with self.assertRaises(ValueError):
            self.service.recommend_practice({"task_id": "counter", "agent": new_mission("coach")}, {"quiz_id": other[0], "reason": "跨题推荐应被拒绝"})

    def test_unknown_attempt_cannot_select_a_path(self):
        with self.assertRaises(ValueError):
            self.service.attempt({"attempts": []}, "../../.env")

    def test_invalid_recommendation_returns_legal_ids_without_answer_key(self):
        with self.assertRaises(ValueError) as error:
            self.service.recommend_practice({"task_id": "counter", "agent": new_mission("coach")}, {"quiz_id": "invented-quiz", "reason": "检验错误恢复"})
        self.assertIn("counter_priority", str(error.exception))
        self.assertIn("null", str(error.exception))
        self.assertNotIn(QUIZZES["counter_priority"]["explanation"], str(error.exception))

    def test_unassigned_practice_cannot_record_a_submission(self):
        run_id = "a"*32
        self.service.jobs[run_id] = {"id": run_id, "agent": new_mission("coach"), "task_id": "counter", "attempts": []}
        with self.assertRaises(ValueError):
            self.service.answer_practice(run_id, "counter_priority", 1)
        self.assertEqual(self.service.store.profile()["quiz_count"], 0)


@unittest.skipUnless(find_ghdl(), "Real GHDL required")
class TeacherAgentIntegrationTests(unittest.TestCase):
    def test_failed_candidate_feedback_then_second_candidate_really_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run_case("failed_then_fixed", Path(folder)/"case")
            self.assertEqual(result["mission_status"], "achieved")
            self.assertEqual(result["attempts"][1]["challenge_checks"], [247, 247])

    def test_actual_wrong_submission_is_recorded_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            result = run_case("wrong_answer_review", Path(folder)/"case")
            self.assertEqual(result["mission_status"], "practice_checked")
            self.assertTrue(result["practice_checked"])
