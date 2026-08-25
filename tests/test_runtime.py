import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.manual_handoff import prepare_manual_handoff
from issue_delivery_orchestrator.runtime import register_owned_process, stop_owned_processes
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

    def test_prepares_manual_handoff_without_stopping_processes(self):
        with tempfile.TemporaryDirectory() as raw:
            worktree = Path(raw) / "worktree"
            worktree.mkdir()
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
                "issue_delivery_orchestrator.manual_handoff._health_status", return_value=200
            ):
                result = prepare_manual_handoff(state, input_path)

            receipt = result["receipt"]
            self.assertEqual(state["status"], "awaiting_manual_review")
            self.assertEqual(state["currentPhase"], "manual-revision")
            self.assertTrue(result["processesPreserved"])
            self.assertNotIn("processesStoppedAt", state)
            self.assertEqual(receipt["services"][0]["port"], 43123)
            self.assertEqual(receipt["processes"][0]["pid"], os.getpid())
            self.assertEqual(receipt["computerUseReview"], "NOT_RUN")
            self.assertTrue(Path(result["receiptPath"]).is_file())

    def test_rejects_manual_handoff_for_full_delivery(self):
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

            with self.assertRaisesRegex(RunBlocked, "was not selected"):
                prepare_manual_handoff(state, worktree / "missing.json")

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
