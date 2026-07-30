from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import OrchestrationError
from .state import review_method, run_root
from .util import ensure_within, read_json


SUPPORTED_SCOPES = {"upload-only", "full-story"}


def validate_upload_assistance(
    manifest: dict[str, Any],
    state: dict[str, Any],
    worktree: Path,
    verification: dict[str, Any],
    screenshot_story_ids: set[str],
) -> list[dict[str, Any]]:
    declared = manifest.get("uploadAssistance", [])
    if not isinstance(declared, list):
        raise OrchestrationError("uploadAssistance must be an array")
    if declared and review_method(state) != "codex-browser":
        raise OrchestrationError(
            "Headless upload assistance is supported only in codex-browser runs"
        )

    scenario_ids = set(verification["scenarioIds"])
    result = []
    for index, item in enumerate(declared, start=1):
        if not isinstance(item, dict):
            raise OrchestrationError(
                f"Upload assistance {index} must be an object"
            )
        story_id = str(item.get("storyId") or "").strip()
        if story_id not in scenario_ids:
            raise OrchestrationError(
                f"Upload assistance {index} references unverified story {story_id or '<empty>'}"
            )
        if story_id not in screenshot_story_ids:
            raise OrchestrationError(
                f"Upload-assisted story {story_id} requires final screenshot evidence"
            )

        receipt_path = _receipt_path(item, state, worktree, index)
        receipt = read_json(receipt_path)
        result.append(
            _validate_receipt(
                receipt,
                story_id=story_id,
                verification=verification,
                run_directory=run_root(worktree, state["runId"]),
                index=index,
                receipt_path=receipt_path,
                worktree=worktree,
            )
        )
    return result


def _receipt_path(
    item: dict[str, Any],
    state: dict[str, Any],
    worktree: Path,
    index: int,
) -> Path:
    relative = str(item.get("receiptPath") or "").strip()
    if not relative:
        raise OrchestrationError(
            f"Upload assistance {index} is missing receiptPath"
        )
    receipt_path = ensure_within(worktree / relative, worktree)
    expected_root = run_root(worktree, state["runId"]) / "validation" / "headless-upload"
    ensure_within(receipt_path, expected_root)
    if not receipt_path.is_file():
        raise OrchestrationError(
            f"Upload assistance receipt does not exist: {receipt_path}"
        )
    return receipt_path


def _validate_receipt(
    receipt: Any,
    *,
    story_id: str,
    verification: dict[str, Any],
    run_directory: Path,
    index: int,
    receipt_path: Path,
    worktree: Path,
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise OrchestrationError(
            f"Upload assistance receipt {index} must be an object"
        )
    expected = {
        "receiptVersion": 1,
        "status": "PASS",
        "driver": "playwright-headless",
        "storyId": story_id,
        "verifiedCommit": verification["verifiedCommit"],
        "runtimeId": verification["runtimeId"],
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise OrchestrationError(
                f"Upload assistance receipt {index} has invalid {field}"
            )

    scope = str(receipt.get("scope") or "").strip()
    if scope not in SUPPORTED_SCOPES:
        raise OrchestrationError(
            f"Upload assistance receipt {index} has unsupported scope {scope or '<empty>'}"
        )
    _validate_timestamp(receipt.get("verifiedAt"), index)
    files = _validate_files(receipt.get("files"), run_directory, index)
    observations = receipt.get("observations")
    if not isinstance(observations, list) or not observations or not all(
        isinstance(item, str) and item.strip() for item in observations
    ):
        raise OrchestrationError(
            f"Upload assistance receipt {index} requires observations"
        )
    return {
        "storyId": story_id,
        "scope": scope,
        "driver": "playwright-headless",
        "receiptPath": str(receipt_path.relative_to(worktree)),
        "receiptSha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "fileCount": len(files),
        "verifiedAt": str(receipt["verifiedAt"]),
    }


def _validate_timestamp(value: Any, index: int) -> None:
    try:
        datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as error:
        raise OrchestrationError(
            f"Upload assistance receipt {index} verifiedAt must be ISO-8601"
        ) from error


def _validate_files(
    files: Any,
    run_directory: Path,
    index: int,
) -> list[Path]:
    if not isinstance(files, list) or not files:
        raise OrchestrationError(
            f"Upload assistance receipt {index} requires uploaded files"
        )
    result = []
    for file_index, item in enumerate(files, start=1):
        if not isinstance(item, dict):
            raise OrchestrationError(
                f"Uploaded file {file_index} in receipt {index} must be an object"
            )
        relative = str(item.get("path") or "").strip()
        path = ensure_within(run_directory / relative, run_directory)
        if not path.is_file():
            raise OrchestrationError(f"Uploaded fixture does not exist: {path}")
        if item.get("size") != path.stat().st_size or path.stat().st_size <= 0:
            raise OrchestrationError(
                f"Uploaded fixture size does not match receipt: {path}"
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if item.get("sha256") != digest:
            raise OrchestrationError(
                f"Uploaded fixture hash does not match receipt: {path}"
            )
        if not str(item.get("mimeType") or "").strip():
            raise OrchestrationError(
                f"Uploaded fixture is missing mimeType: {path}"
            )
        result.append(path)
    return result
