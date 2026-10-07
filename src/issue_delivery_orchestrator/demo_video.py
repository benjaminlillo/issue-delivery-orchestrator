from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .errors import RunBlocked
from .state import run_root


def validate_demo_video(
    state: dict[str, Any], raw: Any, *, runtime_id: str, commit: str
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RunBlocked("Runtime handoff requires a 'demoVideo' result")
    if raw.get("verifiedCommit") != commit or raw.get("runtimeId") != runtime_id:
        raise RunBlocked("Demo video must target the final commit and runtime")
    tickets = raw.get("uiTickets")
    if not isinstance(tickets, list) or any(
        not isinstance(ticket, str) or not ticket.strip() for ticket in tickets
    ) or len(tickets) != len(set(tickets)):
        raise RunBlocked("Demo video uiTickets must be an array of unique ticket IDs")
    status = raw.get("status")
    videos = raw.get("videos", [])
    if not isinstance(videos, list):
        raise RunBlocked("Demo video videos must be an array")
    reason = str(raw.get("reason") or "").strip()
    result = {
        "status": status, "verifiedCommit": commit, "runtimeId": runtime_id,
        "uiTickets": tickets, "videos": [],
    }
    if status in ("SKIPPED", "FAILED"):
        if not reason or videos:
            raise RunBlocked("Skipped or failed demo video requires a reason and no videos")
        if (status == "SKIPPED") != (not tickets):
            raise RunBlocked("Skip demo video only when there are no UI-reviewable tickets")
        return {**result, "reason": reason}
    if status != "RECORDED" or not tickets or not videos:
        raise RunBlocked("UI-reviewable tickets require RECORDED videos or an explicit FAILED result")
    worktree = Path(state["worktree"]).resolve()
    directory = run_root(worktree, state["runId"]).resolve()
    covered: set[str] = set()
    for item in videos:
        if not isinstance(item, dict):
            raise RunBlocked("Every demo video must be an object")
        ids = item.get("ticketIds")
        if not isinstance(ids, list) or not ids or any(
            not isinstance(ticket, str) or ticket not in tickets for ticket in ids
        ):
            raise RunBlocked("Every demo video must reference UI-reviewable ticket IDs")
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            raise RunBlocked("Every demo video requires a local recording path")
        candidate = (worktree / path).resolve()
        if not candidate.is_relative_to(directory):
            raise RunBlocked("Demo video recording must live inside the run directory")
        if not candidate.is_file() or candidate.stat().st_size == 0:
            raise RunBlocked("Demo video recording is missing or empty")
        video = {"ticketIds": ids, "path": str(candidate.relative_to(worktree))}
        url = item.get("url")
        if url is not None:
            try:
                parsed = urlparse(url) if isinstance(url, str) else None
            except ValueError as error:
                raise RunBlocked("Demo video URL must be a valid HTTP(S) link") from error
            if not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise RunBlocked("Demo video URL must be an HTTP(S) link accessible to the user")
            video["url"] = url
        result["videos"].append(video)
        covered.update(ids)
    if covered != set(tickets):
        raise RunBlocked("Demo videos must cover all UI-reviewable tickets")
    return result
