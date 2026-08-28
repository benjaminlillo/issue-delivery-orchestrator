from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import OrchestrationError


@dataclass(frozen=True)
class Secret:
    value: str
    source: str


class CredentialProvider:
    def linear_api_key(self) -> Secret:
        value = os.environ.get("LINEAR_API_KEY", "").strip()
        if not value:
            raise OrchestrationError(
                "LINEAR_API_KEY must be set in the environment or the personal "
                "issue-delivery-orchestrator .env file"
            )
        return Secret(value, "environment")
