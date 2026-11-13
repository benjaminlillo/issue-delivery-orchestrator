"""Share a cheap UI prototype during Grill and publish the approved one."""
from __future__ import annotations

import json
import os
import random
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from . import desktop_browser
from .errors import RunBlocked
from .linear import LinearClient, markdown_section, upsert_markdown_section
from .runtime import _alive, register_owned_process
from .state import GATE_RUNNERS, now, run_mode, run_root, save_state
from .util import atomic_write_json, read_json

LINEAR_SECTION = "Prototipo aprobado"
DRAFT_PREFIX = "pm-draft-"
APPROVED_IMAGE = re.compile(
    r"\*\*(?P<title>[^*\n]+)\*\*\s*\n\s*!\[[^\]]*\]\((?P<url>https://uploads\.linear\.app/[^)\s]+)\)"
)


def prototype_root(state: dict[str, Any]) -> Path:
    return run_root(Path(state["worktree"]), state["runId"]) / "prototype"


def draft_state(worktree: Path, issue_identifier: str) -> dict[str, Any]:
    """Load or create the prototype area a PM uses for an issue before any run exists."""
    run_id = f"{DRAFT_PREFIX}{issue_identifier}"
    root = run_root(worktree.resolve(), run_id)
    state = read_json(root / "state.json", None)
    if isinstance(state, dict) and state.get("draft"):
        return state
    state = {
        "draft": True,
        "runId": run_id,
        "worktree": str(worktree.resolve()),
        "issue": {"identifier": issue_identifier},
        "mode": {"name": _draft_mode()},
        "currentPhase": "grill",
        "status": "draft",
        "ownedProcesses": [],
        "prototype": None,
    }
    (root / "prototype").mkdir(parents=True, exist_ok=True)
    save_state(state)
    return state


def _draft_mode() -> str:
    for name, runner in GATE_RUNNERS.items():
        if os.environ.get(runner["signal"]) == "1":
            return name
    return "conductor-cloud" if os.environ.get("CONDUCTOR_IS_LOCAL") == "0" else "vanilla"


def open_prototype(state: dict[str, Any], page: Path, *, desktop: bool = False) -> dict[str, Any]:
    root = prototype_root(state).resolve()
    page = page.resolve()
    if not page.is_relative_to(root) or not page.is_file():
        raise RunBlocked(f"The prototype page must be a file inside {root}")
    mode = run_mode(state)
    if mode in GATE_RUNNERS:
        if desktop:
            raise RunBlocked(
                f"The {GATE_RUNNERS[mode]['name']} runner has no desktop; share the prototype "
                "through the gate"
            )
        shown = _share_gate_preview(state, root, page, GATE_RUNNERS[mode]["preview"])
    elif desktop:
        shown = _open_on_desktop(state, root, page)
    else:
        shown = _share_preview(state, root, page)
    state["prototype"] = {
        **(state.get("prototype") or {}),
        **shown,
        "status": "IN_REVIEW",
        "page": str(page.relative_to(Path(state["worktree"]).resolve())),
        "openedAt": now(),
    }
    save_state(state)
    return state["prototype"]


def _ensure_server(
    state: dict[str, Any], root: Path, ports: tuple[int, int] | None = None
) -> tuple[int, int]:
    """Serve the prototype directory on 127.0.0.1, reusing the run's live server."""
    previous = state.get("prototype") or {}
    pid, port = previous.get("serverPid"), previous.get("serverPort")
    in_range = ports is None or (port and ports[0] <= int(port) <= ports[1])
    if not (pid and port and in_range and _alive(int(pid)) and _serves(int(port))):
        port = _free_port_in(*ports) if ports else desktop_browser._free_port()
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
    return int(pid), int(port)


def _share_preview(state: dict[str, Any], root: Path, page: Path) -> dict[str, Any]:
    """Serve the prototype directory and share it at the workspace's Conductor preview URL."""
    pid, port = _ensure_server(state, root)
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


