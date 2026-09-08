import tempfile
import unittest
from pathlib import Path

from issue_delivery_orchestrator.errors import RunBlocked
from issue_delivery_orchestrator.state import (
    PHASES,
    complete_phase,
    create_state,
    find_runs,
    handoff_mode,
    load_state,
    review_method,
    resume_run,
    run_mode,
    run_root,
    select_review_method,
    target_branch,
)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.worktrees_root = Path(self.temporary.name)
        self.worktree = self.worktrees_root / "ts-1-run"
        self.worktree.mkdir()
        self.state = create_state(
            worktree=self.worktree,
            run_id="run-1",
            issue={"id": "id", "identifier": "TS-1", "title": "Title"},
            branch="benjamin/ts-1",
            base="development",
            created_from="origin/development",
            adopted_head="abc",
            identities={"linear": "benjalillo@turboshop.cl", "github": "benjaminlillo"},
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_creates_state_inside_ignored_runtime_directory(self):
        path = run_root(self.worktree, "run-1") / "state.json"
        self.assertTrue(path.is_file())
        self.assertEqual(load_state(path)["currentPhase"], "grill")
        self.assertEqual(find_runs(self.worktrees_root, "TS-1")[0]["runId"], "run-1")
        self.assertEqual(run_mode(self.state), "superset")
        self.assertEqual(review_method(self.state), "cua-driver")
        self.assertEqual(handoff_mode(self.state), "full")
        self.assertEqual(target_branch(self.state), "test")
        self.assertEqual(self.state["discardedInitialStatus"], [])
        self.assertEqual(self.state["reviewRepairBudget"]["approvedRepairs"], 5)
        self.assertEqual(self.state["reviewRepairBudget"]["repairs"], [])

    def test_finds_state_inside_additional_registered_worktree(self):
        separate_root = self.worktrees_root / "superset"
        separate_worktree = separate_root / "ts-2"
        separate_worktree.mkdir(parents=True)
        create_state(
            worktree=separate_worktree,
            run_id="run-2",
            issue={"id": "id-2", "identifier": "TS-2", "title": "Title"},
            branch="benjamin/ts-2",
            base="development",
            created_from="adopted:benjamin/ts-2",
            adopted_head="def",
            discarded_status=(" M existing.txt",),
            identities={"linear": "benjalillo@turboshop.cl", "github": "benjaminlillo"},
        )

        found = find_runs(
            self.worktrees_root / "private-only",
            "TS-2",
            (separate_worktree,),
        )

        self.assertEqual(found[0]["runId"], "run-2")
        self.assertEqual(found[0]["adoptedStatus"], [])
        self.assertEqual(found[0]["discardedInitialStatus"], [" M existing.txt"])

    def test_advances_in_order_and_waits_for_fresh_final_runtime(self):
        for phase in PHASES:
            complete_phase(self.state, phase)
        self.assertEqual(self.state["status"], "awaiting_final_runtime_reset")
        self.assertIsNone(self.state["currentPhase"])

    def test_rejects_out_of_order_checkpoint(self):
        with self.assertRaises(RunBlocked):
            complete_phase(self.state, "implement")

    def test_selects_browser_reviewer_before_manual_revision(self):
        self.state.pop("mode")
        selection = select_review_method(self.state, "codex-browser")

        self.assertEqual(selection["method"], "codex-browser")
        self.assertEqual(review_method(self.state), "codex-browser")

    def test_selects_browser_reviewer_at_start_of_manual_revision(self):
        self.state.pop("mode")
        for phase in PHASES[: PHASES.index("manual-revision")]:
            complete_phase(self.state, phase)

        selection = select_review_method(self.state, "codex-browser")

        self.assertEqual(selection["method"], "codex-browser")
        self.assertEqual(review_method(self.state), "codex-browser")

    def test_rejects_reviewer_change_after_manual_revision(self):
        self.state.pop("mode")
        for phase in PHASES[: PHASES.index("manual-revision") + 1]:
            complete_phase(self.state, phase)

        with self.assertRaisesRegex(RunBlocked, "before the first manual-revision"):
            select_review_method(self.state, "codex-browser")

    def test_legacy_state_without_reviewer_defaults_to_cua(self):
        self.state.pop("mode")
        self.state.pop("reviewer")

        self.assertEqual(run_mode(self.state), "superset")
        self.assertEqual(review_method(self.state), "cua-driver")

    def test_codex_mode_selects_browser_reviewer(self):
        state = create_state(
            worktree=self.worktree,
            run_id="run-codex",
            issue={"id": "id", "identifier": "TS-1", "title": "Title"},
            branch="benjamin/ts-1",
            base="development",
            created_from="codex:origin/development",
            adopted_head="abc",
            identities={"linear": "benjalillo@turboshop.cl", "github": "benjaminlillo"},
            mode="codex",
        )

        self.assertEqual(run_mode(state), "codex")
        self.assertEqual(review_method(state), "codex-browser")

    def test_vanilla_mode_selects_cua_reviewer(self):
        state = create_state(
            worktree=self.worktree,
            run_id="run-vanilla",
            issue={"id": "id", "identifier": "TS-1", "title": "Title"},
            branch="benjamin/ts-1",
            base="development",
            created_from="vanilla:origin/development",
            adopted_head="abc",
            identities={"linear": "benjalillo@turboshop.cl", "github": "benjaminlillo"},
            mode="vanilla",
        )

        self.assertEqual(run_mode(state), "vanilla")
        self.assertEqual(review_method(state), "cua-driver")

    def test_explicit_pr_target_is_persisted(self):
        state = create_state(
            worktree=self.worktree,
            run_id="run-custom-target",
            issue={"id": "id", "identifier": "TS-1", "title": "Title"},
            branch="benjamin/ts-1",
            base="main",
            target="production",
            created_from="origin/main",
            adopted_head="abc",
            identities={"linear": "benjalillo@turboshop.cl", "github": "benjaminlillo"},
        )

        self.assertEqual(target_branch(state), "production")

    def test_legacy_state_preserves_profile_target(self):
        self.state.pop("target")
        self.state["profile"] = {"pr_target_branch": "staging"}

        self.assertEqual(target_branch(self.state), "staging")

    def test_conductor_cloud_mode_selects_playwright_reviewer(self):
        state = create_state(
            worktree=self.worktree,
            run_id="run-conductor",
            issue={"id": "id", "identifier": "TS-1", "title": "Title"},
            branch="benjamin/ts-1",
            base="development",
            created_from="conductor-cloud:origin/development",
            adopted_head="abc",
            identities={"linear": "benjalillo@turboshop.cl", "github": "benjaminlillo"},
            mode="conductor-cloud",
        )

        self.assertEqual(run_mode(state), "conductor-cloud")
        self.assertEqual(review_method(state), "playwright-chrome")

    def test_new_mode_cannot_change_reviewer_independently(self):
        with self.assertRaisesRegex(RunBlocked, "fixed by development mode"):
            select_review_method(self.state, "codex-browser")

    def test_manual_runtime_handoff_is_persisted_and_resumable(self):
        state = create_state(
            worktree=self.worktree,
            run_id="run-manual",
            issue={"id": "id", "identifier": "TS-1", "title": "Title"},
            branch="benjamin/ts-1",
            base="development",
            created_from="origin/development",
            adopted_head="abc",
            identities={"linear": "benjalillo@turboshop.cl", "github": "benjaminlillo"},
            handoff="manual-runtime",
        )
        state["status"] = "awaiting_manual_review"
        state["manualHandoff"] = {"status": "ready"}

        resume_run(state)

        self.assertEqual(handoff_mode(state), "manual-runtime")
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["manualHandoff"]["status"], "superseded")

    def test_manual_handoff_can_resume_into_full_delivery(self):
        self.state["status"] = "awaiting_manual_review"
        self.state["handoff"] = {"mode": "manual-runtime"}

        resume_run(self.state, full_delivery=True)

        self.assertEqual(handoff_mode(self.state), "full")

    def test_full_delivery_transition_requires_awaiting_manual_handoff(self):
        self.state["status"] = "blocked"
        self.state["handoff"] = {"mode": "manual-runtime"}

        with self.assertRaisesRegex(RunBlocked, "awaiting manual-runtime"):
            resume_run(self.state, full_delivery=True)


if __name__ == "__main__":
    unittest.main()
