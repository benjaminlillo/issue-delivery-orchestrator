from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from issue_delivery_orchestrator.errors import OrchestrationError
from issue_delivery_orchestrator.evidence import (
    _evidence_target_path,
    _pr_body,
    _verification,
)


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


class EvidenceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.worktree = Path(self.temporary.name)
        git(self.worktree, "init", "-b", "test")
        git(self.worktree, "config", "user.email", "test@example.com")
        git(self.worktree, "config", "user.name", "Test")
        (self.worktree / "file.txt").write_text("content\n")
        git(self.worktree, "add", "file.txt")
        git(self.worktree, "commit", "-m", "initial")
        self.head = git(self.worktree, "rev-parse", "HEAD")
        self.state = {"runtimes": [{"runtimeId": "rt-1"}]}

    def tearDown(self):
        self.temporary.cleanup()

    def manifest(
        self,
        commit: str | None = None,
        *,
        provider: str | None = None,
    ):
        verification = {
            "status": "PASS",
            "verifiedCommit": commit or self.head,
            "runtimeId": "rt-1",
            "verifiedAt": "2026-07-27T12:00:00Z",
            "scenarioIds": ["REPAIR-1"],
        }
        if provider:
            verification["provider"] = provider
        return {
            "verification": {
                **verification,
            }
        }

    def test_accepts_pass_for_current_head_and_registered_runtime(self):
        receipt = _verification(self.manifest(), self.state, self.worktree)
        self.assertEqual(receipt["verifiedCommit"], self.head)
        self.assertNotIn("provider", receipt)

    def test_accepts_browser_pass_for_browser_run(self):
        self.state["mode"] = {"name": "codex"}
        self.state["reviewer"] = {"method": "codex-browser"}

        receipt = _verification(
            self.manifest(provider="codex-browser"),
            self.state,
            self.worktree,
        )

        self.assertEqual(receipt["provider"], "codex-browser")

    def test_rejects_evidence_from_a_different_reviewer(self):
        self.state["mode"] = {"name": "codex"}
        self.state["reviewer"] = {"method": "codex-browser"}

        with self.assertRaisesRegex(OrchestrationError, "provider mismatch"):
            _verification(
                self.manifest(provider="cua-driver"),
                self.state,
                self.worktree,
            )

    def test_rejects_stale_pass_after_code_changes(self):
        stale = self.head
        (self.worktree / "file.txt").write_text("changed\n")
        git(self.worktree, "add", "file.txt")
        git(self.worktree, "commit", "-m", "repair after verification")
        with self.assertRaisesRegex(OrchestrationError, "stale"):
            _verification(self.manifest(stale), self.state, self.worktree)

    def test_rejects_unregistered_runtime(self):
        manifest = self.manifest()
        manifest["verification"]["runtimeId"] = "rt-other"
        with self.assertRaisesRegex(OrchestrationError, "unregistered"):
            _verification(manifest, self.state, self.worktree)

    def test_pr_body_uses_github_path_instead_of_private_linear_url(self):
        body = _pr_body(
            "<!-- marker -->",
            [
                {
                    "storyId": "REPAIR-1",
                    "title": "Fixed state",
                    "caption": "Verified",
                    "url": "https://uploads.linear.app/private/image",
                    "githubUrl": "../blob/codex-ui-evidence/path/image.png?raw=true",
                }
            ],
        )
        self.assertIn("../blob/codex-ui-evidence/path/image.png?raw=true", body)
        self.assertNotIn("uploads.linear.app", body)

    def test_pr_body_names_browser_provider(self):
        body = _pr_body(
            "<!-- marker -->",
            [
                {
                    "storyId": "US-1",
                    "title": "Browser state",
                    "caption": "Verified",
                    "githubUrl": "../blob/codex-ui-evidence/path/image.png?raw=true",
                }
            ],
            provider="codex-browser",
        )

        self.assertIn("Browser integrado de Codex", body)

    def test_evidence_target_is_content_addressed(self):
        screenshot = {
            "storyId": "REPAIR 1",
            "path": self.worktree / "file.txt",
        }
        state = {"issue": {"identifier": "SFW-1"}, "runId": "run-1"}
        target = _evidence_target_path(state, screenshot, 1)
        self.assertRegex(
            target,
            r"^\.issue-delivery-evidence/SFW-1/run-1/01-REPAIR-1-[a-f0-9]{12}\.png$",
        )


if __name__ == "__main__":
    unittest.main()
