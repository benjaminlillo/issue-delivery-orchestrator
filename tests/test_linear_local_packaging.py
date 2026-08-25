from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_SKILLS = (
    ROOT / "skills" / "issue-delivery-spec-publisher" / "SKILL.md",
    ROOT / "skills" / "issue-delivery-ticket-publisher" / "SKILL.md",
)


class LinearLocalPackagingTests(unittest.TestCase):
    def test_publication_skills_use_only_protected_cli_commands(self) -> None:
        required = (
            "$linear-local",
            "codex-linear doctor",
            "codex-linear issue get <issue>",
            "codex-linear issue update-description <issue> --description-file <path>",
            "codex-linear comment create <issue> --body-file <path>",
        )
        forbidden_active_instructions = (
            "Update Linear through the Linear connector",
            "Publish through the Linear connector",
            "Use the Linear connector",
            "Use Linear MCP",
        )

        for path in PUBLISHER_SKILLS:
            content = path.read_text(encoding="utf-8")
            for instruction in required:
                self.assertIn(instruction, content, f"{instruction!r} missing from {path}")
            for instruction in forbidden_active_instructions:
                self.assertNotIn(instruction, content, f"{instruction!r} remains active in {path}")
            self.assertIn("Do not use a Linear connector, Linear MCP", content)
            self.assertIn("failure is blocking", content)

    def test_linear_local_dependency_is_bundled(self) -> None:
        skill = ROOT / "skills" / "linear-local" / "SKILL.md"
        implementation = ROOT / "skills" / "linear-local" / "scripts" / "linear_cli.py"
        command = ROOT / "bin" / "codex-linear"

        self.assertTrue(skill.is_file())
        self.assertTrue(implementation.is_file())
        self.assertTrue(command.is_file())
        self.assertTrue(os.access(command, os.X_OK))

    def test_bundled_cli_help_is_offline_and_available(self) -> None:
        result = subprocess.run(
            [str(ROOT / "bin" / "codex-linear"), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("codex-linear", result.stdout)
        self.assertIn("issue", result.stdout)
        self.assertIn("comment", result.stdout)


if __name__ == "__main__":
    unittest.main()
