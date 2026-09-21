from __future__ import annotations

import json
import shlex
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .config import settings
from .errors import RunBlocked
from .runtime import _alive
from .state import handoff_mode, now, run_root, save_state
from .token_usage import collect_token_usage
from .util import atomic_write_json, read_json, run


def prepare_runtime_handoff(
    state: dict[str, Any],
    input_path: Path,
    *,
    health_timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    if state.get("status") != "preparing_final_runtime":
        raise RunBlocked("Reset the final runtime before publishing its handoff")
    runtime = _active_runtime(state)
    reset = state.get("finalRuntimeReset") or {}
    if reset.get("runtimeId") != runtime.get("runtimeId"):
        raise RunBlocked("The active runtime does not match the final reset receipt")
    try:
        manifest = read_json(Path(runtime["manifestPath"]))
    except (OSError, json.JSONDecodeError) as error:
        raise RunBlocked(f"Could not read the active Local Runtime manifest: {error}") from error
    if not isinstance(manifest, dict):
        raise RunBlocked("The active Local Runtime manifest is missing or invalid")
    urls = manifest.get("urls")
    if not isinstance(urls, dict):
        raise RunBlocked("The active Local Runtime does not declare any URLs")
    try:
        payload = read_json(input_path)
    except (OSError, json.JSONDecodeError) as error:
        raise RunBlocked(f"Could not read runtime handoff input: {error}") from error
    raw_services = payload.get("services") if isinstance(payload, dict) else None
    if not isinstance(raw_services, list) or not raw_services:
        raise RunBlocked("Runtime handoff input requires a non-empty 'services' array")

    services: list[dict[str, Any]] = []
    names: set[str] = set()
    worktree = Path(state["worktree"])
    for item in raw_services:
        if not isinstance(item, dict):
            raise RunBlocked("Every runtime handoff service must be an object")
        name = str(item.get("name") or "").strip()
        if not name or name in names:
            raise RunBlocked("Runtime handoff service names must be non-empty and unique")
        allocated_url = str(urls.get(name) or "").rstrip("/")
        if not allocated_url:
            raise RunBlocked(f"Runtime URL not found for service {name}")
        health_path = str(item.get("healthPath") or "").strip()
        if health_path and not health_path.startswith("/"):
            raise RunBlocked(f"healthPath for {name} must start with '/'")
        health_url = urljoin(f"{allocated_url}/", health_path.lstrip("/"))
        status = _health_status(health_url, health_timeout_seconds)
        log_path = _optional_worktree_file(item.get("logPath"), worktree, name)
        services.append(
            {
                "name": name,
                "url": allocated_url,
                "port": urlparse(allocated_url).port,
                "healthUrl": health_url,
                "healthStatus": status,
                **({"logPath": log_path} if log_path else {}),
            }
        )
        names.add(name)

    dirty = run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=worktree).stdout.strip()
    if dirty:
        raise RunBlocked(
            "Runtime handoff requires a clean committed worktree; "
            "commit or remove pending product changes first"
        )
    commit = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    if reset.get("verifiedCommit") != commit:
        raise RunBlocked(
            "HEAD changed after the final runtime reset; reset it again before handoff"
        )
    runtime_id = runtime["runtimeId"]
    receipt_path = run_root(worktree, state["runId"]) / "validation" / "final-runtime-handoff.json"
    manual = handoff_mode(state) == "manual-runtime"
    if not manual and not (state.get("pr") or {}).get("url"):
        raise RunBlocked("Full delivery requires a recorded PR before runtime handoff")
    token_usage = collect_token_usage(state)
    receipt = {
        "receiptVersion": 1,
        "tokenUsage": token_usage,
        "status": "READY_FOR_USER_TESTING",
        "verifiedCommit": commit,
        "runtimeId": runtime_id,
        "preparedAt": now(),
        "services": services,
        "processes": _live_runtime_processes(state, manifest),
        "cleanupCommand": shlex.join(
            [
                part.replace("{runtime_id}", runtime_id)
                for part in settings().runtime_cleanup_command
            ]
        ),
        "cleanupWorkingDirectory": str(worktree.resolve()),
        "computerUseReview": "NOT_RUN" if manual else "COMPLETED_BEFORE_RESET",
        "pullRequest": "NOT_CREATED" if manual else state["pr"]["url"],
    }
    atomic_write_json(receipt_path, receipt)
    state["finalRuntimeHandoff"] = {
        "status": "ready",
        "verifiedCommit": commit,
        "runtimeId": runtime_id,
        "receipt": str(receipt_path.relative_to(worktree)),
        "preparedAt": receipt["preparedAt"],
        "services": services,
    }
    if manual:
        state["status"] = "awaiting_manual_review"
    else:
        state["status"] = "completed_preserved"
        state["completedAt"] = now()
    state["blocker"] = None
    save_state(state)
    return {
        "receipt": receipt,
        "receiptPath": str(receipt_path),
        "processesPreserved": True,
    }


def _active_runtime(state: dict[str, Any]) -> dict[str, Any]:
    active_runtime_id = state.get("activeRuntimeId")
    runtime = next(
        (
            item
            for item in state.get("runtimes", [])
            if item.get("runtimeId") == active_runtime_id and not item.get("cleanedAt")
        ),
        None,
    )
    if not runtime:
        raise RunBlocked("Initialize and start a Local Runtime before runtime handoff")
    return runtime


def _health_status(url: str, timeout_seconds: float) -> int:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(response.status)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RunBlocked(f"Runtime URL is not healthy: {url} ({error})") from error
    if status < 200 or status >= 400:
        raise RunBlocked(f"Runtime URL is not healthy: {url} returned HTTP {status}")
    return status


def _optional_worktree_file(raw_path: Any, worktree: Path, service: str) -> str | None:
    if raw_path is None:
        return None
    path = Path(str(raw_path))
    candidate = path if path.is_absolute() else worktree / path
    try:
        resolved = candidate.resolve().relative_to(worktree.resolve())
    except ValueError as error:
        raise RunBlocked(f"logPath for {service} must live inside the worktree") from error
    absolute = worktree / resolved
    if not absolute.is_file():
        raise RunBlocked(f"logPath for {service} does not exist: {absolute}")
    return str(resolved)


def _live_runtime_processes(state: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    registry_path = manifest.get("processRegistryPath")
    if registry_path:
        candidate = Path(registry_path)
        if not candidate.is_absolute():
            candidate = Path(state["worktree"]) / candidate
        registry = read_json(candidate, {})
    else:
        registry = {}
    entries = [*registry.get("processes", []), *state.get("ownedProcesses", [])]
    processes: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in entries:
        pid = int(item.get("pid") or 0)
        if pid <= 1 or pid in seen or item.get("endedAt") or not _alive(pid):
            continue
        processes.append(
            {
                "pid": pid,
                "kind": str(item.get("app") or item.get("kind") or "runtime-process"),
                "command": str(item.get("command") or ""),
            }
        )
        seen.add(pid)
    return processes
