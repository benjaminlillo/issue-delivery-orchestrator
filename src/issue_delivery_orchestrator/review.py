from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from .config import settings
from .errors import RunBlocked
from .github import GitHubClient
from .state import run_root, save_state
from .util import atomic_write_json, run


def wait_for_quiet_review(
    state: dict[str, Any],
    *,
    quiet_seconds: int = 300,
    max_seconds: int = 900,
    poll_seconds: int = 15,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    github = GitHubClient(Path(state["worktree"]))
    pr = github.view(state["pr"]["url"])
    root = run_root(Path(state["worktree"]), state["runId"])
    rounds = sorted((root / "review").glob("round-*.json"))
    maximum_rounds = settings().maximum_review_rounds
    if len(rounds) >= maximum_rounds:
        raise RunBlocked(
            f"Remote review reached the maximum of {maximum_rounds} rounds"
        )
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
    if not _is_actionable_blocker_comment(comment):
        raise RunBlocked(
            f"Comment {comment_id} is not an actionable blocker comment from "
            f"{settings().blocker_bot}"
        )
    if decision not in {"FIX", "SKIP"}:
        raise RunBlocked("Processed blocker decision must be FIX or SKIP")
    if decision == "SKIP":
        published_ids = {
            int(item)
            for item in (state.get("skipSummary") or {}).get("commentIds", [])
        }
        if comment_id not in published_ids:
            raise RunBlocked(
                f"SKIP for comment {comment_id} must be explained publicly with "
                "publish-skip-summary before it can be acknowledged"
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


def publish_skip_summary(
    state: dict[str, Any],
    *,
    input_path: Path,
) -> dict[str, Any]:
    if not state.get("pr"):
        raise RunBlocked("Cannot publish SKIP decisions before a PR has been recorded")
    try:
        payload = json.loads(input_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise RunBlocked(f"Could not read SKIP summary input: {error}") from error
    skips = payload.get("skips") if isinstance(payload, dict) else None
    if not isinstance(skips, list) or not skips:
        raise RunBlocked("SKIP summary input must contain a non-empty 'skips' array")

    provided: dict[int, dict[str, Any]] = {}
    for item in skips:
        if not isinstance(item, dict):
            raise RunBlocked("Every SKIP summary item must be an object")
        try:
            comment_id = int(item["commentId"])
        except (KeyError, TypeError, ValueError) as error:
            raise RunBlocked("Every SKIP summary item requires an integer commentId") from error
        reason = " ".join(str(item.get("reason") or "").split())
        title = " ".join(str(item.get("title") or "").split())
        if not reason:
            raise RunBlocked(f"SKIP {comment_id} requires a public reason")
        if comment_id in provided:
            raise RunBlocked(f"Duplicate SKIP comment ID: {comment_id}")
        provided[comment_id] = {
            "commentId": comment_id,
            "title": title or f"Blocker {comment_id}",
            "reason": reason,
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
    previous_summary = state.get("skipSummary") or {}
    previously_published = {
        int(item) for item in previous_summary.get("commentIds", [])
    }
    for item in previous_summary.get("items", []):
        if not isinstance(item, dict) or item.get("commentId") is None:
            continue
        pending.setdefault(
            int(item["commentId"]),
            {
                "commentId": int(item["commentId"]),
                "url": item.get("url"),
                "author": item.get("author"),
            },
        )
    for acknowledgement in state.get("reviewAcknowledgements", []):
        if acknowledgement.get("decision") != "SKIP":
            continue
        comment_id = int(acknowledgement["commentId"])
        if comment_id in previously_published:
            continue
        pending[comment_id] = {
            "commentId": comment_id,
            "url": acknowledgement.get("commentUrl"),
            "author": settings().blocker_bot,
        }

    expected_ids = set(pending)
    provided_ids = set(provided)
    if provided_ids != expected_ids:
        missing = sorted(expected_ids - provided_ids)
        unexpected = sorted(provided_ids - expected_ids)
        raise RunBlocked(
            "SKIP summary must cover exactly all remaining automated blockers; "
            f"missing={missing}, unexpected={unexpected}"
        )

    marker = f"<!-- issue-delivery-skip-summary:{state['runId']} -->"
    lines = [
        marker,
        "## Blockers revisados — SKIP",
        "",
        (
            "Revisé los siguientes blockers automatizados y no aplicaré cambios por "
            "los motivos indicados:"
        ),
        "",
    ]
    for comment_id in sorted(provided):
        decision = provided[comment_id]
        source = pending[comment_id]
        reference = (
            f"[comentario {comment_id}]({source['url']})"
            if source.get("url")
            else f"comentario {comment_id}"
        )
        lines.append(
            f"- **{decision['title']}** ({reference}): {decision['reason']}"
        )
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
    comment_reference = github.upsert_comment(pr.number, marker, body)
    published_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    receipt = {
        "publishedAt": published_at,
        "pr": pr.url,
        "headSha": snapshot.get("headSha"),
        "commentReference": comment_reference,
        "commentIds": sorted(provided),
        "items": [
            {
                **provided[comment_id],
                "url": pending[comment_id].get("url"),
                "author": pending[comment_id].get("author"),
            }
            for comment_id in sorted(provided)
        ],
        "bodyHash": hashlib.sha256(body.encode()).hexdigest(),
    }
    state["skipSummary"] = receipt
    root = run_root(worktree, state["runId"])
    path = root / "review" / "skip-summary.json"
    atomic_write_json(path, receipt)
    state.setdefault("artifacts", {})["skipSummary"] = str(path.relative_to(worktree))
    save_state(state)
    return receipt


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
        if settings().blocker_bot not in author:
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
    author = str((comment.get("user") or {}).get("login") or "").lower()
    configuration = settings()
    if not any(name in author for name in configuration.bot_names):
        return False
    if configuration.blocker_bot in author:
        return _is_actionable_blocker_comment(comment)
    return True


def _is_actionable_blocker_comment(comment: dict[str, Any]) -> bool:
    author = str((comment.get("user") or {}).get("login") or "").lower()
    if settings().blocker_bot not in author:
        return False
    body = str(comment.get("body") or "")
    match = re.search(
        r"(?is)\bblockers?\s*:\s*(.*?)(?=\n\s*[🟡🟢🔵]|\Z)",
        body,
    )
    if not match:
        return False
    content = match.group(1).strip()
    return bool(content) and not bool(
        re.match(
            r"(?is)^[-*]?\s*("
            r"ninguno|none|no blockers?|"
            r"no encontr[ée]\b.*\b(blockers?|defectos?|regresiones?)"
            r")\b",
            content,
        )
    )


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
