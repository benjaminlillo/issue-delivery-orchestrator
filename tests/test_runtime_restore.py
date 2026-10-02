import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.runtime_restore import restore_runtime
from issue_delivery_orchestrator.state import create_state, run_root


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class RuntimeRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.worktree = Path(self.tmp.name)
        git(self.worktree, "init", "-q")
        git(self.worktree, "config", "user.email", "test@example.com")
        git(self.worktree, "config", "user.name", "Test")
        (self.worktree / ".gitignore").write_text(".local-runtime/\n")
        git(self.worktree, "add", ".")
        git(self.worktree, "commit", "-qm", "initial")
        self.state = create_state(
            worktree=self.worktree, run_id="run-1", issue={"identifier": "TS-1", "title": "T"},
            branch="feature", base="development", created_from="origin/development",
            adopted_head="abc", identities={},
        )
        self.state.update({
            "status": "awaiting_manual_review",
            "activeRuntimeId": "rt-1",
            "finalRuntimeHandoff": {
                "status": "ready", "runtimeId": "rt-1", "verifiedCommit": git(self.worktree, "rev-parse", "HEAD"),
                "services": [{"name": "backend"}, {"name": "shops-app"}],
            },
        })
        binding = self.worktree / ".local-runtime" / "worktree.json"
        binding.parent.mkdir(parents=True, exist_ok=True)
        binding.write_text(json.dumps({"runtimeId": "rt-1"}))
        self.settings = SimpleNamespace(
            runtime_root=".local-runtime",
            runtime_init_command=("echo", "init"),
            runtime_services_command=("echo", "ensure", "{services}"),
            runtime_cloud_services_command=("echo", "cloud"),
        )

    def restore(self, environment=None):
        with patch("issue_delivery_orchestrator.runtime_restore.settings", return_value=self.settings), \
                patch.dict(os.environ, environment or {"CONDUCTOR_IS_LOCAL": "0"}):
            return restore_runtime(self.state)

    def test_restarts_infrastructure_and_the_same_services_then_returns_to_handoff(self):
        result = self.restore()
        self.assertEqual(result["services"], ["backend", "shops-app"])
        self.assertEqual(self.state["status"], "preparing_final_runtime")
        log = (run_root(self.worktree, "run-1") / "logs" / "runtime-restore.log").read_text()
        self.assertIn("$ echo cloud", log)
        self.assertIn("$ echo ensure backend shops-app", log)

    def test_local_workspaces_skip_cloud_infrastructure(self):
        self.restore({"CONDUCTOR_IS_LOCAL": "1"})
        log = (run_root(self.worktree, "run-1") / "logs" / "runtime-restore.log").read_text()
        self.assertNotIn("echo cloud", log)

    def test_refuses_changed_code_or_a_different_runtime(self):
        (self.worktree / "change.txt").write_text("x")
        with self.assertRaisesRegex(RunBlocked, "Code changed"):
            self.restore()
        (self.worktree / "change.txt").unlink()
        (self.worktree / ".local-runtime" / "worktree.json").write_text(json.dumps({"runtimeId": "rt-2"}))
        with self.assertRaisesRegex(RunBlocked, "different runtime"):
            self.restore()

    def test_failed_command_blocks_and_keeps_the_previous_status(self):
        self.settings.runtime_services_command = ("false",)
        with self.assertRaisesRegex(RunBlocked, "Runtime restore failed at `false`"):
            self.restore()
        self.assertEqual(self.state["status"], "awaiting_manual_review")

    def test_only_a_handed_off_runtime_can_be_restored(self):
        self.state["status"] = "active"
        with self.assertRaisesRegex(RunBlocked, "Only a handed-off runtime"):
            self.restore()


if __name__ == "__main__":
    unittest.main()
