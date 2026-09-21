import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.runtime import register_owned_process, stop_owned_processes
from issue_delivery_orchestrator.runtime_handoff import prepare_runtime_handoff
from issue_delivery_orchestrator.runtime_reset import reset_final_runtime
from issue_delivery_orchestrator.state import PHASES, complete_phase, create_state


class RuntimeProcessTests(unittest.TestCase):
    def test_stops_only_registered_process(self):
        with tempfile.TemporaryDirectory() as raw:
            worktree = Path(raw) / "worktree"
            worktree.mkdir()
            state = create_state(
                worktree=worktree,
                run_id="run-process",
                issue={"id": "id", "identifier": "TS-2", "title": "Title"},
                branch="benjamin/ts-2",
                base="development",
                created_from="origin/development",
                adopted_head="abc",
                identities={
                    "linear": "benjalillo@turboshop.cl",
                    "github": "benjaminlillo",
                },
            )
            process = subprocess.Popen(["sleep", "30"])
            try:
                register_owned_process(
                    state,
                    process.pid,
                    kind="test",
                    command="sleep 30",
                )
                stopped = stop_owned_processes(state, timeout_seconds=0.1)
                process.wait(timeout=2)
            finally:
                if process.poll() is None:
                    process.kill()
            self.assertIn(process.pid, stopped)
            self.assertIsNotNone(state["ownedProcesses"][0]["endedAt"])

    def test_prepares_fresh_manual_handoff_without_stopping_new_processes(self):
        with tempfile.TemporaryDirectory() as raw:
            worktree = Path(raw) / "worktree"
            worktree.mkdir()
            self._initialize_git_worktree(worktree)
            state = self._manual_state(worktree)
            for phase in PHASES[: PHASES.index("manual-revision")]:
                complete_phase(state, phase)
            manifest = worktree / ".local-runtime" / "runtime.json"
            registry = worktree / ".local-runtime" / "pids.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(
                json.dumps(
                    {
                        "urls": {"web": "http://127.0.0.1:43123"},
                        "processRegistryPath": str(registry),
                    }
                )
            )
            registry.write_text(
                json.dumps(
                    {
                        "processes": [
                            {"pid": os.getpid(), "app": "web", "command": "pnpm web"}
                        ]
                    }
                )
            )
            state["runtimes"] = [
                {
                    "runtimeId": "runtime-1",
                    "manifestPath": str(manifest),
                    "cleanedAt": None,
                }
            ]
            state["activeRuntimeId"] = "runtime-1"
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            state["status"] = "preparing_final_runtime"
            state["finalRuntimeReset"] = {
                "runtimeId": "runtime-1",
                "verifiedCommit": head,
            }
            input_path = (
                worktree
                / ".local-runtime"
                / "issue-delivery-orchestrator"
                / "run-manual"
                / "validation"
                / "services.json"
            )
            input_path.parent.mkdir(parents=True, exist_ok=True)
            input_path.write_text(json.dumps({"services": [{"name": "web"}]}))

            with patch(
                "issue_delivery_orchestrator.runtime_handoff._health_status", return_value=200
            ):
                result = prepare_runtime_handoff(state, input_path)

            receipt = result["receipt"]
            self.assertEqual(receipt["tokenUsage"], state["tokenUsage"])
            persisted = json.loads(Path(result["receiptPath"]).read_text())
            self.assertEqual(persisted["tokenUsage"], state["tokenUsage"])
            self.assertEqual(state["status"], "awaiting_manual_review")
            self.assertEqual(state["currentPhase"], "manual-revision")
            self.assertTrue(result["processesPreserved"])
            self.assertNotIn("processesStoppedAt", state)
            self.assertEqual(receipt["services"][0]["port"], 43123)
            self.assertEqual(receipt["processes"][0]["pid"], os.getpid())
            self.assertEqual(receipt["computerUseReview"], "NOT_RUN")
            self.assertEqual(receipt["status"], "READY_FOR_USER_TESTING")
            self.assertTrue(Path(result["receiptPath"]).is_file())

    def test_completes_full_delivery_only_after_fresh_runtime_handoff(self):
        with tempfile.TemporaryDirectory() as raw:
            worktree = Path(raw) / "worktree"
            worktree.mkdir()
            self._initialize_git_worktree(worktree)
            state = create_state(
                worktree=worktree,
                run_id="run-full",
                issue={"id": "id", "identifier": "TS-2", "title": "Title"},
                branch="benjamin/ts-2",
                base="development",
                created_from="origin/development",
                adopted_head="abc",
                identities={"linear": "test@example.com", "github": "test"},
            )
            for phase in PHASES:
                complete_phase(state, phase)
            manifest = worktree / ".local-runtime" / "runtime.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps({"urls": {"web": "http://127.0.0.1:43123"}}))
            state["runtimes"] = [
                {
                    "runtimeId": "fresh-runtime",
                    "manifestPath": str(manifest),
                    "cleanedAt": None,
                }
            ]
            state["activeRuntimeId"] = "fresh-runtime"
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=worktree,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            state["status"] = "preparing_final_runtime"
            state["finalRuntimeReset"] = {
                "runtimeId": "fresh-runtime",
                "verifiedCommit": head,
            }
            state["pr"] = {"url": "https://github.com/example/repo/pull/1"}
            input_path = (
                worktree
                / ".local-runtime"
                / "issue-delivery-orchestrator"
                / "run-full"
                / "validation"
                / "services.json"
            )
            input_path.parent.mkdir(parents=True, exist_ok=True)
            input_path.write_text(json.dumps({"services": [{"name": "web"}]}))

            with patch(
                "issue_delivery_orchestrator.runtime_handoff._health_status",
                return_value=200,
            ):
                result = prepare_runtime_handoff(state, input_path)

            self.assertEqual(state["status"], "completed_preserved")
            self.assertEqual(
                result["receipt"]["computerUseReview"], "COMPLETED_BEFORE_RESET"
            )
            self.assertEqual(
                result["receipt"]["pullRequest"],
                "https://github.com/example/repo/pull/1",
            )

    def test_rejects_handoff_without_final_runtime_reset(self):
        with tempfile.TemporaryDirectory() as raw:
            worktree = Path(raw) / "worktree"
            worktree.mkdir()
            state = create_state(
                worktree=worktree,
                run_id="run-full",
                issue={"id": "id", "identifier": "TS-2", "title": "Title"},
                branch="benjamin/ts-2",
                base="development",
                created_from="origin/development",
                adopted_head="abc",
                identities={"linear": "test@example.com", "github": "test"},
            )

            with self.assertRaisesRegex(RunBlocked, "Reset the final runtime"):
                prepare_runtime_handoff(state, worktree / "missing.json")

    def test_resets_runtime_before_starting_final_services(self):
        with tempfile.TemporaryDirectory() as raw:
            worktree = Path(raw) / "worktree"
            worktree.mkdir()
            self._initialize_git_worktree(worktree)
            state = self._manual_state(worktree)
            for phase in PHASES[: PHASES.index("manual-revision")]:
                complete_phase(state, phase)
            state["activeRuntimeId"] = "review-runtime"

            def initialize(current_state, *, fresh=False):
                self.assertTrue(fresh)
                current_state["activeRuntimeId"] = "fresh-runtime"
                current_state["runtimes"] = [
                    {
                        "runtimeId": "fresh-runtime",
                        "manifestPath": str(worktree / ".local-runtime" / "fresh.json"),
                        "cleanedAt": None,
                    }
                ]
                return current_state["runtimes"][0]

            with patch(
                "issue_delivery_orchestrator.runtime_reset.stop_owned_processes",
                return_value=[123],
            ), patch(
                "issue_delivery_orchestrator.runtime_reset.cleanup_runtimes",
                return_value=["review-runtime"],
            ), patch(
                "issue_delivery_orchestrator.runtime_reset.initialize_runtime",
                side_effect=initialize,
            ):
                result = reset_final_runtime(state)

            self.assertEqual(state["status"], "preparing_final_runtime")
            self.assertEqual(state["activeRuntimeId"], "fresh-runtime")
            self.assertEqual(result["reset"]["previousRuntimeId"], "review-runtime")
            self.assertEqual(result["reset"]["stoppedPids"], [123])
            self.assertEqual(result["reset"]["cleanedRuntimeIds"], ["review-runtime"])
            self.assertTrue(Path(result["receiptPath"]).is_file())

    @staticmethod
    def _initialize_git_worktree(worktree: Path):
        subprocess.run(["git", "init"], cwd=worktree, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=worktree,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=worktree,
            check=True,
            capture_output=True,
        )
        (worktree / ".gitignore").write_text(".local-runtime/\n")
        (worktree / "tracked.txt").write_text("ready\n")
        subprocess.run(
            ["git", "add", ".gitignore", "tracked.txt"],
            cwd=worktree,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=worktree,
            check=True,
            capture_output=True,
        )

    @staticmethod
    def _manual_state(worktree: Path):
        return create_state(
            worktree=worktree,
            run_id="run-manual",
            issue={"id": "id", "identifier": "TS-2", "title": "Title"},
            branch="benjamin/ts-2",
            base="development",
            created_from="origin/development",
            adopted_head="abc",
            identities={"linear": "test@example.com", "github": "test"},
            handoff="manual-runtime",
        )


if __name__ == "__main__":
    unittest.main()
