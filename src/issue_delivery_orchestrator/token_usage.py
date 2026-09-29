from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .harness import detect_host


FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")
# Claude Code also reports cache writes; they are included in input_tokens.
CACHE_WRITE = "cache_creation_input_tokens"
# Usage after the last completed checkpoint: final runtime reset, handoff and later adjustments.
TAIL_PHASE = "final-handoff"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _threads(home: Path) -> dict[str, dict[str, Any]]:
    uri = f"{(home / 'state_5.sqlite').as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=0.1)) as db:
        rows = db.execute("SELECT id, rollout_path, source FROM threads").fetchall()
    threads = {}
    for thread_id, path, source in rows:
        parent = None
        if source and source.startswith("{"):
            spawn = json.loads(source).get("subagent", {}).get("thread_spawn", {})
            parent = spawn.get("parent_thread_id")
        threads[thread_id] = {"path": path, "parent": parent}
    return threads


def _tree(threads: dict[str, dict[str, Any]], roots: list[str]) -> set[str]:
    selected = set(roots)
    while True:
        children = {key for key, value in threads.items() if value["parent"] in selected}
        expanded = selected | children
        if expanded == selected:
            return selected
        selected = expanded


def _counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict) or any(
        type(value.get(key)) is not int or value[key] < 0 for key in FIELDS
    ):
        raise ValueError("Unsupported token counters")
    return {key: value[key] for key in FIELDS}


def _read(
    path: str,
    cursor: dict[str, Any],
    *,
    baseline: bool = False,
    phase_at: Callable[[datetime], str] | None = None,
) -> None:
    with Path(path).open("rb") as stream:
        stream.seek(0, 2)
        if stream.tell() < cursor["offset"]:
            raise ValueError("Session log was truncated")
        stream.seek(cursor["offset"])
        while line := stream.readline():
            if not line.endswith(b"\n"):
                break
            event = json.loads(line)
            payload = event.get("payload") or {}
            if event.get("type") == "session_meta" and payload.get("id") == cursor["id"]:
                cursor["createdAt"] = event.get("timestamp")
            if payload.get("type") == "token_count" and payload.get("info"):
                info = payload["info"]
                total = _counts(info["total_token_usage"])
                last = _counts(info["last_token_usage"])
                previous = cursor.get("previous")
                stamp = event.get("timestamp")
                created = cursor.get("createdAt")
                own_event = bool(created and stamp and _time(stamp) >= _time(created))
                if not baseline and own_event and (not cursor.get("hasOwnUsage") or total != previous):
                    if not cursor.get("hasOwnUsage"):
                        delta = last
                    else:
                        delta = {key: total[key] - previous[key] for key in FIELDS}
                        if any(value < 0 for value in delta.values()):
                            raise ValueError("Session token counters decreased")
                    for key in FIELDS:
                        cursor["usage"][key] += delta[key]
                    if phase_at:
                        _add(cursor.setdefault("byPhase", {}), phase_at(_time(stamp)), delta)
                if own_event:
                    cursor["hasOwnUsage"] = True
                cursor["previous"] = total
            cursor["offset"] = stream.tell()
    if not cursor.get("createdAt"):
        raise ValueError("Session metadata unavailable")


def _add(buckets: dict[str, dict[str, int]], key: str, counts: dict[str, int]) -> None:
    bucket = buckets.setdefault(key, {})
    for field, value in counts.items():
        bucket[field] = bucket.get(field, 0) + value


def _phase_clock(state: dict[str, Any]) -> Callable[[datetime], str]:
    """Attribute a moment to the phase whose checkpoint had not completed yet."""
    completions = sorted(
        (_time(item["completedAt"]), item["phase"])
        for item in state.get("phases", [])
        if item.get("status") == "completed" and item.get("completedAt")
    )

    def phase_at(stamp: datetime) -> str:
        return next((phase for completed, phase in completions if stamp <= completed), TAIL_PHASE)

    return phase_at


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _cursor(thread_id: str) -> dict[str, Any]:
    return {"id": thread_id, "offset": 0, "usage": dict.fromkeys(FIELDS, 0)}


def attach_token_usage(state: dict[str, Any], *, new_run: bool = False, resume: bool = False) -> None:
    """Register the current session and record whether its usage can be measured."""
    tracking = state.setdefault("tokenUsageTracking", {
        "roots": [], "sessions": {}, "issues": [], "startedAt": _now(),
    })
    if not new_run and not tracking["roots"] and not (tracking.get("claude") or {}).get("sessions"):
        _issue(tracking, "No baseline for the earlier part of this run")
    host, session_id = detect_host()
    if resume and host in {"codex", "claude"}:
        _freeze_other_host(tracking, host)
    if host == "codex":
        registered = _attach_codex(tracking, session_id, resume)
    elif host == "claude":
        registered = _attach_claude(tracking, session_id, resume)
    else:
        registered = False
        _issue(tracking, (
            "Ambiguous session: both Codex and Claude Code session variables are set"
            if host == "ambiguous" else "No Codex or Claude Code session detected"
        ))
    tracking["startCheck"] = {
        "status": "unavailable" if not registered else "partial" if tracking["issues"] else "ready",
        "harness": host,
        "sessionId": session_id,
        "checkedAt": _now(),
        "issues": list(tracking["issues"]),
    }


