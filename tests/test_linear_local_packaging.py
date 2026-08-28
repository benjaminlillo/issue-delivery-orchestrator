from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LINEAR_CLI_PATH = ROOT / "skills" / "linear-local" / "scripts" / "linear_cli.py"
PUBLISHER_SKILLS = (
    ROOT / "skills" / "issue-delivery-spec-publisher" / "SKILL.md",
    ROOT / "skills" / "issue-delivery-ticket-publisher" / "SKILL.md",
)


class LinearLocalPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location(
            "issue_delivery_test_linear_cli",
            LINEAR_CLI_PATH,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not load bundled codex-linear implementation")
        cls.linear_cli = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.linear_cli
        spec.loader.exec_module(cls.linear_cli)

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

    def test_cli_reads_credential_from_process_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LINEAR_API_KEY": "environment-token",
                "LINEAR_EXPECTED_EMAIL": "Developer@Example.com",
            },
            clear=True,
        ):
            credential = self.linear_cli._read_environment_credential()

        self.assertEqual("environment-token", credential.value)
        self.assertEqual("environment", credential.source)
        self.assertEqual("developer@example.com", credential.account)

    def test_cli_loads_credential_from_personal_environment_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            config_dir = Path(raw)
            (config_dir / ".env").write_text(
                "LINEAR_API_KEY=file-token\n"
                "LINEAR_EXPECTED_EMAIL=developer@example.com\n",
                encoding="utf-8",
            )
            with (
                patch.object(self.linear_cli, "ORCHESTRATOR_CONFIG_DIR", config_dir),
                patch.dict(os.environ, {}, clear=True),
            ):
                credential = self.linear_cli._read_environment_credential()

        self.assertEqual("file-token", credential.value)
        self.assertEqual("environment", credential.source)
        self.assertEqual("developer@example.com", credential.account)

    def test_cli_fails_explicitly_when_linear_api_key_is_missing(self) -> None:
        with (
            patch.object(
                self.linear_cli,
                "ORCHESTRATOR_CONFIG_DIR",
                Path("/missing/issue-delivery-config"),
            ),
            patch.dict(os.environ, {}, clear=True),
        ):
            with self.assertRaisesRegex(
                self.linear_cli.LinearCliError,
                "LINEAR_API_KEY is required",
            ):
                self.linear_cli._read_environment_credential()

    def test_packaged_linear_auth_has_no_keychain_dependency(self) -> None:
        paths = (
            ROOT / "src" / "issue_delivery_orchestrator" / "credentials.py",
            LINEAR_CLI_PATH,
            ROOT / "skills" / "linear-local" / "SKILL.md",
            ROOT / "profiles" / "turboshop.json",
            ROOT / ".env.example",
        )
        forbidden = ("Keychain", "keychain", "LINEAR_KEYCHAIN_SERVICE")
        for path in paths:
            content = path.read_text(encoding="utf-8")
            for value in forbidden:
                self.assertNotIn(value, content, f"{value!r} remains in {path}")


if __name__ == "__main__":
    unittest.main()
