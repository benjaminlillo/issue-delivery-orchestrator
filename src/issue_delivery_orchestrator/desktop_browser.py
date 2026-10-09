"""Open the final runtime in Chrome on the Conductor Cloud virtual desktop.

Conductor starts its desktop (Xvnc on DISPLAY :1) only when the user opens it from the app, so
the launcher waits for the display socket in a detached process and then becomes Chrome.
"""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .config import settings
from .errors import RunBlocked
from .runtime import _alive, register_owned_process
from .state import now, run_root, save_state
from .util import read_json, run

DISPLAY = ":1"
DISPLAY_SOCKET = Path("/tmp/.X11-unix/X1")
WAIT_SECONDS = 24 * 60 * 60
BROWSERS = ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")


def desktop_profile(state: dict[str, Any]) -> Path:
    return run_root(Path(state["worktree"]), state["runId"]) / "desktop-browser" / "profile"


def open_desktop_browser(state: dict[str, Any], service: str, path: str) -> dict[str, Any]:
    if state.get("status") != "preparing_final_runtime":
        raise RunBlocked("Open the desktop browser while preparing the final runtime handoff")
    runtime_id = state.get("activeRuntimeId")
    reset = state.get("finalRuntimeReset") or {}
    if not runtime_id or reset.get("runtimeId") != runtime_id:
        raise RunBlocked("The active runtime does not match the final reset receipt")
    if not path.startswith("/"):
        raise RunBlocked("Desktop browser path must start with '/'")
    runtime = next(item for item in state["runtimes"] if item["runtimeId"] == runtime_id)
    urls = (read_json(Path(runtime["manifestPath"]), {}) or {}).get("urls") or {}
    base = str(urls.get(service) or "").rstrip("/")
    if not base:
        raise RunBlocked(f"Runtime URL not found for service {service}")
    url = f"{base}{path}"
    worktree = Path(state["worktree"])
    commit = run(["git", "rev-parse", "HEAD"], cwd=worktree).stdout.strip()
    if reset.get("verifiedCommit") != commit:
        raise RunBlocked("HEAD changed after the final runtime reset; reset it again first")

    previous = state.get("desktopBrowser") or {}
    if previous.get("pid") and _alive(int(previous["pid"])):
        os.kill(int(previous["pid"]), signal.SIGTERM)
        time.sleep(1)
    profile = desktop_profile(state)
    profile.mkdir(parents=True, exist_ok=True)
    if _profile_in_use(profile):
        raise RunBlocked(f"Close the browser that is using {profile} before opening the desktop window")

    log_path = run_root(worktree, state["runId"]) / "logs" / "desktop-browser.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cdp_port = _free_port()
    command = [
        sys.executable, "-m", "issue_delivery_orchestrator.desktop_browser",
        _browser_binary(), str(profile), url, str(cdp_port),
    ]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    desktop_ready = DISPLAY_SOCKET.exists()
    with log_path.open("a") as log:
        process = subprocess.Popen(
            command, cwd=worktree, env=env, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    time.sleep(2)
    if process.poll() is not None:
        raise RunBlocked(f"Desktop browser exited early; inspect {log_path}")
    register_owned_process(state, process.pid, kind="desktop-browser", command=" ".join(command))
    state["desktopBrowser"] = {
        "status": "OPENED" if desktop_ready else "PENDING",
        "verifiedCommit": commit,
        "runtimeId": runtime_id,
        "service": service,
        "url": url,
        "display": DISPLAY,
        "pid": process.pid,
        "cdpUrl": f"http://127.0.0.1:{cdp_port}",
        "profile": str(profile.relative_to(worktree)),
        "openedAt": now(),
    }
    save_state(state)
    return {**state["desktopBrowser"], "log": str(log_path.relative_to(worktree))}


def validate_desktop_browser(state: dict[str, Any], *, runtime_id: str, commit: str) -> dict[str, Any]:
    record = state.get("desktopBrowser") or {}
    if record.get("verifiedCommit") != commit or record.get("runtimeId") != runtime_id:
        raise RunBlocked("Open the final runtime on the Conductor desktop with desktop-browser first")
    if not _alive(int(record.get("pid") or 0)):
        raise RunBlocked("The desktop browser is no longer running; run desktop-browser again")
    return {key: record[key] for key in ("status", "service", "url", "display", "pid", "cdpUrl", "profile")}


def _profile_in_use(profile: Path) -> bool:
    try:
        target = os.readlink(profile / "SingletonLock")
    except OSError:
        return False
    pid = target.rsplit("-", 1)[-1]
    return pid.isdigit() and _alive(int(pid))


def _browser_binary() -> str:
    for candidate in (settings().browser_binary, *BROWSERS):
        resolved = shutil.which(candidate) if candidate else None
        if resolved:
            return resolved
    raise RunBlocked("No Chrome/Chromium binary found. Set ISSUE_DELIVERY_BROWSER explicitly.")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_and_exec(binary: str, profile: str, url: str, cdp_port: str) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    waited = False
    while not DISPLAY_SOCKET.exists():
        if time.monotonic() > deadline:
            raise SystemExit("Conductor desktop never started")
        waited = True
        time.sleep(2)
    if waited:
        # Let the window manager start so the window opens maximized.
        time.sleep(3)
    os.execvpe(binary, [
        binary, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
        "--disable-dev-shm-usage", "--disable-gpu", "--start-maximized",
        # Lets the agent sign in and reach the starting point in the visible window.
        "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={cdp_port}",
        "--new-window", url,
    ], {**os.environ, "DISPLAY": DISPLAY})


if __name__ == "__main__":
    _wait_and_exec(*sys.argv[1:5])