def _freeze_other_host(tracking: dict[str, Any], host: str) -> None:
    """A resume in another host ends measurement of the previous host's sessions."""
    if host == "claude":
        tracking["activeRoots"] = []
        for cursor in tracking["sessions"].values():
            cursor["frozen"] = True
        return
    claude = tracking.get("claude") or {}
    _close_claude_windows(claude)


def _close_claude_windows(claude: dict[str, Any]) -> None:
    # Usage between the last collection and this resume belongs to no run.
    closed_at = claude.get("lastCollectedAt") or _now()
    for session in claude.get("sessions", {}).values():
        if session["windows"][-1][1] is None:
            session["windows"][-1][1] = closed_at


def _attach_codex(tracking: dict[str, Any], thread_id: str, resume: bool) -> bool:
    if not resume and (thread_id in tracking["roots"] or thread_id in tracking["sessions"]):
        return bool(tracking["sessions"].get(thread_id, {}).get("baselineReady"))
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()
    if tracking.get("codexHome") and tracking["codexHome"] != str(home):
        _issue(tracking, "Codex home changed; additional session not measured")
        return False
    tracking["codexHome"] = str(home)
    if thread_id not in tracking["roots"]:
        tracking["roots"].append(thread_id)
    try:
        threads = _threads(home)
        selected = _tree(threads, [thread_id])
        if resume:
            tracking["activeRoots"] = [thread_id]
            for key, cursor in tracking["sessions"].items():
                cursor["frozen"] = key not in selected
        else:
            tracking.setdefault("activeRoots", []).append(thread_id)
            selected -= tracking["sessions"].keys()
        for key in selected:
            cursor = tracking["sessions"].get(key) or _cursor(key)
            tracking["sessions"][key] = cursor
            try:
                _read(threads[key]["path"], cursor, baseline=True)
                cursor["baselineReady"] = True
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                cursor["baselineReady"] = False
                _issue(tracking, f"Baseline unavailable for {key}: {type(error).__name__}")
    except (OSError, ValueError, sqlite3.Error, TypeError, AttributeError):
        _issue(tracking, "Codex session index unavailable at start")
        cursor = tracking["sessions"].setdefault(thread_id, _cursor(thread_id))
        cursor["baselineReady"] = False
    return bool(tracking["sessions"].get(thread_id, {}).get("baselineReady"))


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser().resolve()


def _claude_log(home: Path, session_id: str) -> Path:
    matches = sorted((home / "projects").glob(f"*/{session_id}.jsonl"))
    if len(matches) != 1:
        raise ValueError("not found" if not matches else "found in several projects")
    return matches[0]


def _attach_claude(tracking: dict[str, Any], session_id: str | None, resume: bool) -> bool:
    if not session_id:
        _issue(tracking, "CLAUDE_CODE_SESSION_ID unavailable")
        return False
    claude = tracking.setdefault("claude", {"sessions": {}})
    home = _claude_home()
    if claude.get("home") and claude["home"] != str(home):
        _issue(tracking, "Claude Code config directory changed; additional session not measured")
        return False
    session = claude["sessions"].get(session_id)
    if session and not resume and session["windows"][-1][1] is None:
        return True
    try:
        path = _claude_log(home, session_id)
    except (OSError, ValueError) as error:
        _issue(tracking, f"Claude Code session log {error}")
        return False
    claude["home"] = str(home)
    if resume:
        _close_claude_windows(claude)
    session = claude["sessions"].setdefault(session_id, {"path": str(path), "windows": []})
    if not session["windows"] or session["windows"][-1][1] is not None:
        session["windows"].append([_now(), None])
    return True


def _claude_counts(usage: Any) -> dict[str, int]:
    if not isinstance(usage, dict):
        raise ValueError("Unsupported token counters")
    values = {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read": usage.get("cache_read_input_tokens", 0),
        CACHE_WRITE: usage.get(CACHE_WRITE, 0),
    }
    if any(type(value) is not int or value < 0 for value in values.values()):
        raise ValueError("Unsupported token counters")
    input_tokens = values["input_tokens"] + values["cache_read"] + values[CACHE_WRITE]
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": values["cache_read"],
        "output_tokens": values["output_tokens"],
        "total_tokens": input_tokens + values["output_tokens"],
        CACHE_WRITE: values[CACHE_WRITE],
    }


def _claude_messages(
    log: Path, issues: list[str]
) -> dict[str, tuple[datetime, dict[str, int], str]]:
    """Read one usage record per API message from a session and its subagents.

    An unreadable principal log fails the session; an unreadable subagent log is excluded and
    reported, so one damaged worker does not discard the rest of the run.
    """
    messages = _claude_log_messages(log, "principal")
    for path in sorted((log.parent / log.stem / "subagents").rglob("*.jsonl")):
        try:
            found = _claude_log_messages(path, "subagents")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            issues.append(f"Claude Code subagent log {path.name} unavailable: {type(error).__name__}")
            continue
        for message_id, record in found.items():
            messages.setdefault(message_id, record)
    return messages


