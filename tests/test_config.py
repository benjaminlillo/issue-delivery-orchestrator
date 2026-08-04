from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from issue_delivery_orchestrator.config import settings


class ConfigTests(unittest.TestCase):
    def test_loads_profile_and_user_environment_without_exposing_secret(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            profile = root / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "name": "example",
                        "productName": "Example",
                        "git": {
                            "defaultBase": "main",
                            "prTarget": "staging",
                            "evidenceBranch": "ui-evidence",
                        },
                        "runtime": {
                            "root": ".runtime",
                            "namespace": "issue-delivery",
                            "initCommand": ["tool", "runtime", "init"],
                            "cleanupCommand": [
                                "tool",
                                "runtime",
                                "cleanup",
                                "{runtime_id}",
                            ],
                        },
                        "identity": {
                            "linearExpectedEmail": "",
                            "githubExpectedLogin": "",
                            "linearKeychainService": "example-linear",
                        },
                        "review": {
                            "botNames": ["review-bot"],
                            "blockerBot": "review-bot",
                            "repairBatchSize": 2,
                            "quietSeconds": 30,
                            "maximumWaitSeconds": 90,
                            "pollSeconds": 5,
                        },
                        "linear": {
                            "markerPrefix": "example-delivery",
                            "uiSection": "UI evidence",
                        },
                    }
                )
            )
            env_file = root / ".env"
            env_file.write_text(
                "LINEAR_API_KEY=secret\n"
                "LINEAR_EXPECTED_EMAIL=developer@example.com\n"
                "GITHUB_EXPECTED_LOGIN=developer\n"
            )
            controlled = {
                "ISSUE_DELIVERY_PROFILE": str(profile),
                "ISSUE_DELIVERY_ENV_FILE": str(env_file),
            }
            with patch.dict(os.environ, controlled, clear=True):
                configuration = settings()
                public = configuration.public_dict()

            self.assertEqual(configuration.pr_target_branch, "staging")
            self.assertEqual(
                configuration.linear_expected_email,
                "developer@example.com",
            )
            self.assertEqual(configuration.github_expected_login, "developer")
            self.assertEqual(configuration.review_repair_batch_size, 2)
            self.assertNotIn("LINEAR_API_KEY", public)
            self.assertNotIn("secret", json.dumps(public))

    def test_rejects_parent_traversal_in_runtime_paths(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = json.loads(
                (
                    Path(__file__).resolve().parents[1]
                    / "profiles"
                    / "turboshop.json"
                ).read_text()
            )
            source["runtime"]["root"] = "../outside"
            profile = root / "invalid.json"
            profile.write_text(json.dumps(source))
            with patch.dict(
                os.environ,
                {"ISSUE_DELIVERY_PROFILE": str(profile)},
                clear=True,
            ):
                with self.assertRaisesRegex(Exception, "runtime.root"):
                    settings()

    def test_accepts_legacy_maximum_rounds_as_repair_batch_size(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = json.loads(
                (
                    Path(__file__).resolve().parents[1]
                    / "profiles"
                    / "turboshop.json"
                ).read_text()
            )
            source["review"]["maximumRounds"] = source["review"].pop(
                "repairBatchSize"
            )
            profile = root / "legacy.json"
            profile.write_text(json.dumps(source))

            with patch.dict(
                os.environ,
                {
                    "ISSUE_DELIVERY_PROFILE": str(profile),
                    "ISSUE_DELIVERY_ENV_FILE": "/missing/issue-delivery.env",
                },
                clear=True,
            ):
                configuration = settings()

            self.assertEqual(configuration.review_repair_batch_size, 5)


if __name__ == "__main__":
    unittest.main()
