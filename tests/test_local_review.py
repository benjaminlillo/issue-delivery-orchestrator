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

    def head(self):
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.worktree, text=True).strip()

    def write(self, report=None, **overrides):
        report_path = self.worktree / ".context" / "reviews" / "feature.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report if report is not None else f"SHA revisado: {self.head()}\n")
        payload = {
            "receiptVersion": 2, "status": "PASS", "reviewer": "review-pr",
            "mode": "orchestrated", "verifiedCommit": self.head(),
            "report": ".context/reviews/feature.md", "findings": [],
        }
        payload.update(overrides)
        self.path.write_text(json.dumps(payload))

    def test_accepts_a_review_pr_pass_for_current_head(self):
        self.write()
        receipt = validate_local_review(self.state, str(self.path))
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["validatedCommit"], receipt["verifiedCommit"])
        self.assertEqual(receipt["report"], ".context/reviews/feature.md")

    def test_rejects_stale_receipts_other_reviewers_and_reports_for_another_sha(self):
        self.write(verifiedCommit="stale")
        with self.assertRaisesRegex(RunBlocked, "targets"):
            validate_local_review(self.state, str(self.path))
        self.write(reviewer="codex-native-subagent")
        with self.assertRaisesRegex(RunBlocked, "review-pr skill"):
            validate_local_review(self.state, str(self.path))
        self.write(report="SHA revisado: 0000000\n")
        with self.assertRaisesRegex(RunBlocked, "reviewed SHA"):
            validate_local_review(self.state, str(self.path))
        self.write(report="")
        with self.assertRaisesRegex(RunBlocked, "missing or empty"):
            validate_local_review(self.state, str(self.path))

    def test_pass_cannot_keep_corregir_findings(self):
        self.write(findings=[{"id": "R1", "estado": "Corregir", "disposition": "SKIP"}])
        with self.assertRaisesRegex(RunBlocked, "Corregir"):
            validate_local_review(self.state, str(self.path))
        self.write(findings=[{"id": "S1", "estado": "Considerar", "disposition": "SKIP"}])
        self.assertEqual(validate_local_review(self.state, str(self.path))["status"], "PASS")

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
