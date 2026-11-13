import json
import re
import unittest
from pathlib import Path

from issue_delivery_orchestrator import __version__


ROOT = Path(__file__).resolve().parents[1]


class PluginPackagingTests(unittest.TestCase):
    def test_codex_and_claude_manifests_share_identity_and_version(self):
        codex = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())
        claude = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        package = json.loads((ROOT / "package.json").read_text())
        project = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)

        self.assertEqual(claude["name"], codex["name"])
        self.assertEqual(
            {codex["version"], claude["version"], package["version"], project.group(1)},
            {__version__},
        )

    def test_skills_name_siblings_without_codex_invocation_syntax(self):
        for path in (ROOT / "skills").rglob("*.md"):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotRegex(path.read_text(), r"\$(issue-delivery-|linear-local)")

    def test_pre_approved_spec_contract_is_linked_and_names_its_signals(self):
        orchestrator = (ROOT / "skills" / "issue-delivery-orchestrator" / "SKILL.md").read_text()
        contract = (
            ROOT / "skills" / "issue-delivery-orchestrator" / "references" / "pre-approved-spec.md"
        ).read_text()

        self.assertIn("references/pre-approved-spec.md", orchestrator)
        for signal in (
            "codex-linear issue spec-approval <issue> --prefix <prefix>",
            "Prototipo: aprobado",
            "Prototipo: no (<motivo>)",
            "prototype-adopt",
            "## Prototipo aprobado",
        ):
            self.assertIn(signal, contract)


if __name__ == "__main__":
    unittest.main()
