import tempfile
import unittest
from pathlib import Path

from issue_delivery_orchestrator.errors import OrchestrationError
from issue_delivery_orchestrator.evidence import upsert_ui_run
from issue_delivery_orchestrator.linear import normalize_issue_identifier, upsert_markdown_section


class LinearHelpersTests(unittest.TestCase):
    def test_normalizes_identifier_and_linear_url(self):
        self.assertEqual(normalize_issue_identifier("ts-123"), "TS-123")
        self.assertEqual(
            normalize_issue_identifier("https://linear.app/turboshop/issue/TS-456/a-title"),
            "TS-456",
        )

    def test_rejects_non_issue_value(self):
        with self.assertRaises(OrchestrationError):
            normalize_issue_identifier("not-an-issue")

    def test_upserts_named_section_without_touching_following_section(self):
        source = "# Issue\n\n## Spec\n\nOld\n\n## Tickets\n\nKeep\n"
        updated = upsert_markdown_section(source, "Spec", "New")
        self.assertIn("## Spec\n\nNew", updated)
        self.assertIn("## Tickets\n\nKeep", updated)
        self.assertNotIn("\nOld\n", updated)

    def test_upserts_only_current_ui_run(self):
        source = (
            "Intro\n\n## UI enhancements\n\n"
            "### Issue Delivery old\n\nold-image\n\n"
            "### Issue Delivery current\n\nstale\n\n"
            "## Tickets\n\nKeep\n"
        )
        updated = upsert_ui_run(
            source,
            "current",
            "### Issue Delivery current\n\nfresh",
        )
        self.assertIn("old-image", updated)
        self.assertIn("fresh", updated)
        self.assertNotIn("stale", updated)
        self.assertIn("## Tickets\n\nKeep", updated)


if __name__ == "__main__":
    unittest.main()
