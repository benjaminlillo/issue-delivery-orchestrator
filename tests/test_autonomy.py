import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from issue_delivery_orchestrator.cli import AUTONOMOUS_REVIEW_EXTENSIONS, dispatch, parser
from issue_delivery_orchestrator.errors import OrchestrationError, RunBlocked
from issue_delivery_orchestrator.state import autonomy_mode, create_state, run_root


class AutonomyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.worktree = Path(tmp.name)

    def state(self, autonomy):
        state = create_state(
            worktree=self.worktree, run_id="run-1", issue={"identifier": "TS-1", "title": "T"},
            branch="feature", base="development", created_from="origin/development",
            adopted_head="abc", identities={}, autonomy=autonomy,
        )
        state.update(status="active", currentPhase="review-convergence")
        budget = state["reviewRepairBudget"]
        budget["repairs"] = [{"headSha": f"sha-{n}"} for n in range(budget["approvedRepairs"])]
        request = run_root(self.worktree, "run-1") / "review" / "request.json"
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text(json.dumps({"fixes": [{"title": "Fix", "reason": "Valid blocker"}]}))
        self.request = str(request.relative_to(self.worktree))
        return state

    def run_action(self, state, *arguments):
        with patch("issue_delivery_orchestrator.cli._select_state", return_value=state), patch(
            "issue_delivery_orchestrator.cli._repository", return_value=self.worktree
        ), patch("issue_delivery_orchestrator.cli.GitWorkspace"):
            return dispatch(parser().parse_args(["TS-1", *arguments]))

    def test_runs_are_interactive_unless_autonomy_is_chosen(self):
        self.assertEqual(autonomy_mode(self.state("interactive")), "interactive")
        self.assertEqual(parser().parse_args(["TS-1", "--autonomy", "autonomous"]).autonomy, "autonomous")
        with self.assertRaises(OrchestrationError):
            self.state("unknown")

    def test_autonomous_runs_cannot_wait_for_a_user_decision(self):
        state = self.state("autonomous")
        with self.assertRaisesRegex(RunBlocked, "never wait for a user decision"):
            self.run_action(state, "block", "--reason", "Pick a scope", "--decision")
        blocked = self.run_action(state, "block", "--reason", "Runtime cannot start")
        self.assertEqual(blocked["state"]["status"], "blocked")

    def test_autonomous_runs_grant_repair_extensions_up_to_a_limit(self):
        state = self.state("autonomous")
        for _ in range(AUTONOMOUS_REVIEW_EXTENSIONS):
            result = self.run_action(state, "request-review-extension", "--input", self.request)
            self.assertTrue(result["autoApproved"])
            self.assertEqual(state["status"], "active")
            budget = state["reviewRepairBudget"]
            self.assertEqual(budget["extensions"][-1]["source"], "autonomous-mode")
            budget["repairs"] = [{"headSha": f"sha-{n}"} for n in range(budget["approvedRepairs"])]
        with self.assertRaisesRegex(RunBlocked, "decide each remaining FIX as SKIP"):
            self.run_action(state, "request-review-extension", "--input", self.request)

    def test_interactive_runs_still_wait_for_the_user(self):
        state = self.state("interactive")
        result = self.run_action(state, "request-review-extension", "--input", self.request)
        self.assertNotIn("autoApproved", result)
        self.assertEqual(state["status"], "needs_user_decision")
