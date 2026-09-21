from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import RunBlocked
from .state import run_root
from .util import read_json


STATUSES = {"PASS", "FIX", "NEEDS_USER_DECISION"}


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
    from .util import run
    actual = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    if commit != actual:
        raise RunBlocked(
            f"Local review receipt targets {commit or 'no commit'}, but HEAD is {actual}"
        )
    if receipt.get("reviewer") != "codex-native-subagent":
        raise RunBlocked("Local review receipt must identify codex-native-subagent")
    findings = receipt.get("findings", [])
    if not isinstance(findings, list):
        raise RunBlocked("Local review receipt findings must be an array")
    if status == "PASS" and any(
        isinstance(item, dict) and item.get("disposition") in {"FIX", "NEEDS_USER_DECISION"}
        for item in findings
    ):
        raise RunBlocked("A PASS local review cannot contain unresolved FIX or NEEDS_USER_DECISION findings")
    receipt["receiptPath"] = str(candidate.relative_to(worktree))
    receipt["validatedCommit"] = actual
    return receipt
