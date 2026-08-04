from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .config import settings
from .errors import RunBlocked
from .github import GitHubClient
from .state import block_run, resume_run, save_state
from .util import run


def review_repair_budget(state: dict[str, Any]) -> dict[str, Any]:
    batch_size = settings().review_repair_batch_size
    budget = state.setdefault(
        "reviewRepairBudget",
        {
            "batchSize": batch_size,
            "approvedRepairs": batch_size,
            "repairs": [],
            "extensions": [],
        },
    )
    stored_batch_size = budget.get("batchSize")
    if not isinstance(stored_batch_size, int) or stored_batch_size <= 0:
        stored_batch_size = batch_size
        budget["batchSize"] = stored_batch_size
    approved = budget.get("approvedRepairs")
    if not isinstance(approved, int) or approved < stored_batch_size:
        approved = stored_batch_size
        budget["approvedRepairs"] = approved
    repairs = budget.setdefault("repairs", [])
    extensions = budget.setdefault("extensions", [])
    if not isinstance(repairs, list) or not isinstance(extensions, list):
        raise RunBlocked("Review repair budget is malformed")
    used = len(
        {
            str(item.get("headSha"))
            for item in repairs
            if isinstance(item, dict) and item.get("headSha")
        }
    )
    return {
        "batchSize": stored_batch_size,
        "approvedRepairs": approved,
        "usedRepairs": used,
        "remainingRepairs": max(0, approved - used),
        "extensionCount": len(extensions),
    }


def record_review_repair(
    state: dict[str, Any],
    *,
    fixes: list[str],
) -> dict[str, Any]:
    _require_active_convergence(state, "Review repairs")
    normalized_fixes = [" ".join(item.split()) for item in fixes if item.strip()]
    if not normalized_fixes:
        raise RunBlocked("A review repair must reference at least one processed FIX")
    if not state.get("pr"):
        raise RunBlocked("Cannot record a review repair before a PR has been recorded")
    review_repair_budget(state)

    worktree = Path(state["worktree"])
    github = GitHubClient(worktree)
    github.verify_identity()
    remote_head = github.head_sha(state["pr"]["url"])
    local_head = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    if local_head != remote_head:
        raise RunBlocked(
            "Review repair must be recorded after its validated commit is pushed; "
            f"local HEAD is {local_head or '<empty>'}, PR head is {remote_head}"
        )

    budget = state["reviewRepairBudget"]
    previous = next(
        (
            item
            for item in budget["repairs"]
            if isinstance(item, dict) and item.get("headSha") == remote_head
        ),
        None,
    )
    if previous:
        return {
            "recorded": False,
            "repair": previous,
            "budget": review_repair_budget(state),
        }

    budget_summary = review_repair_budget(state)
    if budget_summary["remainingRepairs"] <= 0:
        raise RunBlocked(
            "Review repair budget is exhausted; request explicit user approval "
            "before applying another FIX"
        )

    receipt = {
        "headSha": remote_head,
        "fixes": normalized_fixes,
        "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reviewSnapshot": state.get("artifacts", {}).get("latestReviewSnapshot"),
    }
    budget["repairs"].append(receipt)
    save_state(state)
    return {
        "recorded": True,
        "repair": receipt,
        "budget": review_repair_budget(state),
    }


def request_review_extension(
    state: dict[str, Any],
    *,
    fixes: list[dict[str, str]],
    artifact: str,
) -> dict[str, Any]:
    _require_active_convergence(state, "Review extensions")
    budget = review_repair_budget(state)
    if budget["remainingRepairs"] > 0:
        raise RunBlocked(
            "Review repair budget still has "
            f"{budget['remainingRepairs']} repair(s) available"
        )
    if not fixes:
        raise RunBlocked("Review extension request requires at least one pending FIX")
    increment = budget["batchSize"]
    reason = (
        f"Remote review repair budget exhausted after {budget['usedRepairs']} repair(s); "
        f"explicit user approval is required for {increment} additional repair(s)"
    )
    block_run(state, reason, decision=True)
    state["blocker"].update(
        {
            "kind": "review_repair_budget",
            "repairBudget": budget,
            "requestedRepairs": increment,
            "pendingFixes": fixes,
            "requestArtifact": artifact,
        }
    )
    state.setdefault("artifacts", {})["reviewExtensionRequest"] = artifact
    save_state(state)
    return {
        "status": state["status"],
        "blocker": state["blocker"],
        "budget": review_repair_budget(state),
    }


def approve_review_extension(state: dict[str, Any]) -> dict[str, Any]:
    blocker = state.get("blocker") or {}
    if (
        state.get("status") != "needs_user_decision"
        or blocker.get("kind") != "review_repair_budget"
    ):
        raise RunBlocked("No review repair extension is awaiting user approval")

    budget_summary = review_repair_budget(state)
    budget = state["reviewRepairBudget"]
    increment = budget_summary["batchSize"]
    previous_limit = budget_summary["approvedRepairs"]
    budget["approvedRepairs"] = previous_limit + increment
    budget["extensions"].append(
        {
            "approvedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "additionalRepairs": increment,
            "previousLimit": previous_limit,
            "newLimit": previous_limit + increment,
            "pendingFixes": blocker.get("pendingFixes", []),
            "requestArtifact": blocker.get("requestArtifact"),
            "source": "explicit-user-approval",
        }
    )
    resume_run(state)
    return review_repair_budget(state)


def _require_active_convergence(state: dict[str, Any], operation: str) -> None:
    if state.get("status") != "active" or state.get("currentPhase") != "review-convergence":
        raise RunBlocked(
            f"{operation} can only be used during active review-convergence"
        )
