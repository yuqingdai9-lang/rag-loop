"""Deterministic, offline state-machine tests; no model or RAG calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from loop_core import (LoopError, NotReady, RunEngine, atomic_json,
                       demo, digest, file_lock, validate_results)


def rows(ids=("Q001", "Q002"), score=1):
    return [dict(id=q, status="ok", score=score) for q in ids]


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)
        self.engine = RunEngine(self.output)
        self.manifest = {key: digest(key) for key in ("code", "data", "index", "eval")}

    def create(self, budget=8, max_repairs=3):
        return self.engine.create(self.manifest, ["Q001", "Q002"], ["Q002"],
                                  budget=budget, max_repairs=max_repairs)

    def reach_review(self):
        self.create()
        self.engine.record_evaluation("baseline", rows(score=0))
        self.engine.record_repair(digest("candidate-1"))
        self.engine.record_evaluation("targeted", rows(["Q002"]))
        return self.engine.record_evaluation("full", rows())

    def review(self, state):
        return self.engine.record_review(dict(status="ok", decision="pass", reviewer="synthetic-reviewer",
                                             candidate_hash=state["candidate_hash"],
                                             manifest_digest=state["manifest_digest"]))

    def test_missing_duplicate_unexpected_and_empty_results_fail(self):
        for bad in ([], rows(["Q001"]), rows(["Q001", "Q001"]), rows(["Q001", "Q099"])):
            with self.subTest(bad=bad), self.assertRaises(LoopError):
                validate_results(["Q001", "Q002"], bad)

    def test_nonfinite_errors_and_invalid_scores_fail(self):
        for score in (float("nan"), float("inf"), -1, 2, 10**400, True, "1"):
            with self.subTest(score=score), self.assertRaises(LoopError):
                validate_results(["Q001"], rows(["Q001"], score=score))
        for row in (dict(id="Q001", score=0, status="timeout"),
                    dict(id="Q001", score=1, status="ok", error="parser failed")):
            with self.assertRaises(LoopError):
                validate_results(["Q001"], [row])

    def test_invalid_evaluation_blocks_and_records_cost(self):
        self.create()
        with self.assertRaises(LoopError):
            self.engine.record_evaluation("baseline", rows(["Q001"]))
        state = self.engine.snapshot()
        self.assertEqual(state["status"], "BLOCKED")
        self.assertEqual(state["budget_used"], 1)
        self.assertEqual(state["evaluations"], {})

    def test_budget_exhaustion_is_durable(self):
        self.create(budget=1)
        self.engine.record_evaluation("baseline", rows(score=0))
        with self.assertRaisesRegex(LoopError, "budget_exhausted"):
            self.engine.record_repair(digest("next"))
        restarted = RunEngine(self.output).snapshot()
        self.assertEqual(restarted["status"], "BLOCKED")
        self.assertEqual(restarted["budget_used"], 1)
        self.assertEqual(restarted["repairs"], 0)

    def test_repair_limit_maximum_three(self):
        self.create(budget=20)
        self.engine.record_evaluation("baseline", rows(score=0))
        for iteration in range(3):
            self.engine.record_repair(digest(iteration))
            self.engine.record_evaluation("targeted", rows(["Q002"], score=0))
        with self.assertRaisesRegex(LoopError, "repair_limit_exhausted"):
            self.engine.record_repair(digest("fourth"))
        self.assertEqual(self.engine.snapshot()["repairs"], 3)

    def test_resume_does_not_repeat_budget_or_change_run(self):
        first = demo(self.output)
        second = demo(self.output)
        self.assertEqual(first, second)
        self.assertEqual(second["status"], "WAIT_APPROVAL")
        self.assertEqual(second["budget_used"], 5)
        self.assertEqual(second["repairs"], 1)

    def test_restart_mid_run_continues_without_duplicate_baseline(self):
        self.create()
        self.engine.record_evaluation("baseline", rows(score=0))
        restarted = RunEngine(self.output)
        state = restarted.create(self.manifest, ["Q001", "Q002"], ["Q002"])
        self.assertEqual(state["status"], "REPAIR")
        self.assertEqual(state["budget_used"], 1)
        with self.assertRaises(LoopError):
            restarted.record_evaluation("baseline", rows())
        self.assertEqual(restarted.snapshot()["budget_used"], 1)

    def test_new_candidate_invalidates_review_and_approval_binding(self):
        state = self.review(self.reach_review())
        old_request = state["approval_request"]
        self.assertTrue(self.engine.approval_binding_matches(old_request))
        state = self.engine.record_repair(digest("candidate-2"))
        self.assertEqual(state["status"], "TARGETED")
        self.assertIsNone(state["approval_request"])
        self.assertIsNone(state["review"])
        self.assertEqual(set(state["evaluations"]), {"baseline"})
        self.assertFalse(self.engine.approval_binding_matches(old_request))

    def test_stale_review_blocks(self):
        state = self.reach_review()
        with self.assertRaises(LoopError):
            self.engine.record_review(dict(status="ok", decision="pass", reviewer="synthetic-reviewer",
                                           candidate_hash=digest("wrong"), manifest_digest=state["manifest_digest"]))
        self.assertEqual(self.engine.snapshot()["status"], "BLOCKED")

    def test_live_and_string_approval_fail_closed(self):
        with self.assertRaises(NotReady):
            self.engine.create(self.manifest, ["Q001"], ["Q001"], mode="live")
        before = demo(self.output)
        with self.assertRaises(NotReady):
            self.engine.accept_approval("approved")
        self.assertEqual(self.engine.snapshot(), before)

    def test_frozen_manifest_and_contract(self):
        self.create()
        modified = dict(self.manifest, data=digest("changed"))
        with self.assertRaises(LoopError):
            self.engine.create(modified, ["Q001", "Q002"], ["Q002"])
        with self.assertRaises(LoopError):
            self.engine.create(self.manifest, ["Q001", "Q002"], ["Q002"], budget=100)
        state = self.engine.snapshot()
        state["manifest"]["index"] = digest("changed-index")
        atomic_json(self.engine.state_path, state)
        with self.assertRaises(LoopError):
            self.engine.snapshot()

    def test_lock_excludes_another_process(self):
        script = "from pathlib import Path; from loop_core import file_lock; import sys\nwith file_lock(Path(sys.argv[1])): pass"
        with file_lock(self.engine.lock_path):
            process = subprocess.run([sys.executable, "-B", "-c", script, str(self.engine.lock_path)],
                                     cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("LockBusy", process.stderr)
        with file_lock(self.engine.lock_path):
            pass

    def test_atomic_write_failure_preserves_previous_state(self):
        self.create()
        before = self.engine.state_path.read_bytes()
        with self.assertRaises(ValueError):
            atomic_json(self.engine.state_path, {"invalid": float("nan")})
        self.assertEqual(self.engine.state_path.read_bytes(), before)
        self.assertEqual(list(self.output.glob(".state-*.tmp")), [])

    def test_full_regression_returns_to_repair(self):
        self.create()
        self.engine.record_evaluation("baseline", rows())
        self.engine.record_repair(digest("new"))
        self.engine.record_evaluation("targeted", rows(["Q002"]))
        measured = [dict(id="Q001", status="ok", score=0), dict(id="Q002", status="ok", score=1)]
        state = self.engine.record_evaluation("full", measured)
        self.assertEqual(state["status"], "REPAIR")
        self.assertIsNone(state["approval_request"])

    def test_cli_demo_is_restartable(self):
        command = [sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "loop_core.py"),
                   "demo", "--output", str(self.output)]
        first = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
        second = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
        self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))
        self.assertEqual(json.loads(first.stdout)["status"], "WAIT_APPROVAL")


if __name__ == "__main__":
    unittest.main()
