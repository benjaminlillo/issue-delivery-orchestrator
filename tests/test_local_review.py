import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.local_review import validate_local_review
from issue_delivery_orchestrator.state import PHASES, create_state, run_root


class LocalReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.worktree = Path(self.tmp.name) / "worktree"
        self.worktree.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.worktree, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.worktree, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.worktree, check=True)
        (self.worktree / "file.txt").write_text("content")
        subprocess.run(["git", "add", "."], cwd=self.worktree, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=self.worktree, check=True)
        self.state = create_state(
            worktree=self.worktree, run_id="run-1",
            issue={"identifier": "TS-1", "title": "Title"}, branch="feature",
            base="development", created_from="origin/development", adopted_head="abc",
            identities={},
        )
        self.path = run_root(self.worktree, "run-1") / "validation" / "local-review.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.tmp.cleanup)

    def write(self, **overrides):
        payload = {
            "receiptVersion": 1, "status": "PASS", "reviewer": "codex-native-subagent",
            "verifiedCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.worktree, text=True).strip(),
            "findings": [], "checked": ["AGENTS.md", "diff"],
        }
        payload.update(overrides)
        self.path.write_text(json.dumps(payload))

    def test_accepts_pass_for_current_head(self):
        self.write()
        receipt = validate_local_review(self.state, str(self.path))
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["validatedCommit"], receipt["verifiedCommit"])

    def test_rejects_stale_or_wrong_reviewer(self):
        self.write(verifiedCommit="stale")
        with self.assertRaisesRegex(RunBlocked, "targets"):
            validate_local_review(self.state, str(self.path))
        self.write(reviewer="codex-exec")
        with self.assertRaisesRegex(RunBlocked, "codex-native-subagent"):
            validate_local_review(self.state, str(self.path))

    def test_rejects_non_pass_checkpoint_and_outside_artifact(self):
        self.write(status="FIX")
        self.assertEqual(validate_local_review(self.state, str(self.path))["status"], "FIX")
        with self.assertRaisesRegex(RunBlocked, "inside the run"):
            validate_local_review(self.state, str(self.worktree / "outside.json"))

    def test_new_runs_include_local_review_but_legacy_runs_do_not(self):
        self.assertIn("local-review", PHASES)
        legacy = dict(self.state)
        legacy.pop("phaseSequence")
        self.assertNotIn("local-review", tuple(__import__("issue_delivery_orchestrator.state", fromlist=["phases_for_state"]).phases_for_state(legacy)))
