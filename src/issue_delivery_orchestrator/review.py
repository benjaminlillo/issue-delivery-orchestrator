from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from .config import settings
from .errors import RunBlocked
from .github import GitHubClient
from .review_budget import review_repair_budget
from .state import run_root, save_state
from .util import atomic_write_json, read_json, run


def wait_for_quiet_review(
    state: dict[str, Any],
    *,
    quiet_seconds: int = 600,
    max_seconds: int = 1200,
    poll_seconds: int = 15,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    github = GitHubClient(Path(state["worktree"]))
    pr = github.view(state["pr"]["url"])
    root = run_root(Path(state["worktree"]), state["runId"])
    rounds = sorted((root / "review").glob("round-*.json"))
    started = clock()
    quiet_since = started
    previous_fingerprint = ""
    latest: dict[str, Any] = {}
    while True:
        latest = review_snapshot(Path(state["worktree"]), pr.number)
        fingerprint = _bot_fingerprint(latest)
        if previous_fingerprint and fingerprint != previous_fingerprint:
            quiet_since = clock()
        previous_fingerprint = fingerprint
        elapsed = clock() - started
        if clock() - quiet_since >= quiet_seconds or elapsed >= max_seconds:
            break
        sleeper(min(poll_seconds, quiet_seconds - (clock() - quiet_since)))

    path = root / "review" / f"round-{len(rounds) + 1:02d}.json"
    latest["quietWindowSeconds"] = quiet_seconds
    latest["maximumWaitSeconds"] = max_seconds
    latest["repairBudget"] = review_repair_budget(state)
    atomic_write_json(path, latest)
    state["artifacts"]["latestReviewSnapshot"] = str(path.relative_to(Path(state["worktree"])))
    save_state(state)
    return latest


def review_snapshot(worktree: Path, pr_number: int) -> dict[str, Any]:
    inline = _flatten(
        _gh_json(
            worktree,
            ["gh", "api", f"repos/:owner/:repo/pulls/{pr_number}/comments", "--paginate", "--slurp"],
        )
    )
    general = _flatten(
        _gh_json(
            worktree,
            ["gh", "api", f"repos/:owner/:repo/issues/{pr_number}/comments", "--paginate", "--slurp"],
        )
    )
    pr = _gh_json(
        worktree,
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "headRefOid,statusCheckRollup,url",
        ],
    )
    return {
        "pr": pr.get("url"),
        "headSha": pr.get("headRefOid"),
        "botInlineComments": [item for item in inline if _is_relevant_bot(item)],
        "botGeneralComments": [item for item in general if _is_relevant_bot(item)],
        "checks": pr.get("statusCheckRollup") or [],
    }


# NONE marks a blocker bot comment the agent read and found without blockers to process.
DECISIONS = {"FIX", "SKIP", "NONE"}


