import os
import unittest
from unittest.mock import patch

from issue_delivery_orchestrator.credentials import CredentialProvider


class CredentialTests(unittest.TestCase):
    def test_environment_is_an_explicit_override(self):
        with patch.dict(os.environ, {"LINEAR_API_KEY": "temporary-token"}):
            secret = CredentialProvider().linear_api_key()
        self.assertEqual(secret.value, "temporary-token")
        self.assertEqual(secret.source, "environment")


if __name__ == "__main__":
    unittest.main()
