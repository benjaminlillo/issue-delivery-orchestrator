from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .config import settings
from .errors import RunBlocked
from .github import GitHubClient
from .state import now, save_state, target_branch
from .util import code_head, run

MERGEABLE_ATTEMPTS = 6
MERGEABLE_WAIT_SECONDS = 5
REVIEWER_ATTEMPTS = 31
REVIEWER_WAIT_SECONDS = 10


def request_review(
    state: dict[str, Any],
    *,
    github: GitHubClient | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Label the handed-off PR once it merges cleanly and wait until the label's workflow
    requests a reviewer. Draft PRs from older runs are marked ready first."""
    if not state.get("pr"):
        raise RunBlocked("There is no PR to request a review for")
    if state.get("status") != "completed_preserved":
        raise RunBlocked("Request a review only after the final runtime handoff of a full run")
    worktree = Path(state["worktree"])
    handoff = state.get("finalRuntimeHandoff") or {}
    if code_head(worktree) != handoff.get("verifiedCommit"):
        raise RunBlocked(
            "Code changed since the final handoff; finish the repair flow before requesting a review"
        )
    if run(["git", "status", "--porcelain"], cwd=worktree).stdout.strip():
        raise RunBlocked("Commit or remove pending changes before requesting a review")
    github = github or GitHubClient(worktree)
    github.verify_identity()
    reference = state["pr"]["url"]
    pr = github.readiness(reference)
    for _ in range(MERGEABLE_ATTEMPTS - 1):
        if pr.get("mergeable") != "UNKNOWN":
            break
        sleeper(MERGEABLE_WAIT_SECONDS)
        pr = github.readiness(reference)
    if pr.get("mergeable") == "CONFLICTING":
        raise RunBlocked(
            f"The PR has conflicts with {target_branch(state)}; merge it, resolve them and apply "
            "the repair and handoff invariant before requesting a review"
        )
    if pr.get("mergeable") != "MERGEABLE":
        raise RunBlocked("GitHub has not computed whether the PR merges cleanly; try again")
    local_head = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    if pr.get("headRefOid") != local_head:
        raise RunBlocked("Push the branch so the PR head matches the local HEAD before requesting a review")

    label = settings().ready_label
    if pr.get("isDraft"):
        github.mark_ready(reference)
    if label and not _has_label(pr, label):
        github.add_label(reference, label)
    pr = github.readiness(reference)
    if pr.get("isDraft") or (label and not _has_label(pr, label)):
        raise RunBlocked("GitHub did not record the PR as ready with its review label")
    if label:
        for _ in range(REVIEWER_ATTEMPTS - 1):
            if _reviewers(pr):
                break
            sleeper(REVIEWER_WAIT_SECONDS)
            pr = github.readiness(reference)
        if not _reviewers(pr):
            raise RunBlocked(
                f"The PR is ready with {label}, but no reviewer was assigned after "
                f"{(REVIEWER_ATTEMPTS - 1) * REVIEWER_WAIT_SECONDS} seconds; check the GitHub "
                "Actions run triggered by the label"
            )
    state["reviewRequest"] = {
        "markedAt": now(),
        "headSha": local_head,
        "label": label or None,
        "reviewers": _reviewers(pr),
    }
    save_state(state)
    return {"pr": pr.get("url"), **state["reviewRequest"]}


def _has_label(pr: dict[str, Any], label: str) -> bool:
    return any(
        str(item.get("name") or "").lower() == label.lower() for item in pr.get("labels") or []
    )


def _reviewers(pr: dict[str, Any]) -> list[str]:
    names = (str(item.get("login") or item.get("name") or "") for item in pr.get("reviewRequests") or [])
    return sorted(name for name in names if name)
