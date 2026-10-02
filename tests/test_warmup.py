import json
import tempfile
import unittest
from pathlib import Path

from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.state import create_state, run_root
from issue_delivery_orchestrator.warmup import validate_warmup


class WarmupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.worktree = Path(self.tmp.name)
        self.state = create_state(
            worktree=self.worktree, run_id="run-1", issue={"identifier": "TS-1", "title": "Title"},
            branch="feature", base="development", created_from="origin/development",
            adopted_head="abc", identities={},
        )
        self.path = run_root(self.worktree, "run-1") / "validation" / "warmup.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.urls = {"shops-app": "http://127.0.0.1:4200"}

    def write(self, **overrides):
        receipt = {
            "receiptVersion": 1, "verifiedCommit": "sha", "runtimeId": "runtime-1",
            "pages": [
                {"service": "shops-app", "path": "/workers/7", "status": "WARMED", "httpStatus": 200, "durationMs": 8200},
                {"service": "shops-app", "path": "/menu", "status": "FAILED", "httpStatus": 500, "error": "HTTP 500"},
            ],
            "logins": [{"service": "shops-app", "status": "PASS"}],
        }
        receipt.update(overrides)
        self.path.write_text(json.dumps(receipt))

    def validate(self, raw_path=None):
        return validate_warmup(
            self.state, raw_path if raw_path is not None else str(self.path),
            urls=self.urls, runtime_id="runtime-1", commit="sha",
        )

    def test_reports_warmed_and_failed_pages_without_blocking(self):
        self.write()
        warmup = self.validate()
        self.assertEqual((warmup["warmed"], warmup["failed"]), (1, 1))
        self.assertEqual(warmup["pages"][0]["url"], "http://127.0.0.1:4200/workers/7")
        self.assertEqual(warmup["pages"][1]["error"], "HTTP 500")

    def test_requires_receipt_for_the_final_commit_and_runtime(self):
        with self.assertRaisesRegex(RunBlocked, "requires 'warmup'"):
            self.validate("")
        self.write(verifiedCommit="old")
        with self.assertRaisesRegex(RunBlocked, "handoff commit"):
            self.validate()
        self.write(runtimeId="previous-runtime")
        with self.assertRaisesRegex(RunBlocked, "final runtime"):
            self.validate()
        with self.assertRaisesRegex(RunBlocked, "inside the run directory"):
            self.validate(str(self.worktree / "warmup.json"))

    def test_rejects_unknown_services_and_unexplained_failures(self):
        self.write(pages=[{"service": "other-app", "path": "/", "status": "WARMED"}])
        with self.assertRaisesRegex(RunBlocked, "unknown runtime service"):
            self.validate()
        self.write(pages=[{"service": "shops-app", "path": "/menu", "status": "FAILED"}])
        with self.assertRaisesRegex(RunBlocked, "requires 'error'"):
            self.validate()

    def test_failed_or_missing_login_blocks_the_handoff(self):
        self.write(logins=[{"service": "shops-app", "status": "FAILED", "error": "auth_context_unavailable"}])
        with self.assertRaisesRegex(RunBlocked, "Login failed.*auth_context_unavailable"):
            self.validate()
        self.write(logins=[])
        with self.assertRaisesRegex(RunBlocked, "login result for: shops-app"):
            self.validate()

    def test_empty_warmup_requires_a_reason(self):
        self.write(pages=[])
        with self.assertRaisesRegex(RunBlocked, "skipReason"):
            self.validate()
        self.write(pages=[], skipReason="Backend-only change without UI pages")
        self.assertEqual(self.validate()["skipReason"], "Backend-only change without UI pages")


if __name__ == "__main__":
    unittest.main()
