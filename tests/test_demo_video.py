import tempfile
import unittest
from pathlib import Path

from issue_delivery_orchestrator.demo_video import validate_demo_video
from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.state import run_root


class DemoVideoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.worktree = Path(self.tmp.name)
        self.state = {"worktree": str(self.worktree), "runId": "run-1"}
        self.video = run_root(self.worktree, "run-1") / "validation" / "demo.mp4"
        self.video.parent.mkdir(parents=True)
        self.video.write_bytes(b"recorded-video")
        self.receipt = {
            "status": "RECORDED", "verifiedCommit": "sha", "runtimeId": "runtime-1",
            "uiTickets": ["T-1", "REPAIR-1"],
            "videos": [{"path": str(self.video), "ticketIds": ["T-1", "REPAIR-1"]}],
        }

    def validate(self):
        return validate_demo_video(self.state, self.receipt, runtime_id="runtime-1", commit="sha")

    def test_accepts_agent_selected_format_and_optional_hosting(self):
        result = self.validate()
        self.assertEqual(result["videos"][0]["path"], str(self.video.relative_to(self.worktree)))
        self.assertNotIn("url", result["videos"][0])
        self.receipt["videos"][0]["url"] = "https://preview.example/demo.mp4"
        self.assertEqual(self.validate()["videos"][0]["url"], "https://preview.example/demo.mp4")

    def test_requires_a_result_bound_to_the_final_commit_and_runtime(self):
        with self.assertRaisesRegex(RunBlocked, "demoVideo"):
            validate_demo_video(self.state, None, runtime_id="runtime-1", commit="sha")
        for field in ("verifiedCommit", "runtimeId"):
            with self.subTest(field=field):
                previous = self.receipt[field]
                self.receipt[field] = "old"
                with self.assertRaisesRegex(RunBlocked, "final commit and runtime"):
                    self.validate()
                self.receipt[field] = previous

    def test_skips_only_non_ui_runs_and_reports_recording_failures(self):
        self.receipt.update(status="SKIPPED", videos=[], reason="Internal refactor")
        with self.assertRaisesRegex(RunBlocked, "no UI-reviewable tickets"):
            self.validate()
        self.receipt["uiTickets"] = []
        self.assertEqual(self.validate()["status"], "SKIPPED")
        self.receipt.update(status="FAILED", uiTickets=["T-1"], reason="Recorder unavailable")
        self.assertEqual(self.validate()["reason"], "Recorder unavailable")
        self.receipt["reason"] = ""
        with self.assertRaisesRegex(RunBlocked, "requires a reason"):
            self.validate()

    def test_requires_real_nonempty_files_within_the_run(self):
        self.video.write_bytes(b"")
        with self.assertRaisesRegex(RunBlocked, "missing or empty"):
            self.validate()
        self.video.unlink()
        with self.assertRaisesRegex(RunBlocked, "missing or empty"):
            self.validate()
        outside = self.worktree / "other-run.mp4"
        outside.write_bytes(b"old-video")
        self.receipt["videos"][0]["path"] = str(outside)
        with self.assertRaisesRegex(RunBlocked, "inside the run"):
            self.validate()
        self.video.symlink_to(outside)
        self.receipt["videos"][0]["path"] = str(self.video)
        with self.assertRaisesRegex(RunBlocked, "inside the run"):
            self.validate()

    def test_requires_coverage_of_each_ui_ticket(self):
        self.receipt["videos"][0]["ticketIds"] = ["T-1"]
        with self.assertRaisesRegex(RunBlocked, "cover all"):
            self.validate()
        self.receipt["videos"].append({"path": str(self.video), "ticketIds": ["REPAIR-1"]})
        self.assertEqual(len(self.validate()["videos"]), 2)
        self.receipt["videos"][1]["ticketIds"] = ["T-99"]
        with self.assertRaisesRegex(RunBlocked, "reference UI-reviewable ticket IDs"):
            self.validate()

    def test_rejects_invalid_delivery_links_and_ticket_lists(self):
        self.receipt["videos"][0]["url"] = "javascript:alert(1)"
        with self.assertRaisesRegex(RunBlocked, "HTTP"):
            self.validate()
        for tickets in ([{}], ["T-1", "T-1"], [""], "T-1"):
            self.receipt["uiTickets"] = tickets
            with self.assertRaisesRegex(RunBlocked, "unique ticket IDs"):
                self.validate()


if __name__ == "__main__":
    unittest.main()