def _share_gate_preview(
    state: dict[str, Any], root: Path, page: Path, prefix: str
) -> dict[str, Any]:
    """Serve the prototype and register it with the runner's preview gate."""
    registry = os.environ.get(f"{prefix}_REGISTRY", "").strip()
    ports = _port_range(os.environ.get(f"{prefix}_PORTS", ""))
    if not registry or not ports:
        raise RunBlocked(
            f"The runner does not expose {prefix}_REGISTRY and {prefix}_PORTS; update the "
            "runner image to share prototypes through its gate"
        )
    pid, port = _ensure_server(state, root, ports)
    preview_id = re.sub(r"[^a-z0-9._-]+", "-", f"{state['issue']['identifier']}-prototype".lower())
    preview_id = preview_id.strip("-.")[:64]
    entry = {
        "id": preview_id,
        "port": port,
        "label": f"{state['issue']['identifier']} · prototipo",
        "path": "/" + quote(str(page.relative_to(root))),
        "worktree": str(Path(state["worktree"]).resolve()),
        "runId": state["runId"],
    }
    directory = Path(registry)
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(directory / f"{preview_id}.json", entry)
    result = subprocess.run(["preview-link", "--preview", preview_id], capture_output=True, text=True)
    url = result.stdout.strip()
    if result.returncode != 0 or not url.startswith(("http://", "https://")):
        detail = result.stderr.strip() or result.stdout.strip()
        raise RunBlocked(f"The runner gate did not issue a prototype link ({detail})")
    return {"serverPid": pid, "serverPort": port, "previewId": preview_id, "url": url}


def _port_range(raw: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", raw or "")
    if not match:
        return None
    low, high = int(match.group(1)), int(match.group(2))
    return (low, high) if 0 < low <= high < 65536 else None


def _free_port_in(low: int, high: int) -> int:
    candidates = list(range(low, high + 1))
    random.shuffle(candidates)
    for port in candidates:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RunBlocked(f"No free port for the prototype server in {low}-{high}")


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
    origin = "antes de iniciar el run" if state.get("draft") else f"para la ejecución `{state['runId']}`"
    linear.post_comment(issue.id, f"Prototipo de UI aprobado {origin}.")
    state["prototype"] = {
        "status": "APPROVED",
        "approvedAt": now(),
        "directory": str(root.relative_to(worktree)),
        "screenshots": items,
    }
    atomic_write_json(root / "approved" / "receipt.json", state["prototype"])
    save_state(state)
    return state["prototype"]


def adopt_prototype(state: dict[str, Any], *, linear: LinearClient) -> dict[str, Any]:
    """Bring into the run the prototype the user approved before it, from the issue in Linear."""
    if state.get("currentPhase") != "grill":
        raise RunBlocked("Adopt the approved prototype during Grill, before Implement starts")
    issue = linear.issue(state["issue"]["identifier"])
    found = [
        (" ".join(match.group("title").split()), match.group("url"))
        for match in APPROVED_IMAGE.finditer(markdown_section(issue.description, LINEAR_SECTION))
    ]
    if not found:
        raise RunBlocked(f"The issue has no screenshots under '## {LINEAR_SECTION}' to adopt")
    worktree = Path(state["worktree"]).resolve()
    root = prototype_root(state).resolve()
    approved = root / "approved"
    approved.mkdir(parents=True, exist_ok=True)
    items = []
    for index, (title, url) in enumerate(found, start=1):
        content = linear.download_file(url)
        if not content.startswith(b"\x89PNG"):
            raise RunBlocked(f"The approved prototype screenshot '{title}' is not a PNG")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "captura"
        path = approved / f"{index:02d}-{slug}.png"
        path.write_bytes(content)
        items.append({"title": title, "path": str(path.relative_to(worktree)), "url": url})
    state["prototype"] = {
        "status": "APPROVED",
        "source": "linear",
        "approvedAt": now(),
        "directory": str(root.relative_to(worktree)),
        "screenshots": items,
    }
    atomic_write_json(approved / "receipt.json", state["prototype"])
    save_state(state)
    return state["prototype"]
