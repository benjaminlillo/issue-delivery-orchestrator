from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import OrchestrationError
from .headless_receipt import validate_headless_receipt
from .state import review_method, run_root
from .util import ensure_within, read_json


SUPPORTED_KINDS = {"file-upload", "hover"}


def validate_headless_assistance(
    manifest: dict[str, Any],
    state: dict[str, Any],
    worktree: Path,
    verification: dict[str, Any],
    screenshot_paths_by_story: dict[str, set[Path]],
) -> list[dict[str, Any]]:
    declared = _declared_assistance(manifest)
    if declared and review_method(state) != "codex-browser":
        raise OrchestrationError(
            "Headless assistance is supported only in codex-browser runs"
        )

    scenario_ids = set(verification["scenarioIds"])
    seen: set[tuple[str, str]] = set()
    result = []
    for index, (item, legacy) in enumerate(declared, start=1):
        if not isinstance(item, dict):
            raise OrchestrationError(
                f"Headless assistance {index} must be an object"
            )
        story_id = str(item.get("storyId") or "").strip()
        if story_id not in scenario_ids:
            raise OrchestrationError(
                f"Headless assistance {index} references unverified story "
                f"{story_id or '<empty>'}"
            )
        if story_id not in screenshot_paths_by_story:
            raise OrchestrationError(
                f"Headless-assisted story {story_id} requires final screenshot evidence"
            )

        kind = "file-upload" if legacy else str(item.get("kind") or "").strip()
        if kind not in SUPPORTED_KINDS:
            raise OrchestrationError(
                f"Headless assistance {index} has unsupported kind "
                f"{kind or '<empty>'}"
            )
        key = (story_id, kind)
        if key in seen:
            raise OrchestrationError(
                f"Duplicate headless assistance for {story_id} and {kind}"
            )
        seen.add(key)

        receipt_path = _receipt_path(
            item,
            state,
            worktree,
            index,
            legacy=legacy,
        )
        receipt = read_json(receipt_path)
        result.append(
            validate_headless_receipt(
                receipt,
                story_id=story_id,
                kind=kind,
                verification=verification,
                run_directory=run_root(worktree, state["runId"]),
                index=index,
                receipt_path=receipt_path,
                screenshot_paths=screenshot_paths_by_story[story_id],
                worktree=worktree,
                legacy=legacy,
            )
        )
    return result


def _declared_assistance(
    manifest: dict[str, Any],
) -> list[tuple[dict[str, Any], bool]]:
    current = manifest.get("headlessAssistance", [])
    legacy = manifest.get("uploadAssistance", [])
    if not isinstance(current, list):
        raise OrchestrationError("headlessAssistance must be an array")
    if not isinstance(legacy, list):
        raise OrchestrationError("uploadAssistance must be an array")
    return [(item, False) for item in current] + [
        (item, True) for item in legacy
    ]


def _receipt_path(
    item: dict[str, Any],
    state: dict[str, Any],
    worktree: Path,
    index: int,
    *,
    legacy: bool,
) -> Path:
    relative = str(item.get("receiptPath") or "").strip()
    if not relative:
        raise OrchestrationError(
            f"Headless assistance {index} is missing receiptPath"
        )
    receipt_path = ensure_within(worktree / relative, worktree)
    directory = "headless-upload" if legacy else "headless-assistance"
    expected_root = run_root(worktree, state["runId"]) / "validation" / directory
    ensure_within(receipt_path, expected_root)
    if not receipt_path.is_file():
        raise OrchestrationError(
            f"Headless assistance receipt does not exist: {receipt_path}"
        )
    return receipt_path
