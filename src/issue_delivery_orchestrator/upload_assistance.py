"""Compatibility wrapper for the v0.3 upload-only validator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .headless_assistance import validate_headless_assistance


def validate_upload_assistance(
    manifest: dict[str, Any],
    state: dict[str, Any],
    worktree: Path,
    verification: dict[str, Any],
    screenshot_story_ids: set[str],
) -> list[dict[str, Any]]:
    return validate_headless_assistance(
        {"uploadAssistance": manifest.get("uploadAssistance", [])},
        state,
        worktree,
        verification,
        {story_id: set() for story_id in screenshot_story_ids},
    )
