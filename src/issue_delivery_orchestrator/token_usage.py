from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")


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


def _read(path: str, cursor: dict[str, Any], *, baseline: bool = False) -> None:
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
                if own_event:
                    cursor["hasOwnUsage"] = True
                cursor["previous"] = total
            cursor["offset"] = stream.tell()
    if not cursor.get("createdAt"):
        raise ValueError("Session metadata unavailable")


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _cursor(thread_id: str) -> dict[str, Any]:
    return {"id": thread_id, "offset": 0, "usage": dict.fromkeys(FIELDS, 0)}


def attach_token_usage(state: dict[str, Any], *, new_run: bool = False, resume: bool = False) -> None:
    tracking = state.setdefault("tokenUsageTracking", {
        "roots": [], "sessions": {}, "issues": [], "startedAt": _now(),
    })
    if not new_run and not tracking["roots"]:
        _issue(tracking, "No baseline for the earlier part of this run")
    thread_id = os.environ.get("CODEX_THREAD_ID")
    if not thread_id:
        _issue(tracking, "CODEX_THREAD_ID unavailable")
        return
    if not resume and (thread_id in tracking["roots"] or thread_id in tracking["sessions"]):
        return
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()
    if tracking.get("codexHome") and tracking["codexHome"] != str(home):
        _issue(tracking, "Codex home changed; additional session not measured")
        return
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


def _issue(tracking: dict[str, Any], message: str) -> None:
    if message not in tracking["issues"]:
        tracking["issues"].append(message)


def collect_token_usage(state: dict[str, Any]) -> dict[str, Any]:
    tracking = state.get("tokenUsageTracking") or {
        "roots": [], "sessions": {}, "issues": ["Run has no token usage baseline"],
    }
    issues = list(tracking["issues"])
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
                    _read(threads[key]["path"], cursor)
                if not cursor.get("hasOwnUsage"):
                    raise ValueError("No recorded usage yet")
                measured += 1
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                issues.append(f"Session {key} unavailable: {type(error).__name__}")
    except (OSError, ValueError, KeyError, sqlite3.Error, TypeError, AttributeError):
        issues.append("Codex session index unavailable at collection")
    totals = {
        key: sum(cursor["usage"][key] for cursor in tracking["sessions"].values())
        for key in FIELDS
    }
    available = bool(measured or totals["total_tokens"])
    status = "complete" if measured and not issues else "partial" if available else "unavailable"
    report = {
        "status": status,
        "scope": "codex_session_tree",
        "measuredAt": _now(),
        "sessions": len(tracking["sessions"]),
        "usage": totals if available else None,
        "issues": sorted(set(issues)),
    }
    state["tokenUsage"] = report
    return report
