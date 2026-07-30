import os
import unittest
from pathlib import Path
from unittest.mock import patch

from issue_delivery_orchestrator.cli import (
    _mode_decision,
    _new_run_mode,
    _path_mode_markers,
    _requested_worktree,
    parser,
)
from issue_delivery_orchestrator.config import settings
from issue_delivery_orchestrator.errors import RunBlocked


class CliModeTests(unittest.TestCase):
    def test_turboshop_review_waits_for_ten_quiet_minutes(self):
        profile = (
            Path(__file__).resolve().parents[1]
            / "profiles"
            / "turboshop.json"
        )
        with patch.dict(
            os.environ,
            {
                "ISSUE_DELIVERY_PROFILE": str(profile),
                "ISSUE_DELIVERY_ENV_FILE": "/missing/issue-delivery.env",
            },
            clear=True,
        ):
            args = parser().parse_args(["TS-1", "wait-review"])

        self.assertEqual(args.quiet_seconds, 600)
        self.assertEqual(args.max_seconds, 1200)
        self.assertEqual(args.poll_seconds, 15)

    def test_parses_explicit_codex_mode_and_worktree(self):
        args = parser().parse_args(
            ["TS-1", "--mode", "codex", "--worktree", "/tmp/codex-worktree"]
        )

        self.assertEqual(args.mode, "codex")
        self.assertEqual(args.worktree, Path("/tmp/codex-worktree"))

    def test_parses_explicit_vanilla_mode_and_worktree(self):
        args = parser().parse_args(
            ["TS-1", "--mode", "vanilla", "--worktree", "/tmp/checkout"]
        )

        self.assertEqual(args.mode, "vanilla")
        self.assertEqual(args.worktree, Path("/tmp/checkout"))

    def test_parses_prepare_evidence_manifest(self):
        args = parser().parse_args(
            ["TS-1", "prepare-evidence", "--manifest", "validation/ui.json"]
        )

        self.assertEqual(args.action, "prepare-evidence")
        self.assertEqual(args.manifest, Path("validation/ui.json"))

    def test_codex_mode_does_not_adopt_superset_environment(self):
        with patch.dict(os.environ, {"SUPERSET_WORKSPACE_PATH": "/tmp/superset"}):
            self.assertIsNone(_requested_worktree(None, "codex"))

    def test_superset_mode_accepts_superset_environment(self):
        with patch.dict(os.environ, {"SUPERSET_WORKSPACE_PATH": "/tmp/superset"}):
            self.assertEqual(
                _requested_worktree(None, "superset"),
                Path("/tmp/superset"),
            )

    def test_vanilla_mode_does_not_adopt_superset_environment(self):
        with patch.dict(os.environ, {"SUPERSET_WORKSPACE_PATH": "/tmp/superset"}):
            self.assertIsNone(_requested_worktree(None, "vanilla"))

    def test_detects_codex_from_path_marker(self):
        configuration = self._settings()

        self.assertEqual(
            _new_run_mode(
                None,
                Path("/tmp/.codex/worktrees/TS-1"),
                configuration,
            ),
            ("codex", "path-marker"),
        )

    def test_detects_superset_from_environment(self):
        configuration = self._settings()
        with patch.dict(
            os.environ,
            {"SUPERSET_WORKSPACE_PATH": "/tmp/superset/worktrees/TS-1"},
        ):
            self.assertEqual(
                _new_run_mode(
                    None,
                    Path("/tmp/superset/worktrees/TS-1"),
                    configuration,
                ),
                ("superset", "superset-environment"),
            )

    def test_detects_superset_from_path_marker_without_environment(self):
        configuration = self._settings()

        self.assertEqual(
            _new_run_mode(
                None,
                Path("/tmp/.superset/worktrees/TS-1"),
                configuration,
            ),
            ("superset", "path-marker"),
        )

    def test_configured_root_has_priority_over_path_marker(self):
        configuration = self._settings(
            ISSUE_DELIVERY_CODEX_WORKTREE_ROOTS="/tmp/custom-worktrees"
        )

        self.assertEqual(
            _new_run_mode(
                None,
                Path("/tmp/custom-worktrees/superset-project/TS-1"),
                configuration,
            ),
            ("codex", "configured-root"),
        )

    def test_explicit_mode_has_priority_over_detection(self):
        configuration = self._settings()

        self.assertEqual(
            _new_run_mode(
                "superset",
                Path("/tmp/.codex/worktrees/TS-1"),
                configuration,
            ),
            ("superset", "explicit"),
        )

    def test_explicit_vanilla_does_not_depend_on_path_markers(self):
        configuration = self._settings()

        self.assertEqual(
            _new_run_mode(
                "vanilla",
                Path("/tmp/.codex/worktrees/TS-1"),
                configuration,
            ),
            ("vanilla", "explicit"),
        )

    def test_mode_decision_exposes_values_required_for_chat_announcement(self):
        decision = _mode_decision(
            {
                "worktree": "/tmp/worktree",
                "mode": {"name": "vanilla"},
                "reviewer": {"method": "cua-driver"},
            },
            "vanilla-fallback",
        )

        self.assertEqual(
            decision,
            {
                "mode": "vanilla",
                "source": "vanilla-fallback",
                "reviewer": "cua-driver",
                "worktree": str(Path("/tmp/worktree").resolve()),
            },
        )

    def test_ambiguous_path_requires_explicit_mode(self):
        configuration = self._settings()

        with self.assertRaisesRegex(RunBlocked, "both Codex and Superset"):
            _new_run_mode(
                None,
                Path("/tmp/codex/superset/TS-1"),
                configuration,
            )

    def test_unknown_path_falls_back_to_vanilla(self):
        configuration = self._settings()

        self.assertEqual(
            _new_run_mode(
                None,
                Path("/tmp/worktrees/TS-1"),
                configuration,
            ),
            ("vanilla", "vanilla-fallback"),
        )

    def test_path_markers_do_not_match_substrings(self):
        self.assertEqual(
            _path_mode_markers(Path("/tmp/mycodexproject/TS-1")),
            set(),
        )

    def _settings(self, **environment):
        profile = (
            Path(__file__).resolve().parents[1]
            / "profiles"
            / "turboshop.json"
        )
        values = {
            "ISSUE_DELIVERY_PROFILE": str(profile),
            "ISSUE_DELIVERY_ENV_FILE": "/missing/issue-delivery.env",
            **environment,
        }
        with patch.dict(os.environ, values, clear=True):
            return settings()


if __name__ == "__main__":
    unittest.main()
