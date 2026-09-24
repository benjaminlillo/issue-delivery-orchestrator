import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from issue_delivery_orchestrator.cli import _public_state, bootstrap, dispatch, parser
from issue_delivery_orchestrator.linear import LinearIssue
from issue_delivery_orchestrator.errors import OrchestrationError
from issue_delivery_orchestrator.stage_models import parse_stage_models, stage_plan, update_stage_models
from issue_delivery_orchestrator.state import PHASES, create_state, load_state, state_path


class StageModelsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = create_state(
            worktree=Path(self.tmp.name), run_id="models", issue={"identifier": "TS-1", "title": "Test"},
            branch="feature", base="development", created_from="origin/development",
            adopted_head="abc", identities={},
        )

    def test_default_and_legacy_use_principal_without_overrides(self):
        for state in (self.state, {key: value for key, value in self.state.items() if key != "phaseSequence"}):
            plan = stage_plan(state, "implement")
            self.assertEqual(plan["executor"], "principal-session")
            self.assertIsNone(plan["model"])
            self.assertIsNone(plan["spawnOptions"])
        self.assertEqual(stage_plan(self.state, "local-review")["spawnOptions"], {"fork_turns": "none"})

    def test_selection_survives_reload_and_partial_updates_preserve_other_stages(self):
        update_stage_models(self.state, parse_stage_models(["grill=model-a", "implement=model-b"]))
        reloaded = load_state(state_path(self.state))
        update_stage_models(reloaded, parse_stage_models(["local-review=model-c"]))
        self.assertEqual(reloaded["stageModels"], {"grill": "model-a", "implement": "model-b", "local-review": "model-c"})
        self.assertEqual(stage_plan(reloaded, "implement")["spawnOptions"], {"fork_turns": "none", "model": "model-b"})
        update_stage_models(reloaded, parse_stage_models(["implement=inherit"]))
        self.assertEqual(stage_plan(reloaded, "implement")["executor"], "principal-session")
        self.assertEqual(stage_plan(reloaded, "local-review")["model"], "model-c")

    def test_every_stage_can_delegate_but_local_review_stays_independent_after_reset(self):
        update_stage_models(self.state, {stage: "model-a" for stage in PHASES})
        for stage in PHASES:
            self.assertEqual(stage_plan(self.state, stage)["executor"], "native-subagent")
        update_stage_models(self.state, {"local-review": "inherit"})
        self.assertEqual(stage_plan(self.state, "local-review")["executor"], "native-subagent")
        self.assertNotIn("model", stage_plan(self.state, "local-review")["spawnOptions"])

    def test_invalid_flags_fail_before_mutation(self):
        for entries in (["implement"], ["unknown=model"], ["implement="], ["implement=two words"], ["implement=a", "implement=b"]):
            with self.subTest(entries=entries), self.assertRaises(OrchestrationError):
                parse_stage_models(entries)
        self.assertEqual(parse_stage_models(["implement=a", "implement=a"]), {"implement": "a"})
        self.state.pop("phaseSequence")
        with self.assertRaises(OrchestrationError):
            update_stage_models(self.state, {"implement": "a", "local-review": "b"})
        self.assertNotIn("stageModels", self.state)

    def test_cli_updates_reads_and_resolves_repair_stage_without_changing_phase(self):
        self.state["currentPhase"] = "review-convergence"
        with patch("issue_delivery_orchestrator.cli._repository", return_value=Path(self.tmp.name)), patch(
            "issue_delivery_orchestrator.cli.GitWorkspace"
        ), patch("issue_delivery_orchestrator.cli._select_state", return_value=self.state):
            result = dispatch(parser().parse_args(["TS-1", "--stage-model", "implement=model-a", "stage-models"]))
            self.assertEqual(result["stageModels"], {"implement": "model-a"})
            plan = dispatch(parser().parse_args(["TS-1", "stage-plan", "--phase", "implement"]))
            self.assertEqual(plan["model"], "model-a")
            self.assertEqual(self.state["currentPhase"], "review-convergence")
            self.assertEqual(dispatch(parser().parse_args(["TS-1", "stage-models"])), result)
            self.assertIsNone(_public_state(self.state)["stageExecution"]["model"])
        self.assertEqual(load_state(state_path(self.state))["stageModels"], {"implement": "model-a"})

    def test_flags_cannot_be_silently_ignored_by_other_actions(self):
        with self.assertRaisesRegex(OrchestrationError, "bootstrap or stage-models"):
            dispatch(parser().parse_args(["TS-1", "--stage-model", "implement=a", "status"]))

    def test_bootstrap_flags_are_optional_and_repeatable(self):
        self.assertEqual(parser().parse_args(["TS-1"]).stage_model, [])
        args = parser().parse_args(["TS-1", "--stage-model", "grill=a", "--stage-model", "implement=b"])
        self.assertEqual(parse_stage_models(args.stage_model), {"grill": "a", "implement": "b"})

    def test_bootstrap_persists_selection_and_resume_preserves_or_explicitly_updates_it(self):
        root = Path(self.tmp.name)
        linear = Mock()
        linear.issue.return_value = LinearIssue("id", "TS-1", "Test", "feature", "Description", "url")
        workspace = Mock()
        workspace.adopt_codex.return_value = SimpleNamespace(
            path=root, created_from="codex:origin/development", adopted_head="abc",
            adopted_status=[], discarded_status=[],
        )
        args = parser().parse_args(["TS-1", "--worktree", str(root), "--stage-model", "implement=a"])
        with patch("issue_delivery_orchestrator.cli._verified_linear", return_value=(linear, "test")), patch(
            "issue_delivery_orchestrator.cli.GitHubClient"
        ) as github, patch("issue_delivery_orchestrator.cli.resumable_run", return_value=None) as previous, patch(
            "issue_delivery_orchestrator.cli._new_run_mode", return_value=("codex", "explicit")
        ):
            github.return_value.verify_identity.return_value = "test"
            result = bootstrap(args, root, root, workspace, ())
            state = load_state(root / ".local-runtime" / "issue-delivery-orchestrator" / result["state"]["runId"] / "state.json")
            self.assertEqual(state["stageModels"], {"implement": "a"})
            previous.return_value = state
            result = bootstrap(parser().parse_args(["TS-1"]), root, root, workspace, ())
            self.assertTrue(result["resumed"])
            self.assertEqual(result["state"]["stageModels"], {"implement": "a"})
            result = bootstrap(parser().parse_args(["TS-1", "--stage-model", "implement=inherit"]), root, root, workspace, ())
            self.assertEqual(result["state"]["stageModels"], {})
            self.assertEqual(load_state(state_path(state))["stageModels"], {})