def acknowledge_processed_blocker(
    state: dict[str, Any],
    *,
    comment_id: int,
    decision: str,
) -> dict[str, Any]:
    github = GitHubClient(Path(state["worktree"]))
    github.verify_identity()
    pr = github.view(state["pr"]["url"])
    comment = github.issue_comment(comment_id)
    comment_pr = int(str(comment.get("issue_url") or "").rstrip("/").rsplit("/", 1)[-1])
    if comment_pr != pr.number:
        raise RunBlocked(f"Comment {comment_id} does not belong to PR #{pr.number}")
    if not _is_blocker_bot(str((comment.get("user") or {}).get("login") or "")):
        raise RunBlocked(
            f"Comment {comment_id} is not from the blocker bots "
            f"{', '.join(settings().blocker_bots)}"
        )
    if decision not in DECISIONS:
        raise RunBlocked("Processed blocker decision must be FIX, SKIP or NONE")
    if decision == "SKIP":
        published_ids = {
            int(item)
            for item in (state.get("skipSummary") or {}).get("commentIds", [])
        }
        if comment_id not in published_ids:
            raise RunBlocked(
                f"SKIP for comment {comment_id} must be explained publicly with "
                "publish-skip-summary when the review ends before it can be acknowledged"
            )

    acknowledgements = state.setdefault("reviewAcknowledgements", [])
    previous = next(
        (item for item in acknowledgements if item.get("commentId") == comment_id),
        None,
    )
    if previous and previous.get("decision") != decision:
        raise RunBlocked(
            f"Comment {comment_id} was already acknowledged as "
            f"{previous.get('decision')}; refusing to rewrite it as {decision}"
        )

    created = github.add_issue_comment_reaction(comment_id, content="+1")
    acknowledged_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    acknowledgement = {
        "commentId": comment_id,
        "commentUrl": comment.get("html_url"),
        "author": (comment.get("user") or {}).get("login"),
        "decision": decision,
        "reaction": "+1",
        "created": created,
        "acknowledgedAt": acknowledged_at,
    }
    if previous:
        previous.setdefault(
            "firstAcknowledgedAt",
            previous.get("acknowledgedAt", acknowledged_at),
        )
        previous.setdefault(
            "reactionCreatedInitially",
            bool(previous.get("created")),
        )
        previous["lastVerifiedAt"] = acknowledged_at
        previous["reactionPresent"] = True
    else:
        acknowledgements.append(
            {
                **acknowledgement,
                "firstAcknowledgedAt": acknowledged_at,
                "reactionCreatedInitially": created,
                "reactionPresent": True,
            }
        )
    save_state(state)
    return acknowledgement


def record_skip(
    state: dict[str, Any],
    *,
    comment_id: int,
    title: str,
    reason: str,
) -> dict[str, Any]:
    """Keep a SKIP's public reason on disk until the review ends; nothing is posted yet."""
    title = " ".join(title.split())
    reason = " ".join(reason.split())
    if not reason:
        raise RunBlocked(f"SKIP {comment_id} requires a public reason")
    if comment_id in _published_skip_ids(state):
        raise RunBlocked(f"SKIP {comment_id} was already published; its reason cannot change")
    path = _skip_ledger_path(state)
    ledger = read_json(path, {"items": []})
    item = {
        "commentId": comment_id,
        "title": title or f"Blocker {comment_id}",
        "reason": reason,
        "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    ledger["items"] = [
        *[entry for entry in ledger["items"] if int(entry["commentId"]) != comment_id],
        item,
    ]
    atomic_write_json(path, ledger)
    state.setdefault("artifacts", {})["skipLedger"] = str(
        path.relative_to(Path(state["worktree"]))
    )
    save_state(state)
    return {"recorded": item, "recordedSkips": len(ledger["items"])}


