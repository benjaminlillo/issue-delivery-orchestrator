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
    receipt_version = receipt.get("receiptVersion")
    if legacy:
        supported_versions = {1}
    else:
        supported_versions = {2, 3}
    if receipt_version not in supported_versions:
        raise OrchestrationError(
            f"Headless assistance receipt {index} has invalid receiptVersion"
        )
    provider = str(verification.get("provider") or "cua-driver")
    if receipt_version == 2 and provider != "codex-browser":
        raise OrchestrationError(
            f"Headless assistance receipt {index} version 2 requires "
            "codex-browser"
        )
    expected = {
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
        primary_attempt = None
    else:
        attempt_field = (
            "browserAttempt" if receipt_version == 2 else "primaryAttempt"
        )
        primary_attempt = _validate_primary_attempt(
            receipt.get(attempt_field),
            kind,
            index,
            provider=provider,
            attempt_field=attempt_field,
        )
        browser_attempt = primary_attempt if receipt_version == 2 else None
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
        "receiptVersion": receipt_version,
        "verifiedAt": str(receipt["verifiedAt"]),
    }
    if browser_attempt:
        summary["browserAttempt"] = browser_attempt
    if primary_attempt and receipt_version == 3:
        summary["primaryAttempt"] = primary_attempt
    if legacy:
        summary["legacy"] = True
        summary["fileCount"] = len(artifacts)
    return summary


def _validate_primary_attempt(
    value: Any,
    kind: str,
    index: int,
    *,
    provider: str,
    attempt_field: str,
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise OrchestrationError(
            f"Headless assistance receipt {index} requires {attempt_field}"
        )
    expected = {"status": "CAPABILITY_GAP", "kind": kind}
    if attempt_field == "primaryAttempt":
        expected["provider"] = provider
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise OrchestrationError(
                f"Headless assistance receipt {index} has invalid "
                f"{attempt_field}.{key}"
            )
    observation = str(value.get("observation") or "").strip()
    if not observation:
        raise OrchestrationError(
            f"Headless assistance receipt {index} requires "
            f"{attempt_field}.observation"
        )
    attempted_at = str(value.get("attemptedAt") or "").strip()
    validate_timestamp(attempted_at, index, f"{attempt_field}.attemptedAt")
    result = {
        "status": "CAPABILITY_GAP",
        "kind": kind,
        "observation": observation,
        "attemptedAt": attempted_at,
    }
    if attempt_field == "primaryAttempt":
        result["provider"] = provider
    return result


def validate_timestamp(value: Any, index: int, field: str) -> None:
    try:
        datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as error:
        raise OrchestrationError(
            f"Headless assistance receipt {index} {field} must be ISO-8601"
        ) from error
