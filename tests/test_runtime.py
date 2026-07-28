import subprocess
import tempfile
import unittest
from pathlib import Path

from issue_delivery_orchestrator.runtime import register_owned_process, stop_owned_processes
from issue_delivery_orchestrator.state import create_state


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


if __name__ == "__main__":
    unittest.main()