def publish_skip_summary(state: dict[str, Any]) -> dict[str, Any]:
    """Publish once, when the review ends, every pending SKIP recorded with record-skip.

    Each publication is a new PR comment with only the SKIPs not published before, so later
    rounds never rewrite an older comment buried in the timeline.
    """
    if not state.get("pr"):
        raise RunBlocked("Cannot publish SKIP decisions before a PR has been recorded")
    recorded = {
        int(item["commentId"]): item
        for item in read_json(_skip_ledger_path(state), {"items": []})["items"]
    }

    worktree = Path(state["worktree"])
    github = GitHubClient(worktree)
    github.verify_identity()
    pr = github.view(state["pr"]["url"])
    snapshot = review_snapshot(worktree, pr.number)
    pending = {
        int(item["commentId"]): item
        for item in [
            *_pending_bot_review_threads(github.review_threads(pr.number)),
            *_pending_general_blockers(snapshot, github),
        ]
        if item.get("commentId") is not None
    }
    for acknowledgement in state.get("reviewAcknowledgements", []):
        if acknowledgement.get("decision") == "SKIP":
            pending.setdefault(
                int(acknowledgement["commentId"]),
                {
                    "commentId": int(acknowledgement["commentId"]),
                    "url": acknowledgement.get("commentUrl"),
                    "author": acknowledgement.get("author") or "configured-blocker-bot",
                },
            )
    published = _published_skip_ids(state)
    to_publish = sorted(set(pending) - published)
    missing = [comment_id for comment_id in to_publish if comment_id not in recorded]
    if missing:
        raise RunBlocked(
            "Publish the SKIP summary only when the review ends with every pending automated "
            "blocker recorded as SKIP with record-skip, and every comment without blockers "
            f"acknowledged with --decision NONE; missing={missing}"
        )
    summary = _skip_summary(state)
    if not to_publish:
        return {**summary, "published": False}

    number = len(summary["publications"]) + 1
    marker = f"<!-- issue-delivery-skip-summary:{state['runId']}:{number} -->"
    lines = [
        marker,
        "## Blockers que no voy a corregir",
        "",
        (
            "Revisé los siguientes blockers automatizados y no aplicaré cambios por "
            "los motivos indicados:"
        ),
        "",
    ]
    for comment_id in to_publish:
        decision = recorded[comment_id]
        source = pending[comment_id]
        reference = (
            f"[comentario {comment_id}]({source['url']})"
            if source.get("url")
            else f"comentario {comment_id}"
        )
        lines.append(f"- **{decision['title']}** ({reference}): {decision['reason']}")
    lines.extend(
        [
            "",
            (
                "Estas decisiones corresponden al alcance y acuerdos vigentes de la PR. "
                "Si cambia ese alcance, deben reevaluarse."
            ),
        ]
    )
    body = "\n".join(lines)
    # The marker is unique per publication, so a retry after a crash reuses the same comment.
    comment_reference = github.upsert_comment(pr.number, marker, body)
    summary["publications"].append(
        {
            "publishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "headSha": snapshot.get("headSha"),
            "commentReference": comment_reference,
            "commentIds": to_publish,
            "items": [
                {
                    "commentId": comment_id,
                    "title": recorded[comment_id]["title"],
                    "reason": recorded[comment_id]["reason"],
                    "url": pending[comment_id].get("url"),
                    "author": pending[comment_id].get("author"),
                }
                for comment_id in to_publish
            ],
            "bodyHash": hashlib.sha256(body.encode()).hexdigest(),
        }
    )
    summary["pr"] = pr.url
    summary["commentIds"] = sorted(published | set(to_publish))
    state["skipSummary"] = summary
    path = run_root(worktree, state["runId"]) / "review" / "skip-summary.json"
    atomic_write_json(path, summary)
    state.setdefault("artifacts", {})["skipSummary"] = str(path.relative_to(worktree))
    save_state(state)
    return {**summary, "published": True}


def _skip_ledger_path(state: dict[str, Any]) -> Path:
    return run_root(Path(state["worktree"]), state["runId"]) / "review" / "skip-ledger.json"


def _published_skip_ids(state: dict[str, Any]) -> set[int]:
    return {int(item) for item in (state.get("skipSummary") or {}).get("commentIds", [])}


def _skip_summary(state: dict[str, Any]) -> dict[str, Any]:
    summary = dict(state.get("skipSummary") or {})
    if summary and "publications" not in summary:
        # Runs from earlier versions kept a single, edited comment.
        legacy = {key: value for key, value in summary.items() if key != "pr"}
        summary = {"pr": summary.get("pr"), "commentIds": summary.get("commentIds", []),
                   "publications": [legacy]}
    summary.setdefault("commentIds", [])
    summary.setdefault("publications", [])
    return summary


