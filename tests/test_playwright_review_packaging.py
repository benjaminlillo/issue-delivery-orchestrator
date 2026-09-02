import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlaywrightReviewPackagingTests(unittest.TestCase):
    def test_conductor_cloud_reviewer_is_bundled_with_primary_provider_contract(self):
        skill = (
            ROOT / "skills" / "issue-delivery-playwright-review" / "SKILL.md"
        ).read_text()

        self.assertIn("provider: playwright-chrome", skill)
        self.assertIn("CONDUCTOR_IS_LOCAL=0", skill)
        self.assertIn("locator.boundingBox()", skill)
        self.assertIn("No declarar `headlessAssistance`", skill)
        self.assertIn("instalar paquetes ni modificar archivos trackeados", skill)


if __name__ == "__main__":
    unittest.main()
