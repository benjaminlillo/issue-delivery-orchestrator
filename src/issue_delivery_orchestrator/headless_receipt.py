from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import OrchestrationError
from .headless_artifacts import (
    validate_artifacts,
    validate_legacy_files,
    validate_required_artifacts,
)


SUPPORTED_SCOPES = {"operation-only", "full-story"}
LEGACY_SCOPES = {"upload-only", "full-story"}


def validate_headless_receipt(
    receipt: Any,
    *,
    story_id: str,
    kind: str,
    verification: dict[str, Any],
    run_directory: Path,
    index: int,
    receipt_path: Path,
    screenshot_paths: set[Path],
    worktree: Path,
    legacy: bool,
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise OrchestrationError(
            f"Headless assistance receipt {index} must be an object"
        )
    expected = {
        "receiptVersion": 1 if legacy else 2,
        "status": "PASS",
        "driver": "playwright-headless",
        "storyId": story_id,
        "verifiedCommit": verification["verifiedCommit"],
        "runtimeId": verification["runtimeId"],
    }
    if not legacy:
        expected["kind"] = kind
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise OrchestrationError(
                f"Headless assistance receipt {index} has invalid {field}"
            )

    scope = str(receipt.get("scope") or "").strip()
    supported_scopes = LEGACY_SCOPES if legacy else SUPPORTED_SCOPES
    if scope not in supported_scopes:
        raise OrchestrationError(
            f"Headless assistance receipt {index} has unsupported scope "
            f"{scope or '<empty>'}"
        )
    validate_timestamp(receipt.get("verifiedAt"), index, "verifiedAt")
    observations = receipt.get("observations")
    if not isinstance(observations, list) or not observations or not all(
        isinstance(item, str) and item.strip() for item in observations
    ):
        raise OrchestrationError(
            f"Headless assistance receipt {index} requires observations"
        )

    if legacy:
        artifacts = validate_legacy_files(
            receipt.get("files"),
            run_directory,
            index,
        )
        browser_attempt = None
    else:
        browser_attempt = _validate_browser_attempt(
            receipt.get("browserAttempt"),
            kind,
            index,
        )
        artifacts = validate_artifacts(
            receipt.get("artifacts"),
            run_directory,
            index,
        )
        validate_required_artifacts(
            artifacts,
            kind=kind,
            scope=scope,
            screenshot_paths=screenshot_paths,
            index=index,
        )

    summary = {
        "storyId": story_id,
        "kind": kind,
        "scope": scope,
        "driver": "playwright-headless",
        "receiptPath": str(receipt_path.relative_to(worktree)),
        "receiptSha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "artifactCount": len(artifacts),
        "verifiedAt": str(receipt["verifiedAt"]),
    }
    if browser_attempt:
        summary["browserAttempt"] = browser_attempt
    if legacy:
        summary["legacy"] = True
        summary["fileCount"] = len(artifacts)
    return summary


def _validate_browser_attempt(
    value: Any,
    kind: str,
    index: int,
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise OrchestrationError(
            f"Headless assistance receipt {index} requires browserAttempt"
        )
    expected = {"status": "CAPABILITY_GAP", "kind": kind}
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise OrchestrationError(
                f"Headless assistance receipt {index} has invalid "
                f"browserAttempt.{field}"
            )
    observation = str(value.get("observation") or "").strip()
    if not observation:
        raise OrchestrationError(
            f"Headless assistance receipt {index} requires "
            "browserAttempt.observation"
        )
    attempted_at = str(value.get("attemptedAt") or "").strip()
    validate_timestamp(attempted_at, index, "browserAttempt.attemptedAt")
    return {
        "status": "CAPABILITY_GAP",
        "kind": kind,
        "observation": observation,
        "attemptedAt": attempted_at,
    }


def validate_timestamp(value: Any, index: int, field: str) -> None:
    try:
        datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as error:
        raise OrchestrationError(
            f"Headless assistance receipt {index} {field} must be ISO-8601"
        ) from error
