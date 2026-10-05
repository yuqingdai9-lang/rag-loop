"""Offline synthetic loop scaffold. No agent calls, live RAG, or publication code.

Budget units count synthetic operations, not tokens or currency. A future live
adapter needs durable call reservations, independent verification, and approvals.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid


class LoopError(Exception):
    """A fail-closed loop condition."""


class LockBusy(LoopError):
    pass


class NotReady(LoopError):
    pass


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def checked_hash(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise LoopError("Expected a lowercase SHA-256 digest")
    return value


def checked_ids(values):
    if not isinstance(values, list) or not values:
        raise LoopError("Expected a nonempty question ID list")
    if any(not isinstance(x, str) or not x.strip() for x in values):
        raise LoopError("Question IDs must be nonempty strings")
    if len(set(values)) != len(values):
        raise LoopError("Duplicate expected question IDs")
    return sorted(values)


@contextmanager
def file_lock(path):
    """Nonblocking OS lock; crash releases it. Never unlink the lock inode."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+b", buffering=0) as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LockBusy("Another writer owns this run") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".state-", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def validate_results(expected_ids, rows):
    """Validate completeness before computing any synthetic score."""
    expected = checked_ids(expected_ids)
    if not isinstance(rows, list):
        raise LoopError("Evaluation results must be a list")
    scores = {}
    for row in rows:
        if not isinstance(row, dict):
            raise LoopError("Invalid evaluation row")
        question_id = row.get("id")
        if not isinstance(question_id, str) or question_id in scores:
            raise LoopError("Invalid or duplicate result ID")
        score = row.get("score")
        if row.get("status") != "ok" or row.get("error") is not None:
            raise LoopError("Evaluation error; result is invalid, not a zero score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise LoopError("Score must be a finite number")
        if not 0 <= score <= 1 or not math.isfinite(score):
            raise LoopError("Score must be finite and between zero and one")
        scores[question_id] = score
    if set(scores) != set(expected):
        raise LoopError("Evaluation ID set mismatch: missing or unexpected questions")
    return {question_id: scores[question_id] for question_id in expected}


class RunEngine:
    def __init__(self, output):
        self.output = Path(output)
        self.state_path = self.output / "state.json"
        self.lock_path = self.output / ".writer.lock"

    def _read(self):
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if state["schema"] != 1 or state["mode"] != "synthetic":
                raise ValueError("unsupported state")
            if digest(state["manifest"]) != state["manifest_digest"]:
                raise ValueError("manifest changed")
            if digest(state["contract"]) != state["contract_digest"]:
                raise ValueError("run contract changed")
            return state
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LoopError("Missing, invalid, or modified run state") from exc

    def snapshot(self):
        with file_lock(self.lock_path):
            return self._read()

    def create(self, manifest, expected_ids, targeted_ids, *, budget=8,
               max_repairs=3, mode="synthetic"):
        if mode != "synthetic":
            raise NotReady("Live agent, RAG, and approval adapters are not configured")
        if not isinstance(manifest, dict) or set(manifest) != {"code", "data", "index", "eval"}:
            raise LoopError("Manifest requires exactly code/data/index/eval hashes")
        manifest = {key: checked_hash(value) for key, value in manifest.items()}
        expected_ids, targeted_ids = checked_ids(expected_ids), checked_ids(targeted_ids)
        if not set(targeted_ids) <= set(expected_ids):
            raise LoopError("Targeted IDs must belong to the frozen evaluation set")
        if type(budget) is not int or budget < 0:
            raise LoopError("Budget must be a nonnegative integer")
        if type(max_repairs) is not int or not 1 <= max_repairs <= 3:
            raise LoopError("Repair limit must be between one and three")
        contract = dict(expected_ids=expected_ids, targeted_ids=targeted_ids,
                        budget_limit=budget, max_repairs=max_repairs)
        with file_lock(self.lock_path):
            if self.state_path.exists():
                state = self._read()
                if state["manifest"] != manifest or state["contract"] != contract:
                    raise LoopError("Existing run is frozen; use a new output directory")
                return state
            state = dict(schema=1, mode=mode, run_id=uuid.uuid4().hex,
                         manifest=manifest, manifest_digest=digest(manifest),
                         contract=contract, contract_digest=digest(contract),
                         status="BASELINE", candidate_hash=manifest["code"],
                         budget_used=0, repairs=0, evaluations={}, review=None,
                         approval_request=None, history=[])
            atomic_json(self.state_path, state)
            return state

    def _action(self, name, allowed, operation):
        with file_lock(self.lock_path):
            state = self._read()
            if state["status"] not in allowed:
                raise LoopError("Action is not allowed in state " + state["status"])
            previous = state["status"]
            try:
                if state["budget_used"] >= state["contract"]["budget_limit"]:
                    raise LoopError("budget_exhausted")
                if name == "repair" and state["repairs"] >= state["contract"]["max_repairs"]:
                    raise LoopError("repair_limit_exhausted")
                state["budget_used"] += 1
                operation(state)
            except LoopError as exc:
                state["status"] = "BLOCKED"
                state["blocked_at"] = previous
                state["reason"] = str(exc)
                state["approval_request"] = None
                state["history"].append(dict(action=name, outcome="BLOCKED", reason=str(exc)))
                atomic_json(self.state_path, state)
                raise
            state["history"].append(dict(action=name, outcome=state["status"]))
            atomic_json(self.state_path, state)
            return state

    def record_evaluation(self, phase, rows):
        if phase not in {"baseline", "targeted", "full"}:
            raise LoopError("Unknown evaluation phase")

        def apply(state):
            expected = state["contract"]["targeted_ids" if phase == "targeted" else "expected_ids"]
            scores = validate_results(expected, rows)
            state["evaluations"][phase] = dict(
                scores=scores, candidate_hash=state["candidate_hash"],
                manifest_digest=state["manifest_digest"], evidence_digest=digest(scores))
            if phase == "baseline":
                state["status"] = "REPAIR"
            elif phase == "targeted":
                state["status"] = "FULL" if all(x == 1 for x in scores.values()) else "REPAIR"
            else:
                baseline = state["evaluations"]["baseline"]["scores"]
                no_regressions = all(scores[key] >= baseline[key] for key in scores)
                targets_pass = all(scores[key] == 1 for key in state["contract"]["targeted_ids"])
                state["status"] = "REVIEW" if no_regressions and targets_pass else "REPAIR"

        return self._action(phase, {phase.upper()}, apply)

    def record_repair(self, candidate_hash):
        candidate_hash = checked_hash(candidate_hash)

        def apply(state):
            if candidate_hash == state["candidate_hash"]:
                raise LoopError("Repair must identify a new candidate")
            state["repairs"] += 1
            state["candidate_hash"] = candidate_hash
            state["evaluations"] = {"baseline": state["evaluations"]["baseline"]}
            state["review"] = None
            state["approval_request"] = None
            state["status"] = "TARGETED"

        return self._action("repair", {"REPAIR", "TARGETED", "FULL", "REVIEW", "WAIT_APPROVAL"}, apply)

    def record_review(self, report):
        def apply(state):
            if (not isinstance(report, dict) or report.get("status") != "ok"
                    or set(report) != {"status", "reviewer", "decision", "candidate_hash", "manifest_digest"}
                    or report.get("reviewer") != "synthetic-reviewer"
                    or report.get("candidate_hash") != state["candidate_hash"]
                    or report.get("manifest_digest") != state["manifest_digest"]
                    or report.get("decision") not in {"pass", "fail"}):
                raise LoopError("Invalid, stale, or non-synthetic review")
            state["review"] = dict(report)
            if report["decision"] == "fail":
                state["status"] = "REPAIR"
                return
            binding = dict(run_id=state["run_id"], manifest_digest=state["manifest_digest"],
                           candidate_hash=state["candidate_hash"],
                           full_evidence_digest=state["evaluations"]["full"]["evidence_digest"],
                           review_digest=digest(report))
            state["approval_request"] = dict(binding, request_id=digest(binding))
            state["status"] = "WAIT_APPROVAL"

        return self._action("review", {"REVIEW"}, apply)

    def approval_binding_matches(self, request):
        """Freshness check only. This NEVER authenticates a person or approves."""
        state = self.snapshot()
        return state["status"] == "WAIT_APPROVAL" and request == state["approval_request"]

    def accept_approval(self, evidence):
        raise NotReady("Approval authentication is not configured; no publication path exists")


def demo(output):
    """Resumable deterministic fixtures: one incorrect item, one repair."""
    engine = RunEngine(output)
    manifest = {key: digest("synthetic-" + key + "-v1") for key in ("code", "data", "index", "eval")}
    engine.create(manifest, ["Q001", "Q002", "Q003"], ["Q002"])
    while True:
        state = engine.snapshot()
        phase = state["status"]
        if phase in {"WAIT_APPROVAL", "BLOCKED"}:
            return state
        if phase == "REPAIR":
            engine.record_repair(digest("synthetic-candidate-v2"))
        elif phase in {"BASELINE", "TARGETED", "FULL"}:
            ids = state["contract"]["targeted_ids" if phase == "TARGETED" else "expected_ids"]
            rows = [dict(id=q, status="ok", score=0 if phase == "BASELINE" and q == "Q002" else 1) for q in ids]
            engine.record_evaluation(phase.lower(), rows)
        elif phase == "REVIEW":
            engine.record_review(dict(status="ok", reviewer="synthetic-reviewer", decision="pass",
                                      candidate_hash=state["candidate_hash"], manifest_digest=state["manifest_digest"]))
        else:
            raise LoopError("Unsupported demo state")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "status", "live"):
        command = commands.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "live":
            raise NotReady("Live adapters are not configured; only synthetic demo is available")
        state = demo(args.output) if args.command == "demo" else RunEngine(args.output).snapshot()
        print(json.dumps(dict(mode=state["mode"], run_id=state["run_id"], status=state["status"],
                              repairs=state["repairs"], budget_used=state["budget_used"],
                              approval_request=state["approval_request"]), sort_keys=True, indent=2))
        return 2 if state["status"] == "BLOCKED" else 0
    except LoopError as exc:
        print(json.dumps({"error": str(exc), "live_ready": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
