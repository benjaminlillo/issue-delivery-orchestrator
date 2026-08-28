import os
import unittest
from unittest.mock import patch

from issue_delivery_orchestrator.credentials import CredentialProvider
from issue_delivery_orchestrator.errors import OrchestrationError


class CredentialTests(unittest.TestCase):
    def test_reads_linear_api_key_from_environment(self):
        with patch.dict(os.environ, {"LINEAR_API_KEY": "temporary-token"}, clear=True):
            secret = CredentialProvider().linear_api_key()
        self.assertEqual(secret.value, "temporary-token")
        self.assertEqual(secret.source, "environment")

    def test_fails_when_linear_api_key_is_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(OrchestrationError, "LINEAR_API_KEY must be set"):
                CredentialProvider().linear_api_key()


if __name__ == "__main__":
    unittest.main()