def _claude_log_messages(path: Path, role: str) -> dict[str, tuple[datetime, dict[str, int], str]]:
    messages: dict[str, tuple[datetime, dict[str, int], str]] = {}
    with path.open("rb") as stream:
        for line in stream:
            if not line.endswith(b"\n"):
                break
            entry = json.loads(line)
            message = entry.get("message")
            if not isinstance(message, dict) or "usage" not in message:
                continue
            # A message is logged once per content block with the same usage.
            if message["id"] not in messages:
                messages[message["id"]] = (
                    _time(entry["timestamp"]), _claude_counts(message["usage"]), role,
                )
    return messages


def _collect_claude(
    tracking: dict[str, Any],
    issues: list[str],
    phase_at: Callable[[datetime], str],
    by_phase: dict[str, dict[str, dict[str, int]]],
) -> tuple[dict[str, int], int]:
    claude = tracking["claude"]
    selected: dict[str, dict[str, int]] = {}
    measured = 0
    for key, session in claude["sessions"].items():
        try:
            messages = _claude_messages(Path(session["path"]), issues)
            windows = [(_time(start), _time(end) if end else None) for start, end in session["windows"]]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            issues.append(f"Claude Code session {key} unavailable: {type(error).__name__}")
            continue
        for message_id, (stamp, counts, role) in messages.items():
            if message_id in selected:
                continue
            if any(stamp >= start and (end is None or stamp <= end) for start, end in windows):
                selected[message_id] = counts
                _add(by_phase.setdefault(phase_at(stamp), {}), role, counts)
        measured += 1
    claude["lastCollectedAt"] = _now()
    keys = (*FIELDS, CACHE_WRITE)
    return {key: sum(counts[key] for counts in selected.values()) for key in keys}, measured


def _issue(tracking: dict[str, Any], message: str) -> None:
    if message not in tracking["issues"]:
        tracking["issues"].append(message)


def collect_token_usage(state: dict[str, Any]) -> dict[str, Any]:
    tracking = state.get("tokenUsageTracking") or {
        "roots": [], "sessions": {}, "issues": ["Run has no token usage baseline"],
    }
    issues = list(tracking["issues"])
    measured = 0
    scopes = []
    totals: dict[str, int] = dict.fromkeys(FIELDS, 0)
    phase_at = _phase_clock(state)
    by_phase: dict[str, dict[str, dict[str, int]]] = {}
    if tracking["roots"] or tracking["sessions"]:
        scopes.append("codex_session_tree")
        measured += _collect_codex(tracking, issues, phase_at)
        for key, cursor in tracking["sessions"].items():
            for field in FIELDS:
                totals[field] += cursor["usage"][field]
            role = "principal" if key in tracking["roots"] else "subagents"
            for phase, counts in (cursor.get("byPhase") or {}).items():
                _add(by_phase.setdefault(phase, {}), role, counts)
    if (tracking.get("claude") or {}).get("sessions"):
        scopes.append("claude_session_tree")
        claude, claude_measured = _collect_claude(tracking, issues, phase_at, by_phase)
        measured += claude_measured
        for key, value in claude.items():
            totals[key] = totals.get(key, 0) + value
    attributed = sum(
        counts["total_tokens"] for roles in by_phase.values() for counts in roles.values()
    )
    if totals["total_tokens"] > attributed:
        # Usage measured before per-phase attribution existed (runs started on older versions).
        by_phase["unattributed"] = {"unknown": {"total_tokens": totals["total_tokens"] - attributed}}
    available = bool(measured or totals["total_tokens"])
    status = "complete" if measured and not issues else "partial" if available else "unavailable"
    report = {
        "status": status,
        "scope": "+".join(scopes) or None,
        "measuredAt": _now(),
        "sessions": len(tracking["sessions"]) + len((tracking.get("claude") or {}).get("sessions", {})),
        "usage": totals if available else None,
        "byPhase": by_phase if available else None,
        "issues": sorted(set(issues)),
    }
    state["tokenUsage"] = report
    return report


def _collect_codex(
    tracking: dict[str, Any], issues: list[str], phase_at: Callable[[datetime], str]
) -> int:
    measured = 0
    try:
        threads = _threads(Path(tracking["codexHome"]))
        for key in _tree(threads, tracking.get("activeRoots", tracking["roots"])) | tracking["sessions"].keys():
            cursor = tracking["sessions"].get(key)
            if cursor is None:
                cursor = _cursor(key)
                cursor["baselineReady"] = True
                tracking["sessions"][key] = cursor
            if not cursor.get("baselineReady"):
                issues.append(f"Session {key} has no reliable baseline")
                continue
            try:
                if not cursor.get("frozen"):
                    _read(threads[key]["path"], cursor, phase_at=phase_at)
                if not cursor.get("hasOwnUsage"):
                    raise ValueError("No recorded usage yet")
                measured += 1
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                issues.append(f"Session {key} unavailable: {type(error).__name__}")
    except (OSError, ValueError, KeyError, sqlite3.Error, TypeError, AttributeError):
        issues.append("Codex session index unavailable at collection")
    return measured
