from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from .config import settings
from .errors import OrchestrationError
from .state import now, run_root, save_state
from .util import atomic_write_json, read_json, run


def initialize_runtime(state: dict[str, Any], *, fresh: bool = False) -> dict[str, Any]:
    worktree = Path(state["worktree"])
    configuration = settings()
    args = list(configuration.runtime_init_command)
    if fresh:
        args.append("--replace")
    run(args, cwd=worktree)
    binding = read_json(worktree / configuration.runtime_root / "worktree.json")
    if not binding or not binding.get("runtimeId") or not binding.get("manifestPath"):
        raise OrchestrationError("Local Runtime did not create a valid worktree binding")
    record = {
        "runtimeId": binding["runtimeId"],
        "manifestPath": binding["manifestPath"],
        "createdAt": binding.get("createdAt") or now(),
        "registeredAt": now(),
        "cleanedAt": None,
    }
    previous = [item for item in state["runtimes"] if item["runtimeId"] != record["runtimeId"]]
    state["runtimes"] = [*previous, record]
    state["activeRuntimeId"] = record["runtimeId"]
    save_state(state)
    return record


def register_owned_process(
    state: dict[str, Any],
    pid: int,
    *,
    kind: str,
    command: str = "",
) -> None:
    if pid <= 1 or not _alive(pid):
        raise OrchestrationError(f"Cannot register inactive or unsafe PID {pid}")
    state["ownedProcesses"] = [
        item for item in state["ownedProcesses"] if int(item["pid"]) != pid
    ]
    state["ownedProcesses"].append(
        {
            "pid": pid,
            "kind": kind,
            "command": command,
            "registeredAt": now(),
            "endedAt": None,
        }
    )
    save_state(state)


def launch_browser(state: dict[str, Any], url: str) -> dict[str, Any]:
    worktree = Path(state["worktree"])
    root = run_root(worktree, state["runId"])
    profile = root / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    binary = _browser_binary()
    log_path = root / "logs" / "browser.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(binary),
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        url,
    ]
    with log_path.open("a") as log:
        process = subprocess.Popen(
            command,
            cwd=worktree,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    time.sleep(0.5)
    if process.poll() is not None:
        raise OrchestrationError(f"Dedicated browser exited early; inspect {log_path}")
    register_owned_process(
        state,
        process.pid,
        kind="dedicated-browser",
        command=" ".join(command),
    )
    return {
        "pid": process.pid,
        "profile": str(profile),
        "log": str(log_path),
        "url": url,
    }


def stop_owned_processes(state: dict[str, Any], timeout_seconds: float = 10.0) -> list[int]:
    configuration = settings()
    registries: list[tuple[Path, dict[str, Any]]] = []
    pids: set[int] = set()
    for runtime in state.get("runtimes", []):
        manifest = read_json(Path(runtime["manifestPath"]))
        if not manifest:
            continue
        registry_path = Path(
            manifest.get("processRegistryPath")
            or Path(state["worktree"])
            / configuration.runtime_root
            / "pids"
            / f"{runtime['runtimeId']}.json"
        )
        registry = read_json(registry_path, {"runtimeId": runtime["runtimeId"], "processes": []})
        registries.append((registry_path, registry))
        for entry in registry.get("processes", []):
            if not entry.get("endedAt") and int(entry.get("pid") or 0) > 1:
                pids.add(int(entry["pid"]))
    for entry in state.get("ownedProcesses", []):
        if not entry.get("endedAt") and int(entry.get("pid") or 0) > 1:
            pids.add(int(entry["pid"]))

    stopped: list[int] = []
    descendants = _descendants(pids)
    for pid in [*descendants, *sorted(pids, reverse=True)]:
        if _terminate(pid, signal.SIGTERM):
            stopped.append(pid)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline and any(_alive(pid) for pid in stopped):
        time.sleep(0.1)
    for pid in stopped:
        if _alive(pid):
            _terminate(pid, signal.SIGKILL)

    ended_at = now()
    for registry_path, registry in registries:
        registry["processes"] = [
            {
                **entry,
                "endedAt": ended_at
                if int(entry.get("pid") or 0) in pids and not entry.get("endedAt")
                else entry.get("endedAt"),
            }
            for entry in registry.get("processes", [])
        ]
        atomic_write_json(registry_path, registry)
    state["ownedProcesses"] = [
        {
            **entry,
            "endedAt": ended_at
            if int(entry.get("pid") or 0) in pids and not entry.get("endedAt")
            else entry.get("endedAt"),
        }
        for entry in state.get("ownedProcesses", [])
    ]
    state["processesStoppedAt"] = ended_at
    save_state(state)
    return sorted(set(stopped))


def cleanup_runtimes(state: dict[str, Any]) -> list[str]:
    worktree = Path(state["worktree"])
    cleaned: list[str] = []
    for runtime in state.get("runtimes", []):
        if runtime.get("cleanedAt"):
            continue
        runtime_id = runtime["runtimeId"]
        manifest_path = Path(runtime["manifestPath"])
        if manifest_path.exists():
            command = [
                part.replace("{runtime_id}", runtime_id)
                for part in settings().runtime_cleanup_command
            ]
            run(command, cwd=worktree)
        runtime["cleanedAt"] = now()
        cleaned.append(runtime_id)
    state["activeRuntimeId"] = None
    save_state(state)
    return cleaned


def _descendants(roots: set[int]) -> list[int]:
    if not roots:
        return []
    result = run(["ps", "-axo", "pid=,ppid="], check=False)
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        pid, parent = map(int, parts)
        children.setdefault(parent, []).append(pid)
    ordered: list[int] = []

    def visit(parent: int) -> None:
        for child in children.get(parent, []):
            visit(child)
            ordered.append(child)

    for root in roots:
        visit(root)
    return list(dict.fromkeys(ordered))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _terminate(pid: int, sig: signal.Signals) -> bool:
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError as error:
        raise OrchestrationError(f"Cannot stop owned PID {pid}: {error}") from error


def _browser_binary() -> Path:
    override = settings().browser_binary
    candidates = [
        Path(override) if override else None,
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise OrchestrationError(
        "No Chrome/Chromium binary found. Set ISSUE_DELIVERY_BROWSER explicitly."
    )
