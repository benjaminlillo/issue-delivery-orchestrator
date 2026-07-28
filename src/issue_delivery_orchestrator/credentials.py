from __future__ import annotations

import os
import platform
from dataclasses import dataclass

from .config import settings
from .errors import OrchestrationError
from .util import run


@dataclass(frozen=True)
class Secret:
    value: str
    source: str


class CredentialProvider:
    def linear_api_key(self) -> Secret:
        override = os.environ.get("LINEAR_API_KEY", "").strip()
        if override:
            return Secret(override, "environment")
        if platform.system() != "Darwin":
            raise OrchestrationError(
                "LINEAR_API_KEY is unset and macOS Keychain is unavailable on this platform"
            )
        configuration = settings()
        account = configuration.linear_expected_email
        if not account:
            raise OrchestrationError(
                "LINEAR_EXPECTED_EMAIL must be configured before using macOS Keychain"
            )
        result = run(
            [
                "security",
                "find-generic-password",
                "-s",
                configuration.linear_keychain_service,
                "-a",
                account,
                "-w",
            ],
            check=False,
        )
        value = result.stdout.strip()
        if result.returncode != 0 or not value:
            raise OrchestrationError(
                "Linear credential not found in macOS Keychain. "
                f"Expected service {configuration.linear_keychain_service!r}, "
                f"account {account!r}; "
                "LINEAR_API_KEY may be used as a temporary override."
            )
        return Secret(value, "macos-keychain")
