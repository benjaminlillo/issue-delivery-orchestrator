import os
import unittest
from pathlib import Path
from unittest.mock import patch

from issue_delivery_orchestrator.cli import _requested_worktree, parser


class CliModeTests(unittest.TestCase):
    def test_parses_explicit_codex_mode_and_worktree(self):
        args = parser().parse_args(
            ["TS-1", "--mode", "codex", "--worktree", "/tmp/codex-worktree"]
        )

        self.assertEqual(args.mode, "codex")
        self.assertEqual(args.worktree, Path("/tmp/codex-worktree"))

    def test_codex_mode_does_not_adopt_superset_environment(self):
        with patch.dict(os.environ, {"SUPERSET_WORKSPACE_PATH": "/tmp/superset"}):
            self.assertIsNone(_requested_worktree(None, "codex"))

    def test_superset_mode_accepts_superset_environment(self):
        with patch.dict(os.environ, {"SUPERSET_WORKSPACE_PATH": "/tmp/superset"}):
            self.assertEqual(
                _requested_worktree(None, "superset"),
                Path("/tmp/superset"),
            )


if __name__ == "__main__":
    unittest.main()