def assert_review_converged(state: dict[str, Any]) -> dict[str, Any]:
    if not state.get("pr"):
        raise RunBlocked("Cannot validate review convergence before a PR has been recorded")

    worktree = Path(state["worktree"])
    github = GitHubClient(worktree)
    github.verify_identity()
    pr = github.view(state["pr"]["url"])
    snapshot = review_snapshot(worktree, pr.number)

    pending_inline = _pending_bot_review_threads(github.review_threads(pr.number))
    pending_general = _pending_general_blockers(snapshot, github)
    published_skip_ids = {
        int(item)
        for item in (state.get("skipSummary") or {}).get("commentIds", [])
    }
    unpublished_skips = [
        {
            "commentId": int(item["commentId"]),
            "url": item.get("commentUrl"),
        }
        for item in state.get("reviewAcknowledgements", [])
        if item.get("decision") == "SKIP"
        and int(item["commentId"]) not in published_skip_ids
    ]

    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    receipt = {
        "checkedAt": checked_at,
        "pr": pr.url,
        "headSha": snapshot.get("headSha"),
        "passed": not pending_inline and not pending_general and not unpublished_skips,
        "pendingInlineThreads": pending_inline,
        "pendingGeneralBlockers": pending_general,
        "unpublishedSkipAcknowledgements": unpublished_skips,
    }
    root = run_root(worktree, state["runId"])
    path = root / "review" / "final-gate.json"
    atomic_write_json(path, receipt)
    state.setdefault("artifacts", {})["finalReviewGate"] = str(path.relative_to(worktree))
    save_state(state)

    if not receipt["passed"]:
        urls = [
            item["url"]
            for item in [*pending_inline, *pending_general, *unpublished_skips]
            if item.get("url")
        ]
        detail = ", ".join(urls) if urls else "see final-gate.json"
        raise RunBlocked(
            "Final review gate found unresolved automated feedback: "
            f"{len(pending_inline)} inline thread(s), "
            f"{len(pending_general)} general blocker(s), "
            f"{len(unpublished_skips)} unpublished SKIP acknowledgement(s). {detail}"
        )
    return receipt


def _pending_general_blockers(
    snapshot: dict[str, Any],
    github: GitHubClient,
) -> list[dict[str, Any]]:
    pending = []
    for comment in snapshot.get("botGeneralComments", []):
        author = str((comment.get("user") or {}).get("login") or "").lower()
        if not _is_blocker_bot(author):
            continue
        comment_id = int(comment["id"])
        if github.has_issue_comment_reaction(comment_id, content="+1"):
            continue
        pending.append(
            {
                "commentId": comment_id,
                "url": comment.get("html_url"),
                "author": (comment.get("user") or {}).get("login"),
            }
        )
    return pending


def _pending_bot_review_threads(
    threads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pending = []
    for thread in threads:
        if thread.get("isResolved"):
            continue
        comments = (thread.get("comments") or {}).get("nodes") or []
        bot_comment = next(
            (
                comment
                for comment in comments
                if any(
                    name
                    in str((comment.get("author") or {}).get("login") or "").lower()
                    for name in settings().bot_names
                )
            ),
            None,
        )
        if not bot_comment:
            continue
        pending.append(
            {
                "threadId": thread.get("id"),
                "commentId": bot_comment.get("databaseId"),
                "url": bot_comment.get("url"),
                "author": (bot_comment.get("author") or {}).get("login"),
            }
        )
    return pending


def _gh_json(cwd: Path, args: list[str]) -> Any:
    result = run(args, cwd=cwd)
    return json.loads(result.stdout or "null")


def _flatten(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    if value and all(isinstance(item, list) for item in value):
        return [child for page in value for child in page]
    return [item for item in value if isinstance(item, dict)]


def _is_relevant_bot(comment: dict[str, Any]) -> bool:
    """Keep every comment from a configured bot; the agent, not a text pattern, reads it.

    Bots change their wording and markup without notice. Filtering by format once let a
    review full of blockers pass the gate unread, so nothing here inspects the body.
    """
    author = str((comment.get("user") or {}).get("login") or "").lower()
    return any(name in author for name in settings().bot_names)


def _is_blocker_bot(
    author: str,
    blocker_bots: tuple[str, ...] | None = None,
) -> bool:
    names = blocker_bots if blocker_bots is not None else settings().blocker_bots
    return any(name in author.lower() for name in names)


def _bot_fingerprint(snapshot: dict[str, Any]) -> str:
    compact = [
        {
            "id": item.get("id"),
            "updated_at": item.get("updated_at"),
            "body": item.get("body"),
        }
        for key in ("botInlineComments", "botGeneralComments")
        for item in snapshot.get(key, [])
    ]
    return hashlib.sha256(json.dumps(compact, sort_keys=True).encode()).hexdigest()
