"""Open the handed-off runtime in Chrome on the Conductor Cloud virtual desktop, on request.

During the final handoff the agent writes a replay script that signs in and reaches the starting
point of the change, and rehearses it headlessly. After the run, when the user has opened the
desktop (Xvnc on DISPLAY :1, started by Conductor) and asks for it, the same script drives a
visible Chrome window there.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from .config import settings
from .errors import RunBlocked
from .runtime import _alive, register_owned_process
from .state import now, run_root, save_state
from .util import read_json, run

DISPLAY = ":1"
DISPLAY_SOCKET = Path("/tmp/.X11-unix/X1")
# Matches the geometry Conductor gives its desktop, so the rehearsal sees the same layout.
WINDOW_SIZE = "1440,900"
REPLAY_TIMEOUT_SECONDS = 300
BROWSERS = ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")
HANDED_OFF_STATUSES = {"awaiting_manual_review", "completed_preserved"}


def prepare_desktop_replay(
    state: dict[str, Any], service: str, path: str, replay: Path
) -> dict[str, Any]:
    if state.get("status") not in {"preparing_final_runtime", *HANDED_OFF_STATUSES}:
        raise RunBlocked("Prepare the desktop replay during or after the final runtime handoff")
    runtime_id, commit = _final_runtime(state)
    if not path.startswith("/"):
        raise RunBlocked("Desktop replay path must start with '/'")
    runtime = next(item for item in state["runtimes"] if item["runtimeId"] == runtime_id)
    urls = (read_json(Path(runtime["manifestPath"]), {}) or {}).get("urls") or {}
    base = str(urls.get(service) or "").rstrip("/")
    if not base:
        raise RunBlocked(f"Runtime URL not found for service {service}")
    worktree = Path(state["worktree"])
    root = run_root(worktree, state["runId"])
    replay = replay.resolve()
    if not replay.is_relative_to(root.resolve()) or not replay.is_file():
        raise RunBlocked("The desktop replay script must be a file inside the run directory")
    url = f"{base}{path}"
    log_path = _log_path(state)
    port = _free_port()
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as profile, log_path.open("a") as log:
        chrome = subprocess.Popen(
            [*_chrome_args(_browser_binary(), profile, port), "--headless=new",
             f"--window-size={WINDOW_SIZE}", url],
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            code = _replay(replay, port, url, log)
        finally:
            _stop_group(chrome.pid)
            chrome.wait(5)
    if code != 0:
        raise RunBlocked(f"The desktop replay did not reach the starting point; inspect {log_path}")
    state["desktopReplay"] = {
        "verifiedCommit": commit,
        "runtimeId": runtime_id,
        "service": service,
        "url": url,
        "replay": str(replay.relative_to(worktree.resolve())),
        "rehearsal": {"status": "REACHED", "durationMs": int((time.monotonic() - started) * 1000)},
        "preparedAt": now(),
    }
    save_state(state)
    return state["desktopReplay"]


def open_desktop_browser(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("status") not in HANDED_OFF_STATUSES:
        raise RunBlocked("Open the desktop browser after the final runtime handoff")
    runtime_id, commit = _final_runtime(state)
    prepared = state.get("desktopReplay") or {}
    if prepared.get("runtimeId") != runtime_id or prepared.get("verifiedCommit") != commit:
        raise RunBlocked("No desktop replay prepared for the handed-off runtime; prepare it first")
    if not DISPLAY_SOCKET.exists():
        raise RunBlocked("The Conductor desktop is not open; open it from the app and ask again")
    worktree = Path(state["worktree"])
    previous = state.get("desktopBrowser") or {}
    if previous.get("pid") and _alive(int(previous["pid"])):
        _stop_group(int(previous["pid"]))
    profile = run_root(worktree, state["runId"]) / "desktop-browser" / "profile"
    preferences = profile / "Default" / "Preferences"
    if not preferences.exists():
        # Keep Chrome's save-password bubble from covering the app after the replay signs in.
        preferences.parent.mkdir(parents=True, exist_ok=True)
        preferences.write_text(json.dumps({
            "credentials_enable_service": False,
            "profile": {"password_manager_enabled": False},
        }))
    if _profile_in_use(profile):
        raise RunBlocked(f"Close the browser that is using {profile} before opening the desktop window")
    log_path = _log_path(state)
    port = _free_port()
    url = prepared["url"]
    command = [*_chrome_args(_browser_binary(), str(profile), port), "--start-maximized",
               "--new-window", url]
    with log_path.open("a") as log:
        chrome = subprocess.Popen(
            command, cwd=worktree, env={**os.environ, "DISPLAY": DISPLAY}, stdout=log,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
        )
        code = _replay(worktree / prepared["replay"], port, url, log)
    if chrome.poll() is not None:
        raise RunBlocked(f"Desktop browser exited early; inspect {log_path}")
    register_owned_process(state, chrome.pid, kind="desktop-browser", command=" ".join(command))
    state["desktopBrowser"] = {
        "status": "REACHED" if code == 0 else "OPENED_WITHOUT_STARTING_POINT",
        "verifiedCommit": commit,
        "runtimeId": runtime_id,
        "url": url,
        "pid": chrome.pid,
        "cdpUrl": f"http://127.0.0.1:{port}",
        "log": str(log_path.relative_to(worktree)),
        "openedAt": now(),
    }
    save_state(state)
    return state["desktopBrowser"]


def _final_runtime(state: dict[str, Any]) -> tuple[str, str]:
    runtime_id = state.get("activeRuntimeId")
    reset = state.get("finalRuntimeReset") or {}
    if not runtime_id or reset.get("runtimeId") != runtime_id:
        raise RunBlocked("The active runtime does not match the final reset receipt")
    commit = run(["git", "rev-parse", "HEAD"], cwd=Path(state["worktree"])).stdout.strip()
    if reset.get("verifiedCommit") != commit:
        raise RunBlocked("HEAD changed after the final runtime reset; reset it again first")
    return runtime_id, commit


def _log_path(state: dict[str, Any]) -> Path:
    path = run_root(Path(state["worktree"]), state["runId"]) / "logs" / "desktop-browser.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _replay(replay: Path, port: int, url: str, log: Any) -> int:
    cdp_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while True:
        try:
            urllib.request.urlopen(f"{cdp_url}/json/version", timeout=2).close()
            break
        except OSError:
            if time.monotonic() > deadline:
                log.write("Chrome did not expose its debugging endpoint\n")
                return 1
            time.sleep(0.5)
    log.flush()
    try:
        return subprocess.run(
            [_node_binary(), str(replay), cdp_url, url], cwd=replay.parent, stdout=log,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=REPLAY_TIMEOUT_SECONDS,
        ).returncode
    except subprocess.TimeoutExpired:
        log.write("Replay timed out\n")
        return 1


def _chrome_args(binary: str, profile: str, port: int) -> list[str]:
    return [
        binary, f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
        "--disable-dev-shm-usage", "--disable-gpu",
        "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}",
    ]


def _stop_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _alive(pid):
        try:
            # Reap our own children so they do not linger as zombies.
            if os.waitpid(pid, os.WNOHANG)[0]:
                return
        except ChildProcessError:
            pass
        time.sleep(0.1)


def _profile_in_use(profile: Path) -> bool:
    try:
        target = os.readlink(profile / "SingletonLock")
    except OSError:
        return False
    pid = target.rsplit("-", 1)[-1]
    return pid.isdigit() and _alive(int(pid))


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _browser_binary() -> str:
    for candidate in (settings().browser_binary, *BROWSERS):
        resolved = shutil.which(candidate) if candidate else None
        if resolved:
            return resolved
    raise RunBlocked("No Chrome/Chromium binary found. Set ISSUE_DELIVERY_BROWSER explicitly.")


def _node_binary() -> str:
    resolved = shutil.which("node")
    if not resolved:
        raise RunBlocked("Node.js is required to replay the desktop starting point")
    return resolved
