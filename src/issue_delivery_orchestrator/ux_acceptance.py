from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import RunBlocked


SECTION = "## User Experience Acceptance"
# Acceptance rows start with their ID: UX-001 for behavior, UXD-001 for design decisions.
ROW_ID = re.compile(r"^\|\s*(UXD?-\d{3})\s*\|", re.MULTILINE)


def required_acceptance_ids(state: dict[str, Any]) -> list[str]:
    """Return the approved UX criteria; specs without the section require none."""
    spec = (state.get("artifacts") or {}).get("spec")
    if not spec:
        return []
    path = Path(state["worktree"]) / spec
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RunBlocked(f"Approved spec snapshot is unavailable: {path}") from error
    start = text.find(SECTION)
    if start < 0:
        return []
    following = re.search(r"^## ", text[start + len(SECTION):], re.MULTILINE)
    section = text[start: start + len(SECTION) + following.start()] if following else text[start:]
    return list(dict.fromkeys(ROW_ID.findall(section)))


def assert_acceptance_verified(state: dict[str, Any], verification: dict[str, Any]) -> None:
    required = required_acceptance_ids(state)
    if not required:
        return
    results = {
        str(item.get("id") or ""): item
        for item in verification.get("acceptance") or []
        if isinstance(item, dict)
    }
    missing = [key for key in required if key not in results]
    failing = [key for key in required if key in results and results[key].get("status") != "PASS"]
    unproven = [
        key for key in required
        if key in results and not str(results[key].get("evidence") or "").strip()
    ]
    problems = []
    if missing:
        problems.append(f"not verified: {', '.join(missing)}")
    if failing:
        problems.append(f"not PASS: {', '.join(failing)}")
    if unproven:
        problems.append(f"without evidence: {', '.join(unproven)}")
    if problems:
        raise RunBlocked("UX acceptance criteria are approval requirements; " + "; ".join(problems))
