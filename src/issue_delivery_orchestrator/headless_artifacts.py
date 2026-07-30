from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .errors import OrchestrationError
from .util import ensure_within


def validate_legacy_files(
    files: Any,
    run_directory: Path,
    index: int,
) -> list[dict[str, Any]]:
    if not isinstance(files, list) or not files:
        raise OrchestrationError(
            f"Headless assistance receipt {index} requires uploaded files"
        )
    return [
        _validate_file(
            item,
            run_directory,
            index,
            file_index,
            label="Uploaded file",
            require_role=False,
        )
        for file_index, item in enumerate(files, start=1)
    ]


def validate_artifacts(
    artifacts: Any,
    run_directory: Path,
    index: int,
) -> list[dict[str, Any]]:
    if not isinstance(artifacts, list) or not artifacts:
        raise OrchestrationError(
            f"Headless assistance receipt {index} requires artifacts"
        )
    return [
        _validate_file(
            item,
            run_directory,
            index,
            file_index,
            label="Artifact",
            require_role=True,
        )
        for file_index, item in enumerate(artifacts, start=1)
    ]


def validate_required_artifacts(
    artifacts: list[dict[str, Any]],
    *,
    kind: str,
    scope: str,
    screenshot_paths: set[Path],
    index: int,
) -> None:
    if kind == "file-upload" and not any(
        item["role"] == "fixture" for item in artifacts
    ):
        raise OrchestrationError(
            f"Headless assistance receipt {index} requires a file-upload fixture"
        )
    if kind != "hover" and scope != "full-story":
        return
    matching_evidence = [
        item
        for item in artifacts
        if item["role"] == "evidence"
        and item["mimeType"] == "image/png"
        and item["path"].resolve() in screenshot_paths
    ]
    if not matching_evidence:
        raise OrchestrationError(
            f"Headless assistance receipt {index} requires a PNG evidence artifact "
            "also declared as the story's final screenshot"
        )


def _validate_file(
    item: Any,
    run_directory: Path,
    index: int,
    file_index: int,
    *,
    label: str,
    require_role: bool,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise OrchestrationError(
            f"{label} {file_index} in receipt {index} must be an object"
        )
    relative = str(item.get("path") or "").strip()
    path = ensure_within(run_directory / relative, run_directory)
    if not path.is_file():
        raise OrchestrationError(f"{label} does not exist: {path}")
    if item.get("size") != path.stat().st_size or path.stat().st_size <= 0:
        raise OrchestrationError(
            f"{label} size does not match receipt: {path}"
        )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if item.get("sha256") != digest:
        raise OrchestrationError(
            f"{label} hash does not match receipt: {path}"
        )
    mime_type = str(item.get("mimeType") or "").strip()
    if not mime_type:
        raise OrchestrationError(f"{label} is missing mimeType: {path}")
    role = str(item.get("role") or "").strip()
    if require_role and role not in {"fixture", "evidence"}:
        raise OrchestrationError(
            f"{label} has unsupported role {role or '<empty>'}: {path}"
        )
    return {
        "path": path,
        "mimeType": mime_type,
        "role": role,
    }
