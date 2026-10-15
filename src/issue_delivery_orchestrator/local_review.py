from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import RunBlocked
from .state import run_root
from .util import read_json, run


STATUSES = {"PASS", "FIX", "NEEDS_USER_DECISION"}
REVIEWER = "review-pr"
MODES = {"orchestrated", "single-agent"}
OPEN_DISPOSITIONS = {"FIX", "NEEDS_USER_DECISION"}


def validate_local_review(state: dict[str, Any], artifact: str) -> dict[str, Any]:
    worktree = Path(state["worktree"])
    path = Path(artifact)
    candidate = path if path.is_absolute() else worktree / path
    root = run_root(worktree, state["runId"]).resolve()
    try:
        candidate = candidate.resolve()
        candidate.relative_to(root)
    except ValueError as error:
        raise RunBlocked("Local review receipt must live inside the run directory") from error
    try:
        receipt = read_json(candidate)
    except (OSError, json.JSONDecodeError) as error:
        raise RunBlocked(f"Could not read local review receipt: {error}") from error
    if not isinstance(receipt, dict):
        raise RunBlocked("Local review receipt must be a JSON object")
    status = str(receipt.get("status") or "")
    if status not in STATUSES:
        raise RunBlocked("Local review receipt status must be PASS, FIX, or NEEDS_USER_DECISION")
    commit = str(receipt.get("verifiedCommit") or "")
    actual = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    if commit != actual:
        raise RunBlocked(
            f"Local review receipt targets {commit or 'no commit'}, but HEAD is {actual}"
        )
    if receipt.get("reviewer") != REVIEWER or receipt.get("mode") not in MODES:
        raise RunBlocked(
            "Local review must run the repository's review-pr skill in orchestrated or "
            "single-agent mode"
        )
    report = _report(worktree, receipt.get("report"))
    if actual[:7] not in report.read_text(encoding="utf-8"):
        raise RunBlocked("The review-pr report does not name the reviewed SHA")
    findings = receipt.get("findings", [])
    if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
        raise RunBlocked("Local review receipt findings must be an array of objects")
    if status == "PASS" and any(
        item.get("estado") == "Corregir" or item.get("disposition") in OPEN_DISPOSITIONS
        for item in findings
    ):
        raise RunBlocked(
            "A PASS local review cannot keep Corregir findings or unresolved FIX or "
            "NEEDS_USER_DECISION dispositions"
        )
    receipt["receiptPath"] = str(candidate.relative_to(worktree))
    receipt["report"] = str(report.relative_to(worktree.resolve()))
    receipt["validatedCommit"] = actual
    return receipt


def _report(worktree: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RunBlocked("Local review receipt must reference the review-pr report")
    path = Path(raw)
    candidate = (path if path.is_absolute() else worktree / path).resolve()
    if not candidate.is_relative_to((worktree / ".context" / "reviews").resolve()):
        raise RunBlocked("The review-pr report must live under .context/reviews/")
    if not candidate.is_file() or candidate.stat().st_size == 0:
        raise RunBlocked("The review-pr report is missing or empty")
    return candidate
