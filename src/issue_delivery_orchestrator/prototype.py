"""Share a cheap UI prototype during Grill and publish the approved one."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from . import desktop_browser
from .errors import RunBlocked
from .linear import LinearClient, upsert_markdown_section
from .runtime import _alive, register_owned_process
from .state import now, run_root, save_state
from .util import atomic_write_json, read_json

LINEAR_SECTION = "Prototipo aprobado"


def prototype_root(state: dict[str, Any]) -> Path:
    return run_root(Path(state["worktree"]), state["runId"]) / "prototype"


def open_prototype(state: dict[str, Any], page: Path, *, desktop: bool = False) -> dict[str, Any]:
    root = prototype_root(state).resolve()
    page = page.resolve()
    if not page.is_relative_to(root) or not page.is_file():
        raise RunBlocked(f"The prototype page must be a file inside {root}")
    shown = _open_on_desktop(state, root, page) if desktop else _share_preview(state, root, page)
    state["prototype"] = {
        **(state.get("prototype") or {}),
        **shown,
        "status": "IN_REVIEW",
        "page": str(page.relative_to(Path(state["worktree"]).resolve())),
        "openedAt": now(),
    }
    save_state(state)
    return state["prototype"]


def _share_preview(state: dict[str, Any], root: Path, page: Path) -> dict[str, Any]:
    """Serve the prototype directory and share it at the workspace's Conductor preview URL."""
    previous = state.get("prototype") or {}
    pid, port = previous.get("serverPid"), previous.get("serverPort")
    if not (pid and port and _alive(int(pid)) and _serves(int(port))):
        port = desktop_browser._free_port()
        command = [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                   "--directory", str(root)]
        with (root / "prototype-server.log").open("a") as log:
            server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + 10
        while not _serves(port):
            if server.poll() is not None or time.monotonic() > deadline:
                raise RunBlocked(f"The prototype server did not start; inspect {root / 'prototype-server.log'}")
            time.sleep(0.2)
        register_owned_process(state, server.pid, kind="prototype-server", command=" ".join(command))
        pid = server.pid
    result = subprocess.run(["conductor", "preview", "set", "--port", str(port), "--json"],
                            capture_output=True, text=True)
    try:
        base = json.loads(result.stdout)["preview"]["url"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RunBlocked(
            f"Conductor did not share the prototype preview ({detail}); retry or use --desktop"
        ) from error
    url = urljoin(base if base.endswith("/") else f"{base}/", quote(str(page.relative_to(root))))
    return {"serverPid": pid, "serverPort": port, "url": url}


def _serves(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2).close()
        return True
    except OSError:
        return False


def _open_on_desktop(state: dict[str, Any], root: Path, page: Path) -> dict[str, Any]:
    if not desktop_browser.DISPLAY_SOCKET.exists():
        raise RunBlocked(
            "The Conductor desktop is not open; ask the user to open it from the app and "
            "wait for them to confirm before opening the prototype"
        )
    previous = (state.get("prototype") or {}).get("pid")
    if previous and _alive(int(previous)):
        desktop_browser._stop_group(int(previous))
    profile = root / "profile"
    profile.mkdir(parents=True, exist_ok=True)
    if desktop_browser._profile_in_use(profile):
        raise RunBlocked(f"Close the browser that is using {profile} before opening the prototype")
    command = [
        desktop_browser._browser_binary(), f"--user-data-dir={profile}", "--no-first-run",
        "--no-default-browser-check", "--disable-dev-shm-usage", "--disable-gpu",
        "--start-maximized", "--new-window", page.as_uri(),
    ]
    log_path = root / "prototype-browser.log"
    with log_path.open("a") as log:
        chrome = subprocess.Popen(
            command, env={**os.environ, "DISPLAY": desktop_browser.DISPLAY}, stdout=log,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
        )
    time.sleep(2)
    if chrome.poll() is not None:
        raise RunBlocked(f"The prototype window exited early; inspect {log_path}")
    register_owned_process(state, chrome.pid, kind="prototype-browser", command=" ".join(command))
    return {"pid": chrome.pid}


def approve_prototype(
    state: dict[str, Any],
    *,
    linear: LinearClient | None,
    manifest: Path | None = None,
    skip_reason: str = "",
) -> dict[str, Any]:
    """Record the approved prototype, or why there is none, before the spec is finalized."""
    if state.get("currentPhase") != "grill":
        raise RunBlocked("Approve or skip the prototype during Grill, before the spec is approved")
    worktree = Path(state["worktree"]).resolve()
    if skip_reason.strip():
        state["prototype"] = {
            "status": "SKIPPED", "reason": " ".join(skip_reason.split()), "decidedAt": now(),
        }
        save_state(state)
        return state["prototype"]
    if manifest is None or linear is None:
        raise RunBlocked("Approve the prototype with a manifest of its screenshots")
    root = prototype_root(state).resolve()
    payload = read_json(manifest.resolve(), None)
    screenshots = payload.get("screenshots") if isinstance(payload, dict) else None
    if not isinstance(screenshots, list) or not screenshots:
        raise RunBlocked("The prototype manifest needs a non-empty 'screenshots' array")
    items = []
    for item in screenshots:
        path = (worktree / str((item or {}).get("path") or "")).resolve()
        title = " ".join(str((item or {}).get("title") or "").split())
        if not title or path.suffix.lower() != ".png" or not path.is_file():
            raise RunBlocked("Every prototype screenshot needs a title and an existing PNG")
        if not path.is_relative_to(root / "approved"):
            raise RunBlocked("Approved prototype screenshots must live in the prototype/approved directory")
        items.append({"title": title, "path": str(path.relative_to(worktree))})

    issue = linear.issue(state["issue"]["identifier"])
    for item in items:
        item["url"] = linear.upload_file(worktree / item["path"])
    body = "\n\n".join(
        [
            "Prototipo de UI y UX aprobado durante el grill. Es la referencia visual de la "
            "implementación y de la revisión UI final.",
            *[f"**{item['title']}**\n\n![{item['title']}]({item['url']})" for item in items],
        ]
    )
    linear.update_description(issue.id, upsert_markdown_section(issue.description, LINEAR_SECTION, body))
    linear.post_comment(issue.id, f"Prototipo de UI aprobado para la ejecución `{state['runId']}`.")
    state["prototype"] = {
        "status": "APPROVED",
        "approvedAt": now(),
        "directory": str(root.relative_to(worktree)),
        "screenshots": items,
    }
    atomic_write_json(root / "approved" / "receipt.json", state["prototype"])
    save_state(state)
    return state["prototype"]
